"""定位 device tab 剩余横向空白的根因：打印各级容器的实际宽度"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

try:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
except ImportError:
    root = tk.Tk()

from app import ADBToolApp
from gui import layout_modern as layout
from config import Config

app = ADBToolApp(root, layout_module=layout)
root.update_idletasks()
root.update()

print("Config.WINDOW_GEOMETRY =", Config.WINDOW_GEOMETRY)
print("root.geometry()        =", root.geometry())
print("root.winfo_reqwidth()  =", root.winfo_reqwidth(), " reqheight =", root.winfo_reqheight())
print("root.winfo_width()     =", root.winfo_width())

lay = app.layout_instance
tab = lay.tabs['device']

def dump(w, name, depth=0):
    info = w.grid_info()
    print("  " * depth + f"{name}: class={w.winfo_class()} w={w.winfo_width()} "
          f"req={w.winfo_reqwidth()} x={w.winfo_x()} "
          f"sticky={info.get('sticky', '-')} column={info.get('column', '-')}")
    for ch in w.winfo_children():
        if ch.winfo_class() in ("TFrame", "Frame"):
            dump(ch, ch.winfo_name(), depth + 1)

print()
print("=== device tab 容器树 ===")
dump(tab, "device_tab")
print()
print("=== 各 Tab 的自然请求宽度（决定左面板最小宽度）===")
for name, t in lay.tabs.items():
    print(f"  {name:14s} req={t.winfo_reqwidth():5d}  实际={t.winfo_width()}")
    for ch in t.winfo_children():
        if ch.winfo_class() in ("TFrame","Frame","TLabelFrame"):
            print(f"      └ {ch.winfo_class():11s} req={ch.winfo_reqwidth():5d}  {ch.winfo_name()}")
            for gc in ch.winfo_children():
                print(f"           └ {gc.winfo_class():11s} req={gc.winfo_reqwidth():5d}")

print()
print("=== tab 的 grid 行列配置 ===")
for i in range(3):
    print(f"  col {i}: weight={tab.grid_columnconfigure(i).get('weight')} "
          f"minsize={tab.grid_columnconfigure(i).get('minsize')} "
          f"uniform={tab.grid_columnconfigure(i).get('uniform')}")
for i in range(3):
    print(f"  row {i}: weight={tab.grid_rowconfigure(i).get('weight')}")
root.destroy()
