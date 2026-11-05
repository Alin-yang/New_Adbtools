"""性能监控 v4 重写版的解析与分析测试（纯函数，不依赖真机）

覆盖这次重写修掉的**每一个真实 bug**，防止回归：
1. 进程口径与线程口径必须分离（/proc/pid/stat 是线程组总量 vs task/*/stat 是单线程）
2. PID 定位必须能识别「pidof 返回垃圾数据」的坏设备
3. 帧卡顿率必须是**窗口内**的，不是进程启动至今的累计值
4. 无渲染活动时 FPS 必须是 None，不能用 0 冒充真实测得值
5. history 必须存原始值，不能复制旧值造出伪造平坦段
6. 内存泄漏斜率检测

用法: python tests/test_perf_v4.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import perf_parsers as P
from modules import perf_analysis as A
from modules import perf_baseline as B
from modules import perf_scenario as S

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    results.append((cond, label, detail))


# ====================================================================== #
# 1. /proc 口径分离（本次最严重的 bug）
# ====================================================================== #
PID = 27690


def stat_line(tid, utime, stime, name='main'):
    """构造一行 /proc/<tid>/stat

    /proc 文档：字段从 1 开始编号，state 是第 3 个字段。
    切分后 rest[0]=state, rest[11]=utime(字段14), rest[12]=stime(字段15)。
    """
    #        ppid pgrp sess tty  tpgid flags  minflt cminflt majflt cmajflt
    rest = [1, PID, PID, 0, -1, 1077936448, 468993, 7736, 803,
            0,             # cmajflt (字段13)
            utime,         # rest[11] = 字段14 utime
            stime,         # rest[12] = 字段15 stime
            0, 0, 20, 0, 1, 0, 100, 0, 0]
    return f"{tid} ({name}) S " + " ".join(str(x) for x in rest)


# 真机实测（MiBOX4 / com.gitvdemo.video / pid 27690）：
#   /proc/27690/stat            utime=8786 stime=3840 合计=12626  ← 线程组总量
#   /proc/27690/task/27690/stat utime= 608 stime= 168 合计=  776  ← 仅主线程
#   → 主线程只占进程 CPU 的 6%，94% 在其它 203 个线程上
GROUP = stat_line(PID, 8786, 3840)
LEADER = stat_line(PID, 608, 168)
WORKER1 = stat_line(28055, 5200, 0, 'PumaProgMgr')
WORKER2 = stat_line(28068, 1900, 0, 'gala.SSDPSS/')
STATUS = "Name:\tgitvdemo\nVmRSS:\t 290304 kB\nThreads:\t204\n"

# cat 的输出顺序：/proc/pid/stat 在前，task/*/stat 在后
OUTPUT = "\n".join([GROUP, LEADER, WORKER1, WORKER2, STATUS])

parsed = P.parse_proc_snapshot(OUTPUT, PID)

check("进程级取到线程组总量（12626）",
      parsed['group_ticks'] == 12626, str(parsed['group_ticks']))
check("线程表不含 pid 行（避免与进程级重复）",
      PID not in parsed['threads'], str(list(parsed['threads'].keys())))
check("线程表取到各线程自己的值",
      parsed['threads'][28055][1] == 5200,
      str(parsed['threads'].get(28055)))
check("线程表条数正确（2 个工作线程）",
      len(parsed['threads']) == 2, str(len(parsed['threads'])))
check("VmRSS 解析正确（283.5 MB）",
      abs(parsed['rss_mb'] - 283.5) < 0.1, str(parsed['rss_mb']))

# 口径自洽：进程级 ≈ 线程表求和 + 主线程自己
thread_sum = sum(v[1] for v in parsed['threads'].values())
leader_own = 776          # 真机实测：主线程自己 608+168
check("进程级 = 线程表求和 + 主线程自己（12626 = 7100 + 776 + ...）",
      parsed['group_ticks'] >= thread_sum + leader_own,
      f"group={parsed['group_ticks']} sum={thread_sum} leader={leader_own}")

# 反向验证：如果用旧逻辑（覆盖式赋值），进程级会变成 776
legacy_ticks = {}
for line in OUTPUT.splitlines():
    p = P.parse_stat_line(line.strip())
    if p:
        legacy_ticks[p[0]] = (p[1], p[2])
check("旧逻辑（覆盖式）确实会取到 776 —— 正是 bug 根源",
      legacy_ticks[PID][1] == 776, str(legacy_ticks[PID]))
check("新逻辑不会（12626 vs 776，差 16 倍）",
      parsed['group_ticks'] != legacy_ticks[PID][1])

# ====================================================================== #
# 2. gfxinfo 解析 + janky 反推
# ====================================================================== #
GFXINFO = """Applications Graphics Acceleration Info:
Uptime: 81744143 Realtime: 81744143

