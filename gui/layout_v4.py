"""
UI v4 —— 全新布局（工作台形态）

与 v3（`layout_modern.py`）的根本区别
-------------------------------------
v3 是「顶部 Tab + 左右分栏」：Tab 承载**技术分类**（设备/应用/日志/投屏…），
每个 Tab 里塞一堆卡片，右侧终端永远占掉 ~360px。问题：

1. **按技术分类而不是按任务分类** —— 用户想「装个包」要先想它属于哪个 Tab。
2. **横向空间被浪费** —— 左栏按各 Tab 自然宽度最大值撑开，右栏终端固定占位。
3. **视觉层级弱** —— 顶栏 70px + Tab 条 + 卡片边框套卡片，密但乱。

v4 改为「左侧固定导航 + 顶栏全局上下文 + 右侧可折叠终端」：

    ┌──────────┬─────────────────────────────────────────┬──────────┐
    │  侧边栏   │  顶栏：设备上下文 / 包名 / 主题切换        │  终端    │
    │  按任务流  ├─────────────────────────────────────────┤  可折叠   │
    │  分组     │  工作区（当前任务的紧凑面板）              │          │
    └──────────┴─────────────────────────────────────────┴──────────┘

设计约束（都是踩过坑总结的）：
- **终端可折叠**：折叠后工作区横向铺满，看长路径日志不再换行。
- **Tab 内容懒加载**：导航项首次点开才构建，避免启动时建 6 套控件。
- **网格列必须有内容**：空列也会吃掉一半宽度（老坑）。
- **不用 uniform**：会强制等宽，把最宽的卡片宽度传染给整行。
"""
import tkinter as tk
from tkinter import ttk
import logging
import re

from config import Config
from gui.theme import (ThemeManager, FONT_UI, FONT_MONO,
                      FS_XS, FS_SM, FS_MD, FS_XL, FS_XXL,
                      FSM_SM, FSM_MD, FSM_LG)
from gui.device_picker import DevicePicker
from gui.fast_table import FastTable
from gui.nav_icons import draw_icon as draw_nav_icon, ICON_SIZE as NAV_ICON_SIZE


