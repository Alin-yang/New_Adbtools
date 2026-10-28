"""测量左右分栏与各 Tab 卡片的实际宽度，用于调空白

用法: python tests/measure_layout.py
"""
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

print("geometry 请求:", Config.WINDOW_GEOMETRY, " 实际:", root.geometry())

lay = app.layout_instance
cf = lay.content_frame
left = lay.content_area
right = lay.output_area

def w(wid):
    return wid.winfo_width()

def h(wid):
    return wid.winfo_height()

print("=" * 72)
print(f"窗口 {root.winfo_width()}x{root.winfo_height()}   content_frame 宽={w(cf)} 高={h(cf)}")
print(f"  左面板 content_area : w={w(left)}  h={h(left)}")
print(f"  右面板 output_area  : w={w(right)}  h={h(right)}")
print(f"  中间空隙            : {w(cf) - w(left) - w(right)}")
print()

# 各 Tab 卡片覆盖情况
for name, tab in lay.tabs.items():
    root.update_idletasks()
    cards = []
    def walk(parent):
        for child in parent.winfo_children():
            if child.winfo_class() in ("Labelframe", "TLabelframe"):
                cards.append((child.cget('text'), child.winfo_x(), child.winfo_y(),
                              w(child), h(child)))
            walk(child)
    walk(tab)
    tab_w, tab_h = w(tab), h(tab)
    max_right = max((x + cw for _, x, _, cw, _ in cards), default=0)
    max_bottom = max((y + ch for _, _, y, _, ch in cards), default=0)
    print(f"--- {name}  tab={tab_w}x{tab_h} ---")
    for title, x, y, cw, ch in cards:
        print(f"    [{title}] x={x:4d} y={y:4d} w={cw:4d} h={ch:3d}  右余={tab_w - x - cw:4d}")
    print(f"    >> 横向余 {tab_w - max_right}px | 纵向余 {tab_h - max_bottom}px"
          + ("   ⚠️ 纵向溢出!" if max_bottom > tab_h else ""))
    print()

# 试几组左右分栏参数
print("=" * 72)
print("左右分栏参数试验（min0/weight0 | min1/weight1 → 左宽 / 右宽）")
base = (300, 1, 260, 3)
for params in [
    (300, 1, 260, 3),
    (320, 1, 380, 1),
    (340, 1, 420, 1),
    (360, 1, 460, 1),
    (380, 1, 500, 1),
    (400, 1, 520, 1),
]:
    m0, w0, m1, w1 = params
    cf.grid_columnconfigure(0, weight=w0, minsize=m0)
    cf.grid_columnconfigure(1, weight=w1, minsize=m1)
    root.update_idletasks()
    root.update()
    print(f"  min0={m0} w0={w0} | min1={m1} w1={w1}  ->  左={w(left)}  右={w(right)}")

root.destroy()
