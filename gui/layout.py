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

    # Status Display
    ttk.Label(app.root, text="Status:").grid(row=8, column=0, sticky=tk.W, padx=5, pady=5)
    app.status_text = tk.Text(app.root, height=20, width=70)
    app.status_text.grid(row=9, column=0, columnspan=3, padx=10, pady=10)
    app.status_text.tag_configure("success", foreground="green")
    app.status_text.tag_configure("error", foreground="red")

    # 添加进度条组件（确保挂载到app实例）
    app.progress = ttk.Progressbar(app.root, mode="indeterminate", length=280)
    app.progress.grid(row=10, column=0, columnspan=3, sticky=tk.EW, padx=10, pady=5)
    app.progress.grid_remove()  # 默认隐藏

    # 功能按钮
    buttons = [
        ("Connect ADB", 3, 0, app.connect_adb),
        ("Disconnect ADB", 3, 1, app.disconnect_adb),
        ("Help", 3, 2, app.show_help),
        ("Force Install", 4, 0, app.force_install),
        ("Uninstall", 4, 1, app.uninstall),
        ("Package List", 4, 2, app.package_list),
        ("Clear Cache", 5, 0, app.clear_cache),
        ("Root", 5, 1, app.root_device),
        ("Pull_ANR", 5, 2, app.pull_anr_file),
        ("Remount", 6, 0, app.remount),
        ("Get Version", 6, 1, app.get_version),
        ("Reboot", 6, 2, app.reboot),
        ("Android Version", 7, 0, app.get_android_version),
        ("Screencap", 0, 2, app.screencap),
        ("Get_SN", 1, 2, app.get_serial_number),
        ("Start Logcat", 7, 1, app.start_logcat),
        ("Stop Logcat", 7, 2, app.stop_logcat),
    ]

    for text, row, col, cmd in buttons:
        ttk.Button(app.root, text=text, command=cmd).grid(
            row=row, column=col, sticky=tk.EW, padx=5, pady=5
        )