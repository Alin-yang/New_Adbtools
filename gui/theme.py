"""
主题系统 —— 深色 / 浅色双套配色，支持运行时一键切换

为什么单独抽一个模块
--------------------
1. **ttk 在 Windows 上默认用 `vista` 主题，会忽略绝大多数 `background` /
   `foreground` 配置** —— 这正是旧版 UI「配色怎么改都不生效、整体显得很 low」
   的真正根因（控件背景被系统主题锁死，只有文字色偶尔生效）。
   本模块统一切到 `clam` 主题（完全可配置），再按语义令牌批量 configure，
   深色配色才真正能落到每一个控件上。
2. 纯 tk 控件（`tk.Text` / `tk.Label` / `tk.Listbox` / `tk.Frame`）
   不跟 ttk 样式走，必须单独上色 —— 用「角色注册表」记录下来，
   切换主题时逐个重新上色。
3. 颜色令牌集中在本文件，**app.py / 布局里不允许再出现裸色值**，
   避免「加了深色主题但某处还是白色」的半吊子状态。

对外 API
--------
    theme = ThemeManager(root, app)
    theme.color('success')          # 取当前主题下的某个令牌
    theme.register(widget, 'panel')  # 登记纯 tk 控件的「角色」
    theme.set_theme('light')        # 切换主题（会重刷所有已登记控件）
    theme.toggle()                  # 深/浅互切
"""
import json
import os
import tkinter as tk
from tkinter import ttk

# ── 字体 ───────────────────────────────────────────────────────────────
# Windows 上「微软雅黑 UI」渲染最干净；等宽用 Consolas。
FONT_UI = 'Microsoft YaHei UI'
FONT_MONO = 'Consolas'


# ── 颜色令牌：深色 ─────────────────────────────────────────────────────
# 取值参考 design/prototype_dark.html 的 CSS 变量，
# 终端背景比面板再暗一档，视觉上把日志区「压」下去。
DARK = {
    'bg_app':       '#0E1116',   # 窗口最外层背景
    'bg_side':      '#131720',   # 左侧导航栏
    'bg_panel':     '#171B24',   # 卡片 / 面板
    'bg_elev':      '#1D222D',   # 悬浮、输入框等抬升面
    'bg_hover':     '#232936',   # 悬停态
    'bg_active':    '#1B2540',   # 选中态（accent 的淡底）
    'line':         '#242A36',   # 分隔线
    'line_soft':    '#1C212B',   # 更弱的分隔线
    'fg':           '#E6E9EF',   # 主要文字
    'fg_muted':     '#9BA3B4',   # 次要文字
    'fg_dim':       '#6B7385',   # 三级文字 / 占位符
    'accent':       '#4C8DFF',   # 主色
    'accent_hover': '#6BA1FF',
    'accent_fg':    '#FFFFFF',   # 主色上的文字
    'success':      '#3DD68C',
    'warning':      '#F5A623',
    'error':        '#F26D6D',
    'purple':       '#A78BFA',
    'terminal_bg':  '#0B0E13',
    'terminal_fg':  '#C8D0DC',
    'hit_bg':       '#4A3A0C',   # 搜索命中高亮（深色底）
    'hit_fg':       '#FFD479',
    'hit_cur_bg':   '#8A6410',   # 当前命中
    'hit_cur_fg':   '#FFFFFF',
    'row_alt':      '#141924',   # 表格斑马纹
    'row_sel':      '#1F2A3D',   # 表格选中行
    'shadow':       '#0A0D12',
}

