import tkinter as tk
from tkinter import ttk


def setup_gui(app):
    """构建左右分栏GUI界面"""
    # 创建主容器(唯一直接挂载到app.root的组件)
    main_frame = ttk.Frame(app.root)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)  #仅此处使用pack布局

    # 左侧控制面板
    left_panel = ttk.Frame(main_frame)
    left_panel.grid(row=0, column=0, sticky=tk.NSEW, padx=5)
    left_panel.grid_propagate(False)  # 防止子组件大小影响父组件

    # 右侧输出面板
    right_panel = ttk.Frame(main_frame)
    right_panel.grid(row=0, column=1, sticky=tk.NSEW, padx=5)
    right_panel.grid_propagate(False)   # 防止子组件大小影响父组件


    # 配置网格权重
    main_frame.grid_columnconfigure(0, weight=30)
    main_frame.grid_columnconfigure(1, weight=1)  # 右侧区域更宽
    main_frame.grid_rowconfigure(0, weight=1)

    # ========== 所有组件必须挂在main_frame的子容器里 ==========
    # ========== 左侧组件 ==========

    # IP Address
    ttk.Label(left_panel, text="IP 地址:").grid(row=0, column=0, padx=5, pady=2)
    app.ip_entry = ttk.Entry(left_panel)
    app.ip_entry.grid(row=0, column=1, padx=5, pady=2, sticky=tk.EW)

    # Package Name
    ttk.Label(left_panel, text="应用包名:").grid(row=1, column=0, padx=5, pady=5)
    app.pkg_entry = ttk.Entry(left_panel)
    app.pkg_entry.grid(row=1, column=1, padx=5, pady=5)

    # APK File
    ttk.Label(left_panel, text="APK 文件:").grid(row=2, column=0, padx=5, pady=5)
    app.apk_entry = ttk.Entry(left_panel)
    app.apk_entry.grid(row=2, column=1, padx=5, pady=5)
    app.browse_btn = ttk.Button(left_panel, text="选择安装包路径", command=app.browse_apk)
    app.browse_btn.grid(row=2, column=2, sticky=tk.EW, padx=5, pady=5)

    # 日志存储路径框
    ttk.Label(left_panel, text="日志存储路径:").grid(row=3, column=0, padx=5, pady=5)
    app.log_path_entry = ttk.Entry(left_panel)
    app.log_path_entry.grid(row=3, column=1,  padx=5, pady=5)
    app.log_path_entry.insert(0, "D:\\")
    app.log_path_btn = ttk.Button(left_panel, text="选择日志存储路径", command=app.choose_log_path)
    app.log_path_btn.grid(row=3, column=2,  padx=5, pady=5,sticky=tk.EW)

    # 功能按钮
    buttons = [
        ("连接 ADB", 4, 0, app.connect_adb),
        ("断开所有ADB连接", 4, 1, app.disconnect_adb),
        ("查看使用说明", 4, 2, app.show_help),
        ("强制安装apk", 5, 0, app.force_install),
        ("卸载当前包名应用", 5, 1, app.uninstall),
        ("获取已安装应用包名列表", 5, 2, app.package_list),
        ("清除应用缓存", 6, 0, app.clear_cache),
        ("获取Root权限", 6, 1, app.root_device),
        ("导出ANR文件", 6, 2, app.pull_anr_file),
        ("重新挂载分区", 7, 0, app.remount),
        ("获取当前包名版本号", 7, 1, app.get_version),
        ("重启设备", 7, 2, app.reboot),
        ("获取Android版本号", 8, 0, app.get_android_version),
        ("清除日志缓存", 9, 1, app.log_clear),
        ("获取当前打开应用包名", 9, 2, app.get_package_name),
        ("截取当前屏幕", 0, 2, app.screencap),
        ("获取设备串号", 1, 2, app.get_serial_number),
        ("启动日志捕获", 8, 1, app.start_logcat),
        ("停止日志捕获", 8, 2, app.stop_logcat),
        ("终止当前包名所有进程", 9, 0, app.kill_app_process),
    ]

    for text, row, col, cmd in buttons:
        ttk.Button(left_panel, text=text, command=cmd).grid(
            row=row, column=col, sticky=tk.EW, padx=5, pady=5
        )

    # ========== 右侧组件 ==========
    # 输出窗口
    app.status_text = tk.Text(right_panel, wrap=tk.WORD)
    app.status_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    app.status_text.tag_configure("success", foreground="green")
    app.status_text.tag_configure("error", foreground="red")

    # 进度条调整到右侧底部
    app.progress = ttk.Progressbar(right_panel, mode="indeterminate",length=600)
    app.progress.pack( fill=tk.X, pady=5)
    app.progress.pack_forget() # 默认隐藏

