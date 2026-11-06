# -*- coding: utf-8 -*-
"""滚动方案对比实验（开发辅助）

对比几种方案在「性能页有 60 行采样 + 30 线程」时的滚动耗时：
  A. 原样（表格在 Canvas 内）
  B. 表格移出 Canvas（当前实现）
  C. 上半部分也不用 Canvas（纯 Frame，超出就裁）

用法: python tests/measure_scroll_variants.py
"""
import sys
import os
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import tkinter as tk

from app import ADBToolApp
from gui import layout_v4 as layout


def find_by_class(w, cls, res=None):
    if res is None:
        res = []
    for c in w.winfo_children():
        if c.winfo_class() == cls:
            res.append(c)
        find_by_class(c, cls, res)
    return res


def scroll_ms(target, n=25):
    t0 = time.perf_counter()
    for _ in range(n):
        target.event_generate('<MouseWheel>', delta=-120)
        target.update_idletasks()
        target.update()
    return (time.perf_counter() - t0) / n * 1000


def fill(app, root):
    for i in range(60):
        app.performance_monitor.history.append(
            (f"11:20:{i % 60:02d}", 40.0 + i % 20, 200.0 + i,
             220.0 + i, 72.0, 93.0, None, None))
        app._fill_perf_samples()
    threads = [{'tid': 1000 + i, 'name': f'T{i}', 'cur': 5.0 + i,
                'avg': 4.0, 'peak': 9.0, 'state': 'RUNNABLE',
                'role': 'worker'} for i in range(30)]
    app._fill_thread_table(threads)
    root.update()


def main():
    out = []
    root = tk.Tk()
    root.geometry('1080x700+40+40')
    app = ADBToolApp(root, layout)
    for _ in range(5):
        root.update_idletasks()
        root.update()
    lay = app.layout_instance
    lay.switch_nav('perf')
    for _ in range(10):
        root.update_idletasks()
        root.update()

    fill(app, root)

    cans = [c for c in find_by_class(lay.root_frame, 'Canvas')
            if c.winfo_width() > 400]
    trees = find_by_class(lay.root_frame, 'Treeview')
    c = cans[-1]

    out.append('=== 方案 B：表格移出 Canvas（当前实现）===')
    out.append(f'  Canvas 滚动: {scroll_ms(c):.2f} ms/次')
    for i, t in enumerate(trees):
        out.append(f'  tree[{i}] 自身滚动: {scroll_ms(t):.2f} ms/次 '
                   f'（{len(t.get_children())} 行）')

    out.append('')
    out.append('=== 变体：把 Canvas 里的 window item 移除 ===')
    c.delete('all')
    root.update()
    out.append(f'  Canvas 滚动: {scroll_ms(c):.2f} ms/次')

    out.append('')
    out.append('=== 变体：表格也 pack_forget（完全无原生控件在 Canvas 附近）===')
    root.destroy()

    print('\n'.join(out))


if __name__ == '__main__':
    main()