# ── 颜色令牌：浅色 ─────────────────────────────────────────────────────
LIGHT = {
    'bg_app':       '#F4F5F7',
    'bg_side':      '#FFFFFF',
    'bg_panel':     '#FFFFFF',
    'bg_elev':      '#F1F3F6',
    'bg_hover':     '#EDEFF3',
    'bg_active':    '#E8EFFE',
    'line':         '#E3E6EB',
    'line_soft':    '#EDEFF3',
    'fg':           '#16191F',
    'fg_muted':     '#5A6472',
    'fg_dim':       '#8A94A3',
    'accent':       '#2563EB',
    'accent_hover': '#1D4ED8',
    'accent_fg':    '#FFFFFF',
    'success':      '#0E9F6E',
    'warning':      '#D97706',
    'error':        '#DC2626',
    'purple':       '#7C3AED',
    'terminal_bg':  '#FBFCFD',
    'terminal_fg':  '#24292F',
    'hit_bg':       '#FFF3A0',
    'hit_fg':       '#7A4F01',
    'hit_cur_bg':   '#FFB300',
    'hit_cur_fg':   '#1A1A1A',
    'row_alt':      '#F7F8FA',
    'row_sel':      '#E3EDFF',
    'shadow':       '#D9DDE3',
}

THEMES = {'dark': DARK, 'light': LIGHT}

# 终端文本的标签配色（对应 status_text.tag_configure 的 tag 名）
TAG_ROLE = {
    'timestamp': 'fg_dim',
    'success':   'success',
    'error':     'error',
    'warning':   'warning',
    'info':      'accent',
    'command':   'purple',
}

# 偏好文件：主题选择跨启动保留
PREFS_PATH = os.path.join(os.path.expanduser('~'), '.adbtool_prefs.json')


