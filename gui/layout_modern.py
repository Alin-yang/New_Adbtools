"""
现代化布局 - 参考 WOA AutoBot UI 风格
特点：卡片式设计、顶部Tab、彩色状态标签、底部实时日志
"""
import tkinter as tk
from tkinter import ttk
from typing import List, Tuple
import logging
from config import Config


class LayoutModern:
    """现代化布局类"""

    # Tab 名称 -> 内容构建方法（懒加载：首次切换到该 Tab 时才构建）
    TAB_BUILDERS = {
        'device': 'create_device_tab',
        'app': 'create_app_tab',
        'log_screen': 'create_log_screen_tab',
        'mirror': 'create_mirror_tab',
        'performance': 'create_performance_tab',
        'script_runner': 'create_script_runner_tab',
    }

    # 配色方案
    COLORS = {
        "primary": "#0078D4",         # 主色调（Windows蓝）
        "success": "#107C10",         # 成功（绿色）
        "warning": "#FFB900",         # 警告（黄色）
        "error": "#E81123",           # 错误（红色）
        "bg_main": "#F3F2F1",         # 主背景
        "bg_card": "#FFFFFF",         # 卡片背景
        "border": "#E1DFDD",          # 边框色
        "text_primary": "#323130",    # 主要文字
        "text_secondary": "#605E5C",  # 次要文字
        "highlight": "#E6F2FF",       # 高亮背景
    }
    
    def __init__(self, app):
        """
        初始化现代化布局
        
        Args:
            app: 应用实例
        """
        self.app = app
        self.main_frame = None
        self.top_bar = None           # 顶部栏
        self.tabs_container = None    # Tab容器
        self.content_area = None      # 内容区域
        self.log_area = None          # 日志区域
        self.tabs = {}
        self.current_tab = None
        self.tab_buttons = {}
        
    def setup_gui(self):
        """构建完整的现代化布局（左右分栏）"""
        # 设置主容器
        self.setup_main_container()

        # 创建顶部栏（标题 + 状态）
        self.create_top_bar()

        # 创建Tab导航
        self.create_tab_navigation()

        # 创建内容区域（左右分栏）
        self.create_content_area()

        # 创建右侧输出区域
        self.create_right_output_area()

        # 设置快捷键
        self.setup_keyboard_shortcuts()

        # ⚠️ 先把窗口显示出来，再构建首屏 Tab 的内容：
        #    ttk 控件创建很贵（自定义样式的 ttk.Button ~34ms/个，
        #    比经典 tk.Button 慢 5 倍），一次性建完 + 首绘要 2.4 秒。
        #    先出窗口框架、内容随后补齐，体感快得多。
        #    ⚠️ 用 update_idletasks（只重绘不处理用户事件）而不是 update()：
        #    update() 会把 idle 队列一起跑掉，等于没分帧。
        try:
            self.app.root.update_idletasks()
        except Exception:
            pass
        # 用 after 而不是 after_idle：idle 会被上面的 update 提前触发
        self.app.root.after(50, self.create_device_tab)

        # 默认显示第一个Tab
        self.app.root.after(100, lambda: self.switch_tab("device"))
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root, style='Modern.TFrame')
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 配置窗口（尺寸统一由 Config 控制，这里不要再硬编码覆盖）
        self.app.root.title("ADB Tool v2.0")
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        self.app.root.minsize(*Config.MIN_WINDOW_SIZE)
        
        # 使用grid布局，左右分栏
        self.main_frame.grid_rowconfigure(0, weight=0)  # 顶部栏
        self.main_frame.grid_rowconfigure(1, weight=0)  # Tab导航
        self.main_frame.grid_rowconfigure(2, weight=0)  # 底部边框
        self.main_frame.grid_rowconfigure(3, weight=1)  # 内容区域（左右分栏）
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        # 配置样式
        self._setup_styles()
    
    def _setup_styles(self) -> None:
        """配置现代化样式"""
        style = ttk.Style()
        
        # 主框架样式
        style.configure('Modern.TFrame', background=self.COLORS["bg_main"])
        style.configure('Card.TFrame', background=self.COLORS["bg_card"])
        style.configure('Card.TLabel', 
                       background=self.COLORS["bg_card"],
                       foreground=self.COLORS["text_primary"])
        style.configure('Card.TLabelframe', 
                       background=self.COLORS["bg_card"],
                       foreground=self.COLORS["text_primary"],
                       borderwidth=2,
                       relief='solid')
        style.configure('Card.TLabelframe.Label',
                       font=('Microsoft YaHei UI', 10, 'bold'),
                       background=self.COLORS["bg_card"],
                       foreground=self.COLORS["primary"],
                       padding=(8, 4))
        
        # 卡片标题样式
        style.configure('CardTitle.TLabel',
                       font=('Microsoft YaHei UI', 11, 'bold'),
                       background=self.COLORS["bg_card"],
                       foreground=self.COLORS["text_primary"])
        
        # Tab按钮样式（未选中）
        style.configure('ModernTab.TButton',
                       font=('Microsoft YaHei UI', 8),
                       padding=(10, 4),
                       background=self.COLORS["bg_card"],
                       foreground=self.COLORS["text_primary"],
                       relief='flat')
        
        # Tab按钮样式（选中）
        style.configure('ModernTabSelected.TButton',
                       font=('Microsoft YaHei UI', 8, 'bold'),
                       padding=(10, 4),
                       background=self.COLORS["highlight"],
                       foreground=self.COLORS["primary"],
                       relief='flat')
        
        # 功能按钮样式（主要操作）
        style.configure('Primary.TButton',
                       font=('Microsoft YaHei UI', 8),
                       padding=(6, 3),
                       foreground=self.COLORS["text_primary"],
                       background='#FFFFFF',
                       relief='flat')
        style.map('Primary.TButton',
                 background=[('active', self.COLORS["highlight"])],
                 foreground=[('!disabled', self.COLORS["text_primary"])])
        
        # 功能按钮样式（次要操作）
        style.configure('Secondary.TButton',
                       font=('Microsoft YaHei UI', 8),
                       padding=(6, 3),
                       foreground=self.COLORS["text_primary"],
                       background='#FFFFFF',
                       relief='flat')
        style.map('Secondary.TButton',
                 background=[('active', self.COLORS["highlight"])])
        
        # 危险操作按钮
        style.configure('Danger.TButton',
                       font=('Microsoft YaHei UI', 8),
                       padding=(6, 3),
                       foreground=self.COLORS["text_primary"],
                       background='#FFFFFF',
                       relief='flat')
        style.map('Danger.TButton',
                 background=[('active', self.COLORS["highlight"])],
                 foreground=[('!disabled', self.COLORS["text_primary"])])
        
        # 状态标签样式
        style.configure('StatusConnected.TLabel',
                       font=('Microsoft YaHei UI', 9, 'bold'),
                       background=self.COLORS["success"],
                       foreground='white',
                       padding=(8, 4),
                       anchor='center')  # 文字居中
        
        style.configure('StatusDisconnected.TLabel',
                       font=('Microsoft YaHei UI', 9, 'bold'),
                       background='#C8C6C4',
                       foreground='white',
                       padding=(8, 4),
                       anchor='center')  # 文字居中
        
        # 配置鼠标悬停效果
        style.map('ModernTab.TButton',
                 background=[('active', self.COLORS["highlight"])])
        style.map('Primary.TButton',
                 background=[('active', '#005A9E')])
        style.map('Secondary.TButton',
                 background=[('active', self.COLORS["highlight"])])
        style.map('Danger.TButton',
                 background=[('active', '#C30010')])
    
    def create_top_bar(self) -> None:
        """创建顶部栏"""
        # ⚠️ 高度必须 ≥ 嵌套 LabelFrame 的需求高度（实测 req_h=67）：
        #    之前设 60 会把内层按钮从 30px 压到 23px，文字显示不全。
        self.top_bar = ttk.Frame(self.main_frame, style='Card.TFrame', height=70)
        self.top_bar.grid(row=0, column=0, sticky=tk.EW, padx=10, pady=(10, 0))
        self.top_bar.pack_propagate(False)
        
        # === 左侧：标题和版本 ===
        title_frame = ttk.Frame(self.top_bar, style='Card.TFrame')
        title_frame.pack(side=tk.LEFT, padx=15, pady=10)
        
        ttk.Label(
            title_frame,
            text="ADB Tool",
            font=('Microsoft YaHei UI', 16, 'bold'),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["primary"]
        ).pack(side=tk.LEFT)
        
        ttk.Label(
            title_frame,
            text=f"v{Config.APP_VERSION}",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"]
        ).pack(side=tk.LEFT, padx=(8, 0), pady=(5, 0))

        # === 中间：设备信息 ===
        device_frame = ttk.LabelFrame(
            self.top_bar,
            text="📱 当前设备",
            style='Card.TLabelframe',
            padding=(8, 5)
        )
        device_frame.pack(side=tk.LEFT, padx=15)

        # IP输入框
        ip_row = ttk.Frame(device_frame, style='Card.TFrame')
        ip_row.pack(fill=tk.X, pady=2)

        ttk.Label(
            ip_row,
            text="设备:",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_primary"]
        ).pack(side=tk.LEFT, padx=(0, 8))

        # ⚠️ 宽度处理：之前 width=20 + expand=True，实测只显示 "192.168." ——
        #    用户连自己填的 IP 都看不全。原因是 expand=True 让 combobox 抢走
        #    全部富余空间（实测膨胀到 508px），把旁边的按钮挤成 86px。
        #    现在不用 expand，给固定宽度；富余空间由顶栏右侧的状态区消化。
        self.app.ip_combobox = ttk.Combobox(
            ip_row, width=22, font=('Microsoft YaHei UI', 9))
        self.app.ip_combobox.pack(side=tk.LEFT, padx=(0, 8))
        # 记录实际宽度，供窗口缩放时按比例调整
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox.insert(0, "192.168.")

        # 连接状态标签（使用 tk.Label 以获得更好的对齐控制）
        self.app.connection_status_label = tk.Label(
            ip_row,
            text="● 未连接",
            font=('Microsoft YaHei UI', 9, 'bold'),
            background='#C8C6C4',
            foreground='white',
            width=11,
            relief='flat',
            anchor='center'  # 文字居中
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(0, 6))

        # ⚠️ 顶部栏补「连接 / 断开」：连设备是最高频动作，
        #    之前必须跨到「设备管理」Tab 才能点「🔌连接ADB」。
        # ⚠️ 顶栏空间紧张，按钮里不要放 emoji：
        #    ttk 的 width 按「字符数」算，不计 emoji 的双宽，
        #    结果「🔌 连接」被算成 86px，文字直接被压扁成色块。
        #    顶栏用纯文字，卡片区（空间充裕）才用 emoji。
        self.app.btn_connect_top = ttk.Button(
            ip_row, text="连接", command=self.app.connect_adb,
            style='Primary.TButton')
        self.app.btn_connect_top.pack(side=tk.LEFT, padx=(0, 4))

        self.app.btn_disconnect_top = ttk.Button(
            ip_row, text="断开", command=self.app.disconnect_adb,
            style='Secondary.TButton')
        self.app.btn_disconnect_top.pack(side=tk.LEFT)

        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)

        # === 右侧：状态指示器 ===
        status_frame = ttk.Frame(self.top_bar, style='Card.TFrame')
        status_frame.pack(side=tk.RIGHT, padx=15)

        # 设备数量标签
        self.app.device_count_label = ttk.Label(
            status_frame,
            text="已连接: 0 台",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"]
        )
        self.app.device_count_label.pack(side=tk.LEFT, padx=5)

        # 刷新按钮 —— ⚠️ 之前绑的是 show_device_info（查看设备信息），
        #    按钮写着「刷新设备」实际却不刷新设备列表。
        refresh_btn = ttk.Button(
            status_frame,
            text="🔄 刷新设备",
            command=self.app.refresh_device_list,
            style='Primary.TButton',
            width=12
        )
        refresh_btn.pack(side=tk.LEFT, padx=5)
    
    def create_tab_navigation(self) -> None:
        """创建顶部Tab导航"""
        self.tabs_container = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.tabs_container.grid(row=1, column=0, sticky=tk.EW, padx=10, pady=(5, 0))
        
        # Tab按钮配置
        tab_configs = [
            ("📱 设备管理", "device"),
            ("📦 应用管理", "app"),
            ("📋 日志录屏", "log_screen"),
            ("🖥️ 投屏", "mirror"),  # 投屏 Tab
            ("📊 性能监控", "performance"),  # 性能监控 Tab
            ("🔧 脚本运行", "script_runner"),  # 脚本运行 Tab
        ]
        
        for i, (text, tab_name) in enumerate(tab_configs):
            btn = ttk.Button(
                self.tabs_container,
                text=text,
                command=lambda t=tab_name: self.switch_tab(t),
                style='ModernTab.TButton',
                width=13
            )
            btn.pack(side=tk.LEFT, padx=2)
            self.tab_buttons[tab_name] = btn
        
        # 底部边框线
        border = tk.Frame(self.main_frame, bg=self.COLORS["border"], height=2)
        border.grid(row=2, column=0, sticky=tk.EW, padx=10)
    
    def switch_tab(self, tab_name: str) -> None:
        """切换Tab页（使用 tkraise 优化，避免 grid_remove+grid 触发布局重算卡顿）"""
        # 所有 Tab 均已 grid 在同一 cell 叠放，仅提升选中项的 Z 顺序
        # ⚠️ Tab 内容懒加载：首次切到某个 Tab 时才构建它。
        #    启动时一次性构建 7 个 Tab 要 4.3s + 首绘 3.0s，而同一刻只显示一个。
        if tab_name not in self.tabs:
            builder = self.TAB_BUILDERS.get(tab_name)
            if builder:
                try:
                    getattr(self, builder)()
                except Exception:
                    logging.exception("[布局] 构建 Tab 失败: %s", tab_name)

        if tab_name in self.tabs:
            self.tabs[tab_name].tkraise()

        # 性能监控页信息密度高（指标卡 + 两张数据表），临时把左右分栏比例倾斜给它
        # 仅在当前 Tab 真正变化时才重排，避免重复点击触发多余布局计算
        if getattr(self, 'current_tab', None) != tab_name:
            if hasattr(self, 'content_frame'):
                wide = (tab_name == 'performance')
                # ⚠️ 右栏 minsize 不能太小：终端搜索栏需要 ~360px 才能
                #    完整显示（搜索框 + 计数 + 导航 + 菜单）。之前设 260，
                #    在 1280 宽的窗口里右栏被压到 356px，搜索栏布局全乱。
                self.content_frame.grid_columnconfigure(
                    0, weight=6 if wide else 1, minsize=620 if wide else 300)
                self.content_frame.grid_columnconfigure(
                    1, weight=1 if wide else 3, minsize=360 if not wide else 260)

            # 更新Tab选中效果
            self._update_tab_selection(tab_name)
    
    def _update_tab_selection(self, selected_tab: str) -> None:
        """更新Tab选中效果"""
        if not hasattr(self, 'tab_buttons'):
            return
        
        for tab_name, btn in self.tab_buttons.items():
            if tab_name == selected_tab:
                btn.configure(style='ModernTabSelected.TButton')
            else:
                btn.configure(style='ModernTab.TButton')
        
        self.current_tab = selected_tab
    
    def create_content_area(self) -> None:
        """创建内容区域（左右分栏）"""
        # 创建主内容容器
        content_frame = ttk.Frame(self.main_frame, style='Modern.TFrame')
        content_frame.grid(row=3, column=0, sticky=tk.NSEW, padx=10, pady=8)
        
        self.content_frame = content_frame   # 保存引用，性能Tab切换时需调整左右比例

        # 配置主容器的grid
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=1, minsize=300)  # 左侧功能按钮区
        content_frame.grid_columnconfigure(1, weight=3)  # 右侧输出框区（弹性扩展，更宽）
        
        # === 左侧：功能按钮区域 ===
        left_panel = ttk.Frame(content_frame, style='Card.TFrame')
        left_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
        
        # 配置左侧面板
        left_panel.grid_rowconfigure(0, weight=1)
        left_panel.grid_columnconfigure(0, weight=1)
        
        self.content_area = left_panel  # Tab内容放在左侧
        
        # === 右侧：输出框区域 ===
        right_panel = ttk.Frame(content_frame, style='Card.TFrame')
        right_panel.grid(row=0, column=1, sticky=tk.NSEW, padx=(5, 0))
        
        # 配置右侧面板
        right_panel.grid_rowconfigure(0, weight=0)  # 标题行
        right_panel.grid_rowconfigure(1, weight=1)  # 输出框（弹性扩展）
        right_panel.grid_rowconfigure(2, weight=0)  # 进度条
        right_panel.grid_columnconfigure(0, weight=1)
        
        self.output_area = right_panel
    
    def create_device_tab(self) -> None:
        """创建设备管理Tab（左侧功能按钮，两列排布填满横向空间）"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['device'] = tab

        # 让tab填满整个区域
        tab.grid(row=0, column=0, sticky=tk.NSEW)
        # ⚠️ 本 Tab 只有一列内容：多设一个空列会让这一列只分到一半宽度（右侧留白）
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # 创建主容器，分为上下两部分
        main_container = ttk.Frame(tab, style='Card.TFrame')
        main_container.grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)
        # ⚠️ main_container 只有一列：多余的空列会让这唯一的一列只分到一半宽度，
        #    卡片区就贴不满左侧面板（右侧留白）
        main_container.grid_columnconfigure(0, weight=1)
        main_container.grid_rowconfigure(0, weight=0)  # 按钮区域
        main_container.grid_rowconfigure(1, weight=1)  # 弹性空白区域

        # 按钮容器（两列，卡片横向拉伸铺满，避免右侧留白）
        button_frame = ttk.Frame(main_container, style='Card.TFrame')
        button_frame.grid(row=0, column=0, sticky="ew")
        # 两列等宽（uniform 保证左右卡片一样宽），横向铺满整块区域
        button_frame.grid_columnconfigure(0, weight=1, uniform="devcols")
        button_frame.grid_columnconfigure(1, weight=1, uniform="devcols")

        # --- 第一行：ADB 服务管理 | 设备信息 ---
        self._create_card(button_frame, "ADB 服务管理", [
            ("🔌连接ADB", "connect_adb", "primary"),
            ("❌断开所有", "disconnect_adb", "danger"),
            ("🔄重启服务", "restart_adb_server", "secondary"),
        ], row=0, col=0)

        self._create_card(button_frame, "设备信息", [
            ("📱查看设备", "show_device_info", "primary"),
            ("📋详细信息", "get_device_info_fast", "secondary"),
            ("🔍获取串号", "get_serial_number", "secondary"),
        ], row=0, col=1)

        # --- 第二行：设备控制 | 系统工具 ---
        self._create_card(button_frame, "设备控制", [
            ("🔁重启设备", "reboot", "primary"),
            ("🔑Root权限", "root_device", "secondary"),
            ("📀重新挂载", "remount", "secondary"),
        ], row=1, col=0)

        # ⚠️ 原「高级工具」Tab 只有「工厂菜单」一个按钮，单独占一个 Tab
        #   太浪费（实测纵向空白 82%）—— 已合并到这里
        self._create_card(button_frame, "系统工具", [
            ("🖥️打开CMD", "open_cmd_window", "secondary"),
            ("📝常用命令", "show_common_adb_commands", "secondary"),
            ("🔍Android版本", "get_android_version", "secondary"),
            ("🔧工厂菜单", "open_factory_menu", "secondary"),
        ], row=1, col=1)

        # --- 第三行：文本输入（跨两列）---
        self._create_text_input_card(button_frame, row=2, col=0, colspan=2)
    
    def create_app_tab(self) -> None:
        """创建应用管理Tab"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['app'] = tab
        
        tab.columnconfigure(0, weight=1, uniform="appcols")
        tab.columnconfigure(1, weight=1, uniform="appcols")
        tab.grid(row=0, column=0, sticky=tk.NSEW)

        # 应用输入卡片
        self._create_app_input_card(tab, row=0, col=0, colspan=2)
        
        # 功能卡片
        self._create_card(
            tab,
            "应用操作",
            [
                ("📲强制安装", "force_install", "primary"),
                ("🗑️卸载应用", "uninstall", "danger"),
                ("🧹清除缓存", "clear_cache", "secondary"),
            ],
            row=1, col=0
        )
        
        self._create_card(
            tab,
            "启动与进程",
            [
                ("▶️启动应用", "start_app", "primary"),
                ("⏹️终止进程", "kill_app_process", "danger"),
                ("📊资源占用", "get_app_resource_usage", "secondary"),
            ],
            row=1, col=1
        )
        
        self._create_card(
            tab,
            "应用信息",
            [
                ("🔍版本号", "get_version", "secondary"),
                ("📂安装路径", "get_package_path", "secondary"),
                ("🔍当前包名", "get_package_name", "secondary"),
            ],
            row=2, col=0
        )
        
        self._create_card(
            tab,
            "应用列表",
            [
                ("📋已安装列表", "package_list", "primary"),
            ],
            row=2, col=1
        )
    
    def create_log_screen_tab(self) -> None:
        """创建日志录屏Tab"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['log_screen'] = tab
        
        tab.columnconfigure(0, weight=1, uniform="logcols")
        tab.columnconfigure(1, weight=1, uniform="logcols")
        tab.grid(row=0, column=0, sticky=tk.NSEW)

        # 日志设置卡片
        self._create_log_settings_card(tab, row=0, col=0, colspan=2)
        
        # 功能卡片
        self._create_card(
            tab,
            "日志捕获",
            [
                ("▶️开始捕获", "start_logcat", "primary"),
                ("⏹️停止捕获", "stop_logcat", "danger"),
                ("🧹清除缓存", "log_clear", "secondary"),
            ],
            row=1, col=0, fill_vertical=True
        )
        
        self._create_card(
            tab,
            "ANR与命令",
            [
                ("📥导出ANR", "pull_anr_file", "secondary"),
                ("📜原始命令", "show_all_adb_commands", "secondary"),
            ],
            row=1, col=1, fill_vertical=True
        )
        
        self._create_card(
            tab,
            "屏幕操作",
            [
                ("🎥开始录制", "start_recording", "primary"),
                ("⏹️停止录制", "stop_recording", "danger"),
                ("📷截屏", "screencap", "secondary"),
            ],
            row=2, col=0, fill_vertical=True
        )
        
        # 打开存储文件夹
        self._create_card(
            tab,
            "文件管理",
            [
                ("📂打开存储文件夹", "open_storage_folder", "primary"),
            ],
            row=2, col=1, fill_vertical=True
        )
    
    def create_mirror_tab(self) -> None:
        """创建投屏Tab"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['mirror'] = tab

        # ⚠️ 改成双列：本 Tab 卡片最多（参数 + 说明 + 4 组按键），
        #    单列时底部「系统控制」会被窗口裁掉，电源/锁屏按钮点不到。
        tab.columnconfigure(0, weight=1, uniform="mirrorcols")
        tab.columnconfigure(1, weight=1, uniform="mirrorcols")
        tab.grid(row=0, column=0, sticky=tk.NSEW)

        # 投屏参数卡片（码率 / 分辨率 / 帧率）
        # ⚠️ 这三个值以前写死在代码里，投屏卡顿或模糊时用户唯一能做的
        #    就是改代码重新打包 —— 没有任何自救手段。
        self._create_mirror_options_card(tab, row=0, col=0)

        # 使用说明卡片
        info_card = ttk.LabelFrame(
            tab,
            text="💡 使用说明",
            style='Card.TLabelframe',
            padding=(12, 6)
        )
        info_card.grid(row=1, column=0, sticky=tk.EW, padx=6, pady=(0, 6))

        # 说明文字压到 4 行：本 Tab 内容最多，文字一多就会把底部的
        # 「系统控制」卡片顶出窗口（电源/锁屏按钮点不到）
        info_text = (
            "🔹 scrcpy 投屏已集成，支持点击/滑动等完整交互，低延迟（<100ms）\n"
            "🔹 点击“启动投屏”即可镜像手机或 TV 屏幕；下方按键可模拟操作设备\n"
            "🔹 投屏卡顿？先降码率/分辨率；投屏时建议关闭设备省电模式"
        )
        info_label = ttk.Label(
            info_card,
            text=info_text,
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["primary"],
            justify=tk.LEFT,
            wraplength=520
        )
        info_label.pack(anchor=tk.W, padx=5, pady=3)
        
        # 投屏控制卡片
        self._create_card(
            tab,
            "投屏控制",
            [
                ("🖥️ 启动投屏", "start_screen_mirror", "primary"),
                ("⏹️ 停止投屏", "stop_screen_mirror", "danger"),
            ],
            row=2, col=0
        )
        
        # 按键模拟卡片
        self._create_card(
            tab,
            "按键模拟",
            [
                ("⬆️ 上", "key_up", "secondary"),
                ("⬇️ 下", "key_down", "secondary"),
                ("⬅️ 左", "key_left", "secondary"),
                ("➡️ 右", "key_right", "secondary"),
                ("✅ 确认", "key_enter", "primary"),
            ],
            row=2, col=1
        )
        
        # 系统按键卡片（分两行）
        # 第一行：返回、主页、菜单、音量
        self._create_card(
            tab,
            "系统按键",
            [
                ("⏪ 返回", "key_back", "secondary"),
                ("🏠 主页", "key_home", "secondary"),
                ("📋 菜单", "key_menu", "secondary"),
            ],
            row=3, col=0
        )
        
        # 第二行：音量、电源、锁屏
        self._create_card(
            tab,
            "系统控制",
            [
                ("🔊 音量+", "key_volume_up", "secondary"),
                ("🔉 音量-", "key_volume_down", "secondary"),
                ("🔇 静音", "key_mute", "secondary"),
                ("⏻ 电源", "key_power", "danger"),
                ("🔒 锁屏", "key_lock", "secondary"),
            ],
            row=3, col=1
        )
    
    def create_script_runner_tab(self) -> None:
        """创建脚本运行Tab"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['script_runner'] = tab
        
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)  # Shell脚本管理
        tab.rowconfigure(1, weight=1)  # Monkey日志导出 + 设备文件（左右排列，扩展）
        tab.grid(row=0, column=0, sticky=tk.NSEW)
        
        # 脚本选择卡片
        script_card = ttk.LabelFrame(
            tab,
            text="📜 Shell脚本管理",
            style='Card.TLabelframe',
            padding=(10, 8)
        )
        script_card.grid(row=0, column=0, columnspan=2, sticky=tk.NSEW,
                        padx=6, pady=6)
        
        # 脚本文件路径行
        script_row = ttk.Frame(script_card, style='Card.TFrame')
        script_row.pack(fill=tk.X, pady=5)
        
        ttk.Label(
            script_row,
            text="脚本文件:",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"]
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        self.app.script_entry = ttk.Entry(
            script_row,
            font=('Microsoft YaHei UI', 9),
            width=40
        )
        self.app.script_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        browse_btn = ttk.Button(
            script_row,
            text="浏览",
            command=self.app.browse_script,
            style='Secondary.TButton',
            width=8
        )
        browse_btn.pack(side=tk.LEFT)
        
        # 操作按钮行
        btn_row = ttk.Frame(script_card, style='Card.TFrame')
        btn_row.pack(fill=tk.X, pady=8)
        
        push_btn = ttk.Button(
            btn_row,
            text="📤 推送脚本",
            command=self.app.push_script_to_device,
            style='Primary.TButton'
        )
        push_btn.pack(side=tk.LEFT, padx=5)
        
        start_btn = ttk.Button(
            btn_row,
            text="▶️ 启动脚本",
            command=self.app.start_script_on_device,
            style='Primary.TButton'
        )
        start_btn.pack(side=tk.LEFT, padx=5)
        
        stop_btn = ttk.Button(
            btn_row,
            text="⏹️ 停止脚本",
            command=self.app.stop_script_on_device,
            style='Danger.TButton'
        )
        stop_btn.pack(side=tk.LEFT, padx=5)
        
        clear_btn = ttk.Button(
            btn_row,
            text="🗑️ 清空tmp",
            command=self.app.clear_tmp_directory,
            style='Secondary.TButton'
        )
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        # ⚠️ Monkey日志导出卡片：原来只有一个按钮，且 sticky=tk.N 贴顶显示，
        #    下方 275px 全空（实测纵向空白 56%）。
        #    现在：① 改成左右双列（与脚本管理并排）② 补上有用的操作
        #    ③ 纵向拉伸填满剩余空间
        monkey_card = ttk.LabelFrame(
            tab,
            text="🐒 Monkey 日志导出",
            style='Card.TLabelframe',
            padding=(10, 8)
        )
        monkey_card.grid(row=1, column=0, sticky=tk.NSEW, padx=6, pady=(2, 6))

        # 说明文字：让用户知道这个功能干什么
        ttk.Label(
            monkey_card,
            text="导出 Monkey 测试产生的崩溃/ANR 日志，\n"
                 "用于定位应用稳定性问题",
            font=('Microsoft YaHei UI', 8),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"],
            justify=tk.LEFT
        ).pack(anchor=tk.W, padx=4, pady=(4, 2))

        # 操作按钮行
        monkey_btn_row = ttk.Frame(monkey_card, style='Card.TFrame')
        monkey_btn_row.pack(fill=tk.X, pady=4)

        export_btn = ttk.Button(
            monkey_btn_row,
            text="📤 导出 Monkey 日志",
            command=self.app.export_monkey_logs,
            style='Primary.TButton'
        )
        export_btn.pack(side=tk.LEFT, padx=4)

        # 右侧：与 Monkey 相关的辅助操作
        self._create_card(
            tab,
            "设备文件",
            [
                ("📂打开存储", "open_storage_folder", "secondary"),
                ("🧹清空tmp", "clear_tmp_directory", "secondary"),
            ],
            row=1, col=1, fill_vertical=True
        )
    
    def create_performance_tab(self) -> None:
        """创建性能监控Tab（重写版：控制条 + 指标卡 + 实时趋势图 + 线程表格）"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['performance'] = tab

        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)   # 采样明细表
        tab.rowconfigure(3, weight=1)   # 线程表
        tab.grid(row=0, column=0, sticky=tk.NSEW)

        # ============ Row0: 采样控制卡片 ============
        control_card = ttk.LabelFrame(
            tab, text="⚡ 采样控制", style='Card.TLabelframe', padding=(10, 6)
        )
        control_card.grid(row=0, column=0, sticky=tk.EW, padx=6, pady=(6, 3))

        # 行1：目标应用 + 采样间隔 + 运行状态
        pkg_row = ttk.Frame(control_card, style='Card.TFrame')
        pkg_row.pack(fill=tk.X, pady=(2, 4))

        ttk.Label(pkg_row, text="应用:", font=('Microsoft YaHei UI', 9),
                  background=self.COLORS["bg_card"]).pack(side=tk.LEFT, padx=(0, 5))

        # 包名输入框（Entry + 浮动搜索下拉）
        # 标签缩到「应用:」+ width=30：既让包名显示得下，
        # 又把控制条的自然宽度控制在 ~700，否则会把整个左面板撑宽、挤扁右侧终端
        self.app.perf_package_entry = ttk.Entry(
            pkg_row, font=('Microsoft YaHei UI', 9), width=30)
        self.app.perf_package_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.app.perf_package_entry.bind('<KeyRelease>', self.app._on_perf_package_search)

        self.app.perf_dropdown_listbox = None
        self.app.perf_dropdown_toplevel = None
        self.app._perf_all_packages = []

        ttk.Button(pkg_row, text="🔄 刷新", command=self.app.refresh_perf_package_list,
                   style='Secondary.TButton', width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(pkg_row, text="📱 当前", command=self.app.get_current_package_for_perf,
                   style='Secondary.TButton', width=7).pack(side=tk.LEFT, padx=2)

        ttk.Label(pkg_row, text="    采样间隔:", font=('Microsoft YaHei UI', 9),
                  background=self.COLORS["bg_card"]).pack(side=tk.LEFT)
        self.app.perf_interval_var = tk.StringVar(value="2")
        ttk.Combobox(pkg_row, textvariable=self.app.perf_interval_var,
                     values=["1", "2", "3", "5", "10"], width=4,
                     font=('Microsoft YaHei UI', 9), state="readonly"
                     ).pack(side=tk.LEFT, padx=4)
        ttk.Label(pkg_row, text="秒", font=('Microsoft YaHei UI', 9),
                  background=self.COLORS["bg_card"]).pack(side=tk.LEFT)

        # 行2：监控控制 + 运行状态指示（右侧）
        btn_row = ttk.Frame(control_card, style='Card.TFrame')
        btn_row.pack(fill=tk.X, pady=(2, 2))

        ttk.Button(btn_row, text="▶ 开始监控", command=self.app.start_performance_monitor,
                   style='Primary.TButton').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_row, text="⏹ 停止", command=self.app.stop_performance_monitor,
                   style='Danger.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="🧹 清空数据", command=self.app.clear_performance_data,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=5)

        # 运行状态指示（右侧）
        self.app.perf_status_label = ttk.Label(
            btn_row, text="● 未开始", font=('Microsoft YaHei UI', 9, 'bold'),
            background=self.COLORS["bg_card"], foreground=self.COLORS["text_secondary"])
        self.app.perf_status_label.pack(side=tk.RIGHT)

        # 行3：快照 / 导出类按钮（单独一行，避免一行塞 6 个按钮把左面板撑得过宽）
        btn_row2 = ttk.Frame(control_card, style='Card.TFrame')
        btn_row2.pack(fill=tk.X, pady=(0, 2))

        ttk.Button(btn_row2, text="📸 单次快照", command=self.app.get_performance_snapshot,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_row2, text="💾 导出 CSV", command=self.app.export_performance_csv,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row2, text="📄 导出报告", command=self.app.export_performance_report,
                   style='Secondary.TButton').pack(side=tk.LEFT, padx=5)

        self.app.perf_pid_label = ttk.Label(
            btn_row2, text="PID: --   模式: --   采样: 0 次",
            font=('Consolas', 9), background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"])
        self.app.perf_pid_label.pack(side=tk.RIGHT)

        # 卡顿率（与 FPS 语义相近，放控制条右侧，不额外占用指标卡）
        self.app.perf_jank_label = ttk.Label(
            btn_row2, text="卡顿率 --", font=('Consolas', 9, 'bold'),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"])
        self.app.perf_jank_label.pack(side=tk.RIGHT, padx=(0, 10))

        # ============ Row1: 指标汇总卡（当前 / 均值 / 峰值） ============
        metric_frame = ttk.Frame(tab, style='Card.TFrame')
        metric_frame.grid(row=1, column=0, sticky=tk.EW, padx=6, pady=3)
        for col in range(6):
            metric_frame.columnconfigure(col, weight=1)

        metric_defs = [
            ('cpu',     "CPU 占用",   self.COLORS["primary"],  "#185FA5"),
            ('pss',     "内存 PSS",   "#107C10", "#0B5C0B"),
            ('rss',     "内存 RSS",   "#1D9E75", "#0F6E56"),
            ('java',    "Java Heap",  "#534AB7", "#3C3489"),
            ('native',  "Native Heap","#0F6E56", "#085041"),
            ('fps',     "帧率 FPS",   "#BA7517", "#854F0B"),
        ]
        self.app.perf_metric_labels = {}
        for col, (key, title, val_color, _accent) in enumerate(metric_defs):
            card = ttk.LabelFrame(metric_frame, text=title, style='Card.TLabelframe',
                                  padding=(6, 2))
            card.grid(row=0, column=col, sticky=tk.NSEW, padx=3, pady=2)

            cur_label = ttk.Label(card, text="--", font=('Consolas', 16, 'bold'),
                                  background=self.COLORS["bg_card"],
                                  foreground=val_color, anchor='center')
            cur_label.pack(fill=tk.X)

            sub_label = ttk.Label(card, text="均值 --  峰值 --",
                                  font=('Microsoft YaHei UI', 8),
                                  background=self.COLORS["bg_card"],
                                  foreground=self.COLORS["text_secondary"],
                                  anchor='center')
            sub_label.pack(fill=tk.X)

            self.app.perf_metric_labels[key] = (cur_label, sub_label)

        # ============ Row2: 采样明细数值表（最新在上，逐次采样可直接读数） ============
        samples_card = ttk.LabelFrame(
            tab, text="📋 采样明细（最新在上）",
            style='Card.TLabelframe', padding=(6, 4)
        )
        samples_card.grid(row=2, column=0, sticky=tk.NSEW, padx=6, pady=3)
        samples_card.columnconfigure(0, weight=1)
        samples_card.rowconfigure(0, weight=1)

        sample_cols = ('ts', 'cpu', 'pss', 'rss', 'java', 'native', 'fps', 'jank')
        self.app.perf_samples_tree = ttk.Treeview(
            samples_card, columns=sample_cols, show='headings', height=10)
        sample_headers = {
            'ts': ('时间', 80, 'center'), 'cpu': ('CPU %', 85, 'e'),
            'pss': ('PSS MB', 85, 'e'), 'rss': ('RSS MB', 85, 'e'),
            'java': ('Java MB', 85, 'e'), 'native': ('Native MB', 95, 'e'),
            'fps': ('FPS', 70, 'e'), 'jank': ('卡顿 %', 80, 'e'),
        }
        for col, (text, width, anchor) in sample_headers.items():
            self.app.perf_samples_tree.heading(col, text=text)
            self.app.perf_samples_tree.column(
                col, width=width, anchor=anchor, stretch=True)

        sample_vsb = ttk.Scrollbar(samples_card, orient=tk.VERTICAL,
                                   command=self.app.perf_samples_tree.yview)
        self.app.perf_samples_tree.configure(yscrollcommand=sample_vsb.set)
        self.app.perf_samples_tree.grid(row=0, column=0, sticky=tk.NSEW)
        sample_vsb.grid(row=0, column=1, sticky=tk.NS)

        self.app.perf_samples_tree.tag_configure('odd', background='#F7F9FC')
        self.app.perf_samples_tree.tag_configure('even', background='#FFFFFF')
        self.app.perf_samples_tree.tag_configure('last', background='#E8F3FF')
        self.app.perf_samples_tree.tag_configure('alert', background='#FDE7E9')

        # ============ Row3: 线程级 CPU 表格 ============
        thread_card = ttk.LabelFrame(
            tab, text="🧵 线程级 CPU（点击表头排序，仅显示活跃线程）",
            style='Card.TLabelframe', padding=(6, 4)
        )
        thread_card.grid(row=3, column=0, sticky=tk.NSEW, padx=6, pady=(3, 6))
        thread_card.columnconfigure(0, weight=1)
        thread_card.rowconfigure(0, weight=1)

        columns = ('tid', 'name', 'cur', 'avg', 'peak')
        self.app.perf_thread_tree = ttk.Treeview(
            thread_card, columns=columns, show='headings', height=9)
        headers = {'tid': ('TID', 90, 'w'), 'name': ('线程名', 260, 'w'),
                   'cur': ('CPU 当前%', 110, 'e'), 'avg': ('CPU 均值%', 110, 'e'),
                   'peak': ('CPU 峰值%', 110, 'e')}
        for col, (text, width, anchor) in headers.items():
            self.app.perf_thread_tree.heading(
                col, text=text,
                command=lambda c=col: self.app._on_perf_thread_sort(c))
            self.app.perf_thread_tree.column(
                col, width=width, anchor=anchor, stretch=True)

        vsb = ttk.Scrollbar(thread_card, orient=tk.VERTICAL,
                            command=self.app.perf_thread_tree.yview)
        self.app.perf_thread_tree.configure(yscrollcommand=vsb.set)
        self.app.perf_thread_tree.grid(row=0, column=0, sticky=tk.NSEW)
        vsb.grid(row=0, column=1, sticky=tk.NS)

        # 斑马纹样式
        self.app.perf_thread_tree.tag_configure('odd', background='#F7F9FC')
        self.app.perf_thread_tree.tag_configure('even', background='#FFFFFF')
    
    def _create_mirror_options_card(self, parent, row: int, col: int) -> None:
        """创建投屏参数卡片（码率 / 分辨率 / 帧率）

        ⚠️ 这三个参数以前写死在代码里，投屏卡顿、模糊、掉帧时
        用户唯一能做的就是改代码重新打包 —— 没有任何自救手段。
        """
        card = ttk.LabelFrame(
            parent,
            text="⚙️ 投屏参数（下次启动生效）",
            style='Card.TLabelframe',
            padding=(10, 6)
        )
        card.grid(row=row, column=col, columnspan=2, sticky=tk.EW, padx=6, pady=(6, 3))
        parent.columnconfigure(col, weight=1)

        row_frame = ttk.Frame(card, style='Card.TFrame')
        row_frame.pack(fill=tk.X)

        def add_combo(parent_row, label, options, default, attr, width=8):
            ttk.Label(
                parent_row, text=label, font=('Microsoft YaHei UI', 9),
                background=self.COLORS["bg_card"]
            ).pack(side=tk.LEFT, padx=(0, 4))

            var = tk.StringVar(value=default)
            combo = ttk.Combobox(
                parent_row, textvariable=var, values=options, width=width,
                font=('Microsoft YaHei UI', 9), state="readonly")
            combo.pack(side=tk.LEFT, padx=(0, 14))
            setattr(self.app, attr, var)
            return var

        add_combo(row_frame, "码率:", Config.SCRCPY_BITRATE_OPTIONS,
                  Config.SCRCPY_BITRATE, "scrcpy_bitrate_var", width=6)
        add_combo(row_frame, "帧率:", Config.SCRCPY_MAX_FPS_OPTIONS,
                  Config.SCRCPY_MAX_FPS, "scrcpy_max_fps_var", width=5)
        add_combo(row_frame, "分辨率:", Config.SCRCPY_MAX_SIZE_OPTIONS,
                  Config.SCRCPY_MAX_SIZE, "scrcpy_max_size_var", width=7)

        ttk.Label(
            row_frame,
            text="💡 投屏卡顿/模糊时：先降码率，再降分辨率（WiFi 下建议 4M + 1080p）",
            font=('Microsoft YaHei UI', 8),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"]
        ).pack(side=tk.LEFT, padx=(4, 0))

    def _create_card(self, parent, title: str, buttons: List[Tuple], row: int,
                     col: int, colspan: int = 1, fill_vertical: bool = False) -> None:
        """创建功能卡片

        Args:
            fill_vertical: 是否纵向拉伸填满所在行。
                内容少的 Tab（如日志录屏，实测纵向空白 47%）开启后，
                卡片变高、按钮更好点，空白被消化掉。
        """
        card = ttk.LabelFrame(
            parent,
            text=title,
            style='Card.TLabelframe',
            padding=(10, 8)
        )
        # ⚠️ 纵向拉伸需要 NSEW（原来只有 EW，卡片不占满行高）
        card.grid(row=row, column=col, columnspan=colspan,
                  sticky=tk.NSEW if fill_vertical else tk.EW,
                  padx=6, pady=6)
        parent.columnconfigure(col, weight=1)
        if fill_vertical:
            parent.rowconfigure(row, weight=1)
        
        # 创建按钮网格
        for i, (text, method_name, btn_type) in enumerate(buttons):
            if hasattr(self.app, method_name):
                # 根据按钮类型选择样式
                if btn_type == "primary":
                    style = 'Primary.TButton'
                elif btn_type == "danger":
                    style = 'Danger.TButton'
                else:
                    style = 'Secondary.TButton'
                
                btn = ttk.Button(
                    card,
                    text=text,
                    command=getattr(self.app, method_name),
                    style=style
                )
                # ⚠️ 纵向拉伸时按钮不能跟着拉高（会变成大方块，很丑）。
                #    做法：sticky 只用 EW（横向拉伸），再给行加权重让单元格变高，
                #    grid 默认 anchor=center → 按钮在单元格内垂直居中。
                btn.grid(row=0, column=i, sticky=tk.EW, padx=4, pady=4)
                card.columnconfigure(i, weight=1)
                if fill_vertical:
                    card.rowconfigure(0, weight=1)
    
    def _create_text_input_card(self, parent, row: int, col: int, colspan: int = 1) -> None:
        """创建文本输入卡片"""
        card = ttk.LabelFrame(
            parent,
            text="文本输入",
            style='Card.TLabelframe',
            padding=(10, 8)
        )
        card.grid(row=row, column=col, columnspan=colspan, sticky=tk.EW, padx=6, pady=6)
        parent.columnconfigure(col, weight=1)
        
        entry_frame = ttk.Frame(card, style='Card.TFrame')
        entry_frame.pack(fill=tk.X)
        
        self.app.text_input_entry = ttk.Entry(
            entry_frame,
            font=('Microsoft YaHei UI', 9),
            width=30
        )
        self.app.text_input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.app.text_input_entry.insert(0, "仅支持数字输入")
        self.app.text_input_entry.config(foreground='gray')
        
        def on_focus_in(event):
            if self.app.text_input_entry.get() == "仅支持数字输入":
                self.app.text_input_entry.delete(0, tk.END)
                self.app.text_input_entry.config(foreground='black')
        
        def on_focus_out(event):
            if not self.app.text_input_entry.get():
                self.app.text_input_entry.insert(0, "仅支持数字输入")
                self.app.text_input_entry.config(foreground='gray')
        
        self.app.text_input_entry.bind("<FocusIn>", on_focus_in)
        self.app.text_input_entry.bind("<FocusOut>", on_focus_out)
        
        send_btn = ttk.Button(
            entry_frame,
            text="发送",
            command=self.app.send_text_input,
            style='Primary.TButton',
            width=8
        )
        send_btn.pack(side=tk.LEFT)
    
    def _create_app_input_card(self, parent, row: int, col: int, colspan: int = 1) -> None:
        """创建应用输入卡片"""
        card = ttk.LabelFrame(
            parent,
            text="应用信息",
            style='Card.TLabelframe',
            padding=(10, 8)
        )
        card.grid(row=row, column=col, columnspan=colspan, sticky=tk.EW, padx=6, pady=6)
        parent.columnconfigure(col, weight=1)
        
        # 包名输入
        pkg_row = ttk.Frame(card, style='Card.TFrame')
        pkg_row.pack(fill=tk.X, pady=3)
        
        ttk.Label(
            pkg_row,
            text="包名:",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            width=8
        ).pack(side=tk.LEFT)
        
        self.app.pkg_combobox = ttk.Combobox(pkg_row, width=30, font=('Microsoft YaHei UI', 9))
        self.app.pkg_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.pkg_combobox['height'] = 10
        self.app.pkg_entry = self.app.pkg_combobox
        
        # APK文件
        apk_row = ttk.Frame(card, style='Card.TFrame')
        apk_row.pack(fill=tk.X, pady=3)
        
        ttk.Label(
            apk_row,
            text="APK文件:",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            width=8
        ).pack(side=tk.LEFT)
        
        self.app.apk_entry = ttk.Entry(apk_row, font=('Microsoft YaHei UI', 9))
        self.app.apk_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # APK 拖放注册依赖 apk_entry，跟随本卡片一起初始化
        # （Tab 是懒加载的，启动时 app Tab 还没建，拖放要等这里）
        try:
            self.app._setup_drag_drop()
        except Exception:
            logging.exception("[布局] 拖放注册失败")

        browse_btn = ttk.Button(
            apk_row,
            text="浏览",
            command=self.app.browse_apk,
            style='Secondary.TButton',
            width=8
        )
        browse_btn.pack(side=tk.LEFT)
        
        # 版本显示
        version_row = ttk.Frame(card, style='Card.TFrame')
        version_row.pack(fill=tk.X, pady=3)
        
        ttk.Label(
            version_row,
            text="版本:",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            width=8
        ).pack(side=tk.LEFT)
        
        self.app.version_display = ttk.Entry(
            version_row,
            state='readonly',
            font=('Microsoft YaHei UI', 9),
            width=30
        )
        self.app.version_display.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    
    def _create_log_settings_card(self, parent, row: int, col: int, colspan: int = 1) -> None:
        """创建日志设置卡片"""
        card = ttk.LabelFrame(
            parent,
            text="日志设置",
            style='Card.TLabelframe',
            padding=(10, 8)
        )
        card.grid(row=row, column=col, columnspan=colspan, sticky=tk.EW, padx=6, pady=6)
        parent.columnconfigure(col, weight=1)
        
        path_row = ttk.Frame(card, style='Card.TFrame')
        path_row.pack(fill=tk.X)
        
        ttk.Label(
            path_row,
            text="路径:",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            width=8
        ).pack(side=tk.LEFT)
        
        self.app.log_path_entry = ttk.Entry(path_row, font=('Microsoft YaHei UI', 9))
        # 监听内容变化，把路径同步到 app 的缓存（后台线程只读缓存，不碰 Tk 控件）
        # ttk.Entry 没有 trace_add，用事件绑定代替
        self.app.log_path_entry.bind('<KeyRelease>', self.app._on_log_path_changed)
        self.app.log_path_entry.bind('<FocusOut>', self.app._on_log_path_changed)
        self.app.log_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.log_path_entry.insert(0, Config.DEFAULT_LOG_PATH)
        
        browse_btn = ttk.Button(
            path_row,
            text="浏览",
            command=self.app.choose_log_path,
            style='Secondary.TButton',
            width=8
        )
        browse_btn.pack(side=tk.LEFT)
    
    def create_right_output_area(self) -> None:
        """创建右侧输出区域"""
        # 日志标题栏
        header = ttk.Frame(self.output_area, style='Card.TFrame')
        header.grid(row=0, column=0, sticky=tk.EW, pady=(5, 5))
        
        ttk.Label(
            header,
            text="📄 实时终端输出",
            font=('Microsoft YaHei UI', 11, 'bold'),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_primary"]
        ).pack(side=tk.LEFT)
        
        # 清空按钮
        clear_btn = ttk.Button(
            header,
            text="清空",
            command=self._clear_output,
            style='Secondary.TButton',
            width=8
        )
        clear_btn.pack(side=tk.RIGHT)
        
        # 自动滚动复选框（标签缩短：右栏只有 ~490px，"自动滚动"会被截断）
        self.auto_scroll_var = tk.BooleanVar(value=True)
        auto_scroll_cb = ttk.Checkbutton(
            header,
            text="滚动",
            variable=self.auto_scroll_var,
            style='Card.TCheckbutton'
        )
        auto_scroll_cb.pack(side=tk.RIGHT, padx=4)

        # ⚠️ 搜索工具栏：logcat 抓几千行后只能肉眼翻，tk.Text 连 Ctrl+F 都没有。
        #    加关键字搜索 + 高亮 + 错误过滤 + 命中计数。
        #
        # ⚠️ 布局要点（踩过的坑）：
        #    1) 右栏只有 ~490px，一行塞不下所有控件 → 拆成两行
        #    2) 用 grid 而不是 pack：pack(side=RIGHT) 是「后进先出」，
        #       排在前面的控件会被挤到容器右边缘外（实测计数标签 w=4，文字全没）
        #    3) Entry 用 sticky=EW 让它吃掉富余空间，但不给它 expand 之外的权重
        search_bar = ttk.Frame(self.output_area, style='Card.TFrame')
        search_bar.grid(row=1, column=0, sticky=tk.EW, pady=(0, 4))
        # ⚠️ 两行搜索栏需要固定高度：grid_propagate(False) 会关掉自动高度调整，
        #    必须显式给 height，否则整个搜索栏高度为 0（完全看不见）。
        search_bar.configure(height=52)
        search_bar.grid_propagate(False)
        search_bar.columnconfigure(1, weight=1)   # 搜索框列可伸缩

        ttk.Label(
            search_bar,
            text="🔍",
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"]
        ).grid(row=0, column=0, padx=(0, 4), pady=(0, 2))

        self.app.log_search_var = tk.StringVar()
        self.app.log_search_entry = ttk.Entry(
            search_bar, textvariable=self.app.log_search_var,
            font=('Consolas', 9))
        self.app.log_search_entry.grid(row=0, column=1, sticky=tk.EW,
                                       padx=(0, 4), pady=(0, 2))
        self.app.log_search_entry.bind('<Return>', lambda e: self._search_log())
        self.app.log_search_entry.bind('<Escape>', lambda e: self._clear_search())

        # 搜索结果计数（第一行右侧）
        self.app.log_search_count = ttk.Label(
            search_bar, text="",
            font=('Consolas', 9),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["text_secondary"],
            width=9, anchor=tk.CENTER
        )
        self.app.log_search_count.grid(row=0, column=2, padx=(2, 6), pady=(0, 2))

        # 第二行：命中导航 + 功能菜单
        self._make_search_btn(search_bar, "▼", self._search_log_next,
                              "跳到下一个命中（回车）", col=0, row=1)
        self._make_search_btn(search_bar, "▲", self._search_log_prev,
                              "跳到上一个命中", col=1, row=1)

        # 「只看错误」「导出」收进「⚙」菜单 —— 一个按钮就够，
        # 省下的横向空间给搜索框（关键字往往很长）
        self.app.log_error_only_var = tk.BooleanVar(value=False)

        menu_btn = ttk.Button(search_bar, text="⚙", width=3,
                              style='Secondary.TButton',
                              command=self._show_log_menu)
        menu_btn.grid(row=1, column=2, sticky=tk.E, padx=2)
        
        # 日志文本框容器 - 增加expand权重使其更大
        # ⚠️ row 编号整体下移：row=1 现在是搜索栏，文本框移到 row=2
        log_frame = ttk.Frame(self.output_area, style='Card.TFrame')
        log_frame.grid(row=2, column=0, sticky=tk.NSEW)
        # 设置行权重，让日志区域占据更多空间（从10增加到20）
        self.output_area.rowconfigure(2, weight=20)
        
        self.app.status_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg='#F8F8F8',
            fg=self.COLORS["text_primary"],
            relief='solid',
            borderwidth=1,
            width=44  # 显式指定请求宽度：默认 80 字符会把右栏撑到 ~580px，挤掉左侧按钮区
        )
        self.app.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(log_frame, command=self.app.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.status_text.config(yscrollcommand=scrollbar.set)
        
        # 配置日志标签样式（带颜色标记）
        self.app.status_text.tag_configure("timestamp", foreground=self.COLORS["text_secondary"])
        self.app.status_text.tag_configure("success", foreground=self.COLORS["success"])
        self.app.status_text.tag_configure("error", foreground=self.COLORS["error"])
        self.app.status_text.tag_configure("warning", foreground="#D83B01")
        self.app.status_text.tag_configure("info", foreground=self.COLORS["primary"])
        self.app.status_text.tag_configure("command", foreground='#6B69D6', font=('Consolas', 9, 'italic'))
        # 搜索命中高亮
        self.app.status_text.tag_configure("search_hit", background='#FFF3A0', foreground='#7A4F01')
        self.app.status_text.tag_configure("search_hit_current", background='#FFB300', foreground='#000000')
        
        # 进度条
        progress_frame = ttk.Frame(self.output_area, style='Card.TFrame')
        progress_frame.grid(row=3, column=0, sticky=tk.EW, pady=(5, 0))
        
        self.app.progress = ttk.Progressbar(
            progress_frame,
            mode="indeterminate",
            style='Modern.Horizontal.TProgressbar'
        )
        self.app.progress.pack(fill=tk.X)
        self.app.progress.pack_forget()
    
    # ------------------------------------------------------------------
    # 终端搜索 / 高亮 / 过滤
    # ------------------------------------------------------------------

    def _show_log_menu(self):
        """弹出终端功能菜单（只看错误 / 导出）"""
        menu = tk.Menu(self.app.root, tearoff=0)
        menu.add_checkbutton(
            label="只看错误",
            variable=self.app.log_error_only_var,
            command=self._toggle_error_only)
        menu.add_separator()
        menu.add_command(label="导出终端输出…", command=self._export_log)
        menu.add_command(label="复制全部", command=self._copy_all_output)

        try:
            menu.tk_popup(self.app.root.winfo_pointerx(),
                          self.app.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _copy_all_output(self):
        """复制终端全部内容到剪贴板"""
        try:
            self.app.status_text.clipboard_clear()
            self.app.status_text.clipboard_append(
                self.app.status_text.get("1.0", tk.END))
            self.app.update_status("已复制终端内容到剪贴板", True)
        except Exception as e:
            self.app.update_status(f"复制失败: {e}", False)

    def _make_search_btn(self, parent, text, command, tooltip, col=None,
                         row=0, side=tk.LEFT):
        """创建一个带 tooltip 的紧凑搜索按钮"""
        btn = ttk.Button(parent, text=text, command=command,
                         style='Secondary.TButton', width=3)
        if col is not None:
            btn.grid(row=row, column=col, padx=1)
        else:
            btn.pack(side=side, padx=1)

        # ttk 没有原生 tooltip，用一个小 Toplevel 模拟
        def show_tip(event=None):
            tip = tk.Toplevel(parent)
            tip.wm_overrideredirect(True)
            x = btn.winfo_rootx() + btn.winfo_width() // 2
            y = btn.winfo_rooty() - 24
            tip.wm_geometry(f"+{x}+{y}")
            tk.Label(tip, text=tooltip, background="#FFFFE0",
                     relief='solid', borderwidth=1,
                     font=('Microsoft YaHei UI', 8)).pack()

            def close(event=None):
                tip.destroy()

            tip.bind('<Leave>', close)
            tip.bind('<ButtonPress>', close)
            tip.after(1500, close)

        btn.bind('<Enter>', show_tip)
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

        # 找出全部命中位置
        hits = []
        start = "1.0"
        while True:
            pos = text.search(keyword, start, stopindex=tk.END,
                              nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(keyword)}c"
            hits.append((pos, end))
            text.tag_add("search_hit", pos, end)
            start = end
            if len(hits) > 5000:      # 防止超大输出卡死
                break

        self._search_hits = hits
        self._search_index = 0

        if hits:
            text.tag_add("search_hit_current", *hits[0])
            text.see(hits[0][0])
            self.app.log_search_count.config(
                text=f"{len(hits)} 处命中",
                foreground=self.COLORS["primary"])
        else:
            self.app.log_search_count.config(
                text="无匹配", foreground=self.COLORS["error"])

    def _search_log_next(self):
        """跳到下一个命中"""
        hits = getattr(self, '_search_hits', [])
        if not hits:
            self._search_log()
            return
        self._search_index = (self._search_index + 1) % len(hits)
        self._goto_hit()

    def _search_log_prev(self):
        """跳到上一个命中"""
        hits = getattr(self, '_search_hits', [])
        if not hits:
            self._search_log()
            return
        self._search_index = (self._search_index - 1) % len(hits)
        self._goto_hit()

    def _goto_hit(self):
        """定位到当前命中项"""
        hits = getattr(self, '_search_hits', [])
        if not hits:
            return
        text = self.app.status_text
        text.tag_remove("search_hit_current", "1.0", tk.END)
        pos, end = hits[self._search_index]
        text.tag_add("search_hit_current", pos, end)
        text.see(pos)
        self.app.log_search_count.config(
            text=f"{self._search_index + 1}/{len(hits)}",
            foreground=self.COLORS["primary"])

    def _clear_search(self):
        """清除搜索高亮"""
        if hasattr(self.app, 'status_text'):
            self.app.status_text.tag_remove("search_hit", "1.0", tk.END)
            self.app.status_text.tag_remove("search_hit_current", "1.0", tk.END)
        self._search_hits = []
        self._search_index = 0
        if hasattr(self.app, 'log_search_var'):
            self.app.log_search_var.set("")
        if hasattr(self.app, 'log_search_count'):
            self.app.log_search_count.config(text="")

    def _toggle_error_only(self):
        """只看错误：隐藏不含错误关键字的行"""
        text = self.app.status_text
        only_error = self.app.log_error_only_var.get()

        # 先清掉所有行级隐藏标记
        text.tag_remove("hidden_line", "1.0", tk.END)

        if not only_error:
            self.app.log_search_count.config(text="")
            return

        # 错误特征：✗ / Error / error / FAIL / Exception / failed / 失败
        error_markers = ("✗", "error", "Error", "ERROR", "FAIL", "Exception",
                         "failed", "Failed", "失败", "Traceback")

        content = text.get("1.0", tk.END)
        lines = content.split("\n")
        hidden = 0
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            if not any(m in line for m in error_markers):
                # ⚠️ 区间必须留出间隙：相邻两行若分别标记 [n.0, n+1.0) 和
                #    [n+1.0, n+2.0)，Tk 会把它们**合并**成一段，
                #    elide 后只隐藏掉其中一部分（实测 4 行只隐藏了 3 行）。
                #    改成标记 [n.0, n+1.0) 的同时跳过行尾换行符，
                #    用「行首到行尾字符」的区间，每段之间自然断开。
                start = f"{i + 1}.0"
                end = f"{i + 1}.end - 1c"
                text.tag_add("hidden_line", start, end)
                hidden += 1

        text.tag_configure("hidden_line", elide=True)
        self.app.log_search_count.config(
            text=f"隐藏 {hidden}/{len(lines)} 行",
            foreground=self.COLORS["warning"])

    def _export_log(self):
        """把终端输出导出到文件"""
        if not hasattr(self.app, 'status_text'):
            return
        try:
            from tkinter import filedialog
            import datetime
            default_name = (f"adbtool_log_"
                            f"{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
            path = filedialog.asksaveasfilename(
                title="导出终端输出",
                defaultextension=".txt",
                initialfile=default_name,
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
            if not path:
                return

            content = self.app.status_text.get("1.0", tk.END)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            self.app.update_status(f"已导出到: {path}", True)
        except Exception as e:
            self.app.update_status(f"导出失败: {e}", False)

    def _clear_output(self):
        """清空输出区域"""
        if hasattr(self.app, 'status_text'):
            self.app.status_text.delete(1.0, tk.END)
    
    def _on_ip_selected(self, event):
        """IP 下拉选择处理：有效 IP 时自动发起连接，无需手动点"立即连接"按钮"""
        if hasattr(self.app, 'ip_combobox'):
            selected_value = self.app.ip_combobox.get()
            self.app.ip_combobox.set(selected_value)
        # 先刷新连接状态标签
        self.app.update_connection_status()
        # 有效 IP（非 192.168. 占位符）时自动连接；否则只显示设备状态
        current_ip = self.app.get_ip_address()
        if current_ip and current_ip != "192.168.":
            self.app.connect_adb()
        else:
            self.app.show_current_device_status(force_display=True)
    
    def setup_keyboard_shortcuts(self) -> None:
        """设置键盘快捷键"""
        shortcuts = {
            '<Control-q>': lambda e: self.app.root.quit(),
            '<Control-c>': lambda e: self.app.connect_adb() if hasattr(self.app, 'connect_adb') else None,
            '<Control-d>': lambda e: self.app.disconnect_adb() if hasattr(self.app, 'disconnect_adb') else None,
            '<Control-i>': lambda e: self.app.force_install() if hasattr(self.app, 'force_install') else None,
            '<Control-u>': lambda e: self.app.uninstall() if hasattr(self.app, 'uninstall') else None,
            '<Control-l>': lambda e: self.app.package_list() if hasattr(self.app, 'package_list') else None,
            '<F5>': lambda e: self.app.reboot() if hasattr(self.app, 'reboot') else None,
            '<F12>': lambda e: self.app.screencap() if hasattr(self.app, 'screencap') else None,
        }
        
        for shortcut, handler in shortcuts.items():
            self.app.root.bind(shortcut, handler)


def setup_gui(app):
    """
    设置GUI入口函数
    
    Args:
        app: 应用实例
    """
    layout = LayoutModern(app)
    layout.setup_gui()
    # 暴露实例，方便调试/自动化脚本拿到 tabs / tab_buttons
    app.layout_instance = layout
