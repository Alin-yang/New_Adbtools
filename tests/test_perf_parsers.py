"""性能监控解析器的真机格式兼容性测试

用各 Android 版本的**真实输出格式**做样本，验证解析器不会静默算错。
（这些样本来自 AOSP 的 dumpsys/gfxinfo 输出格式，字段名与真机一致。）

用法: python tests/test_perf_parsers.py
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.performance_monitor import PerfParsers

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False


# ---------------------------------------------------------------- 样本
MEMINFO_A10 = """
Total PSS by process:
  23456  com.example.app

App Summary
                       Pss(KB)                        Rss(KB)
                        ------                        ------
           Java Heap:   12345                          23456
         Native Heap:    6789                          12345
                Code:    1234                           2345
             Stack:      100                            200
            Graphics:   4567                           4567
        Private Other:   7890                           7890
             System:    1234                           1234

           Total PSS:   45678                         78901
"""

MEMINFO_A9 = """
Applications Memory Usage (in Kilobytes):
Uptime: 1234 Realtime: 5678

** MEMINFO in pid 12345 [com.example.app] **
                   Pss  Private  Private  SwapPss     Heap     Heap     Heap
                 Total    Dirty    Clean    Dirty     Size    Alloc     Free
                ------   ------   ------   ------   ------   ------   ------
  Native Heap    12345     6789        0        0    23456    12345     4567
  Dalvik Heap     2345     1234      567        0    12345     6789     2345
 App Summary
                       Pss(KB)
                        ------
           Java Heap:    2345
         Native Heap:   12345
                 Code:    1234
              Graphics:   4567
           Total PSS:   45678
"""

MEMINFO_A7_TABLE = """
Applications Memory Usage (in Kilobytes):
Uptime: 1234 Realtime: 5678

** MEMINFO in pid 12345 [com.example.app] **
                   Pss  Private  Private  SwapPss     Heap     Heap     Heap
                 Total    Dirty    Clean    Dirty     Size    Alloc     Free
                ------   ------   ------   ------   ------   ------   ------
  Native Heap    12345     6789        0        0    23456    12345     4567
  Dalvik Heap     2345     1234      567        0    12345     6789     2345
  Other:
    mmap:        1234     1234        0        0    23456    12345     4567
  TOTAL        123456    67890     4567       890    123456   67890    45678
"""

def make_stat_line(pid, comm, utime, stime):
    """按 /proc/<pid>/stat 的内核字段布局构造一行（避免手写样本数错字段）

    字段序（1-based）：pid(1) comm(2) state(3) ppid(4) pgrp(5) session(6)
    tty_nr(7) tpgid(8) flags(9) minflt(10) cminflt(11) majflt(12) cmajflt(13)
    utime(14) stime(15) cutime(16) cstime(17) ...
    → 去掉前两个字段后，utime 是 rest[11]、stime 是 rest[12]
    """
    fields = ['0'] * 52
    fields[0] = str(pid)
    fields[1] = f'({comm})'
    fields[2] = 'S'
    fields[3] = '1200'      # ppid
    fields[4] = str(pid)    # pgrp
    fields[5] = str(pid)    # session
    fields[6] = '0'         # tty_nr
    fields[7] = '-1'        # tpgid
    fields[8] = '4194560'   # flags
    fields[9] = '12345'     # minflt
    fields[10] = '0'        # cminflt
    fields[11] = '45'       # majflt
    fields[12] = '0'        # cmajflt
    fields[13] = str(utime)  # utime  ← rest[11]
    fields[14] = str(stime)  # stime  ← rest[12]
    return ' '.join(fields)


PROC_STAT = "\n".join([
    make_stat_line(1234, "com.example.app", 300, 400),
    make_stat_line(1235, "RenderThread", 10, 20),
]) + "\n"

PROC_STATUS = """Name:	com.example.app
State:	S (sleeping)
Tgid:	1234
VmRSS:	  123456 kB
VmSize:	  234567 kB
"""

GFXINFO_A10 = """Applications Graphics Acceleration Info:
Uptime: 12345 Realtime: 67890

** Graphics info for pid 1234 [com.example.app] **

Stats since: 1234567890ns
Total frames rendered: 5432
Janky frames: 234 (4.30%)
50th percentile: 8ms
90th percentile: 20ms
95th percentile: 30ms
99th percentile: 60ms
Number Missed Vsync: 12
"""

GFXINFO_OLD = """** Graphics info for pid 1234 [com.example.app] **
Total frames rendered: 1234
"""

GFXINFO_NO_JANKY = """** Graphics info for pid 1234 [com.example.app] **
Total frames rendered: 5432
50th percentile: 8ms
"""

CPUINFO = """Load: 1.2 1.1 1.0
  15% 1234/com.example.app: 10% user + 5% kernel
   3% 2345/com.other.app: 2% user + 1% kernel
