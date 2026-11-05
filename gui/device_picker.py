"""
设备切换浮层 —— 顶栏「设备 ▾」点开后弹出的设备列表

为什么需要它
------------
以前顶栏只有一个「设备 IP」输入框 + 一个状态徽标，导致：
- 刷新后明明检测到 1 台设备在线，顶栏却仍显示旧 IP + 「未连接」
  （徽标语义把「没有设备」和「设备在但不是我选的那个」混成了一句话）
- 多台设备在线时，用户只能手动去输入框里敲 IP 切换，
  没有「现在有哪些设备可切」的入口

本模块提供：
- **分组列表**：在线设备 / 离线与历史，各自带状态点
- **单击即切换**：点在线设备 → 设为当前目标 + 自动连接
- **型号懒加载**：先秒开列出 IP，型号在后台用一次全量 `getprop` 补齐
  （逐条 getprop 每条要 spawn 一个 adb 进程，10 台设备要 2 秒+）
- **纯 Tkinter**：不引第三方依赖

⚠️ 三条硬约束（都是实际踩过的坑）

1. **必须是主窗口的子控件，不能用 Toplevel**
   Toplevel 是独立的 OS 顶层窗口 —— 移动主窗口它纹丝不动，
   用户会以为「弹窗卡住了」。所以这里用 `place` 把浮层**盖在主窗口内部**。

2. **整行都是点击热区，且必须给出视觉提示**
   之前只在 IP 文字上绑了点击，右边的「可切换」文字看着像按钮却点不动，
   用户完全不知道该点哪。现在：
   - 整行（含状态点、IP、型号、右侧标记）都可点
   - 右侧「可切换」改成**显式的按钮样式**（带边框底色的胶囊）
   - 鼠标悬停整行高亮

3. **列表必须用纯 Canvas 绘制，不能塞 Frame 树**
   Canvas 里嵌 Frame + 几十个 Label，滚动时每个 Label 都要单独重绘 →
   实测明显卡顿。改成纯 Canvas 画 item（create_text/create_rectangle），
   滚动只重绘画布，流畅得多。

⚠️ 线程模型
   浮层本身在主线程创建/销毁；型号补齐走后台线程，
   完成后必须用 `app._run_in_ui()` 回主线程刷新 —— 后台线程直接碰
   Tk 控件会在主线程忙时抛 "main thread is not in main loop"。
"""
import logging
import tkinter as tk

from gui.theme import FONT_UI, FONT_MONO, FS_XS, FS_SM, FS_MD
# ⚠️ 顶层 import（不要放进函数里）：
#    utils 里的 load/save_device_info_cache 只在运行时被调用，
#    放函数内 import 会让 lint 判定为「死代码」。
from utils import (load_device_info_cache, save_device_info_cache,
                    run_adb_command, parse_getprop_all)

# 浮层宽度（px）—— 够放下 IP + 型号副标题
POPUP_WIDTH = 360
# 浮层最大高度（px）—— 超过就滚动，防止历史设备多时浮层顶满屏幕
POPUP_MAX_HEIGHT = 340
# 浮层固定 chrome 的高度（标题行 + 分隔线 + 底部提示）
# 视口高度 = 浮层高度 - 这个值，否则 footer 会被 canvas 挤掉
CHROME_HEIGHT = 62
# 单行高度（px）
ROW_HEIGHT = 46
# 分组标题高度（px）
GROUP_HEIGHT = 26
# 离线历史最多展示几条
MAX_HISTORY_ROWS = 8
# 型号缓存有效期（秒）—— 型号不会频繁变，缓存久一点省 adb 调用
META_CACHE_TTL = 300
# 滚动条宽度（px）—— 画在列表右侧，纯 Canvas 绘制
# ⚠️ 4px 太细了，缩放后基本看不见（等于没有）→ 用 6px，
#    并且滑块用较亮的 fg_muted（常态）/ accent（悬停），保证能看清。
SCROLLBAR_WIDTH = 6
# 滚动条滑块最小高度（px）
SCROLLBAR_MIN_THUMB = 24
# 列表内容宽度（px）—— 浮层宽 - 左右 padx - 滚动条宽 - 2px 余量
CONTENT_WIDTH = POPUP_WIDTH - 12 - SCROLLBAR_WIDTH - 2


