"""
Tab 视图布局 - 重构版本 (三栏布局)
左侧 Tab 导航 + 中间功能按钮 + 右侧输出窗口
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Callable, List, Tuple
from config import Config, get_text


class LayoutTabView:
    """Tab 视图布局类 (三栏布局)"""
    
    def __init__(self, app):
        """
        初始化 Tab 布局
        
        Args:
            app: 应用实例
        """
        self.app = app
        self.main_frame = None
        self.left_panel = None      # 左侧 Tab 导航
        self.center_panel = None    # 中间功能按钮
        self.right_panel = None     # 右侧输出窗口
        self.current_tab_frame = None  # 当前选中的 Tab 内容框架
        self.tabs = {}  # 存储各个 Tab 页
        
    def setup_gui(self):
        """构建完整的三栏布局"""
        # 设置主容器
        self.setup_main_container()
        
        # 创建三栏布局
        self.create_three_column_layout()
        
        # 创建左侧 Tab 导航
        self.create_left_tab_navigation()
        
        # 创建各个 Tab 页内容（功能按钮）
        self.create_device_tab()      # 设备管理
        self.create_app_tab()         # 应用管理
        self.create_log_screen_tab()  # 日志调试与屏幕操作（合并）
        self.create_advanced_tab()    # 高级工具
        
        # 创建右侧输出区域
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
    
    def create_three_column_layout(self) -> None:
        """创建三栏布局：左侧 Tab + 中间功能 + 右侧输出"""
        # 左侧 Tab 面板（固定宽度）
        self.left_panel = ttk.Frame(self.main_frame, width=140)
        self.left_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
        self.left_panel.grid_propagate(False)  # 固定宽度
        
        # 中间功能面板（根据内容自适应宽度）
        self.center_panel = ttk.Frame(self.main_frame)
        self.center_panel.grid(row=0, column=1, sticky=tk.NSEW, padx=5)
        
        # 右侧输出面板（占据剩余所有空间）
        self.right_panel = ttk.Frame(self.main_frame)
        self.right_panel.grid(row=0, column=2, sticky=tk.NSEW, padx=(5, 0))
        
        # 配置网格权重 - 右侧输出区域弹性扩展
        self.main_frame.grid_columnconfigure(0, weight=0)  # 左侧固定
        self.main_frame.grid_columnconfigure(1, weight=0)  # 中间根据内容自适应
        self.main_frame.grid_columnconfigure(2, weight=1)  # 右侧占据剩余空间
        self.main_frame.grid_rowconfigure(0, weight=1)
        
        # 强制更新布局
        self.main_frame.update_idletasks()
    
    def create_left_tab_navigation(self) -> None:
        """创建左侧 Tab 导航栏（垂直排列）"""
        # 使用框架垂直排列 Tab 按钮，添加凹陷边框作为背景
        tab_frame = ttk.Frame(self.left_panel, relief='sunken', borderwidth=2)
        tab_frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        
        # 配置自定义样式 - 使用更深的背景色和更大字体
        style = ttk.Style()
        style.configure('LeftTab.TButton', 
                       font=('Arial', 10, 'bold'),
                       padding=10,
                       anchor='w',
                       background='#e8e8e8')  # 未选中：浅灰色
        
        # 选中状态样式 - 添加明显的蓝色边框和背景
        style.configure('SelectedTab.TButton',
                       font=('Arial', 10, 'bold'),
                       padding=10,
                       anchor='w',
                       background='#0078d7',  # 选中：深蓝色背景 (Windows 标准蓝)
                       relief='solid',        # 实线边框
                       borderwidth=5)         # 边框宽度 5px (更粗)
        
        # 鼠标悬停样式
        style.map('LeftTab.TButton',
                 background=[('active', '#d0d0d0'), ('pressed', '#c0c0c0')])
        
        # 创建各个 Tab 按钮
        tab_configs = [
            ("📱 设备管理", "device"),
            ("📦 应用管理", "app"),
            ("📋 日志与录屏", "log_screen"),  # 合并后的 Tab 名称
            ("⚙️ 高级工具", "advanced"),
        ]
        
        self.tab_buttons = {}  # 保存按钮引用
        
        for i, (text, tab_name) in enumerate(tab_configs):
            btn = ttk.Button(
                tab_frame,
                text=text,
                command=lambda t=tab_name: self.switch_tab(t),
                width=16,
                takefocus=True,
                style='LeftTab.TButton'
            )
            btn.grid(row=i, column=0, sticky=tk.EW, padx=2, pady=3)
            tab_frame.grid_rowconfigure(i, weight=1)
            self.tab_buttons[tab_name] = btn  # 保存按钮引用
        
        tab_frame.grid_columnconfigure(0, weight=1)
        
        # 默认显示第一个 Tab
        self.current_tab_index = 0
        self.current_selected_tab = None  # 当前选中的 Tab
        # 初始化时显示第一个 Tab 的内容
        self.app.root.after(100, lambda: self.switch_tab("device"))
    
    def switch_tab(self, tab_name: str) -> None:
        """切换 Tab 页"""
        # 隐藏所有 Tab 内容
        for name, frame in self.tabs.items():
            frame.grid_forget()
        
        # 显示选中的 Tab 内容
        if tab_name in self.tabs:
            self.tabs[tab_name].grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)
        
        # 更新选中效果
        self._update_tab_selection(tab_name)
    
    def _update_tab_selection(self, selected_tab: str) -> None:
        """更新 Tab 选中效果"""
        if not hasattr(self, 'tab_buttons'):
            return
        
        # 恢复之前选中的 Tab 样式
        if self.current_selected_tab and self.current_selected_tab in self.tab_buttons:
            self.tab_buttons[self.current_selected_tab].configure(
                style='LeftTab.TButton'
            )
        
        # 设置新选中的 Tab 样式
        if selected_tab in self.tab_buttons:
            self.tab_buttons[selected_tab].configure(
                style='SelectedTab.TButton'
            )
            self.current_selected_tab = selected_tab
    
    def create_device_tab(self) -> None:
        """创建设备管理 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['device'] = tab
        
        # 创建输入区域
        self._create_device_input_section(tab)
        
        # 创建设备功能按钮
        device_buttons = [
            ("🔌 连接 ADB", 4, 0, "connect_adb"),
            ("❌ 断开所有 ADB 连接", 4, 1, "disconnect_adb"),
            ("📱 查看已连接设备", 4, 2, "show_device_info"),
            ("🔄 重启 ADB 服务", 5, 0, "restart_adb_server"),  # 新增按钮
            ("📋 获取设备信息", 5, 1, "get_device_info_fast"),
            ("🖥️ 打开 CMD 窗口", 5, 2, "open_cmd_window"),
            ("🔁 重启设备", 6, 0, "reboot"),
            ("📝 常用 ADB 命令", 6, 1, "show_common_adb_commands"),
            ("🔑 获取 Root 权限", 6, 2, "root_device"),
            ("📀 重新挂载分区", 7, 0, "remount"),
            ("获取 Android 版本号", 7, 1, "get_android_version"),
            ("📱 获取设备串号", 7, 2, "get_serial_number"),
        ]
        
        self._create_button_grid(tab, device_buttons)
    
    def _create_device_input_section(self, parent) -> None:
        """创建设备输入区域"""
        # IP Address
        ttk.Label(parent, text=get_text("ip_label")).grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        
        ip_frame = ttk.Frame(parent)
        ip_frame.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky=tk.EW)
        
        # IP 下拉框
        self.app.ip_combobox = ttk.Combobox(ip_frame)
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox['width'] = 20
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
    
    def create_app_tab(self) -> None:
        """创建应用管理 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['app'] = tab
            
        # 创建输入区域
        self._create_app_input_section(tab)
            
        # 创建应用版本展示框
        self._create_app_version_display(tab)
            
        # 创建应用功能按钮
        app_buttons = [
            ("📲 强制安装 APK", 5, 0, "force_install"),
            ("🗑️ 卸载当前包名应用", 5, 1, "uninstall"),
            ("📋 获取已安装应用列表", 5, 2, "package_list"),
            ("🧹 清除应用缓存", 6, 0, "clear_cache"),
            ("⏹️ 终止当前包名进程", 6, 1, "kill_app_process"),
            ("📊 查看内存 CPU 资源占用", 6, 2, "get_app_resource_usage"),
            ("🔍 获取包名版本号", 7, 0, "get_version"),
            ("📂 获取应用安装路径", 7, 1, "get_package_path"),
            ("🔍 获取当前打开应用包名", 7, 2, "get_package_name"),
        ]
            
        self._create_button_grid(tab, app_buttons)
    
    def _create_app_input_section(self, parent) -> None:
        """创建应用输入区域"""
        # 包名
        ttk.Label(parent, text=get_text("package_label")).grid(
            row=0, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.pkg_combobox = ttk.Combobox(parent)
        self.app.pkg_combobox.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky=tk.EW)
        self.app.pkg_combobox['height'] = 10
        self.app.pkg_combobox['width'] = 20
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
    
    def _create_app_version_display(self, parent) -> None:
        """创建应用版本展示框"""
        # 版本号
        ttk.Label(parent, text="应用版本:").grid(
            row=2, column=0, padx=5, pady=5, sticky=tk.W
        )
        self.app.version_display = ttk.Entry(parent, state='readonly')
        self.app.version_display.grid(row=2, column=1, columnspan=3, padx=5, pady=5, sticky=tk.EW)
        self.app.version_display['width'] = 20
        
        # 配置列权重
        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)
    
    def create_log_screen_tab(self) -> None:
        """创建日志调试与屏幕操作合并的 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['log_screen'] = tab
        
        # 创建输入区域（日志路径）
        self._create_log_input_section(tab)
        
        # 创建日志功能按钮（从第 1 行开始）
        log_buttons = [
            ("▶️ 启动日志捕获", 1, 0, "start_logcat"),
            ("⏹️ 停止日志捕获", 1, 1, "stop_logcat"),
            ("🧹 清除日志缓存", 1, 2, "log_clear"),
            ("📥 导出 ANR 文件", 2, 0, "pull_anr_file"),
            ("📜 功能按键原始命令", 2, 1, "show_all_adb_commands"),
        ]
        
        self._create_button_grid(tab, log_buttons, row_offset=0)
        
        # 创建屏幕录制功能按钮（添加分隔标签，从第 3 行开始）
        ttk.Label(tab, text="─ 屏幕操作 ─").grid(
            row=3, column=0, columnspan=3, padx=5, pady=(15, 5), sticky=tk.W
        )
        
        screen_buttons = [
            ("🎥 开始屏幕录制", 4, 0, "start_recording"),
            ("⏹️ 停止屏幕录制", 4, 1, "stop_recording"),
            ("📷 截取当前屏幕", 4, 2, "screencap"),
        ]
        
        self._create_button_grid(tab, screen_buttons, row_offset=0)
        
        # 添加存储文件夹按钮（使用不同的样式突出显示）
        ttk.Label(tab, text="─ 文件管理 ─").grid(
            row=5, column=0, columnspan=3, padx=5, pady=(15, 5), sticky=tk.W
        )
        
        storage_btn = ttk.Button(
            tab,
            text="📂 打开日志截屏录屏储存文件夹",
            command=self.app.open_storage_folder
        )
        storage_btn.grid(
            row=6, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=5
        )
        tab.grid_columnconfigure(0, weight=1, minsize=150)
        tab.grid_columnconfigure(1, weight=1, minsize=150)
        tab.grid_columnconfigure(2, weight=1, minsize=150)
    
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
    

    
    def create_advanced_tab(self) -> None:
        """创建高级工具 Tab"""
        tab = ttk.Frame(self.center_panel)
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
                parent.grid_columnconfigure(col, weight=1, minsize=150)
    
    def create_output_section(self) -> None:
        """创建输出区域"""
        # 状态文本框（自动填充整个右侧面板）
        self.app.status_text = tk.Text(self.right_panel, wrap=tk.WORD)
        self.app.status_text.pack(fill=tk.BOTH, expand=True, padx=0, pady=(0, 5))
        
        # 配置文本标签样式
        self.app.status_text.tag_configure("success", foreground="green")
        self.app.status_text.tag_configure("error", foreground="red")
        self.app.status_text.tag_configure("info", foreground="blue")
        
        # 进度条（自动适应宽度）
        self.app.progress = ttk.Progressbar(
            self.right_panel,
            mode="indeterminate"
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