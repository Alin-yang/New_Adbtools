"""
现代化布局 - 参考 WOA AutoBot UI 风格
特点：卡片式设计、顶部Tab、彩色状态标签、底部实时日志
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Callable, List, Tuple
from config import Config, get_text


class LayoutModern:
    """现代化布局类"""
    
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
        
        # 创建各个Tab页（只包含功能按钮）
        self.create_device_tab()
        self.create_app_tab()
        self.create_log_screen_tab()
        self.create_mirror_tab()      # 投屏
        self.create_advanced_tab()
        
        # 创建右侧输出区域
        self.create_right_output_area()
        
        # 设置快捷键
        self.setup_keyboard_shortcuts()
        
        # 默认显示第一个Tab
        self.app.root.after(100, lambda: self.switch_tab("device"))
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root, style='Modern.TFrame')
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 配置窗口
        self.app.root.title("ADB Tool v2.0")
        self.app.root.geometry("1200x620")  # 增加宽度，给右侧输出框更多空间
        self.app.root.minsize(900, 520)
        
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
        self.top_bar = ttk.Frame(self.main_frame, style='Card.TFrame', height=60)
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
            text="v2.0 · 现代化UI",
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
        device_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=15)
        
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
        
        self.app.ip_combobox = ttk.Combobox(ip_row, width=20, font=('Microsoft YaHei UI', 9))
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox.insert(0, "192.168.")
        
        # 连接状态标签（使用 tk.Label 以获得更好的对齐控制）
        self.app.connection_status_label = tk.Label(
            ip_row,
            text="● 未连接",
            font=('Microsoft YaHei UI', 9, 'bold'),
            background='#C8C6C4',
            foreground='white',
            width=14,
            relief='flat',
            anchor='center'  # 文字居中
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(10, 0))
        
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
        
        # 刷新按钮
        refresh_btn = ttk.Button(
            status_frame,
            text="🔄 刷新设备",
            command=self.app.show_device_info,
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
            ("🖥️ 投屏", "mirror"),  # 新增投屏 Tab
            ("⚙️ 高级工具", "advanced"),
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
        """切换Tab页"""
        # 隐藏所有Tab内容
        for name, frame in self.tabs.items():
            frame.grid_remove()
        
        # 显示选中的Tab
        if tab_name in self.tabs:
            self.tabs[tab_name].grid(row=0, column=0, sticky=tk.NSEW)
        
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
        
        # 配置主容器的grid
        content_frame.grid_rowconfigure(0, weight=1)
        content_frame.grid_columnconfigure(0, weight=0, minsize=300)  # 左侧功能按钮区（进一步缩小）
        content_frame.grid_columnconfigure(1, weight=1)  # 右侧输出框区（弹性扩展）
        
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
        """创建设备管理Tab（左侧功能按钮）"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['device'] = tab
        
        # 让tab填满整个区域
        tab.grid(row=0, column=0, sticky=tk.NSEW)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        
        # 创建主容器，分为上下两部分
        main_container = ttk.Frame(tab, style='Card.TFrame')
        main_container.grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)
        main_container.grid_columnconfigure(0, weight=1)
        main_container.grid_rowconfigure(0, weight=0)  # 按钮区域
        main_container.grid_rowconfigure(1, weight=1)  # 弹性空白区域
        
        # 按钮容器（顶部）
        button_frame = ttk.Frame(main_container, style='Card.TFrame')
        button_frame.grid(row=0, column=0, sticky=tk.NW)
        button_frame.columnconfigure(0, weight=1)
        
        # 使用垂直排列的功能卡片
        row = 0
        
        # ADB 服务管理
        self._create_card(button_frame, "ADB 服务管理", [
            ("🔌连接ADB", "connect_adb", "primary"),
            ("❌断开所有", "disconnect_adb", "danger"),
            ("🔄重启服务", "restart_adb_server", "secondary"),
        ], row=row, col=0)
        row += 1
        
        # 设备信息
        self._create_card(button_frame, "设备信息", [
            ("📱查看设备", "show_device_info", "primary"),
            ("📋详细信息", "get_device_info_fast", "secondary"),
            ("🔍获取串号", "get_serial_number", "secondary"),
        ], row=row, col=0)
        row += 1
        
        # 设备控制
        self._create_card(button_frame, "设备控制", [
            ("🔁重启设备", "reboot", "primary"),
            ("🔑Root权限", "root_device", "secondary"),
            ("📀重新挂载", "remount", "secondary"),
        ], row=row, col=0)
        row += 1
        
        # 系统工具
        self._create_card(button_frame, "系统工具", [
            ("🖥️打开CMD", "open_cmd_window", "secondary"),
            ("📝常用命令", "show_common_adb_commands", "secondary"),
            ("🔍Android版本", "get_android_version", "secondary"),
        ], row=row, col=0)
        row += 1
        
        # 文本输入
        self._create_text_input_card(button_frame, row=row, col=0)
    
    def create_app_tab(self) -> None:
        """创建应用管理Tab"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['app'] = tab
        
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
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
        
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
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
            row=1, col=0
        )
        
        self._create_card(
            tab,
            "ANR与命令",
            [
                ("📥导出ANR", "pull_anr_file", "secondary"),
                ("📜原始命令", "show_all_adb_commands", "secondary"),
            ],
            row=1, col=1
        )
        
        self._create_card(
            tab,
            "屏幕操作",
            [
                ("🎥开始录制", "start_recording", "primary"),
                ("⏹️停止录制", "stop_recording", "danger"),
                ("📷截屏", "screencap", "secondary"),
            ],
            row=2, col=0
        )
        
        # 打开存储文件夹
        self._create_card(
            tab,
            "文件管理",
            [
                ("📂打开存储文件夹", "open_storage_folder", "primary"),
            ],
            row=2, col=1
        )
    
    def create_mirror_tab(self) -> None:
        """创建投屏Tab"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['mirror'] = tab
        
        tab.columnconfigure(0, weight=1)
        tab.grid(row=0, column=0, sticky=tk.NSEW)
        
        # 使用说明卡片
        info_card = ttk.LabelFrame(
            tab,
            text="💡 使用说明",
            style='Card.TLabelframe',
            padding=(12, 10)
        )
        info_card.grid(row=0, column=0, sticky=tk.EW, padx=6, pady=6)
        
        info_text = (
            "🔹 scrcpy 投屏工具已集成，无需额外下载\n"
            "🔹 支持鼠标点击、滑动等完整交互操作\n"
            "🔹 低延迟（<100ms），高帧率（30-60fps）\n"
            "🔹 点击“启动投屏”即可开始镜像手机、TV屏幕\n"
            "🔹 可使用下方按键模拟功能控制设备"
        )
        info_label = ttk.Label(
            info_card,
            text=info_text,
            font=('Microsoft YaHei UI', 9),
            background=self.COLORS["bg_card"],
            foreground=self.COLORS["primary"],
            justify=tk.LEFT,
            wraplength=400
        )
        info_label.pack(anchor=tk.W, padx=5, pady=5)
        
        # 投屏控制卡片
        self._create_card(
            tab,
            "投屏控制",
            [
                ("🖥️ 启动投屏", "start_screen_mirror", "primary"),
                ("⏹️ 停止投屏", "stop_screen_mirror", "danger"),
            ],
            row=1, col=0
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
            row=2, col=0
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
            row=4, col=0
        )
    
    def create_advanced_tab(self) -> None:
        """创建高级工具Tab"""
        tab = ttk.Frame(self.content_area, style='Card.TFrame')
        self.tabs['advanced'] = tab
        
        tab.columnconfigure(0, weight=1)
        tab.grid(row=0, column=0, sticky=tk.NSEW)
        self._create_card(
            tab,
            "工厂菜单",
            [
                ("🔧打开工厂菜单", "open_factory_menu", "primary"),
            ],
            row=0, col=0
        )
    
    def _create_card(self, parent, title: str, buttons: List[Tuple], row: int, col: int, colspan: int = 1) -> None:
        """创建功能卡片"""
        card = ttk.LabelFrame(
            parent,
            text=title,
            style='Card.TLabelframe',
            padding=(10, 8)
        )
        card.grid(row=row, column=col, columnspan=colspan, sticky=tk.EW, padx=6, pady=6)
        parent.columnconfigure(col, weight=1)
        
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
                btn.grid(row=0, column=i, sticky=tk.EW, padx=4, pady=4)
                card.columnconfigure(i, weight=1)
    
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
        
        # 自动滚动复选框
        self.auto_scroll_var = tk.BooleanVar(value=True)
        auto_scroll_cb = ttk.Checkbutton(
            header,
            text="自动滚动",
            variable=self.auto_scroll_var,
            style='Card.TCheckbutton'
        )
        auto_scroll_cb.pack(side=tk.RIGHT, padx=10)
        
        # 日志文本框容器
        log_frame = ttk.Frame(self.output_area, style='Card.TFrame')
        log_frame.grid(row=1, column=0, sticky=tk.NSEW)
        
        self.app.status_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg='#F8F8F8',
            fg=self.COLORS["text_primary"],
            relief='solid',
            borderwidth=1
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
        
        # 进度条
        progress_frame = ttk.Frame(self.output_area, style='Card.TFrame')
        progress_frame.grid(row=2, column=0, sticky=tk.EW, pady=(5, 0))
        
        self.app.progress = ttk.Progressbar(
            progress_frame,
            mode="indeterminate",
            style='Modern.Horizontal.TProgressbar'
        )
        self.app.progress.pack(fill=tk.X)
        self.app.progress.pack_forget()
    
    def _clear_output(self):
        """清空输出区域"""
        if hasattr(self.app, 'status_text'):
            self.app.status_text.delete(1.0, tk.END)
    
    def _on_ip_selected(self, event):
        """IP选择处理"""
        if hasattr(self.app, 'ip_combobox'):
            selected_value = self.app.ip_combobox.get()
            self.app.ip_combobox.set(selected_value)
        
        self.app.on_ip_changed(event)
    
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