class ThemeManager:
    """主题管理器：持有当前主题，负责给 ttk 样式与纯 tk 控件上色"""

    def __init__(self, root, app=None):
        self.root = root
        self.app = app
        self._name = 'dark'
        self._roles = []      # [(widget, role)]
        self._callbacks = []  # [fn(theme_name)]
        self._style = ttk.Style(root)
        self._load_prefs()
        self.apply()

    # ------------------------------------------------------------ 基础
    @property
    def name(self) -> str:
        return self._name

    @property
    def tokens(self) -> dict:
        return THEMES[self._name]

    def color(self, key: str, default: str = '#FF00FF') -> str:
        """取当前主题下的令牌颜色"""
        return self.tokens.get(key, default)

    def is_dark(self) -> bool:
        return self._name == 'dark'

    # ------------------------------------------------------------ 偏好
    def _load_prefs(self) -> None:
        try:
            if os.path.exists(PREFS_PATH):
                with open(PREFS_PATH, encoding='utf-8') as f:
                    data = json.load(f)
                name = data.get('theme')
                if name in THEMES:
                    self._name = name
        except Exception:
            pass  # 读不到就用默认，不影响启动

    def _save_prefs(self) -> None:
        try:
            with open(PREFS_PATH, 'w', encoding='utf-8') as f:
                json.dump({'theme': self._name}, f)
        except Exception:
            pass

    # ------------------------------------------------------------ 登记
    def register(self, widget, role: str) -> None:
        """登记一个纯 tk 控件的「角色」，切换主题时按角色重新上色"""
        if widget is not None:
            self._roles.append((widget, role))

    def on_change(self, callback) -> None:
        """注册主题变化回调（用于刷新运行时改过色的控件）"""
        self._callbacks.append(callback)

    # ------------------------------------------------------------ 切换
    def set_theme(self, name: str) -> None:
        if name not in THEMES or name == self._name:
            return
        self._name = name
        self._save_prefs()
        self.apply()
        for cb in self._callbacks:
            try:
                cb(name)
            except Exception:
                pass

    def toggle(self) -> None:
        self.set_theme('light' if self._name == 'dark' else 'dark')

    # ------------------------------------------------------------ 上色
    def apply(self) -> None:
        """把当前主题刷到全局：ttk 样式 + 已登记的纯 tk 控件"""
        t = self.tokens
        try:
            self.root.configure(background=t['bg_app'])
        except Exception:
            pass
        self._build_styles(t)
        for widget, role in self._roles:
            self._paint(widget, role, t)

    def _paint(self, widget, role: str, t: dict) -> None:
        """按角色给纯 tk 控件上色"""
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return

        try:
            if role == 'terminal':
                widget.config(
                    bg=t['terminal_bg'], fg=t['terminal_fg'],
                    insertbackground=t['terminal_fg'],
                    highlightbackground=t['line'],
                    highlightcolor=t['accent'],
                )
                for tag, token in TAG_ROLE.items():
                    widget.tag_configure(tag, foreground=t[token])
                widget.tag_configure('search_hit',
                                     background=t['hit_bg'], foreground=t['hit_fg'])
                widget.tag_configure('search_hit_current',
                                     background=t['hit_cur_bg'], foreground=t['hit_cur_fg'])
            elif role == 'badge':
                state = getattr(widget, '_badge_state', 'off')
                bg = {'ok': t['success'], 'err': t['error'],
                      'warn': t['warning'], 'off': t['fg_dim']}.get(state, t['fg_dim'])
                widget.config(bg=bg, fg=t['accent_fg'])
            elif role == 'listbox':
                widget.config(
                    bg=t['bg_panel'], fg=t['fg'],
                    selectbackground=t['accent'], selectforeground=t['accent_fg'],
                    highlightbackground=t['line'],
                )
            elif role == 'sep':
                widget.config(bg=t['line'])
            elif role == 'side':
                widget.config(bg=t['bg_side'])
            elif role == 'panel':
                widget.config(bg=t['bg_panel'])
            elif role == 'canvas':
                widget.config(bg=t['bg_app'])
            elif role == 'elev':
                widget.config(bg=t['bg_elev'])
            elif role == 'label':
                # 通用文字标签：跟随「当前主题 + 角色语义」
                # ⚠️ 这类控件最容易漏 —— 面板是懒加载的，
                #    切主题时若不重刷，页面上会残留上一套主题的字色/底色。
                fg_key = getattr(widget, '_fg_key', 'fg')
                bg_key = getattr(widget, '_bg_key', 'bg_app')
                widget.config(fg=t.get(fg_key, t['fg']),
                              bg=t.get(bg_key, t['bg_app']))
            elif role == 'label_side':
                widget.config(fg=t.get(getattr(widget, '_fg_key', 'fg_muted'), t['fg_muted']),
                              bg=t['bg_side'])
            elif role == 'label_panel':
                widget.config(fg=t.get(getattr(widget, '_fg_key', 'fg'), t['fg']),
                              bg=t['bg_panel'])
            elif role == 'label_elev':
                widget.config(fg=t.get(getattr(widget, '_fg_key', 'fg'), t['fg']),
                              bg=t['bg_elev'])
            elif role == 'elev_label':
                # 独立小窗（tooltip）用：抬升底色 + 次要文字
                widget.config(bg=t['bg_elev'], fg=t['fg_muted'])
        except Exception:
            pass

    # ------------------------------------------------------------ 样式表
    def _build_styles(self, t: dict) -> None:
        """按当前主题重建全部 ttk 样式

        ⚠️ 必须切到 `clam` 主题：`vista`（Windows 默认）会锁死控件背景，
           深色配色根本落不下去。clam 主题支持完整自定义。
        """
        style = self._style
        try:
            if style.theme_use() != 'clam':
                style.theme_use('clam')
        except Exception:
            pass

        # ── 容器 ────────────────────────────────────────────────
        style.configure('App.TFrame', background=t['bg_app'])
        style.configure('Side.TFrame', background=t['bg_side'])
        style.configure('Panel.TFrame', background=t['bg_panel'])
        style.configure('Elev.TFrame', background=t['bg_elev'])

        # ── 文字 ────────────────────────────────────────────────
        style.configure('App.TLabel', background=t['bg_app'],
                        foreground=t['fg'], font=(FONT_UI, 9))
        style.configure('Side.TLabel', background=t['bg_side'],
                        foreground=t['fg_muted'], font=(FONT_UI, 9))
        style.configure('Panel.TLabel', background=t['bg_panel'],
                        foreground=t['fg'], font=(FONT_UI, 9))
        style.configure('Elev.TLabel', background=t['bg_elev'],
                        foreground=t['fg'], font=(FONT_UI, 9))
        style.configure('Muted.TLabel', background=t['bg_panel'],
                        foreground=t['fg_muted'], font=(FONT_UI, 9))
        style.configure('Dim.TLabel', background=t['bg_panel'],
                        foreground=t['fg_dim'], font=(FONT_UI, 8))
        style.configure('Mono.TLabel', background=t['bg_panel'],
                        foreground=t['fg_muted'], font=(FONT_MONO, 9))
        style.configure('Title.TLabel', background=t['bg_app'],
                        foreground=t['fg'], font=(FONT_UI, 15, 'bold'))
        style.configure('Sub.TLabel', background=t['bg_app'],
                        foreground=t['fg_muted'], font=(FONT_UI, 9))
        style.configure('H1.TLabel', background=t['bg_panel'],
                        foreground=t['fg'], font=(FONT_UI, 10, 'bold'))
        style.configure('Section.TLabel', background=t['bg_panel'],
                        foreground=t['fg_dim'], font=(FONT_UI, 8, 'bold'))

        # ── 卡片 ────────────────────────────────────────────────
        style.configure('Card.TLabelframe', background=t['bg_panel'],
                        bordercolor=t['line'], lightcolor=t['line'],
                        darkcolor=t['line'], borderwidth=1, relief='solid')
        style.configure('Card.TLabelframe.Label', background=t['bg_panel'],
                        foreground=t['fg'], font=(FONT_UI, 9, 'bold'),
                        padding=(8, 3))

        # ── 按钮 ────────────────────────────────────────────────
        style.configure('Primary.TButton', background=t['accent'],
                        foreground=t['accent_fg'], font=(FONT_UI, 9),
                        bordercolor=t['accent'], lightcolor=t['accent'],
                        darkcolor=t['accent'], relief='flat',
                        padding=(12, 6), focuscolor=t['accent'])
        style.map('Primary.TButton',
                  background=[('pressed', t['accent_hover']),
                              ('active', t['accent_hover']),
                              ('disabled', t['bg_elev'])],
                  foreground=[('disabled', t['fg_dim'])])

        style.configure('Secondary.TButton', background=t['bg_elev'],
                        foreground=t['fg'], font=(FONT_UI, 9),
                        bordercolor=t['line'], lightcolor=t['line'],
                        darkcolor=t['line'], relief='flat',
                        padding=(10, 6), focuscolor=t['bg_hover'])
        style.map('Secondary.TButton',
                  background=[('pressed', t['bg_hover']),
                              ('active', t['bg_hover']),
                              ('disabled', t['bg_panel'])],
                  foreground=[('disabled', t['fg_dim'])])

        style.configure('Danger.TButton', background=t['bg_elev'],
                        foreground=t['error'], font=(FONT_UI, 9),
                        bordercolor=t['line'], lightcolor=t['line'],
                        darkcolor=t['line'], relief='flat',
                        padding=(10, 6), focuscolor=t['bg_hover'])
        style.map('Danger.TButton',
                  background=[('pressed', t['bg_hover']),
                              ('active', t['bg_hover']),
                              ('disabled', t['bg_panel'])],
                  foreground=[('disabled', t['fg_dim'])])

        # 输入框聚焦态用 accent 描边（拖拽高亮也复用它）
        style.configure('App.TEntry', fieldbackground=t['bg_elev'],
                        background=t['bg_elev'], foreground=t['fg'],
                        insertcolor=t['fg'], bordercolor=t['line'],
                        lightcolor=t['line'], darkcolor=t['line'],
                        borderwidth=1, padding=(6, 4))
        style.map('App.TEntry',
                  bordercolor=[('focus', t['accent'])],
                  lightcolor=[('focus', t['accent'])],
                  darkcolor=[('focus', t['accent'])])
        style.configure('Drop.TEntry', fieldbackground=t['bg_active'],
                        background=t['bg_active'], foreground=t['fg'],
                        insertcolor=t['fg'], bordercolor=t['accent'],
                        lightcolor=t['accent'], darkcolor=t['accent'],
                        borderwidth=2, padding=(6, 4))

        style.configure('App.TCombobox', fieldbackground=t['bg_elev'],
                        background=t['bg_elev'], foreground=t['fg'],
                        bordercolor=t['line'], lightcolor=t['line'],
                        darkcolor=t['line'], arrowcolor=t['fg_muted'],
                        borderwidth=1, padding=(6, 4))
        style.map('App.TCombobox',
                  fieldbackground=[('readonly', t['bg_elev']),
                                  ('focus', t['bg_elev'])],
                  bordercolor=[('focus', t['accent'])],
                  lightcolor=[('focus', t['accent'])],
                  darkcolor=[('focus', t['accent'])])
        # 下拉列表是独立的 tk.Listbox，走 option database
        self.root.option_add('*TCombobox*Listbox.background', t['bg_panel'])
        self.root.option_add('*TCombobox*Listbox.foreground', t['fg'])
        self.root.option_add('*TCombobox*Listbox.selectbackground', t['accent'])
        self.root.option_add('*TCombobox*Listbox.selectforeground', t['accent_fg'])

        style.configure('App.TCheckbutton', background=t['bg_panel'],
                        foreground=t['fg_muted'], font=(FONT_UI, 9),
                        focuscolor=t['bg_panel'])
        style.map('App.TCheckbutton',
                  background=[('active', t['bg_panel'])],
                  foreground=[('active', t['fg'])])

        # ── 进度条 / 滚动条 ─────────────────────────────────────
        style.configure('App.Horizontal.TProgressbar',
                        background=t['accent'], troughcolor=t['bg_elev'],
                        bordercolor=t['bg_elev'], lightcolor=t['bg_elev'],
                        darkcolor=t['bg_elev'], thickness=4)
        style.configure('App.Vertical.TScrollbar',
                        background=t['bg_elev'], troughcolor=t['bg_app'],
                        bordercolor=t['bg_app'], lightcolor=t['bg_elev'],
                        darkcolor=t['bg_elev'], arrowcolor=t['fg_dim'],
                        borderwidth=0, arrowsize=12)
        style.map('App.Vertical.TScrollbar',
                  background=[('active', t['bg_hover'])])

        # ── 表格 ────────────────────────────────────────────────
        style.configure('App.Treeview', background=t['bg_panel'],
                        fieldbackground=t['bg_panel'], foreground=t['fg'],
                        bordercolor=t['line'], lightcolor=t['line'],
                        darkcolor=t['line'], rowheight=22)
        style.map('App.Treeview',
                  background=[('selected', t['row_sel'])],
                  foreground=[('selected', t['fg'])])
        style.configure('App.Treeview.Heading', background=t['bg_elev'],
                        foreground=t['fg_muted'], font=(FONT_UI, 8, 'bold'),
                        bordercolor=t['line'], lightcolor=t['line'],
                        darkcolor=t['line'], relief='flat', padding=(4, 4))
        style.map('App.Treeview.Heading',
                  background=[('active', t['bg_hover'])],
                  foreground=[('active', t['fg'])])

        # ── 顶栏 / 侧栏专用 ─────────────────────────────────────
        style.configure('Top.TFrame', background=t['bg_app'])
        style.configure('Top.TLabel', background=t['bg_app'],
                        foreground=t['fg'], font=(FONT_UI, 9))
        style.configure('TopMuted.TLabel', background=t['bg_app'],
                        foreground=t['fg_dim'], font=(FONT_UI, 8))
        style.configure('Icon.TButton', background=t['bg_app'],
                        foreground=t['fg_muted'], font=(FONT_UI, 11),
                        borderwidth=0, relief='flat', padding=(4, 2))
        style.map('Icon.TButton',
                  background=[('active', t['bg_hover'])],
                  foreground=[('active', t['fg'])])
        style.configure('Chip.TLabel', background=t['bg_elev'],
                        foreground=t['fg_muted'], font=(FONT_UI, 8),
                        padding=(6, 2))
