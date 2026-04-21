"""
优化版 Tab 视图布局 - 四区布局
顶部工具栏 + 左侧 Tab 导航 + 中间功能按钮 + 右侧输出窗口 + 底部快捷栏
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Callable, List, Tuple
from config import Config, get_text


class LayoutOptimized:
    """优化版布局类 (四区布局)"""
    
    def __init__(self, app):
        """
        初始化优化布局
        
        Args:
            app: 应用实例
        """
        self.app = app
        self.main_frame = None
        self.top_toolbar = None       # 顶部工具栏
        self.left_panel = None        # 左侧 Tab 导航
        self.center_panel = None      # 中间功能按钮
        self.right_panel = None       # 右侧输出窗口
        self.bottom_bar = None        # 底部快捷栏
        self.current_tab_frame = None
        self.tabs = {}
        
    def setup_gui(self):
        """构建完整的四区布局"""
        # 设置主容器
        self.setup_main_container()
        
        # 创建四区布局框架
        self.create_four_zone_layout()
        
        # 创建顶部工具栏
        self.create_top_toolbar()
        
        # 创建左侧 Tab 导航
        self.create_left_tab_navigation()
        
        # 创建各个 Tab 页内容（功能按钮）
        self.create_device_tab()
        self.create_app_tab()
        self.create_log_screen_tab()
        self.create_advanced_tab()
        
        # 创建右侧输出区域
        self.create_output_section()
        
        # 设置快捷键
        self.setup_keyboard_shortcuts()
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # 配置窗口标题和大小
        self.app.root.title(get_text("window_title"))
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        if hasattr(Config, 'MIN_WINDOW_SIZE'):
            self.app.root.minsize(*Config.MIN_WINDOW_SIZE)
    
    def create_four_zone_layout(self) -> None:
        """创建四区布局：顶部 + 左中右 + 底部"""
        # 顶部工具栏（固定高度）
        self.top_toolbar = ttk.Frame(self.main_frame, height=50)
        self.top_toolbar.grid(row=0, column=0, columnspan=4, sticky=tk.EW, pady=(0, 5))
        self.top_toolbar.grid_propagate(False)
        
        # 左侧 Tab 面板（固定宽度）
        self.left_panel = ttk.Frame(self.main_frame, width=130)
        self.left_panel.grid(row=1, column=0, sticky=tk.NSEW)
        self.left_panel.grid_propagate(False)
        
        # 垂直分割线
        separator1 = tk.Frame(self.main_frame, bg='#e0e0e0', width=1)
        separator1.grid(row=1, column=1, sticky=tk.NS)
        
        # 中间功能面板（自适应宽度，带滚动）
        self.center_container = ttk.Frame(self.main_frame)
        self.center_container.grid(row=1, column=2, sticky=tk.NSEW, padx=(8, 5))
        
        # 创建 Canvas 和滚动条
        self.center_canvas = tk.Canvas(self.center_container, highlightthickness=0)
        center_scrollbar = ttk.Scrollbar(self.center_container, orient=tk.VERTICAL, command=self.center_canvas.yview)
        self.center_scrollable_frame = ttk.Frame(self.center_canvas)
        
        self.center_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.center_canvas.configure(scrollregion=self.center_canvas.bbox("all"))
        )
        
        self.center_canvas.create_window((0, 0), window=self.center_scrollable_frame, anchor="nw")
        self.center_canvas.configure(yscrollcommand=center_scrollbar.set)
        
        self.center_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        center_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            self.center_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.center_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # 中间面板引用改为滚动框架
        self.center_panel = self.center_scrollable_frame
        
        # 右侧输出面板（占据剩余空间）
        self.right_panel = ttk.Frame(self.main_frame)
        self.right_panel.grid(row=1, column=3, sticky=tk.NSEW, padx=(5, 0))
        
        # 配置网格权重
        self.main_frame.grid_columnconfigure(0, weight=0)   # 左侧固定
        self.main_frame.grid_columnconfigure(1, weight=0)   # 分割线
        self.main_frame.grid_columnconfigure(2, weight=0)   # 中间自适应
        self.main_frame.grid_columnconfigure(3, weight=1)   # 右侧扩展
        self.main_frame.grid_rowconfigure(0, weight=0)      # 顶部固定
        self.main_frame.grid_rowconfigure(1, weight=1)      # 中间扩展
    
    def create_top_toolbar(self) -> None:
        """创建顶部工具栏"""
        toolbar_frame = ttk.Frame(self.top_toolbar)
        toolbar_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # === 左侧：设备信息区 ===
        device_info_frame = ttk.LabelFrame(toolbar_frame, text="📱 当前设备", padding=(8, 5))
        device_info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # IP/设备标识输入框
        ip_frame = ttk.Frame(device_info_frame)
        ip_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(ip_frame, text="设备:", font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        self.app.ip_combobox = ttk.Combobox(ip_frame, width=18)
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox.insert(0, "192.168.")
        
        # 连接状态标签
        self.app.connection_status_label = ttk.Label(
            ip_frame, 
            text="未连接", 
            foreground="gray",
            font=('Microsoft YaHei UI', 9, 'bold'),
            width=10
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(8, 0))
        
        # 绑定事件
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)
        
        # === 中间：快速操作按钮 ===
        quick_actions_frame = ttk.Frame(toolbar_frame)
        quick_actions_frame.pack(side=tk.LEFT, padx=5)
        
        # 刷新设备按钮
        refresh_btn = ttk.Button(
            quick_actions_frame,
            text="🔄 刷新设备",
            command=self.app.show_device_info,
            width=12
        )
        refresh_btn.pack(side=tk.LEFT, padx=2)
        
        # 断开连接按钮
        disconnect_btn = ttk.Button(
            quick_actions_frame,
            text="❌ 断开",
            command=self.app.disconnect_adb,
            width=10
        )
        disconnect_btn.pack(side=tk.LEFT, padx=2)
    
    def create_left_tab_navigation(self) -> None:
        """创建左侧 Tab 导航栏"""
        tab_frame = ttk.LabelFrame(
            self.left_panel, 
            text="功能模块",
            padding=(5, 8)
        )
        tab_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 配置样式
        style = ttk.Style()
        
        style.configure('LeftTab.TButton', 
                       font=('Microsoft YaHei UI', 10),
                       padding=(12, 10),
                       anchor='w',
                       background='#f5f5f5',
                       foreground='#333333',
                       relief='flat')
        
        style.configure('SelectedTab.TButton',
                       font=('Microsoft YaHei UI', 10, 'bold'),
                       padding=(12, 10),
                       anchor='w',
                       background='#e3f2fd',
                       foreground='#1976D2',
                       relief='solid',
                       borderwidth=3,
                       lightcolor='#42A5F5',
                       darkcolor='#1565C0')
        
        style.map('LeftTab.TButton',
                 background=[('active', '#e0e0e0')])
        
        style.map('SelectedTab.TButton',
                 background=[('active', '#bbdefb')])
        
        # 创建 Tab 按钮
        tab_configs = [
            ("📱 设备管理", "device"),
            ("📦 应用管理", "app"),
            ("📋 日志录屏", "log_screen"),
            ("⚙️ 高级工具", "advanced"),
        ]
        
        self.tab_buttons = {}
        
        for i, (text, tab_name) in enumerate(tab_configs):
            btn = ttk.Button(
                tab_frame,
                text=text,
                command=lambda t=tab_name: self.switch_tab(t),
                width=14,
                takefocus=False,
                style='LeftTab.TButton'
            )
            btn.grid(row=i, column=0, sticky=tk.EW, padx=2, pady=2)
            tab_frame.grid_rowconfigure(i, weight=1)
            self.tab_buttons[tab_name] = btn
        
        tab_frame.grid_columnconfigure(0, weight=1)
        
        # 默认显示第一个 Tab
        self.current_selected_tab = None
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
        
        if self.current_selected_tab and self.current_selected_tab in self.tab_buttons:
            self.tab_buttons[self.current_selected_tab].configure(
                style='LeftTab.TButton'
            )
        
        if selected_tab in self.tab_buttons:
            self.tab_buttons[selected_tab].configure(
                style='SelectedTab.TButton'
            )
            self.current_selected_tab = selected_tab
    
    def create_device_tab(self) -> None:
        """创建设备管理 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['device'] = tab
        
        # 使用卡片式布局组织功能
        self._create_function_card(tab, "ADB 服务管理", [
            ("🔌 连接 ADB", "connect_adb"),
            ("❌ 断开所有", "disconnect_adb"),
            ("🔄 重启服务", "restart_adb_server"),
        ], row=0)
        
        self._create_function_card(tab, "设备信息", [
            ("📱 查看设备", "show_device_info"),
            ("📋 详细信息", "get_device_info_fast"),
            ("📱 获取串号", "get_serial_number"),
        ], row=1)
        
        self._create_function_card(tab, "设备控制", [
            ("🔁 重启设备", "reboot"),
            ("🔑 Root权限", "root_device"),
            ("📀 重新挂载", "remount"),
        ], row=2)
        
        self._create_function_card(tab, "系统工具", [
            ("🖥️ 打开CMD", "open_cmd_window"),
            ("📝 常用命令", "show_common_adb_commands"),
            ("版本号", "get_android_version"),
        ], row=3)
        
        # 文本输入区域
        self._create_text_input_section(tab)
    
    def _create_function_card(self, parent, title: str, buttons: List[Tuple[str, str]], row: int) -> None:
        """创建功能卡片"""
        card = ttk.LabelFrame(parent, text=title, padding=(8, 6))
        card.grid(row=row, column=0, sticky=tk.EW, padx=5, pady=4)
        parent.grid_columnconfigure(0, weight=1)
        
        # 创建按钮网格
        for i, (text, method_name) in enumerate(buttons):
            if hasattr(self.app, method_name):
                btn = ttk.Button(
                    card,
                    text=text,
                    command=getattr(self.app, method_name),
                    width=14
                )
                btn.grid(row=0, column=i, sticky=tk.EW, padx=3, pady=2)
                card.grid_columnconfigure(i, weight=1)
    
    def _create_text_input_section(self, parent) -> None:
        """创建文本输入区域"""
        input_frame = ttk.LabelFrame(parent, text="文本输入", padding=(8, 6))
        input_frame.grid(row=4, column=0, sticky=tk.EW, padx=5, pady=4)
        parent.grid_columnconfigure(0, weight=1)
        
        entry_frame = ttk.Frame(input_frame)
        entry_frame.pack(fill=tk.X)
        
        self.app.text_input_entry = ttk.Entry(entry_frame)
        self.app.text_input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
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
            width=8
        )
        send_btn.pack(side=tk.LEFT)
    
    def create_app_tab(self) -> None:
        """创建应用管理 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['app'] = tab
        
        # 输入区域
        self._create_app_input_section(tab)
        
        # 功能卡片
        self._create_function_card(tab, "应用操作", [
            ("📲 强制安装", "force_install"),
            ("🗑️ 卸载应用", "uninstall"),
            ("🧹 清除缓存", "clear_cache"),
        ], row=2)
        
        self._create_function_card(tab, "启动与进程", [
            ("▶️ 启动应用", "start_app"),
            ("⏹️ 终止进程", "kill_app_process"),
            ("📊 资源占用", "get_app_resource_usage"),
        ], row=3)
        
        self._create_function_card(tab, "应用信息", [
            ("🔍 版本号", "get_version"),
            ("📂 安装路径", "get_package_path"),
            ("🔍 当前包名", "get_package_name"),
        ], row=4)
        
        self._create_function_card(tab, "应用列表", [
            ("📋 已安装列表", "package_list"),
        ], row=5)
    
    def _create_app_input_section(self, parent) -> None:
        """创建应用输入区域"""
        input_frame = ttk.LabelFrame(parent, text="应用信息", padding=(8, 6))
        input_frame.grid(row=0, column=0, sticky=tk.EW, padx=5, pady=4)
        parent.grid_columnconfigure(0, weight=1)
        
        # 包名输入
        pkg_frame = ttk.Frame(input_frame)
        pkg_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(pkg_frame, text="包名:", width=6).pack(side=tk.LEFT)
        self.app.pkg_combobox = ttk.Combobox(pkg_frame, width=25)
        self.app.pkg_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.pkg_combobox['height'] = 10
        self.app.pkg_entry = self.app.pkg_combobox
        
        # APK 文件
        apk_frame = ttk.Frame(input_frame)
        apk_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(apk_frame, text="APK:", width=6).pack(side=tk.LEFT)
        self.app.apk_entry = ttk.Entry(apk_frame)
        self.app.apk_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        browse_btn = ttk.Button(
            apk_frame,
            text="浏览",
            command=self.app.browse_apk,
            width=8
        )
        browse_btn.pack(side=tk.LEFT)
        
        # 版本显示
        version_frame = ttk.Frame(input_frame)
        version_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(version_frame, text="版本:", width=6).pack(side=tk.LEFT)
        self.app.version_display = ttk.Entry(version_frame, state='readonly', width=25)
        self.app.version_display.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    
    def create_log_screen_tab(self) -> None:
        """创建日志调试与屏幕操作合并的 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['log_screen'] = tab
        
        # 日志路径输入
        log_path_frame = ttk.LabelFrame(tab, text="日志设置", padding=(8, 6))
        log_path_frame.grid(row=0, column=0, sticky=tk.EW, padx=5, pady=4)
        tab.grid_columnconfigure(0, weight=1)
        
        path_frame = ttk.Frame(log_path_frame)
        path_frame.pack(fill=tk.X)
        
        ttk.Label(path_frame, text="路径:", width=6).pack(side=tk.LEFT)
        self.app.log_path_entry = ttk.Entry(path_frame)
        self.app.log_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.log_path_entry.insert(0, Config.DEFAULT_LOG_PATH)
        
        browse_btn = ttk.Button(
            path_frame,
            text="浏览",
            command=self.app.choose_log_path,
            width=8
        )
        browse_btn.pack(side=tk.LEFT)
        
        # 功能卡片
        self._create_function_card(tab, "日志捕获", [
            ("▶️ 开始捕获", "start_logcat"),
            ("⏹️ 停止捕获", "stop_logcat"),
            ("🧹 清除缓存", "log_clear"),
        ], row=1)
        
        self._create_function_card(tab, "ANR与命令", [
            ("📥 导出ANR", "pull_anr_file"),
            ("📜 原始命令", "show_all_adb_commands"),
        ], row=2)
        
        self._create_function_card(tab, "屏幕操作", [
            ("🎥 开始录制", "start_recording"),
            ("⏹️ 停止录制", "stop_recording"),
            ("📷 截屏", "screencap"),
        ], row=3)
        
        # 打开存储文件夹按钮
        storage_btn = ttk.Button(
            tab,
            text="📂 打开储存文件夹",
            command=self.app.open_storage_folder,
            width=20
        )
        storage_btn.grid(row=4, column=0, sticky=tk.EW, padx=5, pady=8)
    
    def create_advanced_tab(self) -> None:
        """创建高级工具 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['advanced'] = tab
        
        self._create_function_card(tab, "工厂菜单", [
            ("🔧 打开工厂菜单", "open_factory_menu"),
        ], row=0)
    
    def create_output_section(self) -> None:
        """创建输出区域"""
        # 输出区域标题
        output_header = ttk.Frame(self.right_panel)
        output_header.pack(fill=tk.X, pady=(0, 3))
        
        ttk.Label(output_header, text="📄 输出结果", font=('Microsoft YaHei UI', 10, 'bold')).pack(side=tk.LEFT)
        
        # 清空按钮
        clear_btn = ttk.Button(
            output_header,
            text="清空",
            command=self._clear_output,
            width=6
        )
        clear_btn.pack(side=tk.RIGHT)
        
        # 状态文本框
        self.app.status_text = tk.Text(
            self.right_panel,
            wrap=tk.WORD,
            font=('Consolas', 9),
            bg='#fafafa'
        )
        self.app.status_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # 滚动条
        scrollbar = ttk.Scrollbar(self.app.status_text, command=self.app.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.status_text.config(yscrollcommand=scrollbar.set)
        
        # 配置文本标签样式
        self.app.status_text.tag_configure("success", foreground="#2e7d32")
        self.app.status_text.tag_configure("error", foreground="#c62828")
        self.app.status_text.tag_configure("info", foreground="#1565c0")
        self.app.status_text.tag_configure("warning", foreground="#f57c00")
        
        # 进度条
        progress_frame = ttk.Frame(self.right_panel)
        progress_frame.pack(fill=tk.X, pady=3)
        
        self.app.progress = ttk.Progressbar(
            progress_frame,
            mode="indeterminate"
        )
        self.app.progress.pack(fill=tk.X)
        self.app.progress.pack_forget()
    
    def _clear_output(self):
        """清空输出区域"""
        if hasattr(self.app, 'status_text'):
            self.app.status_text.delete(1.0, tk.END)
    
    def _on_ip_selected(self, event):
        """IP 选择处理"""
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
    设置 GUI 入口函数
    
    Args:
        app: 应用实例
    """
    layout = LayoutOptimized(app)
    layout.setup_gui()
