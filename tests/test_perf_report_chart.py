# -*- coding: utf-8 -*-
"""性能报告与指标解析 —— 防回归测试（v5.4.10）

⚠️ **这个文件守护三件用户反馈的事**：
  ① 趋势曲线「不够详细、不易读、连时间标示都没有」
  ② 「java heap native fps 为什么没有数据」
  ③ 顺带发现并修的 meminfo 老格式兼容问题

## ① 曲线的可读性
原来 X 轴**完全空白**（只有一条横线），看不出每个点对应哪一刻；
Y 轴只有裸数字（分不清是 MB 还是 %）；没有数据点标记；
空数据时一律写「暂无数据」，用户分不清是「设备不支持」还是「没采到」。

## ② java/native 没数据
两个原因：
  - **报告窗口根本没有这两张卡**（只有 CPU/PSS/FPS）
  - **解析器只认 `Java Heap:`**（Android 8+ 格式），
    而老设备（Android 5~7 电视盒子）用的是 **`Dalvik Heap`** 表格格式
    → java/native 永远是 None
"""
import io
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(_ROOT))

FAILED = []
PASSED = 0


def check(name, cond, detail=''):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}   {detail}")


print("=" * 68)
print("性能报告与指标解析 —— 防回归测试")
print("=" * 68)

# ====================================================================== #
# 1. meminfo 解析：老格式（Dalvik Heap）
# ====================================================================== #
print()
print("=== 1. meminfo 解析（老设备用 Dalvik Heap 而非 Java Heap）===")

from modules import perf_parsers as P

# ⚠️ 这是**真机抓到的原始输出**（Android 5.1.1 康佳电视）
REAL_MEMINFO_TABLE = """Applications Memory Usage (kB):
Uptime: 241105945 Realtime: 241105945

** MEMINFO in pid 23681 [com.konka.livelauncher] **
                   Pss  Private  Private  Swapped     Heap     Heap     Heap
                 Total    Dirty    Clean    Dirty     Size    Alloc     Free
                ------   ------   ------   ------   ------   ------   ------
  Native Heap    22261    22204        0        0    32768    21913    10854
  Dalvik Heap    32257    32056        0        0    44054    36064     7990
 Dalvik Other      680      680        0        0
        Stack      580      580        0        0
    Other dev        8        0        8        0
     .so mmap     2996     1640       72        0
        TOTAL    70309    58856     6500        0    76822    57977    18844
"""

res = P.parse_meminfo(REAL_MEMINFO_TABLE)
print(f"  解析结果: {res}")
check("老格式能解析出 java（认 Dalvik Heap）",
      res['java'] is not None and abs(res['java'] - 32257 / 1024.0) < 0.2,
      f"java={res['java']}，期望 {32257 / 1024.0:.1f}")
check("老格式能解析出 native",
      res['native'] is not None and abs(res['native'] - 22261 / 1024.0) < 0.2,
      f"native={res['native']}，期望 {22261 / 1024.0:.1f}")
check("老格式能解析出 pss（TOTAL 行）",
      res['pss'] is not None and abs(res['pss'] - 70309 / 1024.0) < 0.2,
      f"pss={res['pss']}，期望 {70309 / 1024.0:.1f}")

# Android 8+ 格式不能被改坏
NEW_FORMAT = """App Summary
                       Pss(KB)                        Rss(KB)
                        ------                        ------
           Java Heap:    45678                        78901
         Native Heap:    23456                        34567
                TOTAL:   70309                       123456
"""
res2 = P.parse_meminfo(NEW_FORMAT)
print(f"  Android 8+ 格式: {res2}")
check("Android 8+ 的 Java Heap 仍能解析",
      res2['java'] is not None and abs(res2['java'] - 45678 / 1024.0) < 0.2,
      f"java={res2['java']}")
check("Android 8+ 的 Native Heap 仍能解析",
      res2['native'] is not None and abs(res2['native'] - 23456 / 1024.0) < 0.2,
      f"native={res2['native']}")
check("Android 8+ 的 TOTAL 仍能解析",
      res2['pss'] is not None and abs(res2['pss'] - 70309 / 1024.0) < 0.2,
      f"pss={res2['pss']}")

# 边界：空输入不能崩
res3 = P.parse_meminfo('')
check("空输入返回全 None（不崩）",
      res3['pss'] is None and res3['java'] is None and res3['native'] is None)
res4 = P.parse_meminfo(None)
check("None 输入返回全 None（不崩）",
      res4['pss'] is None and res4['java'] is None and res4['native'] is None)

# ====================================================================== #
# 2. 图表：X 轴时间标签 / Y 轴单位 / 数据点 / 空数据原因
# ====================================================================== #
print()
print("=== 2. LineChart 的可读性 ===")

import inspect
from modules import perf_chart as C

_chart_src = inspect.getsource(C.LineChart)
_base_src = inspect.getsource(C.ChartBase)