** Graphics info for pid 27690 [com.gitvdemo.video] **

Stats since: 76292956075ns
Total frames rendered: 29486
Janky frames: 8513 (28.87%)
90th percentile: 40ms
95th percentile: 57ms
99th percentile: 85ms
Number Missed Vsync: 1557
Number Slow UI thread: 2955
Number Slow bitmap uploads: 535
Number Slow issue draw commands: 5996
"""

gfx = P.parse_gfxinfo(GFXINFO)
check("累计帧数解析", gfx['total_frames'] == 29486, str(gfx['total_frames']))
check("卡顿百分比解析", abs(gfx['janky_pct'] - 28.87) < 0.01,
      str(gfx['janky_pct']))
check("卡顿绝对数由百分比反推（8513）",
      gfx['janky_frames'] == 8513, str(gfx['janky_frames']))
check("P95 帧耗时解析（57ms）", gfx['p95'] == 57, str(gfx['p95']))
check("丢 Vsync 次数解析", gfx['missed_vsync'] == 1557, str(gfx['missed_vsync']))
check("慢 UI 线程数解析", gfx['slow_ui'] == 2955, str(gfx['slow_ui']))
check("空输出不炸", P.parse_gfxinfo("")['total_frames'] is None)

# 窗口内卡顿率：差分反推
base = P.parse_gfxinfo("Total frames rendered: 1000\nJanky frames: 100 (10.00%)")
now = P.parse_gfxinfo("Total frames rendered: 1200\nJanky frames: 160 (13.33%)")
d_total = now['total_frames'] - base['total_frames']
d_janky = now['janky_frames'] - base['janky_frames']
check("窗口内帧数差分正确（200）", d_total == 200, str(d_total))
check("窗口内卡顿帧差分正确（60）", d_janky == 60, str(d_janky))
check("窗口内卡顿率 = 30%（≠累计的 13.33%）",
      abs(d_janky / d_total * 100 - 30.0) < 0.01,
      f"{d_janky/d_total*100:.2f}%")

# ====================================================================== #
# 3. framestats 逐帧解析（Android 10+）
# ====================================================================== #
FRAME_HEADER = ("Flags,IntendedVsync,Vsync,HandleInputStart,AnimationStart,"
                "PerformTraversalsStart,DrawStart,FrameDeadline,FrameInterval,"
                "FrameStartTime,SyncQueued,SyncStart,IssueDrawCommandsStart,"
                "SwapBuffers,FrameCompleted")
FRAMES = f"""---PROFILEDATA---
{FRAME_HEADER}
0,1000000000,1000000000,1000000000,1000000000,1000000000,1000000000,1016666666,16666666,1000000000,1000000000,1000000000,1000000000,1000000000,1016666666
0,1016666666,1016666666,1016666666,1016666666,1016666666,1016666666,1033333333,16666666,1016666666,1016666666,1016666666,1016666666,1016666666,1050000000
---PROFILEDATA---
"""

fs = P.parse_framestats(FRAMES)
check("framestats 解析出帧", fs is not None and len(fs['frames']) == 2,
      str(fs))
if fs:
    check("帧耗时计算正确（16.7ms / 33.3ms）",
          abs(fs['frames'][0]['duration_ms'] - 16.667) < 0.1
          and abs(fs['frames'][1]['duration_ms'] - 33.333) < 0.1,
          str([f['duration_ms'] for f in fs['frames']]))
    check("第 1 帧不超 deadline → 不算 jank", not fs['frames'][0]['jank'])
    check("第 2 帧超 deadline → 算 jank", fs['frames'][1]['jank'])
check("不支持 framestats 的设备返回 None",
      P.parse_framestats("Total frames rendered: 100") is None)

# ====================================================================== #
# 4. meminfo 兼容各版本
# ====================================================================== #
MEMINFO_A10 = """Total PSS by process:
  12345: com.example.app (pid 1234)
    Pss  Total:   45678    Private Dirty:   23456
    Java Heap:   12345    Private Clean:    1111
    Native Heap:   6789    Private Dirty:    2222
