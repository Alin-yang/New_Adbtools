from app import ADBToolApp
import tkinter as tk
from gui import layout_zh as layout  # 恢复原来布局

# 尝试使用支持拖拽的Tk
try:
    from tkinterdnd2 import TkinterDnD
    use_dnd = True
except ImportError:
    use_dnd = False


if __name__ == "__main__":
    if use_dnd:
        # 使用支持拖拽的根窗口
        root = TkinterDnD.Tk()
    else:
        # 使用普通的根窗口
        root = tk.Tk()
    
    app = ADBToolApp(root, layout_module=layout)
    root.mainloop()