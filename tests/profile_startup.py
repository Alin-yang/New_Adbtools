"""启动耗时 profiling：逐段测量启动各阶段

用法: python tests/profile_startup.py
"""
import sys, os, time

T_START = time.perf_counter()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

marks = []
def mark(label):
    marks.append((label, (time.perf_counter() - T_START) * 1000))

mark("解释器启动")

import tkinter as tk
mark("import tkinter")

try:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
    mark("创建 TkinterDnD.Tk()")
except Exception as e:
    print("TkinterDnD 失败:", e)
    root = tk.Tk()
    mark("创建 tk.Tk()")

import app as appmod
from gui import layout_modern as layout
mark("import app + gui")

# ---- 插桩：包住布局构建的各个阶段 ----
inst = {}
def wrap(cls, name, label=None):
    orig = getattr(cls, name)
    lbl = label or f"{cls.__name__}.{name}"
    def w(*a, **kw):
        t = time.perf_counter()
        try:
            return orig(*a, **kw)
        finally:
            marks.append((f"  └ {lbl}", (time.perf_counter() - t) * 1000))
    setattr(cls, name, w)

for m in ('setup_main_container', 'create_top_bar', 'create_tab_navigation',
          'create_content_area', 'create_device_tab', 'create_app_tab',
          'create_log_screen_tab', 'create_mirror_tab', 'create_performance_tab',
          'create_script_runner_tab', 'create_advanced_tab', 'create_right_output_area',
          'setup_keyboard_shortcuts', '_setup_styles', '_create_card'):
    wrap(layout.LayoutModern, m)

wrap(appmod.ADBToolApp, '_setup_gui')
wrap(appmod.ADBToolApp, '_setup_post_components')
wrap(appmod.ADBToolApp, '_setup_drag_drop')
wrap(appmod.ADBToolApp, '_init_variables')

t = time.perf_counter()
app = appmod.ADBToolApp(root, layout_module=layout)
marks.append(("ADBToolApp.__init__ 总计", (time.perf_counter() - t) * 1000))
mark("init 结束")

root.update()
mark("第一次 update()（窗口绘制）")
root.update_idletasks()
mark("update_idletasks()")

# 让延迟任务跑起来
def tick():
    root.update()
    root.after(30, tick)
root.after(30, tick)
time.sleep(1.2)
root.update()
mark("延迟初始化（1.2s 后）")

print()
print("=" * 74)
print("启动耗时分解")
print("=" * 74)
for label, ms in marks:
    bar = "█" * int(ms / 4)
    print(f"  {ms:8.1f} ms  {label}  {bar}")

total = marks[-1][1]
print()
print(f"  到窗口可交互累计：{total:.0f} ms")
init_ms = [m for m in marks if m[0] == "ADBToolApp.__init__ 总计"][0][1]
print(f"  其中 __init__ 同步部分：{init_ms:.0f} ms")