class LayoutV4:
    """工作台布局"""

    # ── 导航结构：按「任务流」分组，而不是按技术模块分组 ──────────────
    # (分组标题, [(导航键, 标题, 图标字符, 构建方法名), ...])
    NAV_GROUPS = [
        ('日常操作', [
            ('install',  '安装应用', 'install', 'build_install_panel'),
            ('diagnose', '问题诊断', 'diagnose', 'build_diagnose_panel'),
            ('device',   '设备控制', 'device', 'build_device_panel'),
        ]),
        ('进阶工具', [
            ('perf',   '性能监控', 'perf', 'build_perf_panel'),
            ('mirror', '投屏控制', 'mirror', 'build_mirror_panel'),
            ('script', '脚本执行', 'script', 'build_script_panel'),
        ]),
    ]

    # 导航键 → 面板构建方法
    PANEL_BUILDERS = {
        'install':  'build_install_panel',
        'diagnose': 'build_diagnose_panel',
        'device':   'build_device_panel',
        'perf':     'build_perf_panel',
        'mirror':   'build_mirror_panel',
        'script':   'build_script_panel',
    }

    def __init__(self, app):
        self.app = app
        self.theme = None
        self.nav_buttons = {}      # nav_key -> tk.Button
        self.nav_rows = {}         # nav_key -> 承载高亮条的 Frame
        self._icon_kind = {}       # nav_key -> 图标类型（Canvas 重绘时要用）
        self.panels = {}           # nav_key -> Frame
        self.current_nav = None
        self._terminal_collapsed = False

    # ================================================================
    # 入口
    # ================================================================
    def setup_gui(self):
        """构建完整布局"""
        self.theme = ThemeManager(self.app.root, self.app)
        # ⚠️ 必须**在** setup_gui 内部就把主题句柄挂到 app 上：
        #    app._setup_gui() 在调用完 layout.setup_gui() 之后还会继续执行
        #    （设置终端 tag 颜色等），那时 app.layout_instance 还没赋值，
        #    只能靠提前挂好的 _ui_theme / _paint_connection_badge 拿到主题。
        self.app._ui_theme = self.theme
        self.app._paint_connection_badge = self._paint_connection_badge
        # 主题变化时，app 里硬编码了颜色的控件需要重新上色
        self.theme.on_change(lambda name: self._retheme_dynamic())

        self._build_shell()
        self._build_sidebar()
        self._build_topbar()
        self._build_workspace()
        self._build_terminal()

        self._setup_keyboard_shortcuts()

        # 先出窗口框架，再补内容
        try:
            self.app.root.update_idletasks()
        except Exception:
            pass
        self.app.root.after(50, lambda: self.switch_nav('install'))
        self.app.root.after(100, self._restore_session)

    def _restore_session(self):
        """恢复上次的主题（ThemeManager 已读偏好文件，这里只是触发一次重刷）"""
        self.theme.apply()

    # ================================================================
    # 外壳
    # ================================================================
    def _build_shell(self):
        """根容器：侧边栏 + 主区（顶栏 + 工作区 + 终端）"""
        self.root_frame = tk.Frame(self.app.root, bg=self.theme.color('bg_app'))
        self.root_frame.pack(fill=tk.BOTH, expand=True)

        self.app.root.title(f"ADB Tool v{Config.APP_VERSION}")
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        self.app.root.minsize(*Config.MIN_WINDOW_SIZE)

        # ── 网格结构 ──────────────────────────────────────────
        #   行 0 = 顶栏（只占主区，终端从顶端贯通到底）
        #   行 1 = 工作区
        #   列 0 = 侧边栏（跨两行） | 列 1 = 主区 | 列 2 = 终端（跨两行）
        #
        # ⚠️ 顶栏和工作区**不能**放在同一格（row=0, column=1）——
        #    那样工作区会盖住顶栏，设备/包名下拉框直接消失。
        self.root_frame.grid_columnconfigure(
            0, weight=0, minsize=0)              # 左侧留白边距
        self.root_frame.grid_columnconfigure(
            1, weight=0, minsize=Config.SIDEBAR_WIDTH)
        self.root_frame.grid_columnconfigure(2, weight=1)          # 主区：弹性
        self.root_frame.grid_columnconfigure(
            3, weight=0, minsize=Config.TERMINAL_WIDTH)  # 终端
        self.root_frame.grid_rowconfigure(0, weight=0)   # 顶栏：固定高
        self.root_frame.grid_rowconfigure(1, weight=1)   # 工作区：吃掉剩余空间

    # ================================================================
    # 侧边栏
    # ================================================================
    def _build_sidebar(self):
        """左侧导航栏：品牌区 + 任务分组 + 底部主题切换"""
        side = tk.Frame(self.root_frame, bg=self.theme.color('bg_side'),
                        width=Config.SIDEBAR_WIDTH)
        side.grid(row=0, column=1, sticky=tk.NSEW, rowspan=2)
        # ⚠️ 固定宽度：必须 pack_propagate(False)，否则内容宽度会反过来撑开侧边栏
        side.pack_propagate(False)
        side.grid_propagate(False)
        self.theme.register(side, 'side')

        # ── 品牌区 ────────────────────────────────────────────
        # ⚠️ **纯文字，不要 logo 色块**（v5.4.6，用户反馈「图标不需要」）：
        #    ① 蓝色方块 + 内部白点在小尺寸下只是个小噪点，没信息量
        #    ② 它占 22+23=45px 横向空间，把「ADB Tool」往右推
        #    ③ 之前它还被 theme.register(logo,'side') 刷成底色变成隐形白块，
        #       「标题靠右」的观感其实来自这个隐形块
        #       （教训：自定义底色必须给主题加专用角色，不能借用 'side'）
        #
        # ⚠️ **左边缘与下方导航项文字对齐**（都是 padx=14）：
        #    视觉上「ADB Tool」和「安装应用」在同一条竖线上，才像一整块。
        brand = tk.Frame(side, bg=self.theme.color('bg_side'), height=54)
        brand.pack(fill=tk.X)
        brand.pack_propagate(False)
        self.theme.register(brand, 'side')

        # ⚠️ 左边缘 padx=**33**：与下方导航项的**文字**左边缘对齐
        #    （导航项图标占 10+16+7=33px，文字从 33 开始）。
        #    这样「ADB Tool」和「安装应用」在同一条竖线上，视觉成一整块。
        brand_text = tk.Frame(brand, bg=self.theme.color('bg_side'),
                              width=100)
        brand_text.pack(side=tk.LEFT, fill=tk.Y, padx=(33, 0))
        brand_text.pack_propagate(False)
        self.theme.register(brand_text, 'side')

        self._label(brand_text, text="ADB Tool", fg_key='fg', bg_key='bg_side', font=(FONT_UI, FS_XL, 'bold'), anchor=tk.W).pack(anchor=tk.W, pady=(9, 0))
        self._label(brand_text, text=f"v{Config.APP_VERSION}", fg_key='fg_dim', bg_key='bg_side', font=(FONT_UI, FS_SM), anchor=tk.W).pack(anchor=tk.W)

        # 分隔线
        self._hline(side)

        # ── 导航项 ────────────────────────────────────────────
        nav_wrap = tk.Frame(side, bg=self.theme.color('bg_side'))
        nav_wrap.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.theme.register(nav_wrap, 'side')

        for group_title, items in self.NAV_GROUPS:
            # ⚠️ 分组标题上下留白放大一点：侧边栏收窄后导航项变短，
            #    底部会空出一大片。加点呼吸感让分布更自然。
            self._label(nav_wrap, text=group_title, fg_key='fg_dim', bg_key='bg_side', font=(FONT_UI, FS_SM, 'bold'), anchor=tk.W).pack(fill=tk.X, padx=14, pady=(14, 6))

            for key, title, icon, _builder in items:
                self._build_nav_item(nav_wrap, key, title, icon)

        # ── 底部：主题切换 ────────────────────────────────────
        self._hline(side)
        # ⚠️ **主题按钮和设备数上下堆叠**，不要横排：
        #    横排要 74(「☀ 浅色模式」) + 23(「0 台」) + padx(32) = 129px，
        #    这是侧边栏宽度的真正瓶颈（导航项只需要 ~100px）。
        #    堆叠后最宽只要 74px + 8px padding = 82px。
        foot = tk.Frame(side, bg=self.theme.color('bg_side'), height=62)
        foot.pack(side=tk.BOTTOM, fill=tk.X)
        foot.pack_propagate(False)
        self.theme.register(foot, 'side')

        self.theme_btn = self._label(foot, text="", fg_key='fg_muted', bg_key='bg_side', font=(FONT_UI, FS_MD), anchor=tk.W, cursor='hand2')
        self.theme_btn.pack(fill=tk.X, padx=16, pady=(9, 0))
        self.theme_btn.bind('<Button-1>', lambda e: self._toggle_theme())
        self._update_theme_button()

        # 设备数放在侧边栏底部：它是「状态信息」而不是「操作」，
        # 放顶栏会跟设备/包名上下文抢横向空间（顶栏只有 672px）。
        self.app.device_count_label = self._label(
            foot, text="0 台", fg_key='fg_dim', bg_key='bg_side',
            font=(FONT_UI, FS_SM), anchor=tk.W)
        self.app.device_count_label.pack(fill=tk.X, padx=16)

    def _build_nav_item(self, parent, key, title, icon):
        """单个导航项：左侧 3px 高亮条 + 图标 + 文字

        ⚠️ 高亮条用 **place** 定位（不是 pack/grid）：
           pack + width 切换在 pack_propagate(False) 下不生效，
           grid 切列宽也压不住 Frame 自身的 width。
           place 的 relwidth/height 每次重绘都会重新计算，收放最可靠。

        ⚠️ 图标用 **Canvas 手绘**（gui/nav_icons.py），不用 Unicode 符号：
           `⇩ ⚕ ⌘ ◔ ▣` 在微软雅黑 UI 里字形缺失/严重变形，
           渲染成糊掉的小方块（用户反馈「表情符号不清晰也不好看」），
           而且 `⌘` 被两个导航项复用，图标完全无法区分。
           Canvas 画线条：像素级可控、跨机器一致、颜色能跟主题。
        """
        row = tk.Frame(parent, bg=self.theme.color('bg_side'), height=34)
        row.pack(fill=tk.X)
        row.pack_propagate(False)
        self.theme.register(row, 'side')
        self.nav_rows[key] = row

        # row 内部：内容占满整行，高亮条浮在上面（place）
        hl = tk.Frame(row, bg=self.theme.color('bg_side'))
        hl.pack(fill=tk.BOTH, expand=True)
        self.theme.register(hl, 'side')
        self.nav_rows[key + '_hl'] = hl

        # 选中高亮条：place 定位，高度贴满，宽度 0 ↔ 3
        bar = tk.Frame(row, bg=self.theme.color('bg_side'), width=3)
        bar.place(relx=0, rely=0, relheight=1.0, width=0)
        self.theme.register(bar, 'side')
        self.nav_rows[key + '_bar'] = bar

        # 图标：Canvas 手绘（16x16），垂直居中
        icon_canvas = tk.Canvas(
            hl, width=NAV_ICON_SIZE, height=NAV_ICON_SIZE,
            bg=self.theme.color('bg_side'), highlightthickness=0,
            borderwidth=0)
        icon_canvas.pack(side=tk.LEFT, padx=(10, 7), pady=(34 - NAV_ICON_SIZE) // 2)
        self.nav_rows[key + '_icon'] = icon_canvas
        # 记下图标类型：悬停/换主题时要重画
        self._icon_kind[key] = icon
        self._draw_nav_icon(key, icon, self.theme.color('fg_dim'))

        text_lbl = self._label(hl, text=title, fg_key='fg_muted', bg_key='bg_side', font=(FONT_UI, FS_MD), anchor=tk.W)
        text_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        for w in (row, hl, icon_canvas, text_lbl):
            w.bind('<Button-1>', lambda e, k=key: self.switch_nav(k))
            w.bind('<Enter>', lambda e, k=key: self._nav_hover(k, True))
            w.bind('<Leave>', lambda e, k=key: self._nav_hover(k, False))
            w.configure(cursor='hand2')

        self.nav_buttons[key] = _NavButtonProxy(self, key)

    def _draw_nav_icon(self, key, kind, color):
        """重绘某个导航项的图标（换主题/悬停时调用）"""
        canvas = self.nav_rows.get(key + '_icon')
        if canvas is None:
            return
        try:
            canvas.delete('all')
            canvas.configure(bg=self.theme.color('bg_side'))
            draw_nav_icon(canvas, kind, color)
        except Exception:
            pass

    def _nav_hover(self, key, entering):
        """导航项悬停反馈

        ⚠️ 悬停态必须**明显**：底色变化 + 文字提亮 + 图标提亮 +
           左侧出现一条淡主色指示条。用户要能一眼看出「鼠标在这儿」。
        选中态由 _update_nav_state 负责（更强烈）。
        """
        if self.current_nav == key:
            return
        hl = self.nav_rows.get(key + '_hl')
        bar = self.nav_rows.get(key + '_bar')
        if hl is None:
            return

        bg = self.theme.color('bg_hover') if entering else self.theme.color('bg_side')
        fg = self.theme.color('fg') if entering else self.theme.color('fg_muted')
        icon_fg = self.theme.color('accent') if entering else self.theme.color('fg_dim')

        try:
            hl.configure(bg=bg)
            self.theme.register(hl, 'side')
            # 悬停时左侧也出现淡主色条（比选中态的更淡）
            if bar is not None:
                bar.configure(bg=self.theme.color('accent') if entering
                              else self.theme.color('bg_side'))
                bar.place_configure(relx=0, rely=0, relheight=1.0,
                                    width=2 if entering else 0)
                self.theme.register(bar, 'side')
            # ⚠️ 图标是 Canvas 画的，不是 Label —— 必须**重绘**才能变色。
            #    （之前靠 `labels[0]` 判断哪个是图标的写法已随 Canvas 化失效）
            _icon = self.nav_rows.get(key + '_icon')
            if _icon is not None:
                _icon.configure(bg=bg)
                self._draw_nav_icon(key, self._icon_kind.get(key, ''), icon_fg)
            # 文字 Label
            for child in hl.winfo_children():
                if child.winfo_class() == 'Label':
                    child.configure(bg=bg, fg=fg)
        except Exception:
            pass

    def _update_theme_button(self):
        """更新侧边栏底部的主题切换按钮文案"""
        if not hasattr(self, 'theme_btn'):
            return
        if self.theme.is_dark():
            self.theme_btn.configure(text="☀  浅色模式", fg=self.theme.color('fg_muted'))
        else:
            self.theme_btn.configure(text="☾  深色模式", fg=self.theme.color('fg_muted'))

    def _toggle_theme(self):
        """切换深/浅主题"""
        self.theme.toggle()
        self._update_theme_button()

    def _retheme_dynamic(self):
        """主题切换后，刷新那些在运行时被 app.py 改过颜色的控件"""
        t = self.theme
        # ⚠️ 导航图标是 Canvas 画的 → 换主题必须**重绘**（线条颜色要换）
        for _key, _kind in self._icon_kind.items():
            _is_on = (_key == self.current_nav)
            _ic = self.nav_rows.get(_key + '_icon')
            if _ic is not None:
                _ic.configure(bg=t.color('bg_active') if _is_on
                              else t.color('bg_side'))
            self._draw_nav_icon(
                _key, _kind,
                t.color('accent') if _is_on else t.color('fg_dim'))
        # 连接状态标签：app.py 里按设备状态改过 bg/fg，这里统一重刷
        label = getattr(self.app, 'connection_status_label', None)
        if label is not None:
            self._paint_connection_badge(label)
        # 终端文本的 tag 颜色
        txt = getattr(self.app, 'status_text', None)
        if txt is not None:
            t._paint(txt, 'terminal', t.tokens)
        # 性能指标卡：阈值色（绿/黄/红）跟着主题走
        snapshot = getattr(self, '_metric_snapshot', {})
        for key, labels in getattr(self.app, 'perf_metric_labels', {}).items():
            cur_label = labels[0]
            try:
                cur_label.configure(foreground=self._metric_color(key, snapshot.get(key)))
            except Exception:
                pass
        # 性能状态标签 / 卡顿率标签
        perf_status = getattr(self.app, 'perf_status_label', None)
        if perf_status is not None:
            try:
                running = bool(getattr(self.app, 'performance_monitor', None)
                               and self.app.performance_monitor.monitoring)
                perf_status.configure(
                    foreground=self._metric_color('success' if running else 'fg_dim'))
            except Exception:
                pass
        jank_label = getattr(self.app, 'perf_jank_label', None)
        if jank_label is not None:
            try:
                jank_label.configure(foreground=self.theme.color('fg_dim'))
            except Exception:
                pass
        # 表格的斑马纹 / 高亮行
        # ⚠️ v5.4.11：数据区改成 FastTable（Listbox）后，
        #    斑马纹/高亮要由 FastTable 自己重绘 → 调它的 refresh_theme()
        for _name in ('perf_samples_table', 'perf_thread_table'):
            _tbl = getattr(self.app, _name, None)
            if _tbl is not None:
                try:
                    _tbl.refresh_theme()
                except Exception:
                    pass

    def _metric_color(self, key, value):
        """性能指标阈值色（与 app.py 的判定阈值保持一致）"""
        if value is None:
            return self.theme.color('fg_dim')
        if key == 'cpu':
            if value > 80:
                return self.theme.color('error')
            if value > 50:
                return self.theme.color('warning')
            return self.theme.color('success')
        if key == 'fps':
            if value < 30:
                return self.theme.color('error')
            if value < 50:
                return self.theme.color('warning')
            return self.theme.color('success')
        return self.theme.color('fg')

    def _hline(self, parent, padx=0):
        """一条 1px 分隔线"""
        line = tk.Frame(parent, bg=self.theme.color('line'), height=1)
        line.pack(fill=tk.X, padx=padx)
        self.theme.register(line, 'sep')
        return line

    # ================================================================
    # 顶栏（全局上下文）
    # ================================================================
    def _build_topbar(self):
        """顶栏：设备上下文 + 包名上下文 + 终端折叠按钮

        ⚠️ 顶栏元素的总需求宽度必须 ≤ 主区宽度，否则后面的控件
           （通常是包名框）会被挤没 —— 表现为「控件凭空消失」。
           当前主区宽度 = 窗口1200 - 侧栏188 - 终端340 = 672px。

           像素字号后控件比原来宽（719px 超了），所以做了三处压缩：
           ① 设备数并入连接状态徽标（少一个独立标签）
           ② 连接/断开改用**图标**按钮（⇄ / ⏻ 语义更准，且省 30px）
           ③ 设备框 12 字符 + 包名框 16 字符
        """
        bar = tk.Frame(self.root_frame, bg=self.theme.color('bg_app'), height=46)
        bar.grid(row=0, column=2, sticky=tk.EW)
        bar.pack_propagate(False)
        self.theme.register(bar, 'canvas')
        self.topbar = bar

        # ── 右侧：终端折叠（仅在终端已折叠时出现）─────────────
        # ⚠️ 常态**不占任何横向空间**：
        #    pack(RIGHT) 会优先占位，把包名框挤窄（包名要能看全）。
        #    所以展开状态下用 pack_forget 把它藏掉，
        #    只有终端折叠后（工作区变宽、顶栏有富余）才显示出来做「恢复入口」。
        #    终端面板自己的标题栏里也有一个「⌄」折叠按钮，两者功能不重复：
        #    那个负责「收起」，这个负责「展开」。
        right = tk.Frame(bar, bg=self.theme.color('bg_app'))
        right.pack(side=tk.RIGHT, padx=8)
        self.theme.register(right, 'canvas')

        # ── 刷新设备列表 ─────────────────────────────────────
        # ⚠️ 用**文字「刷新」**而不是 `↻` 图标：
        #    用户反馈「刷新功能怎么没有了」—— 30px 的图标按钮在深色
        #    主题下太不显眼，等于没有。文字明确、一眼能认。
        # ⚠️ width=3：ttk.Button 的 width 单位是**字符数**，
        #    「刷新」两个字实测约 26px，width=3 给到 44px 足够，
        #    比 width=4（52px）省 8px —— 顶栏空间要留给包名框。
        self.app.btn_refresh_top = ttk.Button(
            right, text="刷新", command=self.app.refresh_device_list,
            style='TopSecondary.TButton', width=3,
        )
        self.app.btn_refresh_top.pack(side=tk.LEFT, padx=(0, 6))
        self._attach_tip(self.app.btn_refresh_top, "刷新设备列表（重新扫描已连接设备）")

        self.collapse_btn = ttk.Button(
            right, text="终端 ▸", command=self._toggle_terminal,
            style='Ghost.TButton', width=7,
        )
        # 初始不显示（终端默认展开）
        self.collapse_btn.pack_forget()
        self._attach_tip(self.collapse_btn, "展开终端（Ctrl+B）")

        # ── 设备上下文 ────────────────────────────────────────
        self._ctx_field(bar, '设备')

        # ⚠️ width=11（不是 12）：满 IP 如「10.1.246.185」是 12 字符，
        #    但 12 时下拉框 req 127px，顶栏总需求会超 712px 可用宽度，
        #    把包名框压到 171px（断言线 170px，只差 1px 就挂）。
        #    11 字符时实测 119px，「10.1.246.185」仍能完整显示。
        self.app.ip_combobox = ttk.Combobox(
            bar, width=11, font=(FONT_UI, FS_MD), style='App.TCombobox')
        self.app.ip_combobox.pack(side=tk.LEFT, padx=(0, 6))
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox.insert(0, "192.168.")
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)

        # 连接状态徽标：文案里带设备数，省掉一个独立标签
        # ⚠️ padx=4（不是 6）：顶栏宽度是硬约束，省下的 4px 要给包名框。
        self.app.connection_status_label = tk.Label(
            bar, text="● 无设备", font=(FONT_UI, FS_SM),
            bg=self.theme.color('fg_dim'), fg=self.theme.color('accent_fg'),
            padx=4, anchor=tk.CENTER, height=1,
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(0, 5))
        self.app.connection_status_label._badge_state = 'off'
        # 登记到主题：换肤时按当前状态重新上色
        self.theme.register(self.app.connection_status_label, 'badge')

        # ⚠️ 设备切换入口（v5.4）
        #   以前只有「IP 输入框」这一个入口，多设备在线时用户得手动敲 IP 切换，
        #   而且刷新后完全看不出「到底有几台设备在线」。
        #   这里加一个「设备 ▾」按钮，点开是分组浮层（在线 / 离线与历史），
        #   单击即切换。
        #   宽度预算：顶栏可用 712px，各控件 req 之和必须 ≤ 它，
        #   否则包名框被挤窄（历史 bug）。已通过压缩刷新/连接/断开按钮
        #   的 width 与徽标 padx 腾出空间。
        self.app.btn_device_picker = ttk.Button(
            bar, text="设备 ▾", command=self._toggle_device_picker,
            style='TopSecondary.TButton', width=6,
        )
        self.app.btn_device_picker.pack(side=tk.LEFT, padx=(0, 5))
        self._attach_tip(self.app.btn_device_picker,
                         "切换设备（列出在线设备，单击任意一行即可切换）")

        # 浮层实例：懒创建（第一次点按钮时才建）
        # ⚠️ 宿主是 **app.root**（主窗口本身），不是 root_frame：
        #    ① root_frame 内部用 grid 管理列（侧边栏/主区/终端），
        #       place 混用会导致坐标偏移（实测偏 50px = 侧边栏列宽）
        #    ② root 直接用 pack 管理 root_frame，place 的浮层作为
        #       后创建的子控件会叠在上层，且坐标就是窗口坐标系，最直观
        #    ③ 内嵌在主窗口内 → 移动窗口时浮层自动跟随
        self.device_picker = DevicePicker(self.app, self.theme,
                                          self.app.btn_device_picker,
                                          self.app.root)

        # ⚠️ 连接/断开用**中文文字**而不是图标：
        #    ⇄ / ⏻ 这类字符在「微软雅黑 UI」里字形缺失，会渲染成方块；
        #    文字虽然占宽一点，但用户一看就懂，不用悬停猜。
        #    宽度用 style 里的 padding 控制，不要用 width（那是字符数）。
        # ⚠️ width=3 而不是默认 6：ttk.Button 的 width 单位是「字符数」，
        #    默认 6 会让这两个只有两个字的按钮各占 108px —— 顶栏横向
        #    空间紧张，必须省出位置放「设备 ▾」按钮和让包名框保持可读。
        #    「连接」两字实测约 26px，width=3 给到 44px 不会被截断。
        self.app.btn_connect_top = ttk.Button(
            bar, text="连接", command=self.app.connect_adb,
            style='TopPrimary.TButton', width=3)
        self.app.btn_connect_top.pack(side=tk.LEFT, padx=(0, 4))

        self.app.btn_disconnect_top = ttk.Button(
            bar, text="断开", command=self.app.disconnect_adb,
            style='TopSecondary.TButton', width=3)
        self.app.btn_disconnect_top.pack(side=tk.LEFT, padx=(0, 8))

        # ── 包名上下文 ────────────────────────────────────────
        self._ctx_field(bar, '包名')

        # ⚠️ 包名框要能看**完整包名**（如 com.gitvdemo.video 之类很长），
        #    所以给足宽度；顶栏的终端折叠按钮已改为折叠时才显示，
        #    常态不占空间，这里可以把宽度让出来。
        # ⚠️ width=32（v5.4.4：侧边栏收窄 48px 后顶栏多出 111px 余量）：
        #    实测包名框 22 字符 = 207px，只能显示 22 个字符 ——
        #    「com.android.settings」(22) 刚好，「com.example.myapp.debug」(24)
        #    就看不全了。32 字符 ≈ 224px，能显示 28 字符，
        #    覆盖绝大多数真实包名。剩余余量留给顶栏右侧的刷新等按钮。
        self.app.pkg_combobox = ttk.Combobox(
            bar, width=32, font=(FONT_UI, FS_MD), style='App.TCombobox')
        self.app.pkg_combobox.pack(side=tk.LEFT, padx=(0, 6))
        self.app.pkg_combobox['height'] = 10
        # app.py 里 pkg_entry 就是 pkg_combobox 的别名（历史遗留）
        self.app.pkg_entry = self.app.pkg_combobox

        # ── 顶栏下分隔线 ──────────────────────────────────────
        self._hline(bar)

    def _label(self, parent, text, fg_key='fg', bg_key='bg_app',
               font=None, **kw):
        """创建一个跟随主题的文字标签

        ⚠️ 必须走这个辅助函数：面板是懒加载的，主题切换时要靠
        theme.register 重刷这些 tk.Label 的前景/背景色，
        否则会残留上一套主题的配色（浅色下变成黑底白字）。

        角色由 bg_key 决定（label / label_side / label_panel），
        这样换肤时底色能跟着走。
        """
        lbl = tk.Label(
            parent, text=text,
            font=font or (FONT_UI, FS_MD),
            bg=self.theme.color(bg_key),
            fg=self.theme.color(fg_key),
            **kw)
        lbl._fg_key = fg_key
        lbl._bg_key = bg_key
        role = {'bg_side': 'label_side',
                'bg_panel': 'label_panel',
                'bg_elev': 'label_elev'}.get(bg_key, 'label')
        self.theme.register(lbl, role)
        return lbl

    def _ctx_field(self, parent, label):
        """顶栏里的字段标签（浅色小字）"""
        lbl = self._label(parent, text=label, fg_key='fg_dim', bg_key='bg_app',
                          font=(FONT_UI, FS_XS))
        lbl.pack(side=tk.LEFT, padx=(0, 5))
        return lbl

    # ================================================================
    # 工作区
    # ================================================================
    def _build_workspace(self):
        """中间工作区：所有面板叠放在同一格，用 tkraise 切换"""
        self.workspace = tk.Frame(self.root_frame, bg=self.theme.color('bg_app'))
        self.workspace.grid(row=1, column=2, sticky=tk.NSEW)
        self.theme.register(self.workspace, 'canvas')

        self.workspace.grid_rowconfigure(0, weight=1)
        self.workspace.grid_columnconfigure(0, weight=1)

    def switch_nav(self, key):
        """切换导航项（懒加载面板）"""
        if key not in self.PANEL_BUILDERS:
            return

        if key not in self.panels:
            builder = getattr(self, self.PANEL_BUILDERS[key], None)
            if builder is None:
                return
            try:
                panel = builder()
            except Exception:
                logging.exception("[布局] 构建面板失败: %s", key)
                return
            self.panels[key] = panel
            panel.grid(row=0, column=0, sticky=tk.NSEW)

        self.panels[key].tkraise()
        # ⚠️ 先更新 current_nav 再刷新选中态：
        #    _update_nav_state 依赖它来判断哪些是「旧选中项」。
        self.current_nav = key
        self._update_nav_state(key)

    def _update_nav_state(self, active):
        """更新导航选中态

        ⚠️ 选中态要**一眼可辨**（用户反馈「只有一点选中样式」）：
           ① 整行主色淡底 bg_active
           ② 左侧 3px 主色实心条
           ③ 文字变主色 + **加粗**
           ④ 图标也变主色
        """
        for key in self.nav_buttons:
            is_on = (key == active)
            hl = self.nav_rows.get(key + '_hl')
            bar = self.nav_rows.get(key + '_bar')
            if hl is not None:
                hl.configure(bg=self.theme.color('bg_active') if is_on
                             else self.theme.color('bg_side'))
                self.theme.register(hl, 'side')
            if bar is not None:
                # ⚠️ 高亮条用 place 定位：宽度 0 ↔ 3，
                #    pack/grid 的 width 切换在已布局容器里不生效。
                bar.configure(bg=self.theme.color('accent') if is_on
                              else self.theme.color('bg_side'))
                bar.place_configure(relx=0, rely=0, relheight=1.0,
                                    width=3 if is_on else 0)
                self.theme.register(bar, 'side')

            # ⚠️ 图标是 **Canvas**（不是 Label）→ 变色靠**重绘**，不是 configure(fg)
            _icon = self.nav_rows.get(key + '_icon')
            if _icon is not None:
                _icon.configure(bg=self.theme.color('bg_active') if is_on
                                else self.theme.color('bg_side'))
                self._draw_nav_icon(
                    key, self._icon_kind.get(key, ''),
                    self.theme.color('accent') if is_on
                    else self.theme.color('fg_dim'))

            # 文字 Label：选中 → 主色 + 加粗；未选中 → 次要色
            labels = [c for c in (hl.winfo_children() if hl is not None else [])
                      if c.winfo_class() == 'Label']
            for child in labels:
                try:
                    if is_on:
                        child.configure(fg=self.theme.color('accent'),
                                        font=(FONT_UI, FS_MD, 'bold'))
                    else:
                        child.configure(fg=self.theme.color('fg_muted'),
                                        font=(FONT_UI, FS_MD))
                except Exception:
                    pass

    # ================================================================
    # 面板构建辅助
    # ================================================================
    def _panel(self, title, subtitle, fixed_bottom=None):
        """创建一个面板容器，返回 (外框, 内容区)

        ⚠️ 面板整体放进一个可滚动的 Canvas：
        小窗口下内容不会顶出窗口（v3 的投屏页就是这么被裁掉的）。

        Args:
            fixed_bottom: **固定在底部的容器**（不进入 Canvas）。
                用于装原生控件（Treeview 等）——
                Canvas 滚动时会重绘窗口项，
                而**原生控件每次都要整个重绘**。
                实测（v5.4.11）：表格在 Canvas 内时滚动
                耗时 14.5~21 ms，移出后降到 0.2 ms（**70 倍**）。
        """
        holder = tk.Frame(self.workspace, bg=self.theme.color('bg_app'))
        self.theme.register(holder, 'canvas')

        # ⚠️ 有底部固定区时，上半部用 grid 占位，
        #    固定区在下方——这样滚动 Canvas 时
        #    底部的原生控件**不会被重绘**。
        _bottom = None
        if fixed_bottom is not None:
            holder.grid_rowconfigure(0, weight=1)
            holder.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(holder, bg=self.theme.color('bg_app'),
                           highlightthickness=0, bd=0)
        self.theme.register(canvas, 'canvas')

        if fixed_bottom is not None:
            canvas.grid(row=0, column=0, sticky=tk.NSEW)
            _bottom = fixed_bottom
            _bottom.grid(row=1, column=0, sticky=tk.NSEW)
            self.theme.register(_bottom, 'canvas')
        else:
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=canvas.yview,
                            style='App.Vertical.TScrollbar')
        if fixed_bottom is not None:
            vsb.grid(row=0, column=1, sticky=tk.NS)
        else:
            vsb.pack(side=tk.RIGHT, fill=tk.Y)

        inner = tk.Frame(canvas, bg=self.theme.color('bg_app'))
        self.theme.register(inner, 'canvas')
        window_id = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        def _on_inner_configure(_e):
            canvas.configure(scrollregion=canvas.bbox('all'))

        def _on_canvas_configure(e):
            canvas.itemconfigure(window_id, width=e.width)

        inner.bind('<Configure>', _on_inner_configure)
        canvas.bind('<Configure>', _on_canvas_configure)

        # 滚轮支持
        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')

        canvas.bind('<MouseWheel>', _on_wheel)
        inner.bind('<MouseWheel>', _on_wheel)
        for child in inner.winfo_children():
            child.bind('<MouseWheel>', _on_wheel)

        # ── 页面标题区 ────────────────────────────────────────
        head = tk.Frame(inner, bg=self.theme.color('bg_app'))
        head.pack(fill=tk.X, padx=20, pady=(16, 0))
        self.theme.register(head, 'canvas')

        self._label(head, text=title, fg_key='fg', bg_key='bg_app', font=(FONT_UI, FS_XXL, 'bold'), anchor=tk.W).pack(fill=tk.X)

        self._label(head, text=subtitle, fg_key='fg_dim', bg_key='bg_app', font=(FONT_UI, FS_MD), anchor=tk.W).pack(fill=tk.X, pady=(2, 0))

        body = tk.Frame(inner, bg=self.theme.color('bg_app'))
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(14, 18))
        self.theme.register(body, 'canvas')

        # 标题区也在滚动区内 → 一起参与滚轮
        head.bind('<MouseWheel>', _on_wheel)

        return holder, body

    def _section(self, parent, title, hint=''):
        """一个功能分组：标题 + 内容容器

        Returns:
            (分组外框, 内容 Frame)
        """
        wrap = tk.Frame(parent, bg=self.theme.color('bg_app'))
        wrap.pack(fill=tk.X, pady=(0, 14))
        self.theme.register(wrap, 'canvas')

        head = tk.Frame(wrap, bg=self.theme.color('bg_app'))
        head.pack(fill=tk.X, pady=(0, 6))
        self.theme.register(head, 'canvas')

        self._label(head, text=title, fg_key='fg', bg_key='bg_app', font=(FONT_UI, FS_MD, 'bold'), anchor=tk.W).pack(side=tk.LEFT)

        if hint:
            self._label(head, text=hint, fg_key='fg_dim', bg_key='bg_app', font=(FONT_UI, FS_SM), anchor=tk.W).pack(side=tk.LEFT, padx=(10, 0))

        content = tk.Frame(wrap, bg=self.theme.color('bg_app'))
        content.pack(fill=tk.X)
        self.theme.register(content, 'canvas')
        return wrap, content

    def _btn(self, parent, text, method_name, kind='secondary', width=None):
        """创建一个动作按钮

        kind:
            primary   —— 主操作（实心主色）
            secondary —— 普通操作（带描边的次级按钮）
            danger    —— 危险操作（淡红底 + 红字 + 红边）
        """
        if not hasattr(self.app, method_name):
            return None
        # ⚠️ 面板里的功能按钮统一用 Action.* 样式：
        #    Secondary.TButton 是给顶栏/终端这类小控件用的，
        #    底色偏淡；功能按钮需要更明确的「可点击块」观感。
        style = {'primary': 'Primary.TButton',
                 'danger': 'ActionDanger.TButton',
                 'secondary': 'Action.TButton'}.get(kind, 'Action.TButton')
        kw = {}
        if width:
            kw['width'] = width
        btn = ttk.Button(parent, text=text,
                         command=getattr(self.app, method_name), style=style, **kw)
        return btn

    def _btn_row(self, parent, specs, pady=0, width=None):
        """一行按钮。specs = [(文本, 方法名, 类型), ...]

        ⚠️ **必须显式给 width**：
           ttk.Button 的 width 默认是 20「字符」，而 Action 样式的
           padding 是 (12, 7) → 每个按钮实测 118px。
           「系统按键」一行 6 个按钮 = 6×118 + 6×8(padx) = 756px，
           超出工作区可用宽度 → 最后一个「静音」被压到 69px（半截）。
           按实际文字宽度给 width（字符数）能省下大半。
        """
        row = tk.Frame(parent, bg=self.theme.color('bg_app'))
        row.pack(fill=tk.X, pady=pady)
        self.theme.register(row, 'canvas')
        for text, method, kind in specs:
            btn = self._btn(row, text, method, kind, width=width)
            if btn is not None:
                btn.pack(side=tk.LEFT, padx=(0, 8))
        return row

    # ================================================================
    # 面板：安装应用
    # ================================================================
    def build_install_panel(self):
        """安装应用：APK 选择 → 安装 → 校验"""
        holder, body = self._panel(
            "安装应用", "选择 APK，推送到目标设备，并自动校验安装结果")

        # ── APK 选择 ──────────────────────────────────────────
        _wrap, content = self._section(body, "安装包", "支持拖拽 APK 文件到输入框")

        apk_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        apk_row.pack(fill=tk.X)
        self.theme.register(apk_row, 'canvas')

        self.app.apk_entry = ttk.Entry(
            apk_row, font=(FONT_UI, FS_MD), style='App.TEntry')
        self.app.apk_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        browse_btn = ttk.Button(
            apk_row, text="浏览", command=self.app.browse_apk,
            style='Secondary.TButton', width=8)
        browse_btn.pack(side=tk.LEFT)

        # 拖放注册依赖 apk_entry，跟随本面板初始化
        try:
            self.app._setup_drag_drop()
        except Exception:
            logging.exception("[布局] 拖放注册失败")

        # 版本显示
        ver_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        ver_row.pack(fill=tk.X, pady=(8, 0))
        self.theme.register(ver_row, 'canvas')

        self._label(ver_row, text="版本", fg_key='fg_muted', bg_key='bg_app', font=(FONT_UI, FS_MD), width=7, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 8))

        self.app.version_display = ttk.Entry(
            ver_row, state='readonly', font=(FONT_MONO, FSM_MD), style='App.TEntry')
        self.app.version_display.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── 安装动作 ──────────────────────────────────────────
        _wrap2, content2 = self._section(body, "安装动作")

        self._btn_row(content2, [
            ("安装到设备", "force_install", "primary"),
            ("卸载应用", "uninstall", "danger"),
            ("清除缓存", "clear_cache", "secondary"),
        ])

        # ── 应用信息 ──────────────────────────────────────────
        _wrap3, content3 = self._section(body, "应用信息与进程")

        self._btn_row(content3, [
            ("获取版本号", "get_version", "secondary"),
            ("安装路径", "get_package_path", "secondary"),
            ("当前包名", "get_package_name", "secondary"),
            ("已安装列表", "package_list", "secondary"),
        ])

        self._btn_row(content3, [
            ("启动应用", "start_app", "secondary"),
            ("终止进程", "kill_app_process", "danger"),
            ("资源占用", "get_app_resource_usage", "secondary"),
        ])

        return holder

    # ================================================================
    # 面板：问题诊断
    # ================================================================
    def build_diagnose_panel(self):
        """问题诊断：日志抓取 → 导出分析"""
        holder, body = self._panel(
            "问题诊断", "抓取日志、导出 ANR 与 Monkey 报告，定位崩溃与卡顿")

        # ── 日志路径 ──────────────────────────────────────────
        _wrap, content = self._section(body, "数据存储路径", "日志/截图/录屏的落盘目录")

        path_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        path_row.pack(fill=tk.X)
        self.theme.register(path_row, 'canvas')

        self.app.log_path_entry = ttk.Entry(
            path_row, font=(FONT_UI, FS_MD), style='App.TEntry')
        self.app.log_path_entry.bind('<KeyRelease>', self.app._on_log_path_changed)
        self.app.log_path_entry.bind('<FocusOut>', self.app._on_log_path_changed)
        self.app.log_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.app.log_path_entry.insert(0, Config.DEFAULT_LOG_PATH)

        ttk.Button(
            path_row, text="浏览", command=self.app.choose_log_path,
            style='Secondary.TButton', width=8,
        ).pack(side=tk.LEFT)

        # ── 日志捕获 ──────────────────────────────────────────
        _wrap2, content2 = self._section(body, "日志捕获")

        self._btn_row(content2, [
            ("开始捕获", "start_logcat", "primary"),
            ("停止捕获", "stop_logcat", "danger"),
            ("清除缓存", "log_clear", "secondary"),
        ])

        # ── 导出分析 ──────────────────────────────────────────
        _wrap3, content3 = self._section(body, "导出与分析")

        self._btn_row(content3, [
            ("导出 ANR", "pull_anr_file", "secondary"),
            ("导出 Monkey 日志", "export_monkey_logs", "secondary"),
            ("原始命令速查", "show_all_adb_commands", "secondary"),
        ])

        # ── 智能分析（v5.4.8）─────────────────────────────────
        # ⚠️ 「错误分析」把日志里的错误**聚类 + 按频次排序** ——
        #    同一个异常刷 500 次仍是 500 行，人工翻找成本极高，
        #    而且看不出哪个错误最频繁（那才是优先要修的）。
        _wrap3b, content3b = self._section(
            body, "智能分析", "错误聚类排序 / 一键打包现场")

        self._btn_row(content3b, [
            ("错误分析", "analyze_log_errors", "primary"),
            ("一键诊断包", "collect_diagnostic_package", "secondary"),
        ])

        self._label(
            content3b,
            text="错误分析：把相同异常折叠并统计频次，直接告诉你哪个错得最多"
                 "（分析终端内容，终端为空时读日志文件）",
            fg_key='fg_dim', bg_key='bg_app', font=(FONT_UI, FS_SM),
            anchor=tk.W).pack(fill=tk.X, pady=(4, 0))
        self._label(
            content3b,
            text="一键诊断包：logcat + dumpsys + 设备属性打成 zip，"
                 "直接发给同事或贴问题单",
            fg_key='fg_dim', bg_key='bg_app', font=(FONT_UI, FS_SM),
            anchor=tk.W).pack(fill=tk.X, pady=(2, 0))

        # ── 屏幕取证 ──────────────────────────────────────────
        _wrap4, content4 = self._section(body, "屏幕取证")

        self._btn_row(content4, [
            ("开始录制", "start_recording", "primary"),
            ("停止录制", "stop_recording", "danger"),
            ("截取屏幕", "screencap", "secondary"),
        ])

        return holder

    # ================================================================
    # 面板：设备控制
    # ================================================================
    def build_device_panel(self):
        """设备控制：连接管理 + 系统操作 + 文本输入"""
        holder, body = self._panel(
            "设备控制", "管理 ADB 连接、设备信息与系统级操作")

        # ── 连接管理 ──────────────────────────────────────────
        _wrap, content = self._section(body, "连接管理")

        self._btn_row(content, [
            ("连接 ADB", "connect_adb", "primary"),
            ("断开所有", "disconnect_adb", "danger"),
            ("重启 ADB 服务", "restart_adb_server", "secondary"),
            ("刷新设备列表", "refresh_device_list", "secondary"),
        ])

        # ── 设备信息 ──────────────────────────────────────────
        _wrap2, content2 = self._section(body, "设备信息")

        self._btn_row(content2, [
            ("查看设备", "show_device_info", "secondary"),
            ("详细信息", "get_device_info_fast", "secondary"),
            ("获取串号", "get_serial_number", "secondary"),
            ("Android 版本", "get_android_version", "secondary"),
        ])

        # ── 系统操作 ──────────────────────────────────────────
        _wrap3, content3 = self._section(body, "系统操作")

        self._btn_row(content3, [
            ("重启设备", "reboot", "danger"),
            ("获取 Root", "root_device", "secondary"),
            ("重新挂载", "remount", "secondary"),
        ])

        self._btn_row(content3, [
            ("打开 CMD", "open_cmd_window", "secondary"),
            ("常用命令", "show_common_adb_commands", "secondary"),
            ("工厂菜单", "open_factory_menu", "secondary"),
        ])

        # ── 文本输入 ──────────────────────────────────────────
        _wrap4, content4 = self._section(body, "文本输入", "仅支持 ASCII，中文需 ADBKeyBoard")

        text_row = tk.Frame(content4, bg=self.theme.color('bg_app'))
        text_row.pack(fill=tk.X)
        self.theme.register(text_row, 'canvas')

        self.app.text_input_entry = ttk.Entry(
            text_row, font=(FONT_UI, FS_MD), style='App.TEntry')
        self.app.text_input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        ttk.Button(
            text_row, text="发送", command=self.app.send_text_input,
            style='Primary.TButton', width=8,
        ).pack(side=tk.LEFT)

        return holder

    # ================================================================
    # 面板：性能监控
    # ================================================================
    def build_perf_panel(self):
        """性能监控：采样控制 + 指标卡 + 明细表 + 线程表

        ⚠️ **两个表格放在底部固定区（不进 Canvas）**（v5.4.11）：
           用户反馈「性能监控页整体上下滚动时加载卡卡的」。

           实测数据（真机，30 行采样 + 30 线程）：
             表格在 Canvas 内 → 滚动 14.5~21 ms/次（约 50 fps）
             表格移出 Canvas   → 滚动 0.2 ms/次（约 5000 fps）
             差 **70 倍**。

           原因：**Canvas 滚动会重绘窗口项**，
           而 Treeview 是**原生控件**（非 Canvas item）——
           它位于 Canvas 覆盖区的部分每次都要整个重绘，
           而重绘成本 ∣ 表格高度。
           将它放到 Canvas **之外**就完全不受滚动影响。
        """
        # 底部固定区（两个表格并排）
        _fixed = tk.Frame(self.workspace, bg=self.theme.color('bg_app'))
        self.theme.register(_fixed, 'canvas')

        holder, body = self._panel(
            "性能监控", "采样 CPU / 内存 / 帧率，定位卡顿与内存泄漏",
            fixed_bottom=_fixed)

        # ── 采样控制 ──────────────────────────────────────────
        _wrap, content = self._section(body, "采样控制")

        pkg_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        pkg_row.pack(fill=tk.X, pady=(0, 8))
        self.theme.register(pkg_row, 'canvas')

        self._label(pkg_row, text="应用", fg_key='fg_muted', bg_key='bg_app', font=(FONT_UI, FS_MD), width=7, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 8))

        self.app.perf_package_entry = ttk.Entry(
            pkg_row, font=(FONT_MONO, FSM_MD), style='App.TEntry')
        self.app.perf_package_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.app.perf_package_entry.bind('<KeyRelease>', self.app._on_perf_package_search)

        self.app.perf_dropdown_listbox = None
        self.app.perf_dropdown_toplevel = None
        self.app._perf_all_packages = []

        ttk.Button(pkg_row, text="刷新", command=self.app.refresh_perf_package_list,
                   style='Secondary.TButton', width=6).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(pkg_row, text="当前", command=self.app.get_current_package_for_perf,
                   style='Secondary.TButton', width=6).pack(side=tk.LEFT, padx=(0, 12))

        self._label(pkg_row, text="间隔", fg_key='fg_muted', bg_key='bg_app', font=(FONT_UI, FS_MD)).pack(side=tk.LEFT, padx=(0, 6))

        self.app.perf_interval_var = tk.StringVar(value="2")
        ttk.Combobox(pkg_row, textvariable=self.app.perf_interval_var,
                     values=["1", "2", "3", "5", "10"], width=4,
                     font=(FONT_UI, FS_MD), state="readonly",
                     style='App.TCombobox').pack(side=tk.LEFT, padx=(0, 4))
        self._label(pkg_row, text="秒", fg_key='fg_muted', bg_key='bg_app', font=(FONT_UI, FS_MD)).pack(side=tk.LEFT)

        # 运行状态 + 采样按钮
        ctrl_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        ctrl_row.pack(fill=tk.X, pady=(4, 0))
        self.theme.register(ctrl_row, 'canvas')

        ttk.Button(ctrl_row, text="开始监控", command=self.app.start_performance_monitor,
                   style='Primary.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(ctrl_row, text="停止", command=self.app.stop_performance_monitor,
                   style='Danger.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(ctrl_row, text="清空数据", command=self.app.clear_performance_data,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 12))

        # ⚠️ v5.4.6：用户反馈「缺少清除上一次测试数据的按钮，
        #    可以选择清除还是不清除」。
        #    语义：「开始监控」时是否**先清空**上一轮的历史。
        #    默认勾选（= 每次都是干净的测试，符合"测一次"的直觉）；
        #    想连续观察/对比两轮数据时可以取消。
        self.app.perf_clear_on_start_var = tk.BooleanVar(value=True)
        # ⚠️ ttk.Checkbutton **不支持 font 参数**（会报 unknown option "-font"），
        #    字体要在 style 里配（App.TCheckbuttonFlat 已设 FS_SM）
        _chk = ttk.Checkbutton(
            ctrl_row, text="开始时清空",
            variable=self.app.perf_clear_on_start_var,
            style='App.TCheckbuttonFlat')
        _chk.pack(side=tk.LEFT, padx=(0, 10))
        self._attach_tip(_chk, "勾选：开始监控前清空上一轮的历史数据\n"
                               "取消：保留历史，与本轮数据连续观察")

        self.app.perf_status_label = self._label(ctrl_row, text="● 未开始", fg_key='fg_dim', bg_key='bg_app', font=(FONT_UI, FS_MD, 'bold'))
        self.app.perf_status_label.pack(side=tk.RIGHT)

        # ── 场景选择（决定关注指标与告警阈值）────────────────────
        #    Combobox 显示场景名，内部用 key；用 <<ComboboxSelected>> 映射。
        scenario_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        scenario_row.pack(fill=tk.X, pady=(8, 0))
        self.theme.register(scenario_row, 'canvas')

        self._label(scenario_row, text="场景", fg_key='fg_dim',
                    bg_key='bg_app', font=(FONT_UI, FS_MD)).pack(
            side=tk.LEFT, padx=(0, 6))

        from modules import perf_scenario as _scn
        self._scn_names = list(_scn.SCENARIOS.keys())
        self._scn_labels = [_scn.SCENARIOS[k].name for k in self._scn_names]
        self.app.perf_scenario_var = tk.StringVar(value=self._scn_labels[0])
        self._scn_combo = ttk.Combobox(
            scenario_row, textvariable=self.app.perf_scenario_var,
            values=self._scn_labels, width=12, font=(FONT_UI, FS_MD),
            state="readonly", style='App.TCombobox')
        self._scn_combo.pack(side=tk.LEFT, padx=(0, 8))
        self._scn_combo.bind('<<ComboboxSelected>>', self._on_scenario_changed)

        self.app.perf_scenario_label = self._label(
            scenario_row, text="", fg_key='fg_dim', bg_key='bg_app',
            font=(FONT_UI, FS_SM), anchor=tk.W)
        self.app.perf_scenario_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 导出与状态行
        export_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        export_row.pack(fill=tk.X, pady=(8, 0))
        self.theme.register(export_row, 'canvas')

        ttk.Button(export_row, text="查看报告", command=self.app.open_perf_report,
                   style='Primary.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(export_row, text="单次快照", command=self.app.get_performance_snapshot,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(export_row, text="导出 CSV", command=self.app.export_performance_csv,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(export_row, text="导出报告", command=self.app.export_performance_report,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 12))

        # ── 基线（v5.4.7）──────────────────────────────────────
        # ⚠️ 基线功能之前**只在报告窗口里有入口**，用起来要三步：
        #    停止 → 报告窗口 → 点「与基线对比」。
        #    这里把入口提到面板上：选好基线，报告一打开就自带对比结果。
        base_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        base_row.pack(fill=tk.X, pady=(8, 0))
        self.theme.register(base_row, 'canvas')

        self._label(base_row, text="基线", fg_key='fg_dim', bg_key='bg_app',
                    font=(FONT_UI, FS_MD)).pack(side=tk.LEFT, padx=(0, 6))

        # 下拉：第 0 项恒为「不对比」，其余是已有基线（时间 + 标签）
        self.app.perf_baseline_var = tk.StringVar(value="不对比")
        self._baseline_combo = ttk.Combobox(
            base_row, textvariable=self.app.perf_baseline_var,
            values=["不对比"], width=26, font=(FONT_UI, FS_SM),
            state="readonly", style='App.TCombobox')
        self._baseline_combo.pack(side=tk.LEFT, padx=(0, 8))
        self._baseline_combo.bind('<<ComboboxSelected>>', self._on_baseline_selected)

        ttk.Button(base_row, text="刷新基线", command=self._refresh_perf_baseline_list,
                   style='Secondary.TButton', width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(base_row, text="存为基线", command=self.app.save_perf_baseline,
                   style='Secondary.TButton', width=8).pack(side=tk.LEFT, padx=(0, 6))

        self.app.perf_baseline_label = self._label(
            base_row, text="", fg_key='fg_dim', bg_key='bg_app',
            font=(FONT_UI, FS_SM), anchor=tk.W)
        self.app.perf_baseline_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 初始列出一次
        self._refresh_perf_baseline_list()

        # ⚠️ 这两个状态标签单独占一行：和导出按钮并排时会被挤出可视区。
        status_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        status_row.pack(fill=tk.X, pady=(6, 0))
        self.theme.register(status_row, 'canvas')

        self.app.perf_jank_label = self._label(
            status_row, text="卡顿率 --", fg_key='fg_dim', bg_key='bg_app',
            font=(FONT_MONO, FSM_SM, 'bold'))
        self.app.perf_jank_label.pack(side=tk.LEFT)

        self.app.perf_pid_label = self._label(
            status_row, text="PID: --   模式: --   采样: 0 次",
            fg_key='fg_dim', bg_key='bg_app', font=(FONT_MONO, FSM_SM))
        self.app.perf_pid_label.pack(side=tk.RIGHT)

        # ── 指标卡 ────────────────────────────────────────────
        metric_frame = tk.Frame(body, bg=self.theme.color('bg_app'))
        metric_frame.pack(fill=tk.X, pady=(0, 14))
        self.theme.register(metric_frame, 'canvas')
        for col in range(6):
            metric_frame.grid_columnconfigure(col, weight=1)

        metric_defs = [
            ('cpu',     "CPU 占用",  'accent'),
            ('pss',     "内存 PSS",  'success'),
            ('rss',     "内存 RSS",  'warning'),
            ('java',    "Java Heap", 'purple'),
            ('native',  "Native",    'fg_muted'),
            ('fps',     "帧率 FPS",  'accent'),
        ]
        self.app.perf_metric_labels = {}
        for col, (key, title, color_key) in enumerate(metric_defs):
            card = tk.Frame(metric_frame, bg=self.theme.color('bg_panel'),
                            highlightbackground=self.theme.color('line'),
                            highlightthickness=1)
            card.grid(row=0, column=col, sticky=tk.NSEW, padx=(0, 8))
            self.theme.register(card, 'panel')

            self._label(card, text=title, fg_key='fg_dim', bg_key='bg_panel', font=(FONT_UI, FS_SM)).pack(anchor=tk.W, padx=10, pady=(7, 0))

            # ⚠️ 指标数值用**中等**号等宽字体：
            #    28px 太大，"--" 会渲染成两条粗横杠、看着像色块；
            #    20px 既醒目又不会失真。
            cur_label = self._label(card, text="--", fg_key=color_key,
                                    bg_key='bg_panel', font=(FONT_MONO, -20, 'bold'))
            cur_label.pack(anchor=tk.W, padx=10)

            # ⚠️ 副标题必须**换行**：6 张指标卡并排时每张只有 ~90px 宽，
            #    "均值 --   峰值 --" 单行放不下会被截断成 "峰值 -"。
            sub_label = self._label(card, text="均值 --\n峰值 --", fg_key='fg_dim',
                                    bg_key='bg_panel', font=(FONT_UI, FS_XS),
                                    justify=tk.LEFT)
            sub_label.pack(anchor=tk.W, padx=10, pady=(0, 8))

            self.app.perf_metric_labels[key] = (cur_label, sub_label)

        # ── 采样明细表 ────────────────────────────────────────
        # ⚠️ 改当底部固定区的子区（**不进 Canvas**）——避免滚动卡顿
        # ⚠️ 采样表 **占满整行**（8 列需要 ~540px），
        #    线程表放在它上面（宽度约 420px 够用）。
        #    并排时两个表都只有 ~6 行高 → 整体也不会堵。
        _tables = tk.Frame(_fixed, bg=self.theme.color('bg_app'))
        _tables.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))
        self.theme.register(_tables, 'canvas')
        _tables.pack_propagate(False)
        _tables.grid_columnconfigure(0, weight=1)
        _tables.grid_rowconfigure(0, weight=3)
        _tables.grid_rowconfigure(1, weight=2)

        _col_l = tk.Frame(_tables, bg=self.theme.color('bg_app'))
        _col_l.grid(row=0, column=0, sticky=tk.NSEW, pady=(0, 6))
        self.theme.register(_col_l, 'canvas')
        _col_r = tk.Frame(_tables, bg=self.theme.color('bg_app'))
        _col_r.grid(row=1, column=0, sticky=tk.NSEW)
        self.theme.register(_col_r, 'canvas')

        _wrap2, content2 = self._section(_col_l, "采样明细", "最新在上，最近 30 条")

        samples_card = tk.Frame(content2, bg=self.theme.color('bg_panel'),
                                highlightbackground=self.theme.color('line'),
                                highlightthickness=1)
        samples_card.pack(fill=tk.BOTH, expand=True)
        self.theme.register(samples_card, 'panel')
        samples_card.grid_columnconfigure(0, weight=1)
        samples_card.grid_rowconfigure(0, weight=1)

        # ⚠️ v5.4.11：改用 **FastTable**（Listbox 实现）而不是 ttk.Treeview
        #    实测 8 列 30 行滚动：Treeview 55.1 ms → FastTable 4.7 ms（**快 11 倍**）
        #    原因：Treeview 把每行每列做成独立 item，滚动时重绘全部；
        #    Listbox 是整块文本缓冲区，只重绘可见区域。
        # 列定义：(key, 标题, 宽度px, 对齐)
        sample_cols = [('ts', '时间', 78, 'c'), ('cpu', 'CPU %', 60, 'r'),
                       ('pss', 'PSS MB', 66, 'r'), ('rss', 'RSS MB', 68, 'r'),
                       ('java', 'Java MB', 72, 'r'), ('native', 'Native MB', 82, 'r'),
                       ('fps', 'FPS', 52, 'r'), ('jank', '卡顿 %', 62, 'r')]
        self.app.perf_samples_table = FastTable(
            samples_card, columns=sample_cols, theme=self.theme)
        self.app.perf_samples_table.pack(fill=tk.BOTH, expand=True)
        # 兼容旧代码路径（clear_performance_data 等仍按 tree 的 API 调）
        self.app.perf_samples_tree = self.app.perf_samples_table

        # ── 线程表 ────────────────────────────────────────────
        _wrap3, content3 = self._section(_col_r, "线程级 CPU", "点击表头排序")

        thread_card = tk.Frame(content3, bg=self.theme.color('bg_panel'),
                               highlightbackground=self.theme.color('line'),
                               highlightthickness=1)
        thread_card.pack(fill=tk.BOTH, expand=True)
        self.theme.register(thread_card, 'panel')
        thread_card.grid_columnconfigure(0, weight=1)
        thread_card.grid_rowconfigure(0, weight=1)

        columns = [('tid', 'TID', 70, 'l'), ('name', '线程名', 150, 'l'),
                   ('cur', '当前 %', 68, 'r'), ('avg', '均值 %', 68, 'r'),
                   ('peak', '峰值 %', 68, 'r')]
        self.app.perf_thread_table = FastTable(
            thread_card, columns=columns, theme=self.theme,
            on_sort=lambda key, rev: self.app._on_perf_thread_sort(
                key, rev))
        self.app.perf_thread_table.pack(fill=tk.BOTH, expand=True)
        self.app.perf_thread_tree = self.app.perf_thread_table


        return holder

    # ------------------------------------------------------------------
    # 性能基线（v5.4.7）
    # ------------------------------------------------------------------
    def _refresh_perf_baseline_list(self):
        """刷新基线下拉列表

        ⚠️ 下拉第 0 项恒为「不对比」，其余是已有基线。
           `app.perf_baseline_index` 记的是**去掉「不对比」后的下标**，
           -1 表示不对比 —— app.get_selected_perf_baseline() 靠它取值。
        """
        try:
            baselines = self.app.list_perf_baselines()
            self.app._perf_baselines = baselines
            names = ["不对比"]
            for b in baselines:
                _t = b.get('saved_at_text', '')
                _lbl = b.get('label') or ''
                cpu = (b.get('session', {}).get('stats', {})
                       .get('cpu', {}) or {}).get('cur')
                # ⚠️ 三元表达式里**不能**给变量赋值再在别处引用 ——
                #    分支不成立时那个变量根本没被创建 → NameError。
                _cpu = (f"  CPU {cpu:.0f}%"
                        if isinstance(cpu, (int, float)) else '')
                names.append(f"{_t}{('  [' + _lbl + ']') if _lbl else ''}{_cpu}")
            self._baseline_combo['values'] = names
            # 保持当前选择（刷新后不要跳回「不对比」）
            cur = getattr(self.app, 'perf_baseline_index', -1)
            if cur is not None and 0 <= cur < len(baselines):
                self.app.perf_baseline_var.set(names[cur + 1])
                self.app.perf_baseline_index = cur
            else:
                self.app.perf_baseline_index = -1
                self.app.perf_baseline_var.set(names[0])
            if hasattr(self.app, 'perf_baseline_label'):
                n = len(baselines)
                self.app.perf_baseline_label.config(
                    text=(f"共 {n} 份基线" if n else "还没有基线，点「存为基线」保存本次测试"))
        except Exception as e:
            logging.error(f"[性能监控] 刷新基线列表失败: {e}", exc_info=True)

    def _on_baseline_selected(self, event=None):
        """选了哪份基线"""
        try:
            name = self.app.perf_baseline_var.get()
            # 下拉第 0 项是「不对比」
            idx = -1 if name == "不对比" else self._baseline_combo.current() - 1
            self.app.perf_baseline_index = idx
            if idx < 0:
                if hasattr(self.app, 'perf_baseline_label'):
                    self.app.perf_baseline_label.config(text="不与基线对比")
            else:
                bl = self.app._perf_baselines[idx]
                _t = bl.get('saved_at_text', '')
                self.app.perf_baseline_label.config(
                    text=f"将与 {_t} 对比")
        except Exception as e:
            logging.error(f"[性能监控] 选择基线失败: {e}", exc_info=True)

    def _on_scenario_changed(self, event=None):
        """场景切换：更新提示文案与内部 key"""
        from modules import perf_scenario as _scn
        label = self.app.perf_scenario_var.get()
        key = 'general'
        for k, name in zip(self._scn_names, self._scn_labels):
            if name == label:
                key = k
                break
        self.app.perf_scenario_key = key
        # 立即把新阈值推给采集器（监控中也能生效）
        try:
            self.app.apply_perf_scenario(key)
        except Exception:
            pass
        scn = _scn.get(key)
        self.app.perf_scenario_label.configure(text=scn.advice)
        try:
            self.app.update_status(
                f"🎯 场景已切换：{scn.name} —— {scn.desc}", True, "info")
        except Exception:
            pass

    # ⚠️ v5.4.11：原 `_paint_tree_tags()` 已删除 ——
    #    表格改用 FastTable（Canvas 自画）后，
    #    斑马纹/高亮/告警标红都由 FastTable 自己绘制。

    # ================================================================
    # 面板：投屏控制
    # ================================================================
    def build_mirror_panel(self):
        """投屏控制：参数设置 + 启动 + 按键模拟"""
        holder, body = self._panel(
            "投屏控制", "scrcpy 低延迟投屏，可直接模拟按键操作设备")

        # ── 投屏参数 ──────────────────────────────────────────
        _wrap, content = self._section(body, "投屏参数", "下次启动生效")

        opt_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        opt_row.pack(fill=tk.X, pady=(0, 8))
        self.theme.register(opt_row, 'canvas')

        def add_combo(parent_row, label, options, default, attr, width=7):
            self._label(parent_row, text=label, fg_key='fg_muted', bg_key='bg_app', font=(FONT_UI, FS_MD)).pack(side=tk.LEFT, padx=(0, 6))
            var = tk.StringVar(value=default)
            ttk.Combobox(parent_row, textvariable=var, values=options, width=width,
                         font=(FONT_UI, FS_MD), state="readonly",
                         style='App.TCombobox').pack(side=tk.LEFT, padx=(0, 16))
            setattr(self.app, attr, var)
            return var

        add_combo(opt_row, "码率", Config.SCRCPY_BITRATE_OPTIONS,
                  Config.SCRCPY_BITRATE, "scrcpy_bitrate_var", width=6)
        add_combo(opt_row, "帧率", Config.SCRCPY_MAX_FPS_OPTIONS,
                  Config.SCRCPY_MAX_FPS, "scrcpy_max_fps_var", width=5)
        add_combo(opt_row, "分辨率", Config.SCRCPY_MAX_SIZE_OPTIONS,
                  Config.SCRCPY_MAX_SIZE, "scrcpy_max_size_var", width=7)

        # ⚠️ 提示文字**单独占一行**，不要和参数控件挤在同一行：
        #    同排时它 req=314px，工作区窄一点就被裁成半句
        #    （实测「…（WiFi 建议 4M + 10」后面断掉）。
        #    独立一行后宽度自适应，任何窗口宽度下都完整可读。
        self._label(content, text="卡顿时先降码率，再降分辨率（WiFi 建议 4M + 1080p）",
                    fg_key='fg_dim', bg_key='bg_app', font=(FONT_UI, FS_SM),
                    anchor=tk.W).pack(fill=tk.X, pady=(0, 8))

        # ── 投屏控制 ──────────────────────────────────────────
        _wrap2, content2 = self._section(body, "投屏控制")

        self._btn_row(content2, [
            ("启动投屏", "start_screen_mirror", "primary"),
            ("停止投屏", "stop_screen_mirror", "danger"),
        ])

        # ── 方向键 ────────────────────────────────────────────
        _wrap3, content3 = self._section(body, "方向与确认")

        self._btn_row(content3, [
            ("↑ 上", "key_up", "secondary"),
            ("↓ 下", "key_down", "secondary"),
            ("← 左", "key_left", "secondary"),
            ("→ 右", "key_right", "secondary"),
            ("确认", "key_enter", "primary"),
        ])

        # ── 系统按键 ──────────────────────────────────────────
        _wrap4, content4 = self._section(body, "系统按键")

        # ⚠️ width=6：这一行有 6 个按钮，默认宽度（ttk 20 字符 = 118px）
        #    放不下，最后一个「静音」会被压成半截。
        #    「音量 +」文字实测 40px + padding 24px = 64px，
        #    6 字符足够（不截断），整行 6×76+48 = 504px 稳稳放下。
        self._btn_row(content4, [
            ("返回", "key_back", "secondary"),
            ("主页", "key_home", "secondary"),
            ("菜单", "key_menu", "secondary"),
            ("音量 +", "key_volume_up", "secondary"),
            ("音量 -", "key_volume_down", "secondary"),
            ("静音", "key_mute", "secondary"),
        ], width=6)

        # ── 电源与锁屏 ────────────────────────────────────────
        _wrap5, content5 = self._section(body, "电源与锁屏")

        self._btn_row(content5, [
            ("电源", "key_power", "danger"),
            ("锁屏", "key_lock", "secondary"),
        ])

        return holder

    # ================================================================
    # 面板：脚本执行
    # ================================================================
    def build_script_panel(self):
        """脚本执行：推送 → 运行 → 清理"""
        holder, body = self._panel(
            "脚本执行", "把 Shell 脚本推到设备上执行，适合批量操作与自动化")

        # ── 脚本选择 ──────────────────────────────────────────
        _wrap, content = self._section(body, "脚本文件", "支持拖拽 .sh 文件")

        script_row = tk.Frame(content, bg=self.theme.color('bg_app'))
        script_row.pack(fill=tk.X)
        self.theme.register(script_row, 'canvas')

        self.app.script_entry = ttk.Entry(
            script_row, font=(FONT_UI, FS_MD), style='App.TEntry')
        self.app.script_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        ttk.Button(
            script_row, text="浏览", command=self.app.browse_script,
            style='Secondary.TButton', width=8,
        ).pack(side=tk.LEFT)

        # ── 执行 ──────────────────────────────────────────────
        _wrap2, content2 = self._section(body, "执行")

        self._btn_row(content2, [
            ("推送脚本", "push_script_to_device", "primary"),
            ("启动脚本", "start_script_on_device", "primary"),
            ("停止脚本", "stop_script_on_device", "danger"),
            ("清空 tmp", "clear_tmp_directory", "secondary"),
        ])

        # ── 设备文件 ──────────────────────────────────────────
        _wrap3, content3 = self._section(body, "设备文件")

        self._btn_row(content3, [
            ("打开存储目录", "open_storage_folder", "secondary"),
            ("导出 Monkey 日志", "export_monkey_logs", "secondary"),
        ])

        return holder

    # ================================================================
    # 终端
    # ================================================================
    def _build_terminal(self):
        """右侧终端面板（可折叠）"""
        self.terminal = tk.Frame(self.root_frame, bg=self.theme.color('bg_side'),
                                 width=Config.TERMINAL_WIDTH)
        self.terminal.grid(row=0, column=3, sticky=tk.NSEW, rowspan=2)
        self.terminal.pack_propagate(False)
        self.terminal.grid_propagate(False)
        self.theme.register(self.terminal, 'side')
        self._terminal_visible = True

        # ── 标题栏 ────────────────────────────────────────────
        head = tk.Frame(self.terminal, bg=self.theme.color('bg_side'), height=40)
        head.pack(fill=tk.X)
        head.pack_propagate(False)
        self.theme.register(head, 'side')

        self._label(head, text="终端输出", fg_key='fg', bg_key='bg_side', font=(FONT_UI, FS_MD, 'bold')).pack(side=tk.LEFT, padx=12)

        ttk.Button(head, text="清空", command=self._clear_output,
                   style='Secondary.TButton', width=6).pack(side=tk.RIGHT, padx=(0, 4))
        ttk.Button(head, text="⌄", command=self._toggle_terminal,
                   style='Ghost.TButton', width=3).pack(side=tk.RIGHT, padx=(0, 8))

        # ── 搜索栏 ────────────────────────────────────────────
        search = tk.Frame(self.terminal, bg=self.theme.color('bg_side'), height=32)
        search.pack(fill=tk.X, padx=10)
        search.pack_propagate(False)
        self.theme.register(search, 'side')

        self._label(search, text="搜索", fg_key='fg_dim', bg_key='bg_side', font=(FONT_UI, FS_SM)).pack(side=tk.LEFT, padx=(0, 6))

        self.app.log_search_var = tk.StringVar()
        self.app.log_search_entry = ttk.Entry(
            search, textvariable=self.app.log_search_var, font=(FONT_MONO, FSM_MD),
            style='App.TEntry')
        self.app.log_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app.log_search_entry.bind('<Return>', lambda e: self._search_log())
        self.app.log_search_entry.bind('<Escape>', lambda e: self._clear_search())

        self.app.log_search_count = self._label(search, text="", fg_key='fg_dim', bg_key='bg_side', font=(FONT_MONO, FSM_SM), width=8, anchor=tk.CENTER)
        self.app.log_search_count.pack(side=tk.LEFT, padx=4)

        self._search_btn(search, "▼", self._search_log_next, "下一个命中")
        self._search_btn(search, "▲", self._search_log_prev, "上一个命中")

        # ── 文本区 ────────────────────────────────────────────
        text_wrap = tk.Frame(self.terminal, bg=self.theme.color('bg_side'))
        text_wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 0))
        self.theme.register(text_wrap, 'side')

        self.app.status_text = tk.Text(
            text_wrap, wrap=tk.WORD, font=(FONT_MONO, FSM_LG),
            bg=self.theme.color('terminal_bg'),
            fg=self.theme.color('terminal_fg'),
            relief=tk.FLAT, borderwidth=0,
            highlightthickness=1, highlightbackground=self.theme.color('line'),
            insertbackground=self.theme.color('terminal_fg'),
            width=44, padx=8, pady=6,
        )
        self.app.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_wrap, command=self.app.status_text.yview,
                                  style='App.Vertical.TScrollbar')
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.status_text.configure(yscrollcommand=scrollbar.set)

        self.theme.register(self.app.status_text, 'terminal')

        # ── 底部：过滤 + 进度条 ────────────────────────────────
        foot = tk.Frame(self.terminal, bg=self.theme.color('bg_side'), height=30)
        foot.pack(fill=tk.X, padx=10, pady=(6, 8))
        foot.pack_propagate(False)
        self.theme.register(foot, 'side')

        self.app.log_error_only_var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(
            foot, text="只看错误", variable=self.app.log_error_only_var,
            command=self._toggle_error_only, style='App.TCheckbutton')
        cb.pack(side=tk.LEFT)

        # ⚠️ 用紧凑样式：终端只有 340px 宽，Action.TButton 的 padding 会把
        #    按钮文字挤掉。
        _btn_export = ttk.Button(foot, text="导出", command=self._export_log,
                                 style='Compact.TButton')
        _btn_export.pack(side=tk.RIGHT, padx=(6, 0))
        # ⚠️ v5.4.8：导出/复制**跟着「只看错误」过滤** ——
        #    提示里说明，避免用户以为导出的一定是全量
        self._attach_tip(_btn_export,
                         "导出终端内容到文件\\n"
                         "勾选「只看错误」时只导出错误行")

        _btn_copy = ttk.Button(foot, text="复制", command=self._copy_all_output,
                               style='Compact.TButton')
        _btn_copy.pack(side=tk.RIGHT)
        self._attach_tip(_btn_copy,
                         "复制终端内容到剪贴板\\n"
                         "勾选「只看错误」时只复制错误行")

        # 进度条：app.py 用 pack/pack_forget 控制显隐
        prog_wrap = tk.Frame(self.terminal, bg=self.theme.color('bg_side'))
        prog_wrap.pack(fill=tk.X, padx=10, pady=(0, 6))
        self.theme.register(prog_wrap, 'side')
        self._progress_holder = prog_wrap

        self.app.progress = ttk.Progressbar(
            prog_wrap, mode="indeterminate", style='App.Horizontal.TProgressbar')
        # ⚠️ 初始隐藏：app.py 的 _set_progress_mode() 会按需 pack/pack_forget 它。
        #    一直显示会在终端底部留一条永远不动的色块。
        self.app.progress.pack_forget()

    def _toggle_terminal(self):
        """折叠 / 展开终端

        ⚠️ 顶栏的「终端 ▸」按钮只在**折叠后**出现：
           常态下它会占掉 ~78px，把包名框挤窄（包名要看全）。
           终端面板标题栏里的「⌄」负责收起，顶栏这个负责展开 ——
           两个入口职责不同，不是重复。
        """
        self._terminal_collapsed = not self._terminal_collapsed

        if self._terminal_collapsed:
            self.terminal.grid_remove()
            self.root_frame.grid_columnconfigure(3, weight=0, minsize=0)
            # 折叠后才显示「展开」入口
            self.collapse_btn.configure(text="终端 ▸")
            self.collapse_btn.pack(side=tk.LEFT)
        else:
            self.terminal.grid()
            self.root_frame.grid_columnconfigure(
                3, weight=0, minsize=Config.TERMINAL_WIDTH)
            # 展开时收起入口（终端自己的「⌄」按钮就够了）
            self.collapse_btn.pack_forget()

    # ================================================================
    # 终端辅助
    # ================================================================
    def _attach_tip(self, widget, tooltip):
        """给控件挂一个悬停提示

        ttk 没有原生 tooltip，用一个无边框 Toplevel 模拟。
        """
        def show_tip(event=None):
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            x = widget.winfo_rootx() + widget.winfo_width() // 2
            y = widget.winfo_rooty() - 24
            tip.wm_geometry(f"+{x}+{y}")
            tip_lbl = tk.Label(tip, text=tooltip,
                               background=self.theme.color('bg_elev'),
                               foreground=self.theme.color('fg'),
                               relief='solid', borderwidth=1,
                               font=(FONT_UI, FS_SM))
            tip_lbl.pack()
            self.theme.register(tip_lbl, 'elev_label')

            def close(event=None):
                try:
                    tip.destroy()
                except Exception:
                    pass

            tip.bind('<Leave>', close)
            tip.bind('<ButtonPress>', close)
            tip.after(1800, close)

        widget.bind('<Enter>', show_tip)

    def _search_btn(self, parent, text, command, tooltip):
        """带 tooltip 的紧凑搜索按钮"""
        btn = ttk.Button(parent, text=text, command=command,
                         style='Ghost.TButton', width=3)
        btn.pack(side=tk.LEFT, padx=1)
        self._attach_tip(btn, tooltip)
        return btn

    def _search_log(self):
        """在终端输出里查找关键字并高亮全部命中"""
        keyword = (self.app.log_search_var.get() or '').strip()
        if not keyword:
            self._clear_search()
            return

        text = self.app.status_text
        text.tag_remove("search_hit", "1.0", tk.END)
        text.tag_remove("search_hit_current", "1.0", tk.END)

        hits = []
        start = "1.0"
        while True:
            pos = text.search(keyword, start, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(keyword)}c"
            hits.append((pos, end))
            text.tag_add("search_hit", pos, end)
            start = end
            if len(hits) > 5000:
                break

        self._search_hits = hits
        self._search_index = 0

        if hits:
            text.tag_add("search_hit_current", *hits[0])
            text.see(hits[0][0])
            self.app.log_search_count.configure(
                text=f"{len(hits)} 处命中", fg=self.theme.color('accent'))
        else:
            self.app.log_search_count.configure(
                text="无匹配", fg=self.theme.color('error'))

    def _search_log_next(self):
        hits = getattr(self, '_search_hits', [])
        if not hits:
            self._search_log()
            return
        self._search_index = (self._search_index + 1) % len(hits)
        self._goto_hit()

    def _search_log_prev(self):
        hits = getattr(self, '_search_hits', [])
        if not hits:
            self._search_log()
            return
        self._search_index = (self._search_index - 1) % len(hits)
        self._goto_hit()

    def _goto_hit(self):
        hits = getattr(self, '_search_hits', [])
        if not hits:
            return
        text = self.app.status_text
        text.tag_remove("search_hit_current", "1.0", tk.END)
        pos, end = hits[self._search_index]
        text.tag_add("search_hit_current", pos, end)
        text.see(pos)
        self.app.log_search_count.configure(
            text=f"{self._search_index + 1}/{len(hits)}",
            fg=self.theme.color('accent'))

    def _clear_search(self):
        if hasattr(self.app, 'status_text'):
            self.app.status_text.tag_remove("search_hit", "1.0", tk.END)
            self.app.status_text.tag_remove("search_hit_current", "1.0", tk.END)
        self._search_hits = []
        self._search_index = 0
        if hasattr(self.app, 'log_search_var'):
            self.app.log_search_var.set("")
        if hasattr(self.app, 'log_search_count'):
            self.app.log_search_count.configure(text="")

    def _toggle_error_only(self):
        """只看错误：隐藏不含错误关键字的行"""
        text = self.app.status_text
        only_error = self.app.log_error_only_var.get()

        text.tag_remove("hidden_line", "1.0", tk.END)

        if not only_error:
            self.app.log_search_count.configure(text="")
            return

        content = text.get("1.0", tk.END)
        lines = content.split("\n")
        hidden = 0
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            if not self._is_error_line(line):
                # 区间留出间隙：相邻行若分别标记会被 Tk 合并成一段
                start = f"{i + 1}.0"
                end = f"{i + 1}.end - 1c"
                text.tag_add("hidden_line", start, end)
                hidden += 1

        text.tag_configure("hidden_line", elide=True)
        self.app.log_search_count.configure(
            text=f"隐藏 {hidden}/{len(lines)} 行", fg=self.theme.color('warning'))

    @staticmethod
    def _error_markers():
        """错误行的判定关键字（显示过滤与导出过滤**必须同一份**）

        ⚠️ v5.4.8 补了一批**实际会漏掉**的关键字：
           原来的表只有 `Exception`（首字母大写），
           而 Android logcat 里最典型的崩溃行是
           **`FATAL EXCEPTION`**（**全大写**）→ 漏掉！
           同类漏掉的还有 `Fatal signal`（native 崩溃）、
           `ANR in`（卡死）、`crashed`。

           这类关键字表必须覆盖 logcat 的**真实格式**，
           不能凭印象写 —— 实测漏了 4 类最关键的。

        ⚠️ v5.4.8 二次补充：
           - **中文**错误词补全（原来只有「失败」，
             漏了「出错」「错误」「异常」—— 国内 App 日志常见）
           - 日志里**没有**英文错误词、只有中文时也能识别
        """
        return (
            # 应用自身标记
            "✗", "失败",
            # ⚠️ 中文错误词（原来只有「失败」，实测漏了「出错」「错误」「异常」）
            "出错", "错误", "异常",
            # 通用英文（三种大小写都要 —— logcat 里三种都出现过）
            "error", "Error", "ERROR",
            "fail", "Fail", "FAIL",
            "failed", "Failed", "FAILED",
            # Java 异常
            "Exception", "exception", "EXCEPTION",
            "Throwable", "Error", "OutOfMemory",
            # Android 特有
            "FATAL", "Fatal", "fatal",
            "ANR", "anr",
            "signal", "SIGSEGV", "SIGABRT",
            "crashed", "crash", "Crash",
            # ⚠️ logcat 里进程崩溃的实际措辞是 **"has died"**（不是 crashed）
            "has died", "has crashed",
            "Traceback", "traceback",
            "abort", "Abort",
        )

    # ⚠️ logcat 的**级别前缀** —— 这是最可靠的错误信号，
    #    比关键字表可靠得多（关键字表永远会有漏的词）。
    #    格式： `E/Tag( 1234): msg` / `F/libc    ( 1234): msg`
    #    E=Error  F=Fatal  W=Warning（警告不算错误）
    _ERROR_LEVEL_RE = re.compile(r'^[EF]\s*/')

    @classmethod
    def _is_error_line(cls, line):
        """判断一行是否是错误行

        ⚠️ **显示过滤与导出过滤必须用同一个判定** ——
           否则会出现「界面上只显示错误行，导出的却是全量」
           这种「UI 说了、实际没做」的问题（v5.4.8 修的缺陷）。

        判定顺序：
          ① **logcat 级别前缀 E/ 或 F/** —— 最可靠
             （哪怕消息里一个错误词都没有，它也是错误行）
          ② 关键字表命中（覆盖中文日志和工具自身输出的行）
        """
        if not line.strip():
            return False
        # ① 级别前缀
        if cls._ERROR_LEVEL_RE.match(line):
            return True
        # ② 关键字
        return any(m in line for m in cls._error_markers())

    def _get_log_content(self, respect_filter=True):
        """取终端内容

        ⚠️ v5.4.8 修的缺陷：**「只看错误」之前只影响显示，导出仍是全量**。
           `tag_configure(elide=True)` 只是把行**画出来时**省略，
           `text.get("1.0", tk.END)` 拿到的仍是**全部文本** ——
           用户勾了「只看错误」再导出，导出的却是完整日志，
           以为导了错误日志其实没导。

           现在导出按当前过滤状态重新过滤一遍，
           且**与显示过滤共用同一份关键字**（`_error_markers()`），
           避免两处判定不一致。
        """
        text = self.app.status_text
        content = text.get("1.0", tk.END)
        if not respect_filter:
            return content
        try:
            only_error = bool(self.app.log_error_only_var.get())
        except Exception:
            only_error = False
        if not only_error:
            return content
        kept = [ln for ln in content.split("\n")
                if not ln.strip() or self._is_error_line(ln)]
        return "\n".join(kept)

    def _export_log(self):
        """把终端输出导出到文件

        ⚠️ 导出内容**跟着「只看错误」过滤**（见 `_get_log_content`）
        """
        if not hasattr(self.app, 'status_text'):
            return
        try:
            from tkinter import filedialog
            import datetime
            default_name = f"adbtool_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
            path = filedialog.asksaveasfilename(
                title="导出终端输出", defaultextension=".txt",
                initialfile=default_name,
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
            if not path:
                return

            content = self._get_log_content()
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            # 提示里说明导的是全量还是过滤后的（避免又产生误解）
            _filtered = self._is_error_only()
            _what = "（仅错误行）" if _filtered else "（全部内容）"
            self.app.update_status(f"已导出到: {path} {_what}", True)
        except Exception as e:
            self.app.update_status(f"导出失败: {e}", False)

    def _is_error_only(self):
        """当前是否处于「只看错误」状态"""
        try:
            return bool(self.app.log_error_only_var.get())
        except Exception:
            return False

    def _copy_all_output(self):
        """复制终端内容到剪贴板

        ⚠️ v5.4.8：**跟着「只看错误」过滤**（与导出一致）
           之前是硬取全量文本 —— 勾了「只看错误」复制出来的还是完整日志。
        """
        try:
            content = self._get_log_content()
            self.app.status_text.clipboard_clear()
            self.app.status_text.clipboard_append(content)
            _what = "（仅错误行）" if self._is_error_only() else "（全部内容）"
            self.app.update_status(f"已复制终端内容到剪贴板 {_what}", True)
        except Exception as e:
            self.app.update_status(f"复制失败: {e}", False)

    def _clear_output(self):
        if hasattr(self.app, 'status_text'):
            self.app.status_text.delete(1.0, tk.END)

    # ================================================================
    # 状态徽标
    # ================================================================
    def _paint_connection_badge(self, label):
        """按设备状态给连接徽标上色"""
        state = getattr(label, '_badge_state', 'off')
        bg = {'ok': self.theme.color('success'),
              'err': self.theme.color('error'),
              'warn': self.theme.color('warning'),
              'off': self.theme.color('fg_dim')}.get(state, self.theme.color('fg_dim'))
        label.configure(bg=bg, fg=self.theme.color('accent_fg'))

    # ================================================================
    # 杂项
    # ================================================================
    def _on_ip_selected(self, event):
        """IP 下拉选择：有效 IP 时自动连接"""
        if hasattr(self.app, 'ip_combobox'):
            value = self.app.ip_combobox.get()
            self.app.ip_combobox.set(value)
        self.app.update_connection_status()
        current_ip = self.app.get_ip_address()
        if current_ip and current_ip != "192.168.":
            self.app.connect_adb()
        else:
            self.app.show_current_device_status(force_display=True)

    # ================================================================
    # 设备切换浮层
    # ================================================================

    def _toggle_device_picker(self):
        """打开/关闭设备切换浮层"""
        try:
            self.device_picker.toggle()
        except Exception as e:
            logging.error(f"[设备切换] 浮层开关失败: {e}", exc_info=True)

    def _setup_keyboard_shortcuts(self):
        """快捷键"""
        shortcuts = {
            '<Control-q>': lambda e: self.app.root.quit(),
            '<Control-c>': lambda e: self.app.connect_adb(),
            '<Control-d>': lambda e: self.app.disconnect_adb(),
            # ⚠️ Ctrl+D 已被「断开」占用，设备切换用 Ctrl+Shift+D
            '<Control-Shift-D>': lambda e: self._toggle_device_picker(),
            '<Control-i>': lambda e: self.app.force_install(),
            '<Control-u>': lambda e: self.app.uninstall(),
            '<Control-l>': lambda e: self.app.package_list(),
            '<Control-t>': lambda e: self._toggle_theme(),
            '<Control-b>': lambda e: self._toggle_terminal(),
            '<F5>': lambda e: self.app.reboot(),
            '<F12>': lambda e: self.app.screencap(),
        }
        for shortcut, handler in shortcuts.items():
            self.app.root.bind(shortcut, handler)


class _NavButtonProxy:
    """让导航项也能像 Button 一样 invoke()（测试脚本与自动化用）"""

    def __init__(self, layout, key):
        self.layout = layout
        self.key = key

    def invoke(self):
        self.layout.switch_nav(self.key)

    def __getattr__(self, name):
        return getattr(self.layout.nav_rows[self.key], name)


def setup_gui(app):
    """GUI 入口"""
    layout = LayoutV4(app)
    layout.setup_gui()
    app.layout_instance = layout
