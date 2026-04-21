"""
精简版布局 - 简洁高效
保留核心功能，移除冗余元素
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Callable, List, Tuple
from config import Config, get_text


class LayoutClean:
    """精简版布局类"""
    
    def __init__(self, app):
        """初始化精简布局"""
        self.app = app
        self.main_frame = None
        self.left_panel = None
        self.center_panel = None
        self.right_panel = None
        self.bottom_bar = None
        
        # 智能快捷功能映射（测试工程师优化版）
        self.smart_quick_actions = {
            "device": [
                ("🔌 连接", "connect_adb"),
                ("📱 查看设备", "show_device_info"),
                ("🔄 重启ADB", "restart_adb_server"),
                ("❌ 断开", "disconnect_adb"),
                ("🔁 重启设备", "reboot"),
            ],
            "app": [
                ("📲 安装APK", "force_install"),
                ("🗑️ 卸载", "uninstall"),
                ("▶️ 启动", "start_app"),
                ("📋 列表", "package_list"),
                ("🧹 清缓存", "clear_cache"),
            ],
            "log_screen": [
                ("🎥 录屏", "start_recording"),
                ("⏹️ 停止", "stop_recording"),
                ("▶️ 日志", "start_logcat"),
                ("📷 截屏", "screencap"),
                ("📂 文件夹", "open_storage_folder"),
                ("📥 导出ANR", "pull_anr_file"),
            ],
            "advanced": [
                ("🔍 当前包名", "get_package_name"),
                ("📊 资源占用", "get_app_resource_usage"),
                ("📜 原始命令", "show_all_adb_commands"),
            ]
        }
        
        self.tabs = {}
        self.current_tab = None
        
    def setup_gui(self):
        """构建精简布局"""
        self.setup_main_container()
        self.create_three_column_layout()
        self.create_left_tab_navigation()
        
        # 创建各个 Tab
        self.create_device_tab()
        self.create_app_tab()
        self.create_log_screen_tab()
        self.create_advanced_tab()
        
        self.create_output_section()
        self.create_bottom_quick_bar()
        self.setup_keyboard_shortcuts()
        
        # 默认显示设备Tab
        self.app.root.after(100, lambda: self.switch_tab("device"))
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        self.app.root.title(get_text("window_title"))
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        if hasattr(Config, 'MIN_WINDOW_SIZE'):
            self.app.root.minsize(*Config.MIN_WINDOW_SIZE)
    
    def create_three_column_layout(self) -> None:
        """创建三栏布局：左侧导航 + 中间功能 + 右侧输出"""
        # 左侧面板（固定宽度）
        self.left_panel = ttk.Frame(self.main_frame, width=120)
        self.left_panel.grid(row=0, column=0, sticky=tk.NSEW)
        self.left_panel.grid_propagate(False)
        
        # 分隔线
        sep1 = tk.Frame(self.main_frame, bg='#e0e0e0', width=1)
        sep1.grid(row=0, column=1, sticky=tk.NS)
        
        # 中间面板
        center_container = ttk.Frame(self.main_frame)
        center_container.grid(row=0, column=2, sticky=tk.NSEW, padx=(8, 5))
        center_container.grid_rowconfigure(0, weight=1)
        center_container.grid_columnconfigure(0, weight=1)
        
        self.center_panel = ttk.Frame(center_container)
        self.center_panel.grid(row=0, column=0, sticky=tk.NSEW)
        
        # 分隔线
        sep2 = tk.Frame(self.main_frame, bg='#e0e0e0', width=1)
        sep2.grid(row=0, column=3, sticky=tk.NS)
        
        # 右侧面板
        self.right_panel = ttk.Frame(self.main_frame)
        self.right_panel.grid(row=0, column=4, sticky=tk.NSEW, padx=(5, 0))
        
        # 底部快捷栏
        self.bottom_bar = ttk.Frame(self.main_frame, height=60)
        self.bottom_bar.grid(row=1, column=0, columnspan=5, sticky=tk.EW, pady=(5, 0))
        self.bottom_bar.grid_propagate(False)
        
        # 配置权重
        self.main_frame.grid_columnconfigure(0, weight=0)
        self.main_frame.grid_columnconfigure(1, weight=0)
        self.main_frame.grid_columnconfigure(2, weight=0)
        self.main_frame.grid_columnconfigure(3, weight=0)
        self.main_frame.grid_columnconfigure(4, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=0)
    
    def create_left_tab_navigation(self) -> None:
        """创建左侧 Tab 导航（简洁版）"""
        tab_frame = ttk.Frame(self.left_panel)
        tab_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        style = ttk.Style()
        style.configure('CleanTab.TButton',
                       font=('Microsoft YaHei UI', 10),
                       padding=(10, 12),
                       anchor='w',
                       relief='flat')
        
        style.configure('CleanTabSelected.TButton',
                       font=('Microsoft YaHei UI', 10, 'bold'),
                       padding=(10, 12),
                       anchor='w',
                       background='#e3f2fd',
                       foreground='#1976D2',
                       relief='solid',
                       borderwidth=2)
        
        style.map('CleanTab.TButton',
                 background=[('active', '#e0e0e0')])
        
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
                width=12,
                takefocus=False,
                style='CleanTab.TButton'
            )
            btn.grid(row=i, column=0, sticky=tk.EW, padx=2, pady=3)
            tab_frame.grid_rowconfigure(i, weight=1)
            self.tab_buttons[tab_name] = btn
        
        tab_frame.grid_columnconfigure(0, weight=1)
    
    def switch_tab(self, tab_name: str) -> None:
        """切换 Tab"""
        for name, frame in self.tabs.items():
            frame.grid_forget()
        
        if tab_name in self.tabs:
            self.tabs[tab_name].grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)
        
        self._update_tab_selection(tab_name)
        self.current_tab = tab_name
        
        # 更新底部快捷栏
        self._update_quick_bar()
    
    def _update_tab_selection(self, selected_tab: str) -> None:
        """更新 Tab 选中状态"""
        if not hasattr(self, 'tab_buttons'):
            return
        
        if hasattr(self, 'current_selected_tab') and self.current_selected_tab in self.tab_buttons:
            self.tab_buttons[self.current_selected_tab].configure(
                style='CleanTab.TButton'
            )
        
        if selected_tab in self.tab_buttons:
            self.tab_buttons[selected_tab].configure(
                style='CleanTabSelected.TButton'
            )
            self.current_selected_tab = selected_tab
    
    def create_device_tab(self) -> None:
        """创建设备管理 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['device'] = tab
        
        # IP 输入区域
        ip_frame = ttk.LabelFrame(tab, text="设备连接", padding=(8, 6))
        ip_frame.grid(row=0, column=0, sticky=tk.EW, padx=5, pady=4)
        tab.grid_columnconfigure(0, weight=1)
        
        input_frame = ttk.Frame(ip_frame)
        input_frame.pack(fill=tk.X)
        
        ttk.Label(input_frame, text="IP:", width=4).pack(side=tk.LEFT)
        self.app.ip_combobox = ttk.Combobox(input_frame, width=18)
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox.insert(0, "192.168.")
        
        self.app.connection_status_label = ttk.Label(
            input_frame,
            text="未连接",
            foreground="gray",
            font=('Microsoft YaHei UI', 9, 'bold'),
            width=10
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(5, 0))
        
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)
        
        # 功能卡片
        self._create_function_card(tab, "ADB 服务", [
            ("🔌 连接 ADB", "connect_adb"),
            ("❌ 断开所有", "disconnect_adb"),
            ("🔄 重启服务", "restart_adb_server"),
        ], row=1)
        
        self._create_function_card(tab, "设备信息", [
            ("📱 查看设备", "show_device_info"),
            ("📋 详细信息", "get_device_info_fast"),
            ("📱 获取串号", "get_serial_number"),
        ], row=2)
        
        self._create_function_card(tab, "设备控制", [
            ("🔁 重启设备", "reboot"),
            ("🔑 Root权限", "root_device"),
            ("📀 重新挂载", "remount"),
        ], row=3)
        
        self._create_function_card(tab, "系统工具", [
            ("🖥️ 打开CMD", "open_cmd_window"),
            ("📝 常用命令", "show_common_adb_commands"),
            ("版本号", "get_android_version"),
        ], row=4)
        
        # 文本输入
        self._create_text_input_section(tab)
    
    def _create_function_card(self, parent, title: str, buttons: List[Tuple[str, str]], row: int) -> None:
        """创建功能卡片"""
        card = ttk.LabelFrame(parent, text=title, padding=(8, 6))
        card.grid(row=row, column=0, sticky=tk.EW, padx=5, pady=4)
        parent.grid_columnconfigure(0, weight=1)
        
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
        input_frame.grid(row=5, column=0, sticky=tk.EW, padx=5, pady=4)
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
        input_frame = ttk.LabelFrame(tab, text="应用信息", padding=(8, 6))
        input_frame.grid(row=0, column=0, sticky=tk.EW, padx=5, pady=4)
        tab.grid_columnconfigure(0, weight=1)
        
        pkg_frame = ttk.Frame(input_frame)
        pkg_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(pkg_frame, text="包名:", width=6).pack(side=tk.LEFT)
        self.app.pkg_combobox = ttk.Combobox(pkg_frame, width=25)
        self.app.pkg_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.pkg_combobox['height'] = 10
        self.app.pkg_entry = self.app.pkg_combobox
        
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
        
        version_frame = ttk.Frame(input_frame)
        version_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(version_frame, text="版本:", width=6).pack(side=tk.LEFT)
        self.app.version_display = ttk.Entry(version_frame, state='readonly', width=25)
        self.app.version_display.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # 功能卡片
        self._create_function_card(tab, "应用操作", [
            ("📲 强制安装", "force_install"),
            ("🗑️ 卸载应用", "uninstall"),
            ("🧹 清除缓存", "clear_cache"),
        ], row=1)
        
        self._create_function_card(tab, "启动与进程", [
            ("▶️ 启动应用", "start_app"),
            ("⏹️ 终止进程", "kill_app_process"),
            ("📊 资源占用", "get_app_resource_usage"),
        ], row=2)
        
        self._create_function_card(tab, "应用信息", [
            ("🔍 版本号", "get_version"),
            ("📂 安装路径", "get_package_path"),
            ("🔍 当前包名", "get_package_name"),
        ], row=3)
        
        self._create_function_card(tab, "应用列表", [
            ("📋 已安装列表", "package_list"),
        ], row=4)
    
    def create_log_screen_tab(self) -> None:
        """创建日志录屏 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['log_screen'] = tab
        
        # 日志路径
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
        output_header = ttk.Frame(self.right_panel)
        output_header.pack(fill=tk.X, pady=(0, 3))
        
        ttk.Label(output_header, text="📄 输出结果", font=('Microsoft YaHei UI', 10, 'bold')).pack(side=tk.LEFT)
        
        clear_btn = ttk.Button(
            output_header,
            text="清空",
            command=self._clear_output,
            width=6
        )
        clear_btn.pack(side=tk.RIGHT)
        
        self.app.status_text = tk.Text(
            self.right_panel,
            wrap=tk.WORD,
            font=('Consolas', 9),
            bg='#fafafa'
        )
        self.app.status_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        scrollbar = ttk.Scrollbar(self.app.status_text, command=self.app.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.status_text.config(yscrollcommand=scrollbar.set)
        
        self.app.status_text.tag_configure("success", foreground="#2e7d32")
        self.app.status_text.tag_configure("error", foreground="#c62828")
        self.app.status_text.tag_configure("info", foreground="#1565c0")
        self.app.status_text.tag_configure("warning", foreground="#f57c00")
        
        progress_frame = ttk.Frame(self.right_panel)
        progress_frame.pack(fill=tk.X, pady=3)
        
        self.app.progress = ttk.Progressbar(progress_frame, mode="indeterminate")
        self.app.progress.pack(fill=tk.X)
        self.app.progress.pack_forget()
    
    def _clear_output(self):
        """清空输出"""
        if hasattr(self.app, 'status_text'):
            self.app.status_text.delete(1.0, tk.END)
    
    def create_bottom_quick_bar(self) -> None:
        """创建底部快捷栏"""
        quick_frame = ttk.LabelFrame(
            self.bottom_bar,
            text="⚡ 快捷操作",
            padding=(8, 5)
        )
        quick_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        
        self.quick_buttons_frame = ttk.Frame(quick_frame)
        self.quick_buttons_frame.pack(fill=tk.X)
    
    def _update_quick_bar(self):
        """更新快捷栏"""
        if not hasattr(self, 'quick_buttons_frame'):
            return
        
        # 清空现有按钮
        for widget in self.quick_buttons_frame.winfo_children():
            widget.destroy()
        
        # 获取当前Tab的快捷功能
        quick_actions = self.smart_quick_actions.get(self.current_tab, [])
        
        # 创建按钮
        for text, method_name in quick_actions[:7]:
            if hasattr(self.app, method_name):
                btn = ttk.Button(
                    self.quick_buttons_frame,
                    text=text,
                    command=getattr(self.app, method_name),
                    width=11
                )
                btn.pack(side=tk.LEFT, padx=3, pady=3)
    
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
    """设置 GUI 入口函数"""
    layout = LayoutClean(app)
    layout.setup_gui()