check("LineChart 有 x_labels（时间标签）字段",
      'x_labels' in inspect.getsource(C.LineChart.__init__))
check("有画 X 轴刻度的方法", '_draw_x_axis' in _chart_src)
check("有画空数据提示的方法", '_draw_empty' in _chart_src)
check("有 y_unit（Y 轴单位）字段", 'y_unit' in inspect.getsource(C.LineChart.__init__))
check("X 轴标签用真实时间戳而不是只有序号",
      'self.x_labels.get(tv)' in _chart_src)
check("空数据时能给出原因说明",
      'empty_hint' in _chart_src)
check("数据点标记（oval）被画出来",
      'create_oval' in _chart_src)

# Y 轴单位只标在顶部（原来 0 和 4 都标 → 左下角重叠）
_y_unit_lines = [ln.strip() for ln in _chart_src.split('\n')
                 if 'self.y_unit' in ln and 'if' in ln]
check("Y 轴单位只标在顶部刻度（避免左下角重叠）",
      any('i == 4' in ln for ln in _y_unit_lines),
      str(_y_unit_lines[:2]))

# Y 轴标题不能放在绘图区上方（会与顶部刻度/图例重叠）
check("Y 轴标题不在绘图区上方（避免与刻度重叠）",
      "y0 - 8, text=self.y_label" not in _chart_src,
      "y_label 在 y0-8 → 与顶部刻度、图例挤在一起")

# ====================================================================== #
# 3. 报告窗口：时间标签 / 单位 / 卡片 / 空数据原因
# ====================================================================== #
print()
print("=== 3. 报告窗口 ===")

_rep_src = io.open(os.path.join(os.path.dirname(_ROOT), 'modules',
                                'perf_report.py'), encoding='utf-8').read()

check("趋势图收集时间标签（从 history 的 ts）",
      "row.get('ts')" in _rep_src)
check("趋势图设置 x_labels", 'self.trend_chart.x_labels = x_labels' in _rep_src)
check("趋势图设置 y_unit", 'self.trend_chart.y_unit' in _rep_src)
check("有指标单位映射", 'def _metric_unit' in _rep_src)
check("CPU 的单位是 %", "'%'" in _rep_src)
check("内存类指标单位是 MB", "'MB'" in _rep_src)
check("有「为什么没数据」的方法", 'def _empty_reason' in _rep_src)
check("区分「设备不支持」与「没采到」",
      'unsupported' in _rep_src and '需要指定包名' in _rep_src)

# 指标卡：必须有 java / native
check("指标卡包含 Java Heap", "('java', 'Java Heap'" in _rep_src)
check("指标卡包含 Native Heap", "('native', 'Native Heap'" in _rep_src)
check("没数据的卡片显示原因而非光一个 '--'",
      "'无数据'" in _rep_src)

# 趋势页的指标切换按钮也要有 java / native
check("趋势页有 Java Heap 切换按钮",
      "('java', 'Java Heap')" in _rep_src)
check("趋势页有 Native Heap 切换按钮",
      "('native', 'Native Heap')" in _rep_src)

# 悬停提示带时间
check("悬停提示显示时间（不是只有序号）",
      'self.trend_chart.x_labels.get(int(info' in _rep_src)

# ====================================================================== #
# 4. 采集层：fps/jank 缺失要能说清原因
# ====================================================================== #
print()
print("=== 4. 采集层 ===")

_col_src = io.open(os.path.join(os.path.dirname(_ROOT), 'modules',
                                'perf_collector.py'), encoding='utf-8').read()

check("内存采集走 dumpsys meminfo <pkg>",
      'dumpsys meminfo' in _col_src)
check("system 模式用 /proc/meminfo（整机，无进程级 java/native）",
      'parse_system_meminfo' in _col_src)
check("有独立的内存采集线程",
      'def _mem_worker' in _col_src)
check("有独立的 framestats 采集线程",
      'def _framestats_worker' in _col_src)

# gfxinfo 解析：老设备没有统计段时必须返回 None（而不是编数）
_gfx = P.parse_gfxinfo("""Applications Graphics Acceleration Info:
Uptime: 241085464 Realtime: 241085464

** Graphics info for pid 9469 [com.gitvdemokonka.video] **

Recent DisplayList operations
DrawPath
""")
check("gfxinfo 无统计段时 total_frames 为 None",
      _gfx.get('total_frames') is None, str(_gfx.get('total_frames')))
check("gfxinfo 无统计段时 janky_pct 为 None",
      _gfx.get('janky_pct') is None, str(_gfx.get('janky_pct')))

print()
print("=" * 68)
if FAILED:
    print(f"HAS FAILURES —— {len(FAILED)} 项失败：")
    for f in FAILED:
        print(f"  - {f}")
    print("=" * 68)
    sys.exit(1)
else:
    print(f"ALL PASS （{PASSED} 项）")
    print("=" * 68)
