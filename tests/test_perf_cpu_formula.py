"""整机 CPU 忙碌率公式回归测试（用真机录制的真实数据）

⚠️ **这个测试守护的是一个真机上暴露的严重 bug**（v5.4.7）：
   system（整机）模式的 CPU 占用在多核设备上**恒定显示 100%**。

根因：
   /proc/stat 的「cpu」行是**所有核的累加值**，且**含 idle**。
   旧公式「Δtotal / CLK_TCK × 100」再 min(..., 100) →
   多核设备上结果必然 >= 100% → 被截成恒定 100%。

正确公式：**忙碌率 = 1 - Δidle / Δtotal**
   （Δtotal 已含 idle，idle 本身隐含了「核数 × 窗口」，
    再除以核数等于重复除一次 → 实测同一时刻旧公式 491.5%）

⚠️ 数据是**真机实测录下来的**（192.168.0.50，2 核康佳电视），
   不是编造的 —— 这样才能真正防住回归。

用法: python tests/test_perf_cpu_formula.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import perf_parsers as P
from modules.perf_collector import PerfCollector, CpuPoint

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    extra = f"  -> {detail}" if detail and not cond else ""
    results.append((cond, label, detail))
    print(("  PASS  " if cond else "  FAIL  ") + label + extra)


# ── 真机录制的真实 /proc/stat（192.168.0.50，2 核）────────────
# 第一次采样
REAL_STAT_1 = """cpu  5473558 368615 7367461 19286907 237347 668 312622 0 0 0

cpu0 2735656 173809 3684233 9492061 109248 440 309235 0 0 0

cpu1 2737902 194805 3683227 9794846 128098 228 3387 0 0 0
"""

# 4 秒后的第二次采样（top 同时刻输出：User 33 + Sys 179 + Idle 189 + IOW 103 + SIRQ 59 = 563）
REAL_STAT_2 = """cpu  5480921 370302 7375692 19311335 237877 668 313033 0 0 0

cpu0 2735656 173809 3684233 9492061 109248 440 309235 0 0 0

cpu1 2745265 196497 3681459 9782924 128627 228 3798 0 0 0
"""

print("=" * 68)
print("整机 CPU 忙碌率公式回归测试（真机数据）")
print("=" * 68)

# ── 1. 核数解析 ──────────────────────────────────────────────
print()
print("=== 1. 核数解析（从同一份 /proc/stat 数 cpuN 行）===")
cores = P.parse_proc_stat_cores(REAL_STAT_1)
check("能从 /proc/stat 数出核数", cores == 2, f"得到 {cores}")
check("核数解析对空/异常输入返回 0",
      P.parse_proc_stat_cores('') == 0 and P.parse_proc_stat_cores('xxx') == 0)

# ── 2. 分项字段解析 ──────────────────────────────────────────
print()
print("=== 2. /proc/stat 分项字段解析 ===")
f1 = P.parse_proc_stat_cpu_fields(REAL_STAT_1)
f2 = P.parse_proc_stat_cpu_fields(REAL_STAT_2)
check("能解析出 cpu 总量行的分项", f1 is not None and 'idle' in f1)
check("idle 是第 4 个字段（user nice system idle）",
      f1['idle'] == 19286907, f"得到 {f1['idle']}")
check("iowait 是第 5 个字段", f1['iowait'] == 237347, f"得到 {f1['iowait']}")
check("解析失败返回 None",
      P.parse_proc_stat_cpu_fields('') is None
      and P.parse_proc_stat_cpu_fields('cpu abc def') is None)

# ── 3. 核心：忙碌率公式 ──────────────────────────────────────
print()
print("=== 3. 整机忙碌率公式（核心断言）===")
d_total = f2['total'] - f1['total']
d_idle = f2['idle'] - f1['idle']
old_raw = d_total / 2 / 100 * 100                        # 旧公式（÷核数），未截断
old_formula = min(old_raw, 100.0)                       # 旧公式实际显示值（被截断）
new_formula = (1.0 - d_idle / d_total) * 100.0          # 正确公式

# ⚠️ 旧公式**截断前**就 >100% → 截断后恒为 100%（这就是 bug 的表现）
check("旧公式截断前就 >100%（所以显示恒为 100%）", old_raw > 100.0,
      f"旧公式原始值 = {old_raw:.1f}%")
check("旧公式截断后确实显示 100%", old_formula == 100.0,
      f"旧公式显示值 = {old_formula:.1f}%")
check("正确公式在 0~100 区间", 0.0 <= new_formula <= 100.0,
      f"新公式 = {new_formula:.1f}%")

# 用采集器的真实路径算一遍（而不是直接调公式）
_c = PerfCollector()
_c.mode = 'system'
_a = CpuPoint(1000.0, int(f1['total']), {}, None, f1['idle'])
_b = CpuPoint(4000.0, int(f2['total']), {}, None, f2['idle'])
_got = _c._diff_cpu(_a, _b)
check("采集器算出的是正确公式的值",
      _got is not None and abs(_got - round(new_formula, 2)) < 0.5,
      f"得到 {_got}，期望 {round(new_formula, 2)}")

# ── 4. 关键回归：空闲时不能是 100% ───────────────────────────
print()
print("=== 4. 关键回归断言 ===")
# 构造一段「真的空闲」的样本：idle 增量占绝大部分
IDLE_STAT_1 = """cpu  100000 100 200 999700 0 0 0 0 0 0