"""


print("=" * 72)
print("=== 1. dumpsys meminfo：PSS 在各 Android 版本都要能解析出来 ===")
for label, sample in (("Android 10+ (Total PSS: + Rss 列)", MEMINFO_A10),
                       ("Android 9  (Total PSS: 单列)", MEMINFO_A9),
                       ("Android 7  (表格 TOTAL 行)", MEMINFO_A7_TABLE)):
    r = PerfParsers.parse_meminfo(sample)
    check(f"{label} -> PSS 有值", r['pss'] is not None, r)
    expect = 120.6 if "Android 7" in label else 44.6
    check(f"{label} -> PSS 数值正确", r['pss'] == expect, r['pss'])

check("Android 10+ 取 Pss 列(与 PSS 同口径)", PerfParsers.parse_meminfo(MEMINFO_A10)['java'] == 12.1,
      PerfParsers.parse_meminfo(MEMINFO_A10))
check("空输出不炸", PerfParsers.parse_meminfo("") == {'pss': None, 'java': None, 'native': None})
check("无 PSS 字段返回 None（降级而非算错）",
      PerfParsers.parse_meminfo("Total PSS by process:\n  1  x")['pss'] is None)

print()
print("=" * 72)
print("=== 2. /proc/<pid>/stat 解析 ===")
ticks = PerfParsers.parse_proc_ticks(PROC_STAT)
check("解析出 2 个线程", len(ticks) == 2, ticks)
check("主线程 ticks = utime+stime = 300+400 = 700", ticks.get(1234, (None, None))[1] == 700, ticks.get(1234))
check("RenderThread ticks = 10+20 = 30", ticks.get(1235, (None, None))[1] == 30, ticks.get(1235))
check("线程名正确", ticks.get(1235, ('', 0))[0] == "RenderThread", ticks.get(1235))

# comm 里含空格和括号的情况
weird = make_stat_line(999, "my (weird) name", 50, 60)
t2 = PerfParsers.parse_proc_ticks(weird)
check("线程名含空格/括号时仍能解析", 999 in t2, t2)
check("含括号时 ticks 正确 (50+60=110)", t2.get(999, (None, None))[1] == 110, t2.get(999))

check("空行不炸", PerfParsers.parse_proc_ticks("") == {})
check("残缺行返回 None", PerfParsers.parse_proc_stat_line("123 (x)") is None)

print()
print("=" * 72)
print("=== 3. /proc/<pid>/status 的 VmRSS ===")
ticks_map, rss = PerfParsers.parse_proc_snapshot(PROC_STAT + PROC_STATUS)
check("VmRSS 解析为 MB", rss == 120.6, rss)
check("同时解析出 ticks", len(ticks_map) == 2, ticks_map)
check("无 status 段时 rss 为 None",
      PerfParsers.parse_proc_snapshot(PROC_STAT)[1] is None)

print()
print("=" * 72)
print("=== 4. gfxinfo：帧数与卡顿率 ===")
check("Total frames rendered 解析", PerfParsers.parse_total_frames(GFXINFO_A10) == 5432)
check("老格式 Frames rendered 解析", PerfParsers.parse_total_frames(GFXINFO_OLD) == 1234)
check("Janky frames 百分比解析", abs(PerfParsers.parse_janky_percent(GFXINFO_A10) - 4.30) < 0.01,
      PerfParsers.parse_janky_percent(GFXINFO_A10))
check("无 Janky 字段时返回 None（降级）",
      PerfParsers.parse_janky_percent(GFXINFO_NO_JANKY) is None)
check("空输出不炸", PerfParsers.parse_total_frames("") is None)

print()
print("=" * 72)
print("=== 5. dumpsys cpuinfo 多进程累加 ===")
v = PerfParsers.parse_cpuinfo_line(CPUINFO, "com.example.app")
check("解析出该包的 CPU%", v == 15.0, v)
check("不存在的包返回 None", PerfParsers.parse_cpuinfo_line(CPUINFO, "com.nope") is None)

print()
print("=" * 72)
print("=== 6. /proc/stat 与 CLK_TCK ===")
check("CLK_TCK 正常", PerfParsers.parse_clk_tck("100") == 100)
check("CLK_TCK 异常时默认 100", PerfParsers.parse_clk_tck("") == 100)
check("/proc/stat 总 jiffies", PerfParsers.parse_proc_stat_cpu("cpu  100 20 30 400 0 0 0 0") == 550,
      PerfParsers.parse_proc_stat_cpu("cpu  100 20 30 400 0 0 0 0"))
check("/proc/stat 空返回 None", PerfParsers.parse_proc_stat_cpu("") is None)

print()
print("=" * 72)
print("=== 7. pidof 多 pid ===")
check("取第一个 pid", PerfParsers.parse_pidof("1234 5678") == 1234)
check("无 pid 返回 None", PerfParsers.parse_pidof("") is None)

print()
print("=" * 72)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 72)
sys.exit(0 if ok else 1)
