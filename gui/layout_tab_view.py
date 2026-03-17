"""
Tab 视图布局 - 重构版本
按功能分组到不同的 Tab 页，提升用户体验
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Callable, List, Tuple
from config import Config, get_text


class LayoutTabView:
    """Tab 视图布局类"""
    
    def __init__(self, app):
        """
        初始化 Tab 布局
        
        Args:
            app: 应用实例
        """
        self.app = app
        self.main_frame = None
        self.left_panel = None
        self.right_panel = None
        self.notebook = None  # Tab 容器
        self.tabs = {}  # 存储各个 Tab 页
        
    def setup_gui(self):
        """构建完整的 Tab 界面布局"""
        # 设置主容器
        self.setup_main_container()
        
        # 创建左右分栏
        self.create_panels(left_weight=55, right_weight=45)
        
        # 创建 Tab 页
        self.create_tab_notebook()
        
        # 创建各个 Tab 页内容
        self.create_device_tab()      # 设备管理
        self.create_app_tab()         # 应用管理
        self.create_log_tab()         # 日志调试
        self.create_screen_tab()      # 屏幕操作
        self.create_advanced_tab()    # 高级工具
        
        # 创建输出区域
        self.create_output_section()
        
        # 设置快捷键
        self.setup_keyboard_shortcuts()
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 配置窗口标题和大小
        self.app.root.title(get_text("window_title"))
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        if hasattr(Config, 'MIN_WINDOW_SIZE'):
            self.app.root.minsize(*Config.MIN_WINDOW_SIZE)
    
    def create_panels(self, left_weight: int = 55, right_weight: int = 45) -> None:
        """
        创建左右分栏面板
        
        Args:
            left_weight: 左侧面板权重 (Tab 页)
            right_weight: 右侧面板权重 (输出区)
        """
        # 左侧 Tab 面板
        self.left_panel = ttk.Frame(self.main_frame)
        self.left_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 10))
        
        # 右侧输出面板
        self.right_panel = ttk.Frame(self.main_frame)
        self.right_panel.grid(row=0, column=1, sticky=tk.NSEW)
        
        # 配置网格权重
        self.main_frame.grid_columnconfigure(0, weight=left_weight)
        self.main_frame.grid_columnconfigure(1, weight=right_weight)
        self.main_frame.grid_rowconfigure(0, weight=1)
    
    def create_tab_notebook(self) -> None:
        """创建 Tab 容器"""
        self.notebook = ttk.Notebook(self.left_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # 配置 Tab 样式
        style = ttk.Style()
        style.configure('TNotebook.Tab', padding=[15, 8], font=('Arial', 10))
        style.configure('TNotebook', padding=5)
    
    def create_device_tab(self) -> None:
        """创建设备管理 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📱 设备管理")
        self.tabs['device'] = tab
        
        # 创建输入区域
        self._create_device_input_section(tab)
        
        # 创建设备功能按钮
        device_buttons = [
            ("🔌 连接 ADB", 4, 0, "connect_adb"),
            ("❌ 断开所有 ADB 连接", 4, 1, "disconnect_adb"),
            ("📱 查看已连接设备", 4, 2, "show_device_info"),
            ("🔄 重启设备", 5, 0, "reboot"),
            ("🔑 获取 Root 权限", 5, 1, "root_device"),
            ("📀 重新挂载分区", 5, 2, "remount"),
            (" 获取 Android 版本号", 6, 0, "get_android_version"),
            ("📱 获取设备串号", 6, 1, "get_serial_number"),
        ]
        
        self._create_button_grid(tab, device_buttons)
    
    def _create_device_input_section(self, parent) -> None:
        """创建设备输入区域"""
        # IP Address
        ttk.Label(parent, text=get_text("ip_label")).grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        
        ip_frame = ttk.Frame(parent)
        ip_frame.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky=tk.EW)
        
        # IP 下拉框
        self.app.ip_combobox = ttk.Combobox(ip_frame)
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox['width'] = 15
        self.app.ip_combobox.insert(0, "192.168.")
        
        # 连接状态标签
        self.app.connection_status_label = ttk.Label(
            ip_frame, 
            text="未连接", 
            foreground="gray",
            width=10
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # 绑定事件
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)
        
        # 配置列权重
        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_columnconfigure(2, weight=0)
    
    def create_app_tab(self) -> None:
        """创建应用管理 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📦 应用管理")
        self.tabs['app'] = tab
        
        # 创建输入区域
        self._create_app_input_section(tab)
        
        # 创建应用功能按钮
        app_buttons = [
            ("📲 强制安装 APK", 4, 0, "force_install"),
            ("🗑️ 卸载当前包名应用", 4, 1, "uninstall"),
            ("📋 获取已安装应用列表", 4, 2, "package_list"),
            ("🧹 清除应用缓存", 5, 0, "clear_cache"),
            ("⏹️ 终止当前包名进程", 5, 1, "kill_app_process"),
            ("🔍 获取包名版本号", 6, 0, "get_version"),
            ("📂 获取应用安装路径", 6, 1, "get_package_path"),
            ("🔍 获取当前打开应用包名", 6, 2, "get_package_name"),
        ]
        
        self._create_button_grid(tab, app_buttons)
    
    def _create_app_input_section(self, parent) -> None:
        """创建应用输入区域"""
        # 包名
        ttk.Label(parent, text=get_text("package_label")).grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.pkg_combobox = ttk.Combobox(parent)
        self.app.pkg_combobox.grid(row=0, column=1, columnspan=2, padx=5, pady=5, sticky=tk.EW)
        self.app.pkg_combobox['height'] = 10
        self.app.pkg_combobox['width'] = 15
        self.app.pkg_entry = self.app.pkg_combobox  # 兼容
        
        # APK 文件
        ttk.Label(parent, text=get_text("apk_label")).grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.apk_entry = ttk.Entry(parent)
        self.app.apk_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        self.app.browse_btn = ttk.Button(
            parent,
            text=get_text("browse_apk"),
            command=self.app.browse_apk
        )
        self.app.browse_btn.grid(row=1, column=2, padx=5, pady=5, sticky=tk.EW)
        
        # 配置列权重
        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_columnconfigure(2, weight=0)
    
    def create_log_tab(self) -> None:
        """创建日志调试 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📋 日志调试")
        self.tabs['log'] = tab
        
        # 创建日志路径输入
        self._create_log_input_section(tab)
        
        # 创建日志功能按钮
        log_buttons = [
            ("▶️ 启动日志捕获", 3, 0, "start_logcat"),
            ("⏹️ 停止日志捕获", 3, 1, "stop_logcat"),
            ("🧹 清除日志缓存", 3, 2, "log_clear"),
            ("📥 导出 ANR 文件", 4, 0, "pull_anr_file"),
            ("📜 功能按键原始命令", 4, 2, "show_all_adb_commands"),
        ]
        
        self._create_button_grid(tab, log_buttons)
    
    def _create_log_input_section(self, parent) -> None:
        """创建日志输入区域"""
        # 日志路径
        ttk.Label(parent, text=get_text("log_path_label")).grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.log_path_entry = ttk.Entry(parent)
        self.app.log_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        self.app.log_path_entry.insert(0, Config.DEFAULT_LOG_PATH)
        self.app.log_path_btn = ttk.Button(
            parent,
            text=get_text("browse_log"),
            command=self.app.choose_log_path
        )
        self.app.log_path_btn.grid(row=0, column=2, padx=5, pady=5, sticky=tk.EW)
        
        # 配置列权重
        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_columnconfigure(2, weight=0)
    
    def create_screen_tab(self) -> None:
        """创建屏幕操作 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📸 屏幕操作")
        self.tabs['screen'] = tab
        
        # 创建屏幕功能按钮
        screen_buttons = [
            ("📷 截取当前屏幕", 0, 0, "screencap"),
            ("🎥 开始屏幕录制", 1, 0, "start_recording"),
            ("⏹️ 停止屏幕录制", 1, 1, "stop_recording"),
        ]
        
        self._create_button_grid(tab, screen_buttons, row_offset=0)
    
    def create_advanced_tab(self) -> None:
        """创建高级工具 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="⚙️ 高级工具")
        self.tabs['advanced'] = tab
        
        # 创建高级功能按钮
        advanced_buttons = [
            ("🔧 打开工厂菜单", 0, 0, "open_factory_menu"),
        ]
        
        self._create_button_grid(tab, advanced_buttons, row_offset=0)
    
    def _create_button_grid(self, parent, button_configs: List[Tuple[str, int, int, str]], 
                           row_offset: int = 2) -> None:
        """
        创建按钮网格
        
        Args:
            parent: 父容器
            button_configs: 按钮配置列表 (文本，行，列，方法名)
            row_offset: 行偏移量
        """
        for text, row, col, method_name in button_configs:
            if hasattr(self.app, method_name):
                btn = ttk.Button(
                    parent, 
                    text=text, 
                    command=getattr(self.app, method_name)
                )
                btn.grid(
                    row=row + row_offset, 
                    column=col, 
                    sticky=tk.EW, 
                    padx=5, 
                    pady=5
                )
                # 设置按钮最小宽度
                parent.grid_columnconfigure(col, weight=1, minsize=120)
    
    def create_output_section(self) -> None:
        """创建输出区域"""
        # 状态文本框
        self.app.status_text = tk.Text(self.right_panel, wrap=tk.WORD, width=25)
        self.app.status_text.pack(fill=tk.BOTH, expand=True, padx=0, pady=(0, 5))
        
        # 配置文本标签样式
        self.app.status_text.tag_configure("success", foreground="green")
        self.app.status_text.tag_configure("error", foreground="red")
        self.app.status_text.tag_configure("info", foreground="blue")
        
        # 进度条
        self.app.progress = ttk.Progressbar(
            self.right_panel,
            mode="indeterminate",
            length=Config.PROGRESS_BAR_LENGTH
        )
        self.app.progress.pack(fill=tk.X, pady=5)
        self.app.progress.pack_forget()  # 默认隐藏
    
    def _on_ip_selected(self, event):
        """IP 选择处理"""
        if hasattr(self.app, 'ip_combobox'):
            selected_value = self.app.ip_combobox.get()
            self.app.ip_combobox.set(selected_value)
        
        # 执行 IP 变更处理
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
    设置 GUI 入口函数
    
    Args:
        app: 应用实例
    """
    layout = LayoutTabView(app)
    layout.setup_gui()
