import tkinter as tk
from tkinter import ttk


def setup_gui(app):
    """构建GUI界面"""
    # IP Address
    ttk.Label(app.root, text="IP Address:").grid(row=0, column=0, padx=5, pady=5)
    app.ip_entry = ttk.Entry(app.root)
    app.ip_entry.grid(row=0, column=1, padx=5, pady=5)

    # Package Name
    ttk.Label(app.root, text="Package Name:").grid(row=1, column=0, padx=5, pady=5)
    app.pkg_entry = ttk.Entry(app.root)
    app.pkg_entry.grid(row=1, column=1, padx=5, pady=5)

    # APK File
    ttk.Label(app.root, text="APK File:").grid(row=2, column=0, padx=5, pady=5)
    app.apk_entry = ttk.Entry(app.root)
    app.apk_entry.grid(row=2, column=1, padx=5, pady=5)
    app.browse_btn = ttk.Button(app.root, text="Browse", command=app.browse_apk)
    app.browse_btn.grid(row=2, column=2, sticky=tk.EW, padx=5, pady=5)

    # 日志存储路径框
    ttk.Label(app.root, text="Log Path:").grid(row=3, column=0, padx=5, pady=5)
    app.log_path_entry = ttk.Entry(app.root)
    app.log_path_entry.grid(row=3, column=1,  padx=5, pady=5)
    app.log_path_entry.insert(0, "D:\\")
    app.log_path_btn = ttk.Button(app.root, text="Browse_Log_Path", command=app.choose_log_path)
    app.log_path_btn.grid(row=3, column=2,  padx=5, pady=5,sticky=tk.EW)


    # Status Display
    ttk.Label(app.root, text="Status:").grid(row=10, column=0, sticky=tk.W, padx=5, pady=5)
    app.status_text = tk.Text(app.root, height=35, width=70)
    app.status_text.grid(row=11, column=0, columnspan=3, padx=10, pady=10)
    app.status_text.tag_configure("success", foreground="green")
    app.status_text.tag_configure("error", foreground="red")

    # 添加进度条组件（确保挂载到app实例）
    app.progress = ttk.Progressbar(app.root, mode="indeterminate", length=280)
    app.progress.grid(row=10, column=0, columnspan=3, sticky=tk.EW, padx=10, pady=5)
    app.progress.grid_remove()  # 默认隐藏

    # 功能按钮
    buttons = [
        ("Connect ADB", 4, 0, app.connect_adb),
        ("Disconnect ADB", 4, 1, app.disconnect_adb),
        ("Help", 4, 2, app.show_help),
        ("Force Install", 5, 0, app.force_install),
        ("Uninstall", 5, 1, app.uninstall),
        ("Package List", 5, 2, app.package_list),
        ("Clear Cache", 6, 0, app.clear_cache),
        ("Root", 6, 1, app.root_device),
        ("Pull_ANR", 6, 2, app.pull_anr_file),
        ("Remount", 7, 0, app.remount),
        ("Get Version", 7, 1, app.get_version),
        ("Reboot", 7, 2, app.reboot),
        ("Android Version", 8, 0, app.get_android_version),
        ("LogClear", 9, 1, app.log_clear),
        ("Get_Packagename", 9, 2, app.get_package_name),
        ("Screencap", 0, 2, app.screencap),
        ("Get_SN", 1, 2, app.get_serial_number),
        ("Start Logcat", 8, 1, app.start_logcat),
        ("Stop Logcat", 8, 2, app.stop_logcat),
        ("Kill_All_Processes", 9, 0, app.kill_app_process),
    ]

    for text, row, col, cmd in buttons:
        ttk.Button(app.root, text=text, command=cmd).grid(
            row=row, column=col, sticky=tk.EW, padx=5, pady=5
        )