# -*- coding: utf-8 -*-
"""性能页滚动性能测量（开发辅助）

用法: python tests/measure_perf_scroll.py
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


def main():
    root = tk.Tk()
    app = ADBToolApp(root, layout)
    for _ in range(5):
        root.update_idletasks()
        root.update()
    lay = app.layout_instance
    lay.switch_nav('perf')
    for _ in range(8):
        root.update_idletasks()
        root.update()

    out = []

    # 填满 60 行采样 + 30 线程
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

    trees = find_by_class(lay.root_frame, 'Treeview')
    cans = [c for c in find_by_class(lay.root_frame, 'Canvas')
            if c.winfo_width() > 400]
    out.append(f'Treeview {len(trees)} 个:')
    for t in trees:
        out.append(f'  行数={len(t.get_children())} '
                   f'{t.winfo_width()}x{t.winfo_height()}')
    out.append(f'大 Canvas {len(cans)} 个')

    def scroll(target, n=25):
        t0 = time.perf_counter()
        for _ in range(n):
            target.event_generate('<MouseWheel>', delta=-120)
            root.update_idletasks()
            root.update()
        return (time.perf_counter() - t0) / n * 1000

    if cans:
        c = cans[-1]
        ms = scroll(c)
        out.append('')
        out.append(f'性能页 Canvas 滚动: {ms:.2f} ms/次  '
                   f'(≈{1000 / max(ms, 0.01):.0f} fps)')
        if ms > 5:
            out.append('  ⚠️ 仍然偏慢（>5ms）')
        else:
            out.append('  ✅ 流畅（<5ms）')

    for i, t in enumerate(trees):
        ms = scroll(t)
        out.append(f'Treeview[{i}] 自身滚动: {ms:.2f} ms/次')

    print('\n'.join(out))
    with open(os.path.join(_ROOT, 'tests', '_shots_v4', 'perf_scroll.txt'),
              'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    root.destroy()


if __name__ == '__main__':
    main()
