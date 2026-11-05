"""性能基线入口回归测试（v5.4.7）

守护「性能面板上直接选基线 → 报告自动带对比」这条链路。

⚠️ 背景：基线功能（`modules/perf_baseline.py`）其实**早就写好了**
   （存 / 选 / 对比 / 曲线叠加），但入口只在**报告窗口**里 ——
   用起来要「停止 → 报告窗口 → 点『与基线对比』」三步。
   v5.4.7 把入口提到性能面板上。

⚠️ 这里守护两个曾经踩过的坑：
   ① `list_baselines()` 返回的是**存储包装**（含 session 键），
      而 `compare()` 期望 **session 本体**（含 stats 键）——
      少取一层 → 对比结果全空
   ② 三元表达式里给变量赋值、别处引用 → 分支不成立时 NameError

用法: python tests/test_perf_baseline_entry.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import perf_baseline as B

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    extra = f"  -> {detail}" if detail and not cond else ""
    results.append((cond, label, detail))
    print(("  PASS  " if cond else "  FAIL  ") + label + extra)


def make_session(cpu=30.0, pss=250.0, fps=60.0, jank=1.0):
    """造一份 session（结构对齐 PerfCollector._stats_snapshot）"""
    m = lambda v: {'cur': v, 'avg': v, 'peak': v, 'p95': v, 'p05': v}
    return {
        'package': '', 'pid': 1234,
        'stats': {
            'cpu': m(cpu), 'pss': m(pss), 'rss': m(None), 'java': m(None),
            'native': m(None), 'fps': m(fps), 'jank': m(jank),
            'p95_frame': m(16.0), 'p99_frame': m(20.0),
            'threads': [], 'thread_sum': 0.0, 'sample_count': 10,
            'elapsed': 20.0, 'mode': 'system', 'quality': {},
        },
        'history': [], 'frame_samples': [], 'conclusions': [],
        'scenario': 'general',
    }


print("=" * 68)
print("性能基线入口回归测试")
print("=" * 68)

# ── 1. 存取 ──────────────────────────────────────────────────
print()
print("=== 1. 基线存取 ===")
store = B.BaselineStore()
PKG = '__baseline_test__'
for b in store.list_baselines(PKG):
    store.delete(b['_path'])

p1 = store.save(PKG, make_session(cpu=30.0, pss=250.0))
check("能保存基线", bool(p1), p1)
time.sleep(1.1)
p2 = store.save(PKG, make_session(cpu=45.0, pss=280.0))
check("能保存第二份基线", bool(p2), p2)

bl = store.list_baselines(PKG)
check("能列出基线（2 份）", len(bl) == 2, len(bl))
check("基线按「新 → 旧」排序", bl[0]['saved_at'] >= bl[1]['saved_at'])

# ── 2. ⚠️ 关键：存储包装 vs session 本体 ──────────────────────
print()
print("=== 2. 存储包装 vs session 本体（最容易用错的地方）===")
check("list_baselines 返回的是**存储包装**（含 session 键）",
      'session' in bl[0], sorted(bl[0].keys()))
check("存储包装里有 _path（供 delete 用）", '_path' in bl[0])

session_of = bl[0]['session']
check("取 ['session'] 后才有 stats 键",
      'stats' in session_of, sorted(session_of.keys()))

loaded = store.load(p1)
check("load() 返回的也是存储包装", loaded is not None and 'session' in loaded)

# ⚠️ 如果这里忘了取 ['session']，compare 会拿不到 stats
wrong = B.compare(make_session(38.0, 265.0), bl[0])
check("**直接传包装**给 compare → 对比结果为空（这就是那个坑）",
      len(wrong['metrics']) == 0, len(wrong['metrics']))

right = B.compare(make_session(38.0, 265.0), session_of)
check("**传 session 本体**给 compare → 对比结果正确",
      len(right['metrics']) > 0, len(right['metrics']))

# ── 3. 对比内容 ──────────────────────────────────────────────
print()
print("=== 3. 对比内容正确性 ===")
_cpu_m = next((m for m in right['metrics'] if m['key'] == 'cpu'), None)
check("对比结果含 CPU 项", _cpu_m is not None)
if _cpu_m:
    check("CPU 差值 = 当前 - 基线 = 38 - 45 = -7",
          abs(_cpu_m['delta'] - (-7.0)) < 0.01, _cpu_m['delta'])
    check("CPU 变好（降了算好）", _cpu_m['better'] is True, _cpu_m['better'])

_pss_m = next((m for m in right['metrics'] if m['key'] == 'pss'), None)
check("对比结果含内存项", _pss_m is not None)
if _pss_m:
    check("内存差值 = 265 - 280 = -15",
          abs(_pss_m['delta'] - (-15.0)) < 0.01, _pss_m['delta'])

_fps_m = next((m for m in right['metrics'] if m['key'] == 'fps'), None)
if _fps_m:
    check("持平的项 better 为 None（不是 True 也不是 False）",
          _fps_m['better'] is None, _fps_m['better'])

summary = B.summarize_comparison(right)
check("摘要非空", bool(summary), summary)
check("摘要提到改善的指标", 'CPU' in summary, summary)

# ── 4. 基线选择状态机（模拟面板交互）────────────────────────
print()
print("=== 4. 基线选择状态机（面板交互逻辑）===")
# 模拟 layout 的下拉：第 0 项恒为「不对比」，其余是基线
names = ['不对比']
for b in bl:
    names.append(b['saved_at_text'])
check("下拉第 0 项是「不对比」", names[0] == '不对比')
check("下拉项数 = 基线数 + 1", len(names) == len(bl) + 1, len(names))

# index 约定：-1 = 不对比；>=0 是「去掉不对比后」的下标
sel_index = -1
check("index = -1 时取不到基线",
      (sel_index < 0) or (sel_index >= len(bl)))

sel_index = 0
check("index = 0 时取到第 1 份基线", sel_index < len(bl))
if sel_index < len(bl):
    got = bl[sel_index].get('session')
    check("取到的 session 含 stats（报告能直接用）",
          got is not None and 'stats' in got)

# ── 5. 清理 ──────────────────────────────────────────────────
print()
print("=== 5. 删除 ===")
check("能删除基线", store.delete(p1) is True)
check("删除后剩 1 份", len(store.list_baselines(PKG)) == 1,
      len(store.list_baselines(PKG)))
for b in store.list_baselines(PKG):
    store.delete(b['_path'])
check("清理干净", len(store.list_baselines(PKG)) == 0)

# ── 6. 源码级守护：入口不能被删掉 ────────────────────────────
print()
print("=== 6. 源码级守护（入口不能被悄悄删掉）===")
import inspect
_app = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'app.py')
with open(_app, encoding='utf-8') as f:
    _app_src = f.read()
check("app.py 有 list_perf_baselines()", 'def list_perf_baselines' in _app_src)
check("app.py 有 get_selected_perf_baseline()",
      'def get_selected_perf_baseline' in _app_src)
check("app.py 有 save_perf_baseline()", 'def save_perf_baseline' in _app_src)
check("_open_perf_report 会自动带上选中的基线",
      'get_selected_perf_baseline()' in _app_src)

_lay = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'gui', 'layout_v4.py')
with open(_lay, encoding='utf-8') as f:
    _lay_src = f.read()
check("性能面板有基线下拉", 'perf_baseline_var' in _lay_src)
check("性能面板有「存为基线」按钮", '存为基线' in _lay_src)
check("性能面板有「刷新基线」按钮", '刷新基线' in _lay_src)
# ⚠️ 三元表达式里给变量赋值再别处引用 → NameError
check("没有「三元里赋值、别处引用」的反模式",
      "f\"  CPU {_cpu:.0f}%\" if isinstance(cpu" not in _lay_src)

print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