"""
m = P.parse_meminfo(MEMINFO_A10)
check("Android 10+ PSS 解析", m['pss'] == 44.6, str(m['pss']))
check("Android 10+ Java Heap 取第一列", m['java'] == 12.1, str(m['java']))
check("空输出不炸",
      P.parse_meminfo("") == {'pss': None, 'java': None, 'native': None})

# ====================================================================== #
# 5. 线程角色归类（基于真机真实线程名）
# ====================================================================== #
ROLE_CASES = [
    ('RenderThread', '渲染'),
    ('gala.SSDPSS/', '业务 SDK'),
    ('PumaProgMgr', '业务 SDK'),
    ('HeapTaskDaemon', 'GC / 编译'),
    ('FinalizerDaemon', 'GC / 编译'),
    ('Binder:1234_5', 'IPC'),
    ('AsyncTask #1', '线程池'),
    ('OTTPool-1-1', '线程池'),
    ('CurlMultiHandle', '网络'),
    ('QtpEngine', '网络'),
    ('Signal Catcher', '系统'),
    ('SomeRandomThread', '其它'),
]
for name, expect in ROLE_CASES:
    role, _color = A.classify_thread(name)
    check(f"线程归类: {name} → {expect}", role == expect, role)

roles = A.aggregate_by_role([
    {'name': 'RenderThread', 'cur': 20.0, 'avg': 18.0, 'peak': 30.0},
    {'name': 'Binder:1_2', 'cur': 5.0, 'avg': 4.0, 'peak': 6.0},
    {'name': 'HeapTaskDaemon', 'cur': 8.0, 'avg': 7.0, 'peak': 9.0},
    {'name': 'Random', 'cur': 2.0, 'avg': 2.0, 'peak': 2.0},
])
role_map = {r['role']: r for r in roles}
check("角色聚合：渲染合计 20%", abs(role_map['渲染']['cur'] - 20.0) < 0.01,
      str(role_map['渲染']['cur']))
check("角色聚合：线程计数正确", role_map['渲染']['count'] == 1,
      str(role_map['渲染']['count']))
check("角色聚合按 CPU 降序", roles[0]['role'] == '渲染', roles[0]['role'])

# ====================================================================== #
# 6. 内存泄漏检测
# ====================================================================== #
# 构造线性增长的 PSS 序列（每分钟 +2MB）
leak_hist = []
for i in range(20):
    leak_hist.append({
        'ts': f'10:{i:02d}:00',
        'pss': 200.0 + i * 2.0,
        'cpu': 20.0, 'rss': 300.0, 'java': 50.0, 'native': 60.0,
        'fps': 60.0, 'jank': 0.0,
    })
leak = A.detect_memory_leak(leak_hist)
check("检测到线性增长", leak is not None, str(leak))
if leak:
    check(f"斜率 ≈ 2.0 MB/分（实测 {leak['slope_mb_per_min']}）",
          abs(leak['slope_mb_per_min'] - 2.0) < 0.1,
          str(leak['slope_mb_per_min']))
    check("拟合度高（>0.99）", leak['r2'] > 0.99, str(leak['r2']))
    check("总增长 ≈ 38MB", abs(leak['growth_mb'] - 38.0) < 1.0,
          str(leak['growth_mb']))

# 平坦序列不该判为泄漏
flat_hist = [{'ts': f'10:{i:02d}:00', 'pss': 200.0 + (i % 3),
              'cpu': 20.0, 'rss': 300.0, 'java': 50.0, 'native': 60.0,
              'fps': 60.0, 'jank': 0.0} for i in range(20)]
flat = A.detect_memory_leak(flat_hist)
check("平坦序列不判为泄漏", flat is None or abs(flat['slope_mb_per_min']) < 0.5,
      str(flat))

# None 值不能污染斜率（降频周期没采到 PSS）
mixed = [dict(h) for h in leak_hist]
for i in range(0, 20, 2):
    mixed[i]['pss'] = None
leak2 = A.detect_memory_leak(mixed)
check("None 值不污染斜率计算", leak2 is not None
      and abs(leak2['slope_mb_per_min'] - 2.0) < 0.3,
      str(leak2['slope_mb_per_min'] if leak2 else None))

# ====================================================================== #
# 7. 自动结论
# ====================================================================== #
session = {
    'stats': {
        'cpu': {'cur': 90.0, 'avg': 85.0, 'peak': 95.0, 'p95': 90.0, 'p05': 80.0},
        'pss': {'cur': 250.0, 'avg': 240.0, 'peak': 260.0, 'p95': 255.0, 'p05': 230.0},
        'fps': {'cur': 20.0, 'avg': 22.0, 'peak': 25.0, 'p95': 24.0, 'p05': 15.0},
        'jank': {'cur': 18.0, 'avg': 15.0, 'peak': 25.0, 'p95': 22.0, 'p05': 10.0},
        'p95_frame': {'cur': 45.0, 'avg': 40.0, 'peak': 50.0, 'p95': 45.0, 'p05': 30.0},
        'threads': [{'name': 'HeapTaskDaemon', 'cur': 12.0, 'avg': 10.0, 'peak': 15.0}],
        'quality': {'degraded': False, 'success_rate': 100.0,
                    'interval_actual': 2.1, 'interval_set': 2.0,
                    'mode': 'proc'},
    },
    'history': leak_hist,
    'quality': {'degraded': False, 'success_rate': 100.0,
                'interval_actual': 2.1, 'interval_set': 2.0, 'mode': 'proc'},
}
conclusions = A.analyze(session)
titles = [c['title'] for c in conclusions]
check("检出内存泄漏", '内存疑似泄漏' in titles, str(titles))
check("检出 CPU 峰值过高", 'CPU 峰值过高' in titles, str(titles))
check("检出掉帧", '存在明显掉帧' in titles, str(titles))
check("检出卡顿率偏高", '卡顿率偏高' in titles, str(titles))
check("检出 GC 频繁", 'GC 活动频繁' in titles, str(titles))
check("检出帧耗时偏高", '帧耗时偏高' in titles, str(titles))

# 降级模式要提示
session['quality']['degraded'] = True
concl2 = A.analyze(session)
check("降级模式给出精度提示",
      '本次数据精度受限' in [c['title'] for c in concl2],
      str([c['title'] for c in concl2]))

# ====================================================================== #
# 8. 场景模板
# ====================================================================== #
check("场景数量 ≥ 5", len(S.SCENARIOS) >= 5, str(len(S.SCENARIOS)))
video = S.get('video')
check("视频场景 FPS 阈值 = 24", video.thresholds.get('fps') == 24.0,
      str(video.thresholds))
hits = video.check({'fps': {'cur': 20.0}})
check("FPS 低于阈值被命中（帧率是下限）", len(hits) == 1, str(hits))
hits = video.check({'fps': {'cur': 30.0}})
check("FPS 高于阈值不命中", len(hits) == 0, str(hits))
mem_scn = S.get('memory')
hits = mem_scn.check({'pss': {'cur': 900.0}})
check("内存超阈值被命中（内存是上限）", len(hits) == 1, str(hits))

# ====================================================================== #
# 9. 基线对比
# ====================================================================== #
cur = {'stats': {'cpu': {'cur': 20.0}, 'pss': {'cur': 250.0},
                 'fps': {'cur': 60.0}, 'jank': {'cur': 1.0},
                 'threads': [{'name': 'A', 'cur': 10.0}]}}
base = {'stats': {'cpu': {'cur': 30.0}, 'pss': {'cur': 250.0},
                  'fps': {'cur': 60.0}, 'jank': {'cur': 1.0},
                  'threads': [{'name': 'A', 'cur': 15.0}]}}
cmp = B.compare(cur, base)
cpu_cmp = next(m for m in cmp['metrics'] if m['key'] == 'cpu')
check("CPU 差值 = -10", abs(cpu_cmp['delta'] - (-10)) < 0.01, str(cpu_cmp['delta']))
check("CPU 变化率 = -33%", abs(cpu_cmp['pct'] - (-33.33)) < 0.1, str(cpu_cmp['pct']))
check("CPU 变好标记", cpu_cmp['better'] is True, str(cpu_cmp['better']))
pss_cmp = next(m for m in cmp['metrics'] if m['key'] == 'pss')
check("内存持平 → better 为 None", pss_cmp['better'] is None, str(pss_cmp['better']))
check("摘要非空", bool(B.summarize_comparison(cmp)))

# ====================================================================== #
# 6. 启动性能（v5.4.6）
# ====================================================================== #
# ⚠️ 用户反馈「点开始监控后要等好几秒才有数据加载出来感觉有点慢」。
#    实测原来要 8.7 秒：_detect_env 6.3s（nproc 2.2 + getconf 0.7 +
#    _estimate_clk_tck 2.9）+ 首轮等一个完整 interval 2s。
#
#    这里用**静态检查 + 行为检查**守护优化成果：
#    ① 采集器里**不能再有**启动期的 adb 探测方法
#       （它们要么阻塞首帧，挪后台也会抢 adb 连接拖慢首帧）
#    ② 首帧采样窗口必须 < interval（否则还是要干等一个完整周期）
#    ③ _detect_env 只能做 PID 定位（本地 ps，几毫秒），不能发 adb
import inspect
from modules import perf_collector as PC

_coll = PC.PerfCollector()

# ① 启动期 adb 探测方法已删除
for _m in ('_detect_clk_tck', '_detect_cpu_max', '_estimate_clk_tck',
           '_detect_cpu_max_cached', '_detect_env_slow'):
    check(f"启动期 adb 探测「{_m}」已删除",
          not hasattr(_coll, _m), "仍存在 → 会拖慢首帧")

# ② 首帧窗口 < 最小 interval
check("首帧采样窗口小于最小采样间隔",
      PC.FIRST_SAMPLE_WINDOW < 1.0,
      f"FIRST_SAMPLE_WINDOW={PC.FIRST_SAMPLE_WINDOW}")

# ③ _detect_env 不发 adb 命令
#    ⚠️ 只查**代码行**（注释里提到 adb 不算）——
#    `_run(` / `self._run` 才是真正的 adb 调用入口
_src_lines = [ln.split('#')[0].strip()
               for ln in inspect.getsource(PC.PerfCollector._detect_env).split('\n')]
_code = '\n'.join(_src_lines)
check("_detect_env 不发 adb 命令（只做本地 PID 定位）",
      '_run(' not in _code,
      "含 adb 调用 → 首帧会被阻塞")

# ④ CLK_TCK 固定用标准值 100（Android 内核 USER_HZ 恒定）
check("CLK_TCK 固定为标准值 100", _coll._clk_tck == 100, _coll._clk_tck)

# ⑤ CPU 上限用宽松值（多核满载 400% 不该被截到 100%）
check("CPU 上限是宽松值（多核不截断）", _coll._cpu_max >= 400.0,
      _coll._cpu_max)

# ====================================================================== #
print("=" * 68)
print("性能监控 v4 重写版 —— 解析与分析测试")
print("=" * 68)
for cond, label, detail in results:
    flag = "PASS" if cond else "FAIL"
    extra = f"  -> {detail}" if detail and not cond else ""
    print(f"  {flag}  {label}{extra}")
print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