class DevicePicker:
    """设备切换浮层（盖在主窗口内部，不是独立窗口）

    用法：
        picker = DevicePicker(app, theme, anchor_widget, host_widget)
        picker.toggle()          # 打开/关闭
        picker.refresh()         # 重新拉设备列表并重绘
    """

    def __init__(self, app, theme, anchor, host):
        self.app = app
        self.theme = theme
        self.anchor = anchor      # 「设备 ▾」按钮（定位锚点）
        self.host = host          # 浮层的父容器（主窗口内的 Frame）

        self.win = None           # 浮层容器（host 的子控件）
        self._canvas = None       # 列表画布
        self._rows = []           # 渲染后的条目 [(device_id, y0, y1)]
        self._meta_cache = {}     # {归一化设备标识: {'model':..., 'version':...}}
        self._meta_time = {}      # {归一化设备标识: 时间戳}
        self._loading_meta = set()
        self._hover_index = -1
        self._reposition_pending = False
        # 上一次主窗口的尺寸（用来区分「移动」和「缩放」）
        # ⚠️ 初始化成 0 的话，浮层打开时窗口的**首次** Configure
        #    （尺寸从 0 变成实际值）会被误判成「缩放」→ 触发一次
        #    布局未稳定时的重定位 → 浮层偏出去。这里直接记当前实际尺寸。
        try:
            self._last_host_w = self.app.root.winfo_width()
            self._last_host_h = self.app.root.winfo_height()
        except Exception:
            self._last_host_w = 0
            self._last_host_h = 0
        # 上一次算出的锚点偏移（用于识别「取值不可信」的中间态）
        self._last_ax = None
        # 上一次定位时用的浮层总高（变了才需要重新 place）
        self._placed_height = 0
        # ⚠️ 启动时加载磁盘缓存 —— 离线设备查不到 getprop，
        #    只能靠之前在线时存下来的型号信息。
        self._load_meta_cache()

    def _load_meta_cache(self):
        """从磁盘加载设备信息缓存"""
        try:
            cached = load_device_info_cache(self.app)
            if cached:
                self._meta_cache.update(cached)
                # 磁盘缓存没有时间戳，给个旧时间让它 5 分钟后重新拉
                for key in cached:
                    self._meta_time.setdefault(key, 0)
        except Exception as e:
            logging.debug(f"[设备切换] 加载设备信息缓存失败: {e}")

    def _save_meta_cache(self):
        """把设备信息缓存写回磁盘（离线设备也要能显示型号）"""
        try:
            save_device_info_cache(self._meta_cache, self.app)
        except Exception as e:
            logging.debug(f"[设备切换] 保存设备信息缓存失败: {e}")

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------

    def toggle(self):
        """打开 / 关闭浮层"""
        try:
            if self.is_open():
                self.hide()
            else:
                self.show()
        except Exception as e:
            logging.error(f"[设备切换] 浮层开关失败: {e}", exc_info=True)

    def show(self):
        """显示浮层"""
        try:
            self._build()
            # ⚠️ 重置定位基准：打开浮层时必须无条件按当前布局定位一次，
            #    不能被「与上次偏差过大」的校验挡住
            self._last_ax = None
            self._placed_height = 0
            # ⚠️ **先 _place() 再 refresh()**：
            #    refresh() → _render() 里会按内容高度重定位，
            #    但那一刻 canvas 还没真正布局完，算出来的高度/位置不准。
            #    先用当前状态定位一次（保证浮层出现在正确位置），
            #    再刷新内容（内容高度变了会再触发一次重定位）。
            self._place()
            self.refresh()
            self._place()
            self.win.place_info()  # 触发一次布局
            self.win.lift()
            # 抢焦点，让 Esc 能关
            self.win.focus_set()
        except Exception as e:
            logging.error(f"[设备切换] 显示浮层失败: {e}", exc_info=True)

    def hide(self):
        """隐藏浮层"""
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.place_forget()
        except Exception:
            pass

    def is_open(self) -> bool:
        """浮层是否处于「打开」状态

        ⚠️ 用 **place_info 的 x 是否为空**判断，而不是 `winfo_ismapped()`：
           place 之后控件还没完成映射，ismapped 会间歇性地返回 False
           （实测测试偶发失败）。place_info 才是「我们让它显示了」的准确信号。
        """
        try:
            if self.win is None or not self.win.winfo_exists():
                return False
            return self.win.place_info().get('x') is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self):
        """创建浮层（只建一次，之后只重绘内容）"""
        if self.win is not None and self.win.winfo_exists():
            return

        bg = self.theme.color('bg_elev')
        win = tk.Frame(self.host, bg=bg,
                       highlightbackground=self.theme.color('line'),
                       highlightthickness=1)
        self.win = win
        self.theme.register(win, 'elev')

        # ── 标题行 ────────────────────────────────────────────
        header = tk.Frame(win, bg=bg)
        header.pack(fill=tk.X, padx=12, pady=(9, 6))
        self.theme.register(header, 'elev')

        tk.Label(header, text="切换设备", font=(FONT_UI, FS_MD, 'bold'),
                 bg=bg, fg=self.theme.color('fg')).pack(side=tk.LEFT)
        self._count_label = tk.Label(header, text="", font=(FONT_UI, FS_SM),
                                     bg=bg, fg=self.theme.color('fg_dim'))
        self._count_label.pack(side=tk.RIGHT)
        self.theme.register(self._count_label, 'elev_label')

        # 分隔线
        sep = tk.Frame(win, bg=self.theme.color('line'), height=1)
        sep.pack(fill=tk.X)
        self.theme.register(sep, 'sep')

        # ── 底部提示 ──────────────────────────────────────────
        # ⚠️ **必须先 pack footer，再 pack canvas**：
        #    pack 按调用顺序分配空间，canvas 在前的话它会先把高度占满，
        #    footer 被挤到浮层外面（y 变成负数）→ 提示文字看不见。
        foot = tk.Frame(win, bg=bg)
        foot.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(3, 9))
        self.theme.register(foot, 'elev')
        # ⚠️ 提示文案**随内容长度变**：
        #    内容超出视口时，光有滚动条还不够 —— 底部那半截条目
        #    用户会以为是渲染错误。明确告诉他"下面还有，滚一下"。
        self._hint_label = tk.Label(
            foot, text="点击任意一行即可切换到该设备",
            font=(FONT_UI, FS_XS), bg=bg,
            fg=self.theme.color('fg_dim'))
        self._hint_label.pack(side=tk.LEFT)
        self.theme.register(self._hint_label, 'elev_label')
        self.theme.register(foot, 'elev')

        # ── 列表画布（纯 Canvas，不用 Frame 树）──────────────
        # ⚠️ **不能用 expand=True**：canvas 会撑满父容器的剩余空间，
        #    忽略我设的 height → 视口比预期高，滚动区对不上，
        #    底部内容看起来像被裁断。高度由 _render() 按内容算好后设置。
        # ⚠️ 画布 + 滚动条放在同一个横向容器里（list_row）：
        #    滚动条要贴着画布右侧，且高度与画布**严格相等**。
        #    如果分开 pack，两者高度会各自算 → 滚动条与内容错位。
        list_row = tk.Frame(win, bg=bg)
        list_row.pack(fill=tk.X, padx=6, pady=4)
        self.theme.register(list_row, 'elev')

        # ⚠️ **滚动条必须先 pack（side=RIGHT）**：
        #    pack 按调用顺序分配空间，canvas 在前的话它会把宽度吃光，
        #    滚动条只剩 2px（实测）→ 几乎看不见，等于没有。
        self._sbar = tk.Canvas(
            list_row, bg=bg, highlightthickness=0, borderwidth=0,
            height=200, width=SCROLLBAR_WIDTH)
        self._sbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.theme.register(self._sbar, 'elev')
        self._sbar.bind('<Button-1>', self._on_sbar_click)
        self._sbar.bind('<B1-Motion>', self._on_sbar_drag)
        self._sbar.bind('<Motion>', self._on_sbar_motion)
        self._sbar.bind('<Leave>', self._on_sbar_leave)

        self._canvas = tk.Canvas(
            list_row, bg=bg, highlightthickness=0, borderwidth=0,
            height=200, width=CONTENT_WIDTH)
        self._canvas.pack(side=tk.LEFT, fill=tk.Y)
        self.theme.register(self._canvas, 'elev')

        # 滚动条状态：滑块位置 + 拖拽偏移
        self._sb_thumb = None      # (y0, y1) 滑块在轨道上的位置
        self._sb_drag_off = 0      # 拖拽时鼠标相对滑块顶部的偏移
        self._sb_hover = False

        # 交互
        self._canvas.bind('<Button-1>', self._on_click)
        self._canvas.bind('<Motion>', self._on_motion)
        self._canvas.bind('<MouseWheel>', self._on_mousewheel)
        self._canvas.bind('<Leave>', self._on_leave)

        # Esc 关闭（浮层在主窗口内，所以绑在浮层上）
        win.bind('<Escape>', lambda e: self.hide())

        # 点击主窗口其它地方关闭
        self.app.root.bind('<Button-1>', self._on_root_click, add='+')

        # ⚠️ 监听主窗口的 <Configure> → **只在尺寸变化时**重新定位浮层。
        #    浮层是 place 到 host 里的，坐标相对 host —— host 跟着窗口走，
        #    浮层**自动跟随**（实测：完全不动 place，浮层与按钮的相对差恒为 0）。
        #    只有**尺寸**变化时 grid 会重排、按钮在 host 内的位置真的变了，
        #    才需要重算一次。
        #    ⚠️ 位置（移动）变化时**绝对不要**重算：
        #    那一刻 host 可能还没移动到位，
        #    `anchor.winfo_rootx() - host.winfo_rootx()` 会取到中间态，
        #    实测能让浮层偏出去 50~100px。
        self.app.root.bind('<Configure>', self._on_host_configure, add='+')

        # 主题切换后重刷配色
        self.theme.on_change(lambda name: self._retheme())

    def _on_host_configure(self, event=None):
        """主窗口**尺寸**变化 → 重新定位浮层

        ⚠️ 只在**尺寸**变化时重定位，位置（移动）变化时**不要**重算：
           浮层是 place 到 host 里的，坐标相对 host —— host 跟着窗口走，
           浮层自然跟随（这是内嵌浮层最大的好处）。
           移动窗口时重算会取到中间态，把浮层放到错误位置。
        """
        try:
            if not self.is_open():
                return
            # 只响应主窗口自身的 Configure（子控件的 Configure 也会触发）
            if event is not None and event.widget is not self.app.root:
                return
            # 位置变化（移动）→ 不用重算
            if event is not None:
                if (event.width == self._last_host_w
                        and event.height == self._last_host_h):
                    return
                self._last_host_w = event.width
                self._last_host_h = event.height
            if self._reposition_pending:
                return
            self._reposition_pending = True
            self.app.root.after_idle(self._do_reposition)
        except Exception:
            pass

    def _do_reposition(self):
        """实际执行重新定位

        ⚠️ **重定位后必须校验**：如果算出来的位置和锚点对不上
           （说明这次取到的是布局中间态），就恢复上一次的位置 ——
           内嵌浮层本身会跟着窗口走，位置稍微偏一点用户能接受，
           偏出去 50px 就很明显了。
        """
        try:
            self._reposition_pending = False
            if not self.is_open():
                return
            before = self.win.place_info()
            old_x = before.get('x')
            old_y = before.get('y')
            self._place()
            # 校验：算出来的 x 与锚点是否还对得上
            ax, _ay = self._offset_in_host(self.anchor)
            new_x = int(self.win.place_info().get('x') or 0)
            if old_x is not None and abs(new_x - int(old_x)) > 40:
                # 这次算出来的位置偏了 → 恢复
                self.win.place_configure(x=int(old_x),
                                         y=int(old_y) if old_y is not None else None)
        except Exception:
            pass

    def _retheme(self):
        """主题切换后重刷浮层配色"""
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            self.win.configure(bg=self.theme.color('bg_elev'))
            self.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 定位
    # ------------------------------------------------------------------

    def _offset_in_host(self, widget):
        """算 widget 相对 host（root 客户区）的偏移

        ⚠️ `winfo_x()`/`winfo_y()` 是相对**直接父容器**的偏移，
           要逐级向上累加才是相对 host 的位置。
           ⚠️ 不能用 `winfo_rootx()` 差值 —— 那是屏幕坐标，
              与 place 用的客户区坐标差一个窗口边框宽度。

        Returns:
            (x, y): 相对 host 的像素偏移
        """
        x = y = 0
        w = widget
        try:
            while w is not None and w is not self.host:
                x += w.winfo_x()
                y += w.winfo_y()
                w = w.master
        except Exception:
            pass
        return x, y

    def _place(self):
        """把浮层定位到锚点按钮下方

        ⚠️ 浮层是**主窗口的子控件**（place 到 app.root），
           坐标相对 root 的**客户区**。
           内嵌在主窗口内 → 移动窗口时浮层自动跟随。

        ⚠️ **坐标必须逐级累加 winfo_x()/winfo_y()**：
           锚点按钮的父容器是顶栏（bar），而 bar 在 root_frame 里用 grid 管理，
           root_frame 又在 root 里用 pack 管理。
           `winfo_x()` 是相对**直接父容器**的偏移，逐级相加才是相对 root 的位置。
           ⚠️ 用 `winfo_rootx()` 差值是**错的**：
              那是屏幕坐标，而 place 用的是客户区坐标，
              两者差一个窗口边框宽度（实测偏 50px）。
           ⚠️ 也不能把浮层放进 grid 管理的容器（root_frame/top_bar）：
              **grid 和 place 混用在同一个父容器里坐标系统会打架**。

        ⚠️ **只在打开时定位一次**：
           内嵌浮层会跟着主窗口自动移动，
           移动窗口时重算反而会取到「还没移动到位」的中间态，把浮层放偏。

        ⚠️ **左对齐到按钮左边缘**，不要右对齐：
           按钮在顶栏偏右（x≈270），浮层宽 360，右对齐算出来的 x 是负数
           → 被 clamp 到 4 → 浮层跑到窗口最左边挡住侧边栏导航。
        """
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            self.host.update_idletasks()
            self.anchor.update_idletasks()

            # 锚点按钮相对 host（root 客户区）的位置：逐级累加
            ax, ay = self._offset_in_host(self.anchor)
            ah = self.anchor.winfo_height()

            width = POPUP_WIDTH
            host_w = self.host.winfo_width()
            host_h = self.host.winfo_height()

            # 浮层总高 = 视口高 + chrome（标题/分隔线/底部提示）
            # ⚠️ chrome 高度用**实测反推**：先按估算 place 一次，
            #    再看 canvas 实际被挤掉多少（footer 先占位 + canvas pady），
            #    补回差值，footer 才不会被挤出可视区。
            #    比硬编码常量准 —— pack 的实际分配比预估多几个像素。
            view_h = getattr(self, '_view_height', 200)
            chrome = getattr(self, '_chrome_height', CHROME_HEIGHT)
            height = view_h + chrome

            # 左对齐按钮左边缘，并夹在 host 内
            x = ax
            if x + width > host_w - 4:
                x = host_w - width - 4
            x = max(4, x)

            y = ay + ah + 2
            # 下方空间不够就往上弹
            if y + height > host_h - 4:
                y = max(4, ay - height - 2)

            self.win.place(x=x, y=y, width=width, height=height)

            # ── 反推真实 chrome 高度并修正 ──────────────────────
            # 第一次 place 后 canvas 才有实际高度。
            # canvas 实际高 < 视口高 → chrome 占了更多，浮层要再加高这么多。
            try:
                self.host.update_idletasks()
                actual_view = self._canvas.winfo_height()
                if 40 < actual_view < view_h:
                    delta = view_h - actual_view
                    height += delta
                    self._chrome_height = chrome + delta
                    if y + height > host_h - 4:
                        y = max(4, ay - height - 2)
                    self.win.place_configure(height=height, y=y)
            except Exception:
                pass
        except Exception as e:
            logging.debug(f"[设备切换] 浮层定位失败: {e}")

    # ------------------------------------------------------------------
    # 渲染（纯 Canvas）
    # ------------------------------------------------------------------

    def refresh(self):
        """重新拉设备列表并重绘内容

        ⚠️ **这里不调 _place()**：
           浮层的位置在打开时算一次就够了（内嵌浮层会自己跟着窗口走）。
           refresh() 会被后台设备监控频繁触发，
           那时窗口可能正在移动 → 重定位会取到中间态 → 浮层跑偏。
        """
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            devices = self.app.get_online_devices()
            self._render(devices)
        except Exception as e:
            logging.error(f"[设备切换] 刷新列表失败: {e}", exc_info=True)

    def _render(self, online_devices):
        """按「在线 / 离线与历史」分组渲染（纯 Canvas 绘制）"""
        try:
            c = self._canvas
            c.delete('all')
            self._rows = []
            self._hover_index = -1

            t = self.theme
            bg = t.color('bg_elev')
            fg = t.color('fg')
            dim = t.color('fg_dim')
            accent = t.color('accent')
            success = t.color('success')
            line = t.color('line')

            current = self.app.get_ip_address()
            # ⚠️ 当前目标可能是「10.1.246.185:5555」（带端口），
            #    而设备列表里也是带端口的 —— 但 get_ip_address() 有时返回
            #    去掉端口的形式。**两边都要归一化再比**，
            #    否则「当前设备」永远认不出来（截图里 10.1.246.185
            #    明明是当前目标，却显示成「切换到」）。
            current_norm = self._normalize(current) if current else None
            online_norm = set()
            for d in online_devices:
                online_norm.add(self._normalize(d))
            # 记录在线集合 —— _apply_meta 刷新型号时要用它判断
            # 该行是「在线设备」还是「离线历史」，好决定要不要带「已离线」
            self._online_norm = online_norm

            y = 4
            # ⚠️ 内容宽度要**扣掉滚动条**：
            #    列表画布实际宽度 = CONTENT_WIDTH，
            #    画布宽一点就会把「切换到」胶囊画到滚动条下面被盖住。
            width = CONTENT_WIDTH

            # ── 在线设备分组 ──────────────────────────────
            y = self._draw_group(c, "在线设备", y, width, dim)
            if online_devices:
                for device in online_devices:
                    y = self._draw_row(
                        c, device, y, width,
                        online=True,
                        is_current=(current_norm is not None
                                    and self._normalize(device) == current_norm),
                        bg=bg, fg=fg, dim=dim, accent=accent,
                        success=success)
                # ⚠️ **后台补型号**（v5.4.1 修：这里原来漏了调用，
                #    导致副标题永远是「在线/已离线」，用户看不到
                #    哪个 IP 对应哪台设备 —— 而这正是这个列表存在的意义）。
                #    在线设备才查得到型号，离线的查不到。
                for device in online_devices:
                    self._load_meta_async(device)
            else:
                c.create_text(10, y + 8, text="当前没有在线设备",
                              anchor=tk.NW, font=(FONT_UI, FS_SM), fill=dim)
                y += 24

            # ── 离线与历史分组 ────────────────────────────
            history = [d for d in self.app.ip_history
                       if self._normalize(d) not in online_norm]
            if history:
                # 分隔线
                c.create_line(6, y + 4, width - 6, y + 4, fill=line)
                y += 8
                y = self._draw_group(c, "离线与历史", y, width, dim)
                for device in history[:MAX_HISTORY_ROWS]:
                    y = self._draw_row(
                        c, device, y, width,
                        online=False,
                        is_current=(current_norm is not None
                                    and self._normalize(device) == current_norm),
                        bg=bg, fg=fg, dim=dim, accent=accent,
                        success=success)
                if len(history) > MAX_HISTORY_ROWS:
                    c.create_text(10, y + 4,
                                  text=f"还有 {len(history) - MAX_HISTORY_ROWS} 条历史记录…",
                                  anchor=tk.NW, font=(FONT_UI, FS_XS), fill=dim)
                    y += 20

            # 内容总高度 → 滚动区域
            self._content_height = y + 6
            c.configure(scrollregion=(0, 0, width, self._content_height))
            # ⚠️ 视口高度 = min(内容高, 上限)
            #    canvas 的 height 决定可视区；浮层总高 = 视口 + chrome。
            #    两者必须用同一个值，否则底部要么露白、要么被裁断。
            max_view = POPUP_MAX_HEIGHT - CHROME_HEIGHT
            view_h = max(60, min(self._content_height, max_view))
            c.configure(height=view_h)
            # ⚠️ 滚动条画布高度必须与列表画布**严格相等**，
            #    否则滑块位置算出来会整体偏移（轨道比视口短/长）。
            if self._sbar is not None:
                self._sbar.configure(height=view_h)
            # 记录视口高度，_place() 用它算浮层总高
            self._view_height = view_h

            # ⚠️ 浮层高度变了要跟着变（内容变多/变少）。
            #    只在**高度真的变了**时才重定位 —— 位置不动，
            #    避免窗口移动过程中取到中间态。
            if self._placed_height != view_h + CHROME_HEIGHT:
                self._placed_height = view_h + CHROME_HEIGHT
                if self.is_open():
                    self._place()

            # 更新标题右侧的计数
            if hasattr(self, '_count_label') and self._count_label.winfo_exists():
                n = len(online_devices)
                self._count_label.config(text=f"在线 {n} 台")

            # ⚠️ **最后**才画滚动条 —— 它依赖上面算好的 content_height / view_h
            self._draw_scrollbar()

            # 提示文案随「内容是否超出视口」变
            self._update_hint(view_h)
        except Exception as e:
            logging.error(f"[设备切换] 渲染失败: {e}", exc_info=True)

    def _update_hint(self, view_h):
        """底部提示文案：内容超出视口时提示可滚动"""
        try:
            if not hasattr(self, '_hint_label'):
                return
            content_h = getattr(self, '_content_height', 0)
            if content_h > view_h + 1:
                self._hint_label.config(
                    text="点击任意一行即可切换 · 右侧滑块可滚动查看更多")
            else:
                self._hint_label.config(
                    text="点击任意一行即可切换到该设备")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 滚动条（纯 Canvas 绘制）
    # ------------------------------------------------------------------

    def _draw_scrollbar(self):
        """画右侧滚动条

        ⚠️ 为什么必须画：
           内容超出视口时（实测 10 台设备 → 内容 550px / 视口 278px），
           列表底部会被裁掉一半，用户**完全看不出下面还有东西**，
           以为就这么多设备 → 根本不知道要滚。
           滚动条是这个信息缺失的唯一视觉出口。
        """
        try:
            sb = self._sbar
            if sb is None or not sb.winfo_exists():
                return
            sb.delete('all')
            self._sb_thumb = None

            view_h = self._canvas.winfo_height()
            content_h = getattr(self, '_content_height', 0)
            if view_h <= 10 or content_h <= view_h:
                # 内容能全放下 → 不需要滚动条
                return

            track = self.theme.color('line')
            thumb_c = self.theme.color('accent') if self._sb_hover \
                else self.theme.color('fg_muted')

            # 轨道
            sb.create_rectangle(1, 0, SCROLLBAR_WIDTH - 1, view_h,
                                fill=track, outline='')
            # 滑块：高度按内容/视口比例，位置按当前滚动偏移
            ratio = view_h / float(content_h)
            thumb_h = max(SCROLLBAR_MIN_THUMB, int(view_h * ratio))
            if thumb_h > view_h:
                thumb_h = view_h
            # yview 返回 (first, last) 比例
            try:
                first = self._canvas.yview()[0]
            except Exception:
                first = 0.0
            travel = view_h - thumb_h
            thumb_y = int(travel * first)
            sb.create_rectangle(1, thumb_y, SCROLLBAR_WIDTH - 1,
                                thumb_y + thumb_h,
                                fill=thumb_c, outline='')
            self._sb_thumb = (thumb_y, thumb_y + thumb_h)
        except Exception as e:
            logging.debug(f"[设备切换] 绘制滚动条失败: {e}")

    def _update_scrollbar(self):
        """滚动后更新滑块位置"""
        try:
            if self._sbar is None:
                return
            self._draw_scrollbar()
        except Exception:
            pass

    def _on_sbar_click(self, event):
        """点击滚动条：拖到点击处（点空白处跳一屏）"""
        try:
            if self._sb_thumb is None:
                return
            view_h = self._canvas.winfo_height()
            content_h = getattr(self, '_content_height', 0)
            if view_h <= 0 or content_h <= 0:
                return
            ty0, ty1 = self._sb_thumb
            if ty0 <= event.y <= ty1:
                # 点在滑块上 → 准备拖拽，记录鼠标相对滑块顶部的偏移
                self._sb_drag_off = event.y - ty0
            else:
                # 点在轨道空白处 → 跳到该位置
                self._sb_drag_off = (ty1 - ty0) // 2
                self._scroll_to_pixel(event.y - self._sb_drag_off)
        except Exception:
            pass

    def _on_sbar_drag(self, event):
        """拖动滑块"""
        try:
            self._scroll_to_pixel(event.y - self._sb_drag_off)
        except Exception:
            pass

    def _scroll_to_pixel(self, thumb_top):
        """把滑块顶边移到 thumb_top 对应的内容位置"""
        try:
            view_h = self._canvas.winfo_height()
            content_h = getattr(self, '_content_height', 0)
            if view_h <= 0 or content_h <= 0:
                return
            ratio = view_h / float(content_h)
            thumb_h = max(SCROLLBAR_MIN_THUMB, int(view_h * ratio))
            travel = max(1, view_h - thumb_h)
            frac = min(1.0, max(0.0, thumb_top / float(travel)))
            self._canvas.yview_moveto(frac)
            self._update_scrollbar()
        except Exception:
            pass

    def _on_sbar_motion(self, event=None):
        """鼠标移到滚动条上 → 滑块高亮"""
        try:
            if self._sb_hover:
                return
            self._sb_hover = True
            self._sbar.configure(cursor='hand2')
            self._draw_scrollbar()
        except Exception:
            pass

    def _on_sbar_leave(self, event=None):
        """鼠标移出滚动条 → 恢复常态"""
        try:
            self._sb_hover = False
            self._sbar.configure(cursor='')
            self._draw_scrollbar()
        except Exception:
            pass

    def _draw_group(self, c, text, y, width, dim):
        """画分组小标题，返回新的 y"""
        c.create_text(8, y, text=text, anchor=tk.NW,
                      font=(FONT_UI, FS_XS), fill=dim)
        return y + GROUP_HEIGHT

    def _draw_row(self, c, device, y, width, online, is_current,
                  bg, fg, dim, accent, success):
        """画一行设备条目，返回新的 y

        ⚠️ **整行都是点击热区**（不是只有 IP 文字可点）——
           之前右侧写着「可切换」却点不动，用户完全不知道该点哪。
           现在：
           - 整行绑定点击
           - 悬停整行高亮（bg_hover 底色）
           - 右侧「可切换」画成**带边框的胶囊按钮**，视觉上明确是按钮
        """
        idx = len(self._rows)
        top = y
        bottom = y + ROW_HEIGHT

        # 悬停高亮背景（默认隐藏，鼠标移入时显示）
        hover_bg = self.theme.color('bg_hover')
        tag = f'row{idx}'
        c.create_rectangle(2, top, width - 2, bottom,
                           fill=hover_bg, outline='', tags=(tag, 'hover'))
        c.tag_lower('hover')

        # 状态点：●（在线）/ ○（离线）
        dot_color = success if online else dim
        c.create_text(14, top + ROW_HEIGHT / 2,
                      text="●" if online else "○",
                      font=(FONT_UI, FS_SM), fill=dot_color,
                      anchor=tk.CENTER)

        # 设备标识（主行）
        c.create_text(28, top + 13, text=self._display_id(device),
                      anchor=tk.W, font=(FONT_MONO, FS_MD), fill=fg)

        # 型号 · 版本（副行）
        # ⚠️ 打 tag（sub<行号>）—— 后台拉到型号后要**精确**更新这一行，
        #    不能用 find_overlapping 按坐标猜（会误改到别的行）。
        idx = len(self._rows)
        c.create_text(28, top + 31, text=self._meta_text(device, online),
                      anchor=tk.W, font=(FONT_UI, FS_XS), fill=dim,
                      tags=(f'sub{idx}',))

        # 右侧标记
        if is_current:
            # 当前设备：实心主色胶囊 + 文字
            label = "当前"
            tw = 46
            c.create_rectangle(width - 12 - tw, top + 12, width - 12,
                               top + 12 + 18, fill=accent, outline='')
            c.create_text(width - 12 - tw / 2, top + 21, text=label,
                          font=(FONT_UI, FS_XS), fill=self.theme.color('accent_fg'))
        elif online:
            # 可切换：**描边胶囊**，一眼看出是个可点的按钮
            label = "切换到"
            tw = 52
            c.create_rectangle(width - 12 - tw, top + 12, width - 12,
                               top + 12 + 18, fill='', outline=success,
                               width=1)
            c.create_text(width - 12 - tw / 2, top + 21, text=label,
                          font=(FONT_UI, FS_XS), fill=success)

        self._rows.append((device, top, bottom))
        return bottom + 2

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _row_at(self, y):
        """找到 y 坐标落在哪一行"""
        for i, (device, top, bottom) in enumerate(self._rows):
            if top <= y <= bottom:
                return i
        return -1

    def _on_click(self, event):
        """点击某一行 → 切换到该设备"""
        try:
            idx = self._row_at(self._canvas.canvasy(event.y))
            if idx < 0:
                return
            device = self._rows[idx][0]
            self.hide()
            self.app.select_device(device)
            # ⚠️ 型号未知时后台补拉一次：
            #    这台设备可能刚连上（列表刷新前是离线的），
            #    拉到后写进缓存，下次打开就能看到型号。
            if self._normalize(device) not in self._meta_cache:
                self._load_meta_async(device)
        except Exception as e:
            logging.error(f"[设备切换] 选中设备失败: {e}", exc_info=True)

    def _on_motion(self, event):
        """鼠标移动 → 高亮所在行"""
        try:
            idx = self._row_at(self._canvas.canvasy(event.y))
            if idx == self._hover_index:
                return
            # 取消旧高亮
            if 0 <= self._hover_index < len(self._rows):
                self._canvas.itemconfigure(
                    f'row{self._hover_index}', fill=self.theme.color('bg_elev'))
            self._hover_index = idx
            # 高亮新行
            if idx >= 0:
                self._canvas.itemconfigure(
                    f'row{idx}', fill=self.theme.color('bg_hover'))
            self._canvas.configure(cursor='hand2' if idx >= 0 else '')
        except Exception:
            pass

    def _on_leave(self, event=None):
        """鼠标移出 → 取消高亮"""
        try:
            if 0 <= self._hover_index < len(self._rows):
                self._canvas.itemconfigure(
                    f'row{self._hover_index}', fill=self.theme.color('bg_elev'))
            self._hover_index = -1
            self._canvas.configure(cursor='')
        except Exception:
            pass

    def _on_mousewheel(self, event):
        """滚轮滚动"""
        try:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
            # ⚠️ 滚轮在**列表画布**上，但滑块在**滚动条画布**上 ——
            #    两个是独立控件，不会自动同步，必须手动重画。
            self._update_scrollbar()
        except Exception:
            pass
    def _on_root_click(self, event):
        """点击主窗口其它地方 → 关闭浮层"""
        try:
            if not self.is_open():
                return
            widget = self.app.root.winfo_containing(event.x_root, event.y_root)
            if widget is None:
                self.hide()
                return
            # 在浮层内则不关
            w = str(widget)
            if w.startswith(str(self.win)):
                return
            self.hide()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 型号懒加载
    # ------------------------------------------------------------------

    def _display_id(self, device):
        """展示用的设备标识（IP 去掉端口）"""
        return self._normalize(device)

    @staticmethod
    def _normalize(device):
        """IP 设备去掉端口号，USB 序列号原样保留"""
        if not device:
            return ''
        if ':' in device and '.' in device:
            return device.split(':')[0]
        return device

    def _meta_text(self, device, online):
        """副标题：型号 · Android 版本（离线设备还要标出「已离线」）

        ⚠️ 缓存按**归一化 key** 存（去端口的 IP / USB 序列号）：
           在线列表里是「10.1.246.185:5555」，历史列表里是「10.1.246.185」，
           用同一把 key 才能命中同一台设备的型号。
        ⚠️ 离线设备**必须**也显示「已离线」——
           用户切设备时要能一眼分清「这台能连」和「这台连不上」。
        """
        meta = self._meta_cache.get(self._normalize(device))
        parts = []
        if meta:
            parts = [p for p in (meta.get('model'), meta.get('version')) if p]
        if not online:
            parts.append('已离线')
        return ' · '.join(parts) if parts else '在线'

    def _load_meta_async(self, device):
        """后台补型号信息（一次全量 getprop，别逐条查）"""
        import time
        now = time.time()
        key = self._normalize(device)
        cached_at = self._meta_time.get(key, 0)
        if key in self._meta_cache and (now - cached_at) < META_CACHE_TTL:
            return
        if key in self._loading_meta:
            return
        self._loading_meta.add(key)

        def _work():
            try:
                meta = self._fetch_meta(device)
                if meta:
                    self._meta_cache[key] = meta
                    self._meta_time[key] = time.time()
                    # ⚠️ 存盘 —— 设备离线后查不到 getprop，
                    #    靠这份缓存才能显示「这个 IP 是哪台机器」
                    self._save_meta_cache()
                    # ⚠️ 必须回主线程刷新 UI
                    self.app._run_in_ui(
                        lambda d=device, m=meta: self._apply_meta(d, m))
            except Exception as e:
                logging.debug(f"[设备切换] 读取型号失败 {device}: {e}")
            finally:
                self._loading_meta.discard(key)

        try:
            self.app.run_in_background(_work)
        except Exception:
            self._loading_meta.discard(key)

    def _apply_meta(self, device, meta):
        """把型号信息刷到对应的副标题上

        ⚠️ 用 **tag 精确定位**副标题 item，不要用 find_overlapping ——
           那个会按坐标范围匹配，主行/副行/其它文字都可能命中，
           结果把型号写到错误的行上。
        """
        try:
            if not self.is_open():
                return
            key = self._normalize(device)
            for i, (d, top, bottom) in enumerate(self._rows):
                if self._normalize(d) != key:
                    continue
                # 离线行要保留「已离线」标记
                is_online = key in getattr(self, '_online_norm', set())
                text = self._meta_text(d, is_online)
                tag = f'sub{i}'
                if self._canvas.find_withtag(tag):
                    self._canvas.itemconfigure(tag, text=text)
                break
        except Exception:
            pass

    def _fetch_meta(self, device):
        """取设备型号与 Android 版本

        ⚠️ 一次 `adb shell getprop`（不带参数）拿全部属性 ——
           逐条 getprop 每条都要 spawn 一个 adb 进程（~200ms），
           取 2 个属性 10 台设备要 4 秒；全量一次只要 ~0.3 秒/台。
        """
        # -s 用带端口的完整标识，USB 设备用序列号
        output, ok = run_adb_command(
            "adb shell getprop", retries=1, timeout=8, target_device=device)
        if not ok or not output:
            return {}
        props = parse_getprop_all(output)
        return {
            'model': props.get('ro.product.model', ''),
            'version': props.get('ro.build.version.release', ''),
        }