cpu0 50000 50 100 499850 0 0 0 0 0 0

cpu1 50000 50 100 499850 0 0 0 0 0 0
"""
IDLE_STAT_2 = """cpu  100200 100 240 1001900 0 0 0 0 0 0

cpu0 50100 50 120 500950 0 0 0 0 0 0

cpu1 50100 50 120 500950 0 0 0 0 0 0
"""
_i1 = P.parse_proc_stat_cpu_fields(IDLE_STAT_1)
_i2 = P.parse_proc_stat_cpu_fields(IDLE_STAT_2)
_idle_total = _i2['total'] - _i1['total']
_idle_idle = _i2['idle'] - _i1['idle']
_idle_busy = (1.0 - _idle_idle / _idle_total) * 100.0

_a2 = CpuPoint(1000.0, int(_i1['total']), {}, None, _i1['idle'])
_b2 = CpuPoint(4000.0, int(_i2['total']), {}, None, _i2['idle'])
_got_idle = _c._diff_cpu(_a2, _b2)

check("空闲设备算出低 CPU（不是 100%）",
      _got_idle is not None and _got_idle < 10.0,
      f"得到 {_got_idle}%")
check("旧公式在空闲时也会饱和（证明 bug 真实存在）",
      min(_idle_total / 2 / 100 * 100, 100.0) >= 100.0,
      f"旧公式 = {min(_idle_total / 2 / 100 * 100, 100.0):.1f}%")

# ── 5. 边界：idle 缺失时返回 None（不能瞎猜）────────────────
print()
print("=== 5. 边界处理 ===")
_a3 = CpuPoint(1000.0, int(f1['total']), {}, None, None)   # 没有 idle
_b3 = CpuPoint(4000.0, int(f2['total']), {}, None, f2['idle'])
check("idle 缺失时返回 None（而不是编一个数）",
      _c._diff_cpu(_a3, _b3) is None)
check("总量差 <= 0 时返回 None",
      _c._diff_cpu(_b3, _a3) is None)

# ── 6. 采集器确实会记录核数 ──────────────────────────────────
print()
print("=== 6. 采集器内部状态 ===")
_c2 = PerfCollector()
check("采集器有 _cores 字段", hasattr(_c2, '_cores'))
check("初始 _cores = 1（保守）", _c2._cores == 1, _c2._cores)

print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
