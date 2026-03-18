"""
Tab 页布局模块
为 ADB 工具提供基于 Tab 页的界面分类功能
"""
import tkinter as tk
from tkinter import ttk
from functools import partial  # 添加 partial 导入
from typing import Dict, Any, Callable, List, Tuple
from config import Config, get_text


class TabLayout:
    """Tab页布局管理器"""
    
    def __init__(self, app):
        """
        初始化Tab布局
        
        Args:
            app: 应用实例
        """
        self.app = app
        self.notebook = None
        self.tabs = {}  # 存储各个tab页的frame
        
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
        # 左侧控制面板（包含Tab页）
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
        """创建输入区域（在Tab页上方）"""
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
        
        # 优化事件绑定：确保IP选择及时响应
        # Combobox选择事件 - 立即处理
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)
        # 移除FocusOut事件绑定，避免冲突和重复处理
        # FocusOut事件通常在用户完成编辑时触发，但对于下拉选择来说不需要

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
        
        # Log Path
        ttk.Label(self.left_panel, text=get_text("log_path_label")).grid(
            row=3, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.log_path_entry = ttk.Entry(self.left_panel)
        self.app.log_path_entry.grid(row=3, column=1, padx=5, pady=5, sticky=tk.EW)
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
    
    def create_tab_pages(self) -> None:
        """创建Tab页面"""
        # 创建Notebook控件
        self.notebook = ttk.Notebook(self.left_panel)
        self.notebook.grid(row=4, column=0, columnspan=3, sticky=tk.NSEW, padx=5, pady=5)
        
        # 配置Tab页的权重
        self.left_panel.grid_rowconfigure(4, weight=1)
        
        # 定义 Tab 页配置
        tab_configs = [
            ("设备管理", self._create_device_management_tab),
            ("应用管理", self._create_app_management_tab),
            ("日志与录屏", self._create_log_screen_tab),  # 合并后的 Tab
            ("系统信息", self._create_system_info_tab),
        ]
        
        # 创建各个Tab页
        for tab_name, create_func in tab_configs:
            tab_frame = ttk.Frame(self.notebook)
            self.notebook.add(tab_frame, text=tab_name)
            self.tabs[tab_name] = tab_frame
            # 调用对应的创建函数
            create_func(tab_frame)
    
    def _create_device_management_tab(self, parent_frame: ttk.Frame) -> None:
        """创建设备管理Tab页"""
        # 设备管理相关按钮
        device_buttons = [
            ("连接 ADB", "connect_adb"),
            ("断开所有ADB连接", "disconnect_adb"),
            ("查看已连接设备", "show_device_info"),
        ]
        
        self._create_button_grid(parent_frame, device_buttons, columns=1)
    
    def _create_app_management_tab(self, parent_frame: ttk.Frame) -> None:
        """创建应用管理Tab页"""
        # 应用管理相关按钮
        app_buttons = [
            ("强制安装apk", "force_install"),
            ("卸载当前包名应用", "uninstall"),
            ("获取已安装应用包名列表", "package_list"),
            ("清除应用缓存", "clear_cache"),
            ("终止当前包名所有进程", "kill_app_process"),
            ("获取当前包名版本号", "get_version"),
            ("获取当前包名应用安装路径", "get_package_path"),
        ]
        
        self._create_button_grid(parent_frame, app_buttons, columns=2)
    
    def _create_log_screen_tab(self, parent_frame: ttk.Frame) -> None:
        """创建日志调试与屏幕操作合并的 Tab 页"""
        # 日志调试相关按钮
        log_buttons = [
            ("启动日志捕获", "start_logcat"),
            ("停止日志捕获", "stop_logcat"),
            ("清除日志缓存", "log_clear"),
            ("导出 ANR 文件", "pull_anr_file"),
        ]
            
        self._create_button_grid(parent_frame, log_buttons, columns=2)
            
        # 添加分隔标签
        separator = ttk.Label(parent_frame, text="─ 屏幕操作 ─")
        separator.grid(row=2, column=0, columnspan=2, pady=(15, 5), sticky=tk.W)
            
        # 屏幕操作相关按钮（按用户要求的顺序）
        screen_buttons = [
            ("开始屏幕录制", "start_recording"),      # 第一
            ("停止屏幕录制", "stop_recording"),      # 第二
            ("截取当前屏幕", "screencap"),          # 第三
        ]
            
        # 从第 3 行开始放置屏幕操作按钮（横向排列）
        for i, (text, method_name) in enumerate(screen_buttons):
            row = 3  # 都在第 3 行
            col = i  # 第 0、1、2 列，横向排列
                    
            if hasattr(self.app, method_name):
                btn = ttk.Button(parent_frame, text=text)
                def on_click(m=method_name, t=text):
                    self.app.root.after(0, lambda: self.app.execute_task_async(t, m))
                btn.configure(command=on_click)
                btn.grid(row=row, column=col, sticky=tk.EW, padx=5, pady=5)
            else:
                btn = ttk.Button(parent_frame, text=text, state="disabled")
                btn.grid(row=row, column=col, sticky=tk.EW, padx=5, pady=5)
        
        # 添加存储文件夹按钮
        separator2 = ttk.Label(parent_frame, text="─ 文件管理 ─")
        separator2.grid(row=5, column=0, columnspan=2, pady=(15, 5), sticky=tk.W)
        
        storage_btn = ttk.Button(
            parent_frame,
            text="打开日志截屏录屏储存文件夹",
            command=self.app.open_storage_folder
        )
        storage_btn.grid(row=6, column=0, columnspan=2, sticky=tk.EW, padx=5, pady=5)
            
        # 配置列权重使按钮能够伸缩
        for i in range(2):
            parent_frame.grid_columnconfigure(i, weight=1)
    
    def _create_system_info_tab(self, parent_frame: ttk.Frame) -> None:
        """创建系统信息Tab页"""
        # 系统信息相关按钮
        system_buttons = [
            ("获取Android版本号", "get_android_version"),
            ("获取设备串号", "get_serial_number"),
            ("截取当前屏幕", "screencap"),
            ("开始屏幕录制", "start_recording"),
            ("停止屏幕录制", "stop_recording"),
            ("获取Root权限", "root_device"),
            ("重新挂载分区", "remount"),
            ("重启设备", "reboot"),
            ("获取当前打开应用包名", "get_package_name"),
            ("功能按键原始执行命令", "show_all_adb_commands"),
            ("打开工厂菜单", "open_factory_menu"),
        ]
        
        self._create_button_grid(parent_frame, system_buttons, columns=2)
    
    def _create_button_grid(self, parent_frame: ttk.Frame, buttons: List[Tuple[str, str]], columns: int = 2) -> None:
        """创建按钮网格布局（底层优化版 - 添加视觉反馈）
            
        Args:
            parent_frame: 父框架
            buttons: 按钮配置列表 [(文本，方法名), ...]
            columns: 列数
        """
        for i, (text, method_name) in enumerate(buttons):
            row = i // columns
            col = i % columns
                
            # 检查方法是否存在
            if hasattr(self.app, method_name):
                # 创建按钮
                btn = ttk.Button(parent_frame, text=text)
                    
                # 底层优化：绑定点击事件，添加视觉反馈
                def on_click(m=method_name, t=text):
                    # 立即返回，让 UI 线程可以响应
                    self.app.root.after(0, lambda: self.app.execute_task_async(t, m))
                    
                btn.configure(command=on_click)
                btn.grid(row=row, column=col, sticky=tk.EW, padx=5, pady=5)
            else:
                # 如果方法不存在，创建禁用的按钮
                btn = ttk.Button(parent_frame, text=text, state="disabled")
                btn.grid(row=row, column=col, sticky=tk.EW, padx=5, pady=5)
            
        # 配置列权重使按钮能够伸缩
        for i in range(columns):
            parent_frame.grid_columnconfigure(i, weight=1)
    
    def _on_ip_selected(self, event):
        """优化的IP选择处理"""
        # 立即更新combobox的值以确保UI同步
        if hasattr(self.app, 'ip_combobox'):
            # 获取选中的值
            selected_value = self.app.ip_combobox.get()
            # 确保值正确设置到combobox中
            self.app.ip_combobox.set(selected_value)
        
        # 立即执行IP变更处理，不再延迟
        self.app.on_ip_changed(event)
    
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
        """设置键盘快捷键（异步优化版）"""
        shortcuts = {
            '<Control-q>': lambda e: self.app.root.quit(),
            '<Control-c>': lambda e: self.app.execute_task_async("连接 ADB", "connect_adb"),
            '<Control-d>': lambda e: self.app.execute_task_async("断开 ADB", "disconnect_adb"),
            '<Control-i>': lambda e: self.app.execute_task_async("强制安装", "force_install"),
            '<Control-u>': lambda e: self.app.execute_task_async("卸载应用", "uninstall"),
            '<Control-l>': lambda e: self.app.execute_task_async("获取应用列表", "package_list"),
            '<F5>': lambda e: self.app.execute_task_async("重启设备", "reboot"),
            '<F12>': lambda e: self.app.execute_task_async("屏幕截图", "screencap"),
        }
        
        for shortcut, handler in shortcuts.items():
            self.app.root.bind(shortcut, handler)


def get_tab_button_configs() -> Dict[str, List[Tuple[str, str]]]:
    """
    获取Tab页按钮配置
        
    Returns:
        Dict[str, List[Tuple[str, str]]]: 按Tab页分类的按钮配置
    """
    return {
        "设备管理": [
            ("连接 ADB", "connect_adb"),
            ("断开所有ADB连接", "disconnect_adb"),
            ("查看已连接设备", "show_device_info"),
        ],
        "应用管理": [
            ("强制安装apk", "force_install"),
            ("卸载当前包名应用", "uninstall"),
            ("获取已安装应用包名列表", "package_list"),
            ("清除应用缓存", "clear_cache"),
            ("终止当前包名所有进程", "kill_app_process"),
            ("获取当前包名版本号", "get_version"),
            ("获取当前包名应用安装路径", "get_package_path"),
        ],
        "日志与录屏": [
            ("启动日志捕获", "start_logcat"),
            ("停止日志捕获", "stop_logcat"),
            ("清除日志缓存", "log_clear"),
            ("导出 ANR 文件", "pull_anr_file"),
            ("截取当前屏幕", "screencap"),
            ("开始屏幕录制", "start_recording"),
            ("停止屏幕录制", "stop_recording"),
        ],
        "系统信息": [
            ("获取 Android 版本号", "get_android_version"),
            ("获取设备串号", "get_serial_number"),
            ("获取 Root 权限", "root_device"),
            ("重新挂载分区", "remount"),
            ("重启设备", "reboot"),
            ("获取当前打开应用包名", "get_package_name"),
            ("功能按键原始执行命令", "show_all_adb_commands"),
            ("打开工厂菜单", "open_factory_menu"),
        ]
    }