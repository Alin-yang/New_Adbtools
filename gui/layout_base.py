"""
GUI布局基类模块
为中文界面提供统一的布局创建和管理功能
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Callable, List, Tuple
from config import Config, get_text


class LayoutBase:
    """GUI布局基类"""
    
    def __init__(self, app):
        """
        初始化布局基类
        
        Args:
            app: 应用实例
        """
        self.app = app
        self.main_frame = None
        self.left_panel = None
        self.right_panel = None
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 配置窗口标题和大小
        self.app.root.title(get_text("window_title"))
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        if hasattr(Config, 'MIN_WINDOW_SIZE'):
            self.app.root.minsize(*Config.MIN_WINDOW_SIZE)
    
    def create_panels(self, left_weight: int = 50, right_weight: int = 40) -> None:
        """
        创建左右分栏面板
        
        Args:
            left_weight: 左侧面板权重
            right_weight: 右侧面板权重
        """
        # 左侧控制面板
        self.left_panel = ttk.Frame(self.main_frame)
        self.left_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=5)
        self.left_panel.grid_propagate(False)
        
        # 右侧输出面板
        self.right_panel = ttk.Frame(self.main_frame)
        self.right_panel.grid(row=0, column=1, sticky=tk.NSEW, padx=(10, 5))
        self.right_panel.grid_propagate(False)
        
        # 配置网格权重
        self.main_frame.grid_columnconfigure(0, weight=left_weight)
        self.main_frame.grid_columnconfigure(1, weight=right_weight)
        self.main_frame.grid_rowconfigure(0, weight=1)
    
    def create_input_section(self) -> None:
        """创建输入区域"""
        # IP Address
        ttk.Label(self.left_panel, text=get_text("ip_label")).grid(
            row=0, column=0, padx=5, pady=2, sticky=tk.W
        )
        
        # 创建一个框架来容纳IP输入框和状态标签
        ip_frame = ttk.Frame(self.left_panel)
        ip_frame.grid(row=0, column=1, padx=5, pady=2, sticky=tk.EW)
        
        # 使用下拉框支持IP历史记录
        self.app.ip_combobox = ttk.Combobox(ip_frame)
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app.ip_combobox['height'] = 8  # 减少下拉高度，提高响应速度
        self.app.ip_combobox['width'] = 12
        # 设置默认IP前缀，方便快速输入
        self.app.ip_combobox.insert(0, "192.168.")
        
        # 连接状态标签
        self.app.connection_status_label = ttk.Label(
            ip_frame, 
            text="未连接", 
            foreground="gray",
            width=12
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # 优化事件绑定：减少不必要的事件处理
        # 只在用户明确选择时才触发完整处理
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)
        # FocusOut事件保持原有行为
        self.app.ip_combobox.bind('<FocusOut>', lambda e: self.app.on_ip_changed(e))
        
        # 创建其他输入区域
        self.create_package_section()
        self.create_apk_section()
        self.create_log_path_section()

    def _on_ip_selected(self, event):
        """优化的IP选择处理"""
        # 在主线程中延迟执行，避免阻塞UI
        self.app.root.after(10, lambda: self.app.on_ip_changed(event))

    def create_package_section(self) -> None:
        """创建包名输入区域"""
        # Package Name
        ttk.Label(self.left_panel, text=get_text("package_label")).grid(
            row=1, column=0, padx=5, pady=5, sticky=tk.W
        )
        # 使用下拉框支持包名历史记录
        self.app.pkg_combobox = ttk.Combobox(self.left_panel)
        self.app.pkg_combobox.grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
        self.app.pkg_combobox['height'] = 10
        self.app.pkg_combobox['width'] = 15
        
        # 为了向后兼容，创建一个 pkg_entry 属性指向 pkg_combobox
        self.app.pkg_entry = self.app.pkg_combobox
        
    def create_apk_section(self) -> None:
        """创建APK文件输入区域"""
        # APK File
        ttk.Label(self.left_panel, text=get_text("apk_label")).grid(
            row=2, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.apk_entry = ttk.Entry(self.left_panel)
        self.app.apk_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.EW)
        self.app.browse_btn = ttk.Button(
            self.left_panel,
            text=get_text("browse_apk"),
            command=self.app.browse_apk
        )
        self.app.browse_btn.grid(row=2, column=2, sticky=tk.EW, padx=5, pady=5)
        
    def create_log_path_section(self) -> None:
        """创建日志路径输入区域"""
        # Log Path
        ttk.Label(self.left_panel, text=get_text("log_path_label")).grid(
            row=3, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.log_path_entry = ttk.Entry(self.left_panel)
        self.app.log_path_entry.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)
        self.app.log_path_entry['width'] = 30
        self.app.log_path_entry.insert(0, Config.DEFAULT_LOG_PATH)
        self.app.log_path_btn = ttk.Button(
            self.left_panel,
            text=get_text("browse_log"),
            command=self.app.choose_log_path
        )
        self.app.log_path_btn.grid(row=3, column=2, padx=5, pady=5, sticky=tk.EW)
        
        # 配置左侧面板的列权重
        self.left_panel.grid_columnconfigure(0, weight=1)
        self.left_panel.grid_columnconfigure(1, weight=2)
        self.left_panel.grid_columnconfigure(2, weight=1)
    
    def create_buttons(self, button_config: List[Tuple[str, int, int, Callable]]) -> None:
        """
        创建功能按钮
        
        Args:
            button_config: 按钮配置列表，每个元素为(文本, 行, 列, 回调函数)
        """
        for text, row, col, command in button_config:
            ttk.Button(self.left_panel, text=text, command=command).grid(
                row=row, column=col, sticky=tk.EW, padx=5, pady=5
            )
    
    def create_output_section(self) -> None:
        """创建输出区域"""
        # 状态文本框
        self.app.status_text = tk.Text(self.right_panel, wrap=tk.WORD, width=25)
        self.app.status_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
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


def get_button_configs() -> List[Tuple[str, int, int, str]]:
    """
    获取中文按钮配置
        
    Returns:
        List[Tuple[str, int, int, str]]: 按钮配置列表(文本, 行, 列, 方法名)
    """
    return [
        ("连接 ADB", 4, 0, "connect_adb"),
        ("断开所有ADB连接", 4, 1, "disconnect_adb"),
        ("查看已连接设备", 4, 2, "show_device_info"),
        ("强制安装apk", 5, 0, "force_install"),
        ("卸载当前包名应用", 5, 1, "uninstall"),
        ("获取已安装应用包名列表", 5, 2, "package_list"),
        ("清除应用缓存", 6, 0, "clear_cache"),
        ("获取Root权限", 6, 1, "root_device"),
        ("导出ANR文件", 6, 2, "pull_anr_file"),
        ("重新挂载分区", 7, 0, "remount"),
        ("获取当前包名版本号", 7, 1, "get_version"),
        ("重启设备", 7, 2, "reboot"),
        ("获取Android版本号", 8, 0, "get_android_version"),
        ("启动日志捕获", 8, 1, "start_logcat"),
        ("停止日志捕获", 8, 2, "stop_logcat"),
        ("终止当前包名所有进程", 9, 0, "kill_app_process"),
        ("清除日志缓存", 9, 1, "log_clear"),
        ("获取当前打开应用包名", 9, 2, "get_package_name"),
        ("获取当前包名应用安装路径", 10, 0, "get_package_path"),
        ("开始屏幕录制", 10, 1, "start_recording"),
        ("停止屏幕录制", 10, 2, "stop_recording"),
        ("截取当前屏幕", 0, 2, "screencap"),
        ("获取设备串号", 1, 2, "get_serial_number"),
        ("功能按键原始执行命令", 11, 0, "show_all_adb_commands"),
        ("打开工厂菜单", 11, 2, "open_factory_menu"),
    ]