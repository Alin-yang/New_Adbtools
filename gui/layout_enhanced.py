"""
增强版布局 - 极简高效 + 响应式自适应
特性：命令面板、可调节分隔条、智能快捷栏、工作区预设
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, Callable, List, Tuple, Optional
from config import Config, get_text


class LayoutEnhanced:
    """增强版布局类"""
    
    def __init__(self, app):
        """初始化增强布局"""
        self.app = app
        self.main_frame = None
        self.top_toolbar = None
        self.left_panel = None
        self.center_panel = None
        self.right_panel = None
        self.bottom_bar = None
        self.status_bar = None  # 新增：底部状态栏
        
        # 可调节分隔条
        self.separator_left = None
        self.separator_right = None
        
        # 命令面板
        self.command_palette = None
        self.command_search_var = None
        self.command_listbox = None
        
        # 主题管理
        self.current_theme = "light"  # light/dark
        self.themes = {
            "light": {
                "bg": "#ffffff",
                "fg": "#333333",
                "frame_bg": "#f5f5f5",
                "select_bg": "#e3f2fd",
                "select_fg": "#1976D2",
                "border": "#cccccc",
                "button_bg": "#f0f0f0",
                "text_bg": "#fafafa"
            },
            "dark": {
                "bg": "#1e1e1e",
                "fg": "#d4d4d4",
                "frame_bg": "#252526",
                "select_bg": "#264f78",
                "select_fg": "#ffffff",
                "border": "#3c3c3c",
                "button_bg": "#3c3c3c",
                "text_bg": "#1e1e1e"
            }
        }
        
        # 工作区模式
        self.workspace_mode = "dev"  # dev/test/debug
        self.workspace_modes = {
            "dev": "🛠️ 开发模式",
            "test": "🧪 测试模式",
            "debug": "🐛 调试模式"
        }
        
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
        
        # 命令数据映射（用于命令面板）
        self.command_data_map = {}  # {index: (text, method, tab)}
        
        # 设备列表
        self.device_list = []  # 存储已连接设备
        self.device_listbox = None  # 设备列表控件
        
        self.tabs = {}
        self.current_tab = None
        
    def setup_gui(self):
        """构建增强版布局"""
        self.setup_main_container()
        self.create_responsive_layout()
        self.create_top_toolbar()
        self.create_left_tab_navigation()
        
        # 创建各个 Tab
        self.create_device_tab()
        self.create_app_tab()
        self.create_log_screen_tab()
        self.create_advanced_tab()
        
        self.create_output_section()
        self.create_smart_bottom_bar()
        self.create_status_bar()  # 新增：状态栏
        self.create_command_palette()
        self.setup_keyboard_shortcuts()
        
        # 加载设备列表
        self._refresh_device_list()
        
        # 默认显示设备Tab
        self.app.root.after(100, lambda: self.switch_tab("device"))
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        self.app.root.title(get_text("window_title") + " - 增强版")
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        if hasattr(Config, 'MIN_WINDOW_SIZE'):
            self.app.root.minsize(*Config.MIN_WINDOW_SIZE)
    
    def create_responsive_layout(self) -> None:
        """创建响应式布局（带可调节分隔条）"""
        # 顶部工具栏
        self.top_toolbar = ttk.Frame(self.main_frame, height=55)
        self.top_toolbar.grid(row=0, column=0, columnspan=5, sticky=tk.EW, pady=(0, 5))
        self.top_toolbar.grid_propagate(False)
        
        # 左侧面板（可调节宽度）
        self.left_panel = ttk.Frame(self.main_frame, width=130)
        self.left_panel.grid(row=1, column=0, sticky=tk.NSEW)
        self.left_panel.grid_propagate(False)
        
        # 左侧分隔条（可拖动）
        self.separator_left = tk.Frame(
            self.main_frame, 
            bg='#cccccc', 
            width=3,
            cursor='sb_h_double_arrow'
        )
        self.separator_left.grid(row=1, column=1, sticky=tk.NS)
        self.separator_left.bind('<B1-Motion>', lambda e: self._resize_left_panel(e))
        self.separator_left.bind('<Double-Button-1>', lambda e: self._reset_left_panel())
        
        # 中间面板容器（用于放置Tab内容）
        center_container = ttk.Frame(self.main_frame)
        center_container.grid(row=1, column=2, sticky=tk.NSEW, padx=(5, 0))
        center_container.grid_rowconfigure(0, weight=1)
        center_container.grid_columnconfigure(0, weight=1)
        
        # 中间面板（实际功能区域）
        self.center_panel = ttk.Frame(center_container)
        self.center_panel.grid(row=0, column=0, sticky=tk.NSEW)
        
        # 右侧分隔条（可拖动）
        self.separator_right = tk.Frame(
            self.main_frame,
            bg='#cccccc',
            width=3,
            cursor='sb_h_double_arrow'
        )
        self.separator_right.grid(row=1, column=3, sticky=tk.NS)
        self.separator_right.bind('<B1-Motion>', lambda e: self._resize_right_panel(e))
        self.separator_right.bind('<Double-Button-1>', lambda e: self._reset_right_panel())
        
        # 右侧面板
        self.right_panel = ttk.Frame(self.main_frame)
        self.right_panel.grid(row=1, column=4, sticky=tk.NSEW, padx=(5, 0))
        
        # 底部快捷栏
        self.bottom_bar = ttk.Frame(self.main_frame, height=65)
        self.bottom_bar.grid(row=2, column=0, columnspan=5, sticky=tk.EW, pady=(5, 0))
        self.bottom_bar.grid_propagate(False)
        
        # 配置权重
        self.main_frame.grid_columnconfigure(0, weight=0)
        self.main_frame.grid_columnconfigure(1, weight=0)
        self.main_frame.grid_columnconfigure(2, weight=0)
        self.main_frame.grid_columnconfigure(3, weight=0)
        self.main_frame.grid_columnconfigure(4, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=0)
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=0)
    
    def _resize_left_panel(self, event):
        """调整左侧面板宽度"""
        new_width = event.x
        if 100 <= new_width <= 250:
            self.left_panel.config(width=new_width)
    
    def _reset_left_panel(self):
        """重置左侧面板宽度"""
        self.left_panel.config(width=130)
    
    def _resize_right_panel(self, event):
        """调整右侧面板宽度（通过调整中间面板）"""
        # 简化实现：固定右侧宽度，让用户通过窗口大小调整
        pass
    
    def _reset_right_panel(self):
        """重置右侧面板"""
        pass
    
    def create_top_toolbar(self) -> None:
        """创建顶部工具栏（测试工程师专用）"""
        toolbar = ttk.Frame(self.top_toolbar)
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # === 左侧：设备信息 ===
        device_frame = ttk.LabelFrame(toolbar, text="📱 设备", padding=(8, 4))
        device_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        ip_frame = ttk.Frame(device_frame)
        ip_frame.pack(fill=tk.X)
        
        self.app.ip_combobox = ttk.Combobox(ip_frame, width=16)
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox.insert(0, "192.168.")
        
        self.app.connection_status_label = ttk.Label(
            ip_frame,
            text="未连接",
            foreground="gray",
            font=('Microsoft YaHei UI', 9, 'bold'),
            width=10
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(8, 0))
        
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)
        
        # === 右侧：快速操作 ===
        action_frame = ttk.Frame(toolbar)
        action_frame.pack(side=tk.RIGHT)
        
        # 命令面板按钮
        cmd_btn = ttk.Button(
            action_frame,
            text="⌨️ Ctrl+P",
            command=self._toggle_command_palette,
            width=10
        )
        cmd_btn.pack(side=tk.LEFT, padx=2)
        
        # 刷新设备
        refresh_btn = ttk.Button(
            action_frame,
            text="🔄 刷新",
            command=self.app.show_device_info,
            width=8
        )
        refresh_btn.pack(side=tk.LEFT, padx=2)
    

    
    def create_left_tab_navigation(self) -> None:
        """创建左侧设备列表 + Tab 导航（Escrcpy 风格）"""
        # 主容器
        left_container = ttk.Frame(self.left_panel)
        left_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # === 第一部分：设备列表 ===
        device_frame = ttk.LabelFrame(left_container, text="📱 已连接设备", padding=(5, 5))
        device_frame.pack(fill=tk.X, pady=(0, 5))
        
        # 设备列表框
        list_frame = ttk.Frame(device_frame)
        list_frame.pack(fill=tk.X, pady=2)
        
        self.device_listbox = tk.Listbox(
            list_frame,
            font=('Microsoft YaHei UI', 9),
            height=4,
            selectmode=tk.SINGLE,
            activestyle='none'
        )
        self.device_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.device_listbox.bind('<<ListboxSelect>>', self._on_device_selected)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame, command=self.device_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.device_listbox.config(yscrollcommand=scrollbar.set)
        
        # 设备操作按钮
        btn_frame = ttk.Frame(device_frame)
        btn_frame.pack(fill=tk.X, pady=2)
        
        refresh_btn = ttk.Button(
            btn_frame,
            text="🔄 刷新",
            command=self._refresh_device_list,
            width=8
        )
        refresh_btn.pack(side=tk.LEFT, padx=2)
        
        # === 第二部分：功能模块 Tab ===
        tab_frame = ttk.LabelFrame(left_container, text="⚙️ 功能模块", padding=(5, 5))
        tab_frame.pack(fill=tk.BOTH, expand=True)
        
        style = ttk.Style()
        theme = self.themes[self.current_theme]
        
        style.configure('EnhancedTab.TButton',
                       font=('Microsoft YaHei UI', 10),
                       padding=(10, 10),
                       anchor='w',
                       relief='flat',
                       background=theme['frame_bg'],
                       foreground=theme['fg'])
        
        style.configure('EnhancedTabSelected.TButton',
                       font=('Microsoft YaHei UI', 10, 'bold'),
                       padding=(10, 10),
                       anchor='w',
                       background=theme['select_bg'],
                       foreground=theme['select_fg'],
                       relief='solid',
                       borderwidth=2)
        
        style.map('EnhancedTab.TButton',
                 background=[('active', theme['border'])])
        
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
                style='EnhancedTab.TButton'
            )
            btn.grid(row=i, column=0, sticky=tk.EW, padx=2, pady=2)
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
        
        # 更新智能快捷栏
        self._update_smart_quick_bar()
    
    def _update_tab_selection(self, selected_tab: str) -> None:
        """更新 Tab 选中状态"""
        if not hasattr(self, 'tab_buttons'):
            return
        
        if hasattr(self, 'current_selected_tab') and self.current_selected_tab in self.tab_buttons:
            self.tab_buttons[self.current_selected_tab].configure(
                style='EnhancedTab.TButton'
            )
        
        if selected_tab in self.tab_buttons:
            self.tab_buttons[selected_tab].configure(
                style='EnhancedTabSelected.TButton'
            )
            self.current_selected_tab = selected_tab
    
    def _refresh_device_list(self):
        """刷新设备列表"""
        try:
            # 获取当前连接的设备
            from utils import get_connected_devices
            devices = get_connected_devices()
            
            # 清空列表框
            self.device_listbox.delete(0, tk.END)
            
            # 添加设备到列表
            for device in devices:
                # 确定设备状态
                current_ip = self.app.get_ip_address() if hasattr(self.app, 'get_ip_address') else ''
                status = "●" if device == current_ip or (current_ip and device.startswith(current_ip + ':')) else "○"
                display_text = f"{status} {device}"
                self.device_listbox.insert(tk.END, display_text)
                
            # 更新设备列表
            self.device_list = devices
            
            # 更新状态栏
            self._update_status_bar()
            
        except Exception as e:
            print(f"刷新设备列表失败: {e}")
            self.device_listbox.delete(0, tk.END)
            self.device_listbox.insert(tk.END, f"❌ 错误: {str(e)}")

    def _on_device_selected(self, event):
        """设备选择事件"""
        selection = self.device_listbox.curselection()
        if selection:
            index = selection[0]
            selected_text = self.device_listbox.get(index)
            # 提取设备标识（去掉状态符号）
            device = selected_text.split(' ', 1)[1] if ' ' in selected_text else selected_text
            
            # 更新IP输入框
            if hasattr(self.app, 'ip_combobox'):
                self.app.ip_combobox.delete(0, tk.END)
                self.app.ip_combobox.insert(0, device)
                
            # 触发IP变更事件
            if hasattr(self.app, 'on_ip_changed'):
                self.app.on_ip_changed()
            
            # 重新加载设备列表以更新状态
            self._refresh_device_list()

    def create_status_bar(self) -> None:
        """创建底部状态栏（Escrcpy 风格）"""
        self.status_bar = ttk.Frame(self.app.root, height=25, relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_bar.pack_propagate(False)
        
        # 状态信息
        self.status_label = ttk.Label(
            self.status_bar,
            text="就绪",
            font=('Microsoft YaHei UI', 8)
        )
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        # ADB 服务状态
        self.adb_status_label = ttk.Label(
            self.status_bar,
            text="ADB: 未连接",
            font=('Microsoft YaHei UI', 8)
        )
        self.adb_status_label.pack(side=tk.LEFT, padx=10)
        
        # 日志状态
        self.log_status_label = ttk.Label(
            self.status_bar,
            text="日志: 停止",
            font=('Microsoft YaHei UI', 8)
        )
        self.log_status_label.pack(side=tk.LEFT, padx=10)
        
        # 录屏状态
        self.record_status_label = ttk.Label(
            self.status_bar,
            text="录屏: 停止",
            font=('Microsoft YaHei UI', 8)
        )
        self.record_status_label.pack(side=tk.LEFT, padx=10)
        
        # 设备数量
        self.device_count_label = ttk.Label(
            self.status_bar,
            text="设备: 0",
            font=('Microsoft YaHei UI', 8)
        )
        self.device_count_label.pack(side=tk.RIGHT, padx=5)
        
        # 更新状态栏
        self._update_status_bar()
        
    def _update_status_bar(self):
        """更新状态栏信息"""
        try:
            # 设备数量
            device_count = len(self.device_list)
            self.device_count_label.config(text=f"设备: {device_count}")
            
            # ADB 服务状态
            # 检查当前连接状态
            current_ip = self.app.get_ip_address() if hasattr(self.app, 'get_ip_address') else ''
            if current_ip and self.device_list and any(d == current_ip or d.startswith(current_ip + ':') for d in self.device_list):
                self.adb_status_label.config(text="ADB: 已连接", foreground="#2e7d32")
            else:
                self.adb_status_label.config(text="ADB: 未连接", foreground="#c62828")
            
            # 日志状态
            if hasattr(self.app, 'logging_active') and self.app.logging_active:
                self.log_status_label.config(text="日志: 运行中", foreground="#2e7d32")
            else:
                self.log_status_label.config(text="日志: 停止", foreground="#757575")
            
            # 录屏状态
            if hasattr(self.app, 'recording_active') and self.app.recording_active:
                self.record_status_label.config(text="录屏: 运行中", foreground="#2e7d32")
            else:
                self.record_status_label.config(text="录屏: 停止", foreground="#757575")
                
        except Exception as e:
            print(f"更新状态栏失败: {e}")
    
    def create_device_tab(self) -> None:
        """创建设备管理 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['device'] = tab
        
        self._create_function_card(tab, "ADB 服务", [
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
        
        self._create_app_input_section(tab)
        
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
    
    def create_log_screen_tab(self) -> None:
        """创建日志录屏 Tab"""
        tab = ttk.Frame(self.center_panel)
        self.tabs['log_screen'] = tab
        
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
    
    def _update_smart_quick_bar(self):
        """更新智能快捷栏（固定显示测试相关功能）"""
        if not hasattr(self, 'quick_buttons_frame'):
            return
        
        # 清空现有按钮
        for widget in self.quick_buttons_frame.winfo_children():
            widget.destroy()
        
        # 获取当前Tab的快捷功能（已按测试需求优化排序）
        quick_actions = self.smart_quick_actions.get(self.current_tab, [])
        
        # 创建按钮
        for text, method_name in quick_actions[:7]:  # 最多显示7个
            if hasattr(self.app, method_name):
                btn = ttk.Button(
                    self.quick_buttons_frame,
                    text=text,
                    command=getattr(self.app, method_name),
                    width=11
                )
                btn.pack(side=tk.LEFT, padx=3, pady=3)
    
    def create_smart_bottom_bar(self) -> None:
        """创建智能快捷栏（测试工程师优化版）"""
        quick_frame = ttk.LabelFrame(
            self.bottom_bar,
            text="⚡ 快捷操作（测试工程师优化）",
            padding=(8, 5)
        )
        quick_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        
        self.quick_buttons_frame = ttk.Frame(quick_frame)
        self.quick_buttons_frame.pack(fill=tk.X)
    
    def create_command_palette(self) -> None:
        """创建命令面板（类似 VS Code 的 Ctrl+P）"""
        # 创建顶层窗口
        self.command_palette = tk.Toplevel(self.app.root)
        self.command_palette.title("命令面板")
        self.command_palette.geometry("500x300")
        self.command_palette.overrideredirect(True)  # 无边框
        self.command_palette.withdraw()  # 默认隐藏
        
        # 居中显示
        self._center_command_palette()
        
        # 搜索框
        search_frame = ttk.Frame(self.command_palette)
        search_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(search_frame, text="🔍", font=('Microsoft YaHei UI', 12)).pack(side=tk.LEFT)
        
        self.command_search_var = tk.StringVar()
        search_entry = ttk.Entry(
            search_frame,
            textvariable=self.command_search_var,
            font=('Microsoft YaHei UI', 11)
        )
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        search_entry.bind('<KeyRelease>', self._filter_commands)
        search_entry.bind('<Return>', self._execute_selected_command)
        search_entry.bind('<Escape>', lambda e: self._hide_command_palette())
        
        # 命令列表
        list_frame = ttk.Frame(self.command_palette)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.command_listbox = tk.Listbox(
            list_frame,
            font=('Microsoft YaHei UI', 10),
            selectmode=tk.SINGLE,
            activestyle='none'
        )
        self.command_listbox.pack(fill=tk.BOTH, expand=True)
        self.command_listbox.bind('<Double-Button-1>', lambda e: self._execute_selected_command())
        
        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame, command=self.command_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.command_listbox.config(yscrollcommand=scrollbar.set)
        
        # 加载所有命令
        self._load_all_commands()
    
    def _center_command_palette(self):
        """居中显示命令面板"""
        self.command_palette.update_idletasks()
        width = self.command_palette.winfo_width()
        height = self.command_palette.winfo_height()
        x = (self.app.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.app.root.winfo_screenheight() // 2) - (height // 2)
        self.command_palette.geometry(f'+{x}+{y}')
    
    def _load_all_commands(self):
        """加载所有可用命令"""
        all_commands = []
        
        # 从各个 Tab 收集命令
        for tab_name, actions in self.smart_quick_actions.items():
            for text, method_name in actions:
                all_commands.append((text, method_name, tab_name))
        
        # 清空映射
        self.command_data_map.clear()
        
        # 添加到列表框
        for idx, (text, method, tab) in enumerate(all_commands):
            display_text = f"{text}  [{tab}]"
            self.command_listbox.insert(tk.END, display_text)
            # 存储元数据到映射字典
            self.command_data_map[idx] = (text, method, tab)
    
    def _filter_commands(self, event=None):
        """过滤命令"""
        search_text = self.command_search_var.get().lower()
        
        # 清空列表和映射
        self.command_listbox.delete(0, tk.END)
        self.command_data_map.clear()
        
        # 重新加载匹配的命令
        idx = 0
        for tab_name, actions in self.smart_quick_actions.items():
            for text, method_name in actions:
                if search_text in text.lower() or search_text in method_name.lower():
                    display_text = f"{text}  [{tab_name}]"
                    self.command_listbox.insert(tk.END, display_text)
                    # 存储元数据到映射字典
                    self.command_data_map[idx] = (text, method_name, tab_name)
                    idx += 1
        
        # 自动选中第一个
        if self.command_listbox.size() > 0:
            self.command_listbox.selection_set(0)
    
    def _execute_selected_command(self, event=None):
        """执行选中的命令"""
        selection = self.command_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        
        # 从映射字典获取命令数据
        if index in self.command_data_map:
            text, method_name, tab_name = self.command_data_map[index]
            
            # 切换到对应 Tab
            self.switch_tab(tab_name)
            
            # 执行命令
            if hasattr(self.app, method_name):
                getattr(self.app, method_name)()
                
                self.update_status(f"执行命令: {text}", True)
        
        # 隐藏命令面板
        self._hide_command_palette()
    
    def _toggle_command_palette(self):
        """显示/隐藏命令面板"""
        if self.command_palette.winfo_viewable():
            self._hide_command_palette()
        else:
            self._show_command_palette()
    
    def _show_command_palette(self):
        """显示命令面板"""
        self._center_command_palette()
        self.command_palette.deiconify()
        self.command_search_var.set("")
        self._filter_commands()
        
        # 聚焦搜索框
        for widget in self.command_palette.winfo_children():
            if isinstance(widget, ttk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Entry):
                        child.focus_set()
                        break
    
    def _hide_command_palette(self):
        """隐藏命令面板"""
        self.command_palette.withdraw()
        # 恢复焦点到主窗口
        self.app.root.focus_set()
    
    def _on_ip_selected(self, event):
        """IP 选择处理"""
        if hasattr(self.app, 'ip_combobox'):
            selected_value = self.app.ip_combobox.get()
            self.app.ip_combobox.set(selected_value)
        self.app.on_ip_changed(event)
    
    def update_status(self, message: str, success: bool = True, msg_type: str = "info"):
        """更新状态（委托给 app）"""
        if hasattr(self.app, 'update_status'):
            self.app.update_status(message, success, msg_type)
    
    def setup_keyboard_shortcuts(self) -> None:
        """设置键盘快捷键"""
        shortcuts = {
            '<Control-q>': lambda e: self.app.root.quit(),
            '<Control-p>': lambda e: self._toggle_command_palette(),
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
    layout = LayoutEnhanced(app)
    layout.setup_gui()
