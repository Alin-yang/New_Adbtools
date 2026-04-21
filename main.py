from app import ADBToolApp
import tkinter as tk
# 布局选项：layout_tab_view（原版）/ layout_optimized（优化版-推荐）/ layout_workflow（工作流版）
from gui import layout_optimized as layout  # 使用优化版四区布局

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