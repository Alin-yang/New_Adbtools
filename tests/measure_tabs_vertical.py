"""测量各 Tab 的纵向空白占用

用法: python tests/measure_tabs_vertical.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk

try:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
except ImportError:
    root = tk.Tk()

root.geometry("1280x620")

from gui import layout_modern as layout_mod
from app import ADBToolApp

app = ADBToolApp(root, layout_mod)
root.update_idletasks()
root.update()

lay = app.layout_instance

TABS = ['device', 'app', 'log_screen', 'mirror', 'performance',
        'script_runner']

print("=" * 72)
print("各 Tab 纵向空白测量（窗口 1280x620）")
print("=" * 72)
print(f"{'Tab':16s} {'可用高':>7s} {'内容高':>7s} {'纵向余':>7s} {'占比':>7s}")
print("-" * 72)

# ⚠️ Tab 是懒加载的：必须先 switch_tab 触发构建，否则 lay.tabs 里没有
for key in TABS:
    if key in lay.tab_buttons:
        lay.tab_buttons[key].invoke()
        root.update_idletasks()
        root.update()
        # 等构建完成（构建是同步的，update 即可）
        root.update()

for key in TABS:
    if key not in lay.tabs:
        print(f"{key:16s} 未构建")
        continue
    tab = lay.tabs[key]
    root.update_idletasks()
    root.update()

    # 递归找所有后代控件的最大底边（相对 tab 顶部）
    # ⚠️ 必须递归：卡片是 TLabelframe > TFrame > TFrame 三层嵌套，
    #    只看两层会严重低估内容高度。
    tab_top = tab.winfo_rooty()

    def max_bottom(w):
        b = w.winfo_rooty() - tab_top + w.winfo_height()
        for child in w.winfo_children():
            cb = max_bottom(child)
            if cb > b:
                b = cb
        return b

    content_h = 0
    for c in tab.winfo_children():
        b = max_bottom(c)
        if b > content_h:
            content_h = b

    avail = tab.winfo_height()
    rest = avail - content_h
    pct = rest * 100 // avail if avail else 0
    flag = " ⚠ 空白过多" if pct > 35 else ""
    print(f"{key:16s} {avail:7d} {content_h:7d} {rest:7d} {pct:6d}%{flag}")

print()
print("=" * 72)
print("说明：占比 > 35% 说明该 Tab 内容太少，底部大片留白")
print("=" * 72)

root.destroy()
