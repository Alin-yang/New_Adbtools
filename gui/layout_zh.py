import tkinter as tk
from tkinter import ttk


def setup_gui(app):
    """构建GUI界面"""
    # IP Address
    ttk.Label(app.root, text="IP 地址:").grid(row=0, column=0, padx=5, pady=5)
    app.ip_entry = ttk.Entry(app.root)
    app.ip_entry.grid(row=0, column=1, padx=5, pady=5)

    # Package Name
    ttk.Label(app.root, text="应用包名:").grid(row=1, column=0, padx=5, pady=5)
    app.pkg_entry = ttk.Entry(app.root)
    app.pkg_entry.grid(row=1, column=1, padx=5, pady=5)

    # APK File
    ttk.Label(app.root, text="APK 文件:").grid(row=2, column=0, padx=5, pady=5)
    app.apk_entry = ttk.Entry(app.root)
    app.apk_entry.grid(row=2, column=1, padx=5, pady=5)
    app.browse_btn = ttk.Button(app.root, text="选择安装包", command=app.browse_apk)
    app.browse_btn.grid(row=2, column=2, sticky=tk.EW, padx=5, pady=5)

    # 日志存储路径框
    ttk.Label(app.root, text="日志存储路径:").grid(row=3, column=0, padx=5, pady=5)
    app.log_path_entry = ttk.Entry(app.root)
    app.log_path_entry.grid(row=3, column=1, padx=5, pady=5)
    app.log_path_entry.insert(0, "D:\\")
    app.log_path_btn = ttk.Button(app.root, text="选择日志存储路径", command=app.choose_log_path)
    app.log_path_btn.grid(row=3, column=2, padx=5, pady=5, sticky=tk.EW)

    # Status Display
    ttk.Label(app.root, text="输出窗口:").grid(row=9, column=0, sticky=tk.W, padx=5, pady=5)
    app.status_text = tk.Text(app.root, height=30, width=70)
    app.status_text.grid(row=10, column=0, columnspan=3, padx=10, pady=10)
    app.status_text.tag_configure("success", foreground="green")
    app.status_text.tag_configure("error", foreground="red")

    # 添加进度条组件（确保挂载到app实例）
    app.progress = ttk.Progressbar(app.root, mode="indeterminate", length=280)
    app.progress.grid(row=10, column=0, columnspan=3, sticky=tk.EW, padx=10, pady=5)
    app.progress.grid_remove()  # 默认隐藏

    # 功能按钮
    buttons = [
        ("连接 ADB", 4, 0, app.connect_adb),
        ("断开所有ADB连接", 4, 1, app.disconnect_adb),
        ("帮助说明", 4, 2, app.show_help),
        ("强制安装", 5, 0, app.force_install),
        ("卸载应用", 5, 1, app.uninstall),
        ("获取已安装包名列表", 5, 2, app.package_list),
        ("清除应用缓存", 6, 0, app.clear_cache),
        ("获取Root权限", 6, 1, app.root_device),
        ("导出ANR文件", 6, 2, app.pull_anr_file),
        ("重新挂载分区", 7, 0, app.remount),
        ("获取应用版本", 7, 1, app.get_version),
        ("重启设备", 7, 2, app.reboot),
        ("获取Android版本", 8, 0, app.get_android_version),
        ("清除日志缓存", 9, 1, app.log_clear),
        ("获取当前打开应用包名", 9, 2, app.get_package_name),
        ("截屏", 0, 2, app.screencap),
        ("获取设备串号", 1, 2, app.get_serial_number),
        ("启动日志捕获", 8, 1, app.start_logcat),
        ("停止日志捕获", 8, 2, app.stop_logcat),
    ]

    for text, row, col, cmd in buttons:
        ttk.Button(app.root, text=text, command=cmd).grid(
            row=row, column=col, sticky=tk.EW, padx=5, pady=5
        )