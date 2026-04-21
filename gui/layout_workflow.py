"""
工作流布局 - 任务导向设计
左侧任务阶段 + 中间工作区 + 右侧反馈面板
"""
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Tuple
from config import Config, get_text


class LayoutWorkflow:
    """工作流布局类（任务导向）"""
    
    def __init__(self, app):
        """初始化工作流布局"""
        self.app = app
        
        # 任务阶段定义
        self.workflow_stages = [
            {
                "id": "device_prep",
                "name": "📱 设备准备",
                "description": "连接设备、检查状态",
                "actions": [
                    ("🔌 连接ADB", "connect_adb"),
                    ("❌ 断开连接", "disconnect_adb"),
                    ("🔄 重启ADB", "restart_adb_server"),
                    ("📱 查看设备", "show_device_info"),
                    ("📋 详细信息", "get_device_info_fast"),
                    ("🔁 重启设备", "reboot"),
                    ("🔑 Root权限", "root_device"),
                ]
            },
            {
                "id": "app_test",
                "name": "📦 应用测试",
                "description": "安装、启动、操作应用",
                "actions": [
                    ("📲 安装APK", "force_install"),
                    ("▶️ 启动应用", "start_app"),
                    ("⏹️ 终止进程", "kill_app_process"),
                    ("🗑️ 卸载应用", "uninstall"),
                    ("🧹 清除缓存", "clear_cache"),
                    ("📋 应用列表", "package_list"),
                    ("🔍 当前包名", "get_package_name"),
                ]
            },
            {
                "id": "data_collect",
                "name": "📊 数据收集",
                "description": "日志、截屏、录屏、ANR",
                "actions": [
                    ("▶️ 开始日志", "start_logcat"),
                    ("⏹️ 停止日志", "stop_logcat"),
                    ("🎥 开始录屏", "start_recording"),
                    ("⏹️ 停止录屏", "stop_recording"),
                    ("📷 截屏", "screencap"),
                    ("📥 导出ANR", "pull_anr_file"),
                    ("📂 打开文件夹", "open_storage_folder"),
                ]
            },
            {
                "id": "advanced",
                "name": "⚙️ 高级工具",
                "description": "命令执行、系统工具",
                "actions": [
                    ("📊 资源占用", "get_app_resource_usage"),
                    ("🔍 版本号", "get_version"),
                    ("📂 安装路径", "get_package_path"),
                    ("📝 常用命令", "show_common_adb_commands"),
                    ("📜 原始命令", "show_all_adb_commands"),
                    ("🖥️ 打开CMD", "open_cmd_window"),
                    ("🔧 工厂菜单", "open_factory_menu"),
                ]
            }
        ]
        
        self.current_stage = None
        self.main_frame = None
        self.left_panel = None
        self.center_panel = None
        self.right_panel = None
        
    def setup_gui(self):
        """构建工作流布局"""
        self.setup_main_container()
        self.create_three_panel_layout()
        self.create_task_navigation()
        self.create_search_bar()
        self.create_workspace()
        self.create_feedback_panel()
        self.setup_keyboard_shortcuts()
        
        # 默认显示第一个任务阶段
        self.app.root.after(100, lambda: self.switch_stage("device_prep"))
    
    def setup_main_container(self) -> None:
        """创建主容器"""
        self.main_frame = ttk.Frame(self.app.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.app.root.title(get_text("window_title") + " - 工作流版")
        self.app.root.geometry(Config.WINDOW_GEOMETRY)
        if hasattr(Config, 'MIN_WINDOW_SIZE'):
            self.app.root.minsize(*Config.MIN_WINDOW_SIZE)
    
    def create_three_panel_layout(self) -> None:
        """创建三面板布局"""
        # 左侧：任务导航（固定宽度 150px）
        self.left_panel = ttk.Frame(self.main_frame, width=150)
        self.left_panel.grid(row=0, column=0, sticky=tk.NSEW, rowspan=2)
        self.left_panel.grid_propagate(False)
        
        # 分隔线
        sep1 = tk.Frame(self.main_frame, bg='#e0e0e0', width=1)
        sep1.grid(row=0, column=1, sticky=tk.NS, rowspan=2)
        
        # 中间：工作区（弹性宽度）
        center_frame = ttk.Frame(self.main_frame)
        center_frame.grid(row=0, column=2, sticky=tk.NSEW)
        center_frame.grid_columnconfigure(0, weight=1)
        center_frame.grid_rowconfigure(0, weight=0)  # 搜索栏
        center_frame.grid_rowconfigure(1, weight=1)  # 工作区
        
        # 搜索栏
        self.search_frame = ttk.Frame(center_frame)
        self.search_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 5))
        
        # 工作区
        self.center_panel = ttk.Frame(center_frame)
        self.center_panel.grid(row=1, column=0, sticky=tk.NSEW)
        
        # 分隔线
        sep2 = tk.Frame(self.main_frame, bg='#e0e0e0', width=1)
        sep2.grid(row=0, column=3, sticky=tk.NS, rowspan=2)
        
        # 右侧：反馈面板（固定宽度 300px）
        self.right_panel = ttk.Frame(self.main_frame, width=300)
        self.right_panel.grid(row=0, column=4, sticky=tk.NSEW, rowspan=2)
        self.right_panel.grid_propagate(False)
        
        # 配置权重
        self.main_frame.grid_columnconfigure(0, weight=0)
        self.main_frame.grid_columnconfigure(1, weight=0)
        self.main_frame.grid_columnconfigure(2, weight=1)
        self.main_frame.grid_columnconfigure(3, weight=0)
        self.main_frame.grid_columnconfigure(4, weight=0)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=0)
    
    def create_task_navigation(self) -> None:
        """创建左侧任务导航"""
        nav_frame = ttk.LabelFrame(self.left_panel, text="测试任务", padding=(8, 8))
        nav_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        style = ttk.Style()
        style.configure('WorkflowNav.TButton',
                       font=('Microsoft YaHei UI', 10),
                       padding=(10, 15),
                       anchor='w',
                       relief='flat')
        
        style.configure('WorkflowNavSelected.TButton',
                       font=('Microsoft YaHei UI', 10, 'bold'),
                       padding=(10, 15),
                       anchor='w',
                       background='#e3f2fd',
                       foreground='#1976D2',
                       relief='solid',
                       borderwidth=2)
        
        style.map('WorkflowNav.TButton',
                 background=[('active', '#f0f0f0')])
        
        self.stage_buttons = {}
        
        for i, stage in enumerate(self.workflow_stages):
            btn = ttk.Button(
                nav_frame,
                text=stage["name"],
                command=lambda s=stage["id"]: self.switch_stage(s),
                width=16,
                takefocus=False,
                style='WorkflowNav.TButton'
            )
            btn.grid(row=i, column=0, sticky=tk.EW, pady=3)
            nav_frame.grid_rowconfigure(i, weight=1)
            self.stage_buttons[stage["id"]] = btn
            
            # 添加描述标签
            desc_label = ttk.Label(
                nav_frame,
                text=stage["description"],
                font=('Microsoft YaHei UI', 8),
                foreground='#666666'
            )
            desc_label.grid(row=i, column=0, sticky=tk.NW, padx=(35, 0), pady=(28, 0))
        
        nav_frame.grid_columnconfigure(0, weight=1)
    
    def create_search_bar(self) -> None:
        """创建顶部搜索/命令栏"""
        search_container = ttk.Frame(self.search_frame)
        search_container.pack(fill=tk.X)
        
        # 搜索图标
        ttk.Label(search_container, text="🔍", font=('Microsoft YaHei UI', 11)).pack(side=tk.LEFT, padx=(0, 5))
        
        # 搜索输入框
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(
            search_container,
            textvariable=self.search_var,
            font=('Microsoft YaHei UI', 10)
        )
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.bind('<KeyRelease>', self._on_search)
        search_entry.bind('<Return>', self._execute_search_command)
        
        # 提示信息
        hint_label = ttk.Label(
            search_container,
            text="输入关键词查找功能或执行ADB命令",
            font=('Microsoft YaHei UI', 8),
            foreground='#999999'
        )
        hint_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # 搜索结果下拉框（隐藏，搜索时显示）
        self.search_results = tk.Listbox(
            self.search_frame,
            font=('Microsoft YaHei UI', 9),
            height=8,
            selectmode=tk.SINGLE
        )
        self.search_results.bind('<<ListboxSelect>>', self._on_search_result_selected)
        self.search_results.bind('<Return>', self._execute_search_command)
        # 默认隐藏
    
    def create_workspace(self) -> None:
        """创建工作区（动态显示当前任务的功能）"""
        # IP 和设备信息区域（始终显示）
        device_frame = ttk.LabelFrame(self.center_panel, text="设备连接", padding=(10, 8))
        device_frame.grid(row=0, column=0, sticky=tk.EW, padx=5, pady=5)
        self.center_panel.grid_columnconfigure(0, weight=1)
        
        ip_frame = ttk.Frame(device_frame)
        ip_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(ip_frame, text="IP地址:", width=8).pack(side=tk.LEFT)
        self.app.ip_combobox = ttk.Combobox(ip_frame, width=20)
        self.app.ip_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.ip_combobox['height'] = 8
        self.app.ip_combobox.insert(0, "192.168.")
        
        self.app.connection_status_label = ttk.Label(
            ip_frame,
            text="未连接",
            foreground="gray",
            font=('Microsoft YaHei UI', 9, 'bold'),
            width=10
        )
        self.app.connection_status_label.pack(side=tk.LEFT, padx=(5, 0))
        
        self.app.ip_combobox.bind('<<ComboboxSelected>>', self._on_ip_selected)
        
        # 快捷操作按钮区域（根据任务阶段动态更新）
        self.actions_frame = ttk.LabelFrame(self.center_panel, text="快捷操作", padding=(10, 8))
        self.actions_frame.grid(row=1, column=0, sticky=tk.NSEW, padx=5, pady=5)
        self.center_panel.grid_rowconfigure(1, weight=1)
        
        # 包名和APK输入区域（始终创建，但默认隐藏）
        self.app_input_frame = ttk.LabelFrame(self.center_panel, text="应用信息", padding=(10, 8))
        self._create_app_input_fields()
        # 默认隐藏，切换到应用测试阶段时显示
        
        # 日志路径输入区域（始终创建，但默认隐藏）
        self.log_input_frame = ttk.LabelFrame(self.center_panel, text="日志设置", padding=(10, 8))
        self._create_log_input_fields()
        # 默认隐藏，切换到数据收集阶段时显示
    
    def create_feedback_panel(self) -> None:
        """创建右侧反馈面板"""
        # 上半部分：状态监控
        status_frame = ttk.LabelFrame(self.right_panel, text="实时状态", padding=(8, 8))
        status_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # ADB 状态
        adb_status_frame = ttk.Frame(status_frame)
        adb_status_frame.pack(fill=tk.X, pady=2)
        ttk.Label(adb_status_frame, text="ADB:", width=6).pack(side=tk.LEFT)
        self.adb_status_indicator = ttk.Label(
            adb_status_frame,
            text="● 未连接",
            foreground="#c62828",
            font=('Microsoft YaHei UI', 9)
        )
        self.adb_status_indicator.pack(side=tk.LEFT)
        
        # 日志状态
        log_status_frame = ttk.Frame(status_frame)
        log_status_frame.pack(fill=tk.X, pady=2)
        ttk.Label(log_status_frame, text="日志:", width=6).pack(side=tk.LEFT)
        self.log_status_indicator = ttk.Label(
            log_status_frame,
            text="● 停止",
            foreground="#757575",
            font=('Microsoft YaHei UI', 9)
        )
        self.log_status_indicator.pack(side=tk.LEFT)
        
        # 录屏状态
        record_status_frame = ttk.Frame(status_frame)
        record_status_frame.pack(fill=tk.X, pady=2)
        ttk.Label(record_status_frame, text="录屏:", width=6).pack(side=tk.LEFT)
        self.record_status_indicator = ttk.Label(
            record_status_frame,
            text="● 停止",
            foreground="#757575",
            font=('Microsoft YaHei UI', 9)
        )
        self.record_status_indicator.pack(side=tk.LEFT)
        
        # 下半部分：输出日志
        output_frame = ttk.LabelFrame(self.right_panel, text="输出日志", padding=(8, 8))
        output_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 清空按钮
        clear_btn = ttk.Button(
            output_frame,
            text="清空",
            command=self._clear_output,
            width=8
        )
        clear_btn.pack(anchor=tk.E, pady=(0, 5))
        
        # 文本框
        self.app.status_text = tk.Text(
            output_frame,
            wrap=tk.WORD,
            font=('Consolas', 9),
            bg='#fafafa'
        )
        self.app.status_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.app.status_text, command=self.app.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.status_text.config(yscrollcommand=scrollbar.set)
        
        self.app.status_text.tag_configure("success", foreground="#2e7d32")
        self.app.status_text.tag_configure("error", foreground="#c62828")
        self.app.status_text.tag_configure("info", foreground="#1565c0")
        self.app.status_text.tag_configure("warning", foreground="#f57c00")
        
        # 进度条
        self.app.progress = ttk.Progressbar(self.right_panel, mode="indeterminate")
        self.app.progress.pack(fill=tk.X, padx=5, pady=5)
        self.app.progress.pack_forget()
    
    def switch_stage(self, stage_id: str) -> None:
        """切换任务阶段"""
        # 更新导航选中状态
        if hasattr(self, 'current_stage') and self.current_stage in self.stage_buttons:
            self.stage_buttons[self.current_stage].configure(style='WorkflowNav.TButton')
        
        if stage_id in self.stage_buttons:
            self.stage_buttons[stage_id].configure(style='WorkflowNavSelected.TButton')
            self.current_stage = stage_id
        
        # 获取当前阶段配置
        stage_config = next((s for s in self.workflow_stages if s["id"] == stage_id), None)
        if not stage_config:
            return
        
        # 更新工作区标题
        self.actions_frame.config(text=f"快捷操作 - {stage_config['name']}")
        
        # 清空现有按钮
        for widget in self.actions_frame.winfo_children():
            widget.destroy()
        
        # 创建新的操作按钮（网格布局）
        actions = stage_config["actions"]
        cols = 2  # 每行2个按钮
        for idx, (text, method_name) in enumerate(actions):
            row = idx // cols
            col = idx % cols
            
            if hasattr(self.app, method_name):
                btn = ttk.Button(
                    self.actions_frame,
                    text=text,
                    command=getattr(self.app, method_name),
                    width=16
                )
                btn.grid(row=row, column=col, sticky=tk.EW, padx=5, pady=5)
                self.actions_frame.grid_columnconfigure(col, weight=1)
        
        # 显示/隐藏特定输入区域
        self._toggle_input_frames(stage_id)
        
        # 更新状态指示器
        self._update_status_indicators()
    
    def _toggle_input_frames(self, stage_id: str):
        """根据阶段显示/隐藏输入区域"""
        # 隐藏所有特殊输入框
        if hasattr(self, 'app_input_frame'):
            self.app_input_frame.grid_forget()
        if hasattr(self, 'log_input_frame'):
            self.log_input_frame.grid_forget()
        
        # 应用测试阶段：显示包名和APK输入
        if stage_id == "app_test":
            self.app_input_frame.grid(row=2, column=0, sticky=tk.EW, padx=5, pady=5)
        
        # 数据收集阶段：显示日志路径输入
        elif stage_id == "data_collect":
            self.log_input_frame.grid(row=2, column=0, sticky=tk.EW, padx=5, pady=5)
    
    def _create_app_input_fields(self):
        """创建应用输入字段"""
        for widget in self.app_input_frame.winfo_children():
            widget.destroy()
        
        # 包名
        pkg_frame = ttk.Frame(self.app_input_frame)
        pkg_frame.pack(fill=tk.X, pady=2)
        ttk.Label(pkg_frame, text="包名:", width=6).pack(side=tk.LEFT)
        self.app.pkg_combobox = ttk.Combobox(pkg_frame, width=25)
        self.app.pkg_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.pkg_combobox['height'] = 10
        self.app.pkg_entry = self.app.pkg_combobox
        
        # APK
        apk_frame = ttk.Frame(self.app_input_frame)
        apk_frame.pack(fill=tk.X, pady=2)
        ttk.Label(apk_frame, text="APK:", width=6).pack(side=tk.LEFT)
        self.app.apk_entry = ttk.Entry(apk_frame)
        self.app.apk_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        browse_btn = ttk.Button(apk_frame, text="浏览", command=self.app.browse_apk, width=8)
        browse_btn.pack(side=tk.LEFT)
        
        # 版本
        version_frame = ttk.Frame(self.app_input_frame)
        version_frame.pack(fill=tk.X, pady=2)
        ttk.Label(version_frame, text="版本:", width=6).pack(side=tk.LEFT)
        self.app.version_display = ttk.Entry(version_frame, state='readonly', width=25)
        self.app.version_display.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
    
    def _create_log_input_fields(self):
        """创建日志输入字段"""
        for widget in self.log_input_frame.winfo_children():
            widget.destroy()
        
        path_frame = ttk.Frame(self.log_input_frame)
        path_frame.pack(fill=tk.X)
        ttk.Label(path_frame, text="路径:", width=6).pack(side=tk.LEFT)
        self.app.log_path_entry = ttk.Entry(path_frame)
        self.app.log_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.app.log_path_entry.insert(0, Config.DEFAULT_LOG_PATH)
        browse_btn = ttk.Button(path_frame, text="浏览", command=self.app.choose_log_path, width=8)
        browse_btn.pack(side=tk.LEFT)
    
    def _on_search(self, event=None):
        """搜索功能"""
        keyword = self.search_var.get().strip().lower()
        
        if not keyword:
            self.search_results.pack_forget()
            return
        
        # 在所有阶段的操作中搜索
        results = []
        for stage in self.workflow_stages:
            for text, method_name in stage["actions"]:
                if keyword in text.lower() or keyword in method_name.lower():
                    results.append((text, method_name, stage["name"]))
        
        # 显示结果
        self.search_results.delete(0, tk.END)
        for text, method, stage_name in results:
            self.search_results.insert(tk.END, f"{text}  [{stage_name}]")
            # 存储元数据
            self.search_results.itemconfig(tk.END, {'data': (text, method)})
        
        if results:
            self.search_results.pack(fill=tk.X, pady=5)
            self.search_results.selection_set(0)
        else:
            self.search_results.pack_forget()
    
    def _on_search_result_selected(self, event):
        """选择搜索结果"""
        pass  # 按回车执行
    
    def _execute_search_command(self, event=None):
        """执行搜索选中的命令"""
        selection = self.search_results.curselection()
        if not selection:
            return
        
        index = selection[0]
        item_data = self.search_results.itemconfig(index, 'data')
        
        if item_data and len(item_data) >= 5 and item_data[4]:
            try:
                text, method_name = eval(item_data[4][0])
                
                # 找到对应的阶段并切换
                for stage in self.workflow_stages:
                    if any(m == method_name for _, m in stage["actions"]):
                        self.switch_stage(stage["id"])
                        break
                
                # 执行命令
                if hasattr(self.app, method_name):
                    getattr(self.app, method_name)()
                    
            except Exception as e:
                print(f"执行命令失败: {e}")
        
        # 隐藏搜索结果
        self.search_results.pack_forget()
        self.search_var.set("")
    
    def _update_status_indicators(self):
        """更新状态指示器"""
        # ADB 状态
        current_ip = self.app.get_ip_address() if hasattr(self.app, 'get_ip_address') else ''
        if current_ip and current_ip != "192.168.":
            self.adb_status_indicator.config(text="● 已连接", foreground="#2e7d32")
        else:
            self.adb_status_indicator.config(text="● 未连接", foreground="#c62828")
        
        # 日志状态
        if hasattr(self.app, 'logging_active') and self.app.logging_active:
            self.log_status_indicator.config(text="● 运行中", foreground="#2e7d32")
        else:
            self.log_status_indicator.config(text="● 停止", foreground="#757575")
        
        # 录屏状态
        if hasattr(self.app, 'recording_active') and self.app.recording_active:
            self.record_status_indicator.config(text="● 运行中", foreground="#2e7d32")
        else:
            self.record_status_indicator.config(text="● 停止", foreground="#757575")
    
    def _on_ip_selected(self, event):
        """IP 选择处理"""
        if hasattr(self.app, 'ip_combobox'):
            selected_value = self.app.ip_combobox.get()
            self.app.ip_combobox.set(selected_value)
        self.app.on_ip_changed(event)
        self._update_status_indicators()
    
    def _clear_output(self):
        """清空输出"""
        if hasattr(self.app, 'status_text'):
            self.app.status_text.delete(1.0, tk.END)
    
    def setup_keyboard_shortcuts(self) -> None:
        """设置键盘快捷键"""
        shortcuts = {
            '<Control-q>': lambda e: self.app.root.quit(),
            '<Control-f>': lambda e: self._focus_search(),
            '<Control-c>': lambda e: self.app.connect_adb() if hasattr(self.app, 'connect_adb') else None,
            '<Control-d>': lambda e: self.app.disconnect_adb() if hasattr(self.app, 'disconnect_adb') else None,
            '<Control-i>': lambda e: self.app.force_install() if hasattr(self.app, 'force_install') else None,
            '<Control-u>': lambda e: self.app.uninstall() if hasattr(self.app, 'uninstall') else None,
            '<F5>': lambda e: self.app.reboot() if hasattr(self.app, 'reboot') else None,
            '<F12>': lambda e: self.app.screencap() if hasattr(self.app, 'screencap') else None,
        }
        
        for shortcut, handler in shortcuts.items():
            self.app.root.bind(shortcut, handler)
    
    def _focus_search(self):
        """聚焦搜索框"""
        if hasattr(self, 'search_var'):
            for widget in self.search_frame.winfo_children():
                if isinstance(widget, ttk.Frame):
                    for child in widget.winfo_children():
                        if isinstance(child, ttk.Entry):
                            child.focus_set()
                            break


def setup_gui(app):
    """设置 GUI 入口函数"""
    layout = LayoutWorkflow(app)
    layout.setup_gui()
