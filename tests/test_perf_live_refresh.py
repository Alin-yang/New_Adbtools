"""性能监控**实时刷新**链路回归测试

背景（真实 bug，用户报「点开始监控后不显示数据，停止后才在报告里看到」）：

  根因是 app._run_in_ui / _schedule_ui_pump 的线程模型缺陷：
    · Tk 的 after() 只能在**主线程**调用
    · 旧实现是「谁投递谁 after 一次」，后台线程调用会抛
      "main thread is not in main loop"，而异常被 except 吞掉
    · 结果：队列里的回调永远不被消费 —— 后台在采集，界面不刷新
  其它功能没暴露是因为它们的 _run_in_ui 大多在主线程触发；
  性能采集是**纯后台线程驱动**，100% 命中。

修法：主线程启动**常驻泵**（_start_ui_pump），后台线程只往队列塞东西。

本测试守护三件事：
  1. 后台线程调用 _run_in_ui，回调必须真的被执行（不能静默失效）
  2. PerfCollector._publish 的投递方式正确（单参数 callable）
  3. 指标卡副标题格式与布局层一致（两行，不会被截断）

用法: python tests/test_perf_live_refresh.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk                                   # noqa: E402

try:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
except ImportError:
    root = tk.Tk()
root.geometry('1200x680')

from app import ADBToolApp                               # noqa: E402
from gui import layout_v4 as layout                      # noqa: E402

ok = True


def check(name, cond, extra=''):
    global ok
    print(('  PASS  ' if cond else '  FAIL  ') + name
          + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        ok = False


def pump(n=6):
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(0.02)


print('=' * 72)
print('=== 1. UI 队列泵：后台线程投递必须被执行 ===')
app = ADBToolApp(root, layout_module=layout)
pump()

check('常驻泵已启动', getattr(app, '_ui_pump_started', False),
      getattr(app, '_ui_pump_started', None))

# 从后台线程投递一个会设置标记的回调
flag = {'hit': False}


def _bg_job():
    app._run_in_ui(lambda: flag.__setitem__('hit', True))


th = threading.Thread(target=_bg_job, daemon=True)
th.start()
th.join(timeout=3)

# 给主线程时间处理队列（常驻泵 50ms 一跳）
for _ in range(30):
    pump(2)
    if flag['hit']:
        break
    time.sleep(0.02)

check('后台线程投递的回调被执行', flag['hit'])

# 连投多个，确认队列不丢
counter = {'n': 0}
for _ in range(5):
    threading.Thread(
        target=lambda: app._run_in_ui(lambda: counter.__setitem__('n', counter['n'] + 1)),
        daemon=True).start()
for _ in range(40):
    pump(2)
    if counter['n'] >= 5:
        break
    time.sleep(0.02)
check('连续投递 5 个回调全部执行', counter['n'] == 5, counter['n'])

print()
print('=' * 72)
print('=== 2. PerfCollector._publish 的投递方式 ===')
import inspect
from modules.perf_collector import PerfCollector

src = inspect.getsource(PerfCollector._publish)
# 必须是「单参数 callable」，不能是 (callback, snapshot) 两参数
check('_publish 不再以 (callback, snapshot) 两参数调用 _run_in_ui',
      'self.update_callback, snapshot' not in src)
check('_publish 用 lambda 绑定 snapshot', 'lambda snap=snapshot' in src)

print()
print('=' * 72)
print('=== 3. 指标卡副标题：与布局层一致（两行）===')
lay = app.layout_instance
lay.switch_nav('perf')
pump()

check('perf_metric_labels 已创建', bool(app.perf_metric_labels),
      list(app.perf_metric_labels.keys()))

# 布局层初始文本
for key, (cur_lbl, sub_lbl) in app.perf_metric_labels.items():
    txt = sub_lbl.cget('text')
    check(f'初始副标题含换行（{key}）', '\n' in txt, repr(txt))
    break

# UI 更新后也应保持两行
src_ui = inspect.getsource(app._update_performance_ui)
check('UI 更新写入的副标题含换行', '\\n' in src_ui and '均值 --\\n峰值 --' in src_ui)

print()
print('=' * 72)
print('=== 4. 采集→UI 的实际刷新（mock 采集器，不依赖真机）===')
# 用假的采集结果驱动一次 UI 更新，验证指标卡确实会变
fake_stats = {
    'mode': 'proc', 'pid': 12345, 'sample_count': 7, 'elapsed': 14.0,
    'cpu': {'cur': 42.5, 'avg': 40.0, 'peak': 60.0, 'p95': 55.0, 'p05': 20.0},
    'pss': {'cur': 128.0, 'avg': 120.0, 'peak': 150.0, 'p95': 145.0, 'p05': 100.0},
    'rss': {'cur': 200.0, 'avg': 190.0, 'peak': 220.0, 'p95': 215.0, 'p05': 180.0},
    'java': {'cur': 50.0, 'avg': 48.0, 'peak': 60.0, 'p95': 58.0, 'p05': 40.0},
    'native': {'cur': 30.0, 'avg': 28.0, 'peak': 35.0, 'p95': 33.0, 'p05': 20.0},
    'fps': {'cur': 58.0, 'avg': 55.0, 'peak': 60.0, 'p95': 60.0, 'p05': 30.0},
    'jank': {'cur': 1.2, 'avg': 2.0, 'peak': 8.0, 'p95': 6.0, 'p05': 0.0},
    'p95_frame': {'cur': 18.0, 'avg': 17.0, 'peak': 25.0, 'p95': 22.0, 'p05': 12.0},
    'p99_frame': {'cur': 30.0, 'avg': 28.0, 'peak': 45.0, 'p95': 40.0, 'p05': 20.0},
    'alert': False, 'threads': [], 'thread_sum': 0.0,
    'quality': {'ok_points': 7, 'fail_points': 0, 'total_points': 7,
                'success_rate': 100.0, 'interval_actual': 2.0,
                'interval_set': 2.0, 'costs': {}, 'degraded': False,
                'mode': 'proc', 'clk_tck': 100, 'cpu_max': 400.0},
}
app._update_performance_ui(fake_stats)
pump()

cpu_text = app.perf_metric_labels['cpu'][0].cget('text')
pss_text = app.perf_metric_labels['pss'][0].cget('text')
check('CPU 指标卡显示数值', cpu_text == '42.5%', cpu_text)
check('PSS 指标卡显示数值', pss_text == '128.0 MB', pss_text)
sub_text = app.perf_metric_labels['cpu'][1].cget('text')
check('副标题为两行', '\n' in sub_text, repr(sub_text))

pid_text = app.perf_pid_label.cget('text')
check('PID/模式指示已更新', '12345' in pid_text and '精确差分' in pid_text, pid_text)

print()
print('=' * 72)
root.destroy()
if ok:
    print('ALL PASS')
else:
    print('HAS FAIL')
sys.exit(0 if ok else 1)
