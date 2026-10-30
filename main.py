from app import ADBToolApp
import tkinter as tk
import os

# 布局选项：
#   layout_v4    全新工作台布局（默认：左侧导航 + 全局上下文栏 + 可折叠终端 + 深/浅主题）
#   layout_modern 旧版布局（保留作回退，UI 可用环境变量 ADBTOOL_LAYOUT=v3 切回）
_LAYOUT_ENV = os.environ.get('ADBTOOL_LAYOUT', 'v4').lower()

if _LAYOUT_ENV in ('v3', 'modern', 'legacy'):
    from gui import layout_modern as layout
else:
    from gui import layout_v4 as layout

# 尝试使用支持拖拽的Tk
try:
    from tkinterdnd2 import TkinterDnD
    use_dnd = True
except ImportError:
    use_dnd = False


if __name__ == "__main__":
    import time
    import logging

    # ⚠️ 启动耗时基准要用「进程创建时间」，不能用 main.py 里的 import 时刻：
    #    onefile 打包时，PyInstaller 的 bootloader 会先解压内嵌 archive
    #    （实测约 12 秒），那段时间发生在 main.py 之前，用 import 时刻算会漏掉。
    try:
        import psutil
        _t0 = psutil.Process().create_time()
    except Exception:
        _t0 = time.time()

    if use_dnd:
        # 使用支持拖拽的根窗口
        root = TkinterDnD.Tk()
    else:
        # 使用普通的根窗口
        root = tk.Tk()

    app = ADBToolApp(root, layout_module=layout)

    # 启动耗时诊断：首帧完成（窗口已可见）时打一条日志
    def _log_first_frame():
        logging.info(
            f"[启动] 首帧完成，进程启动至今 {(time.time() - _t0) * 1000:.0f} ms")
    root.after(0, _log_first_frame)

    root.mainloop()
