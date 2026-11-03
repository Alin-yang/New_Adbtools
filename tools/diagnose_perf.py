"""性能监控真机诊断脚本（v5.0 新模块版）

在连接了 Android 设备的情况下运行，把各采集命令的**原始输出**打印出来，
用于验证解析器在真机上的行为（尤其是 PSS / 卡顿率 / CPU% 这几个指标）。

⚠️ v5.0 重写后，本脚本已改为调用 `modules/perf_parsers.py` 的新 API。
   旧版引用的 `modules/performance_monitor.py` 已删除。

用法：
    D:\\tool\\python\\python.exe tools\\diagnose_perf.py [包名] [设备]
    D:\\tool\\python\\python.exe tools\\diagnose_perf.py com.example.app
    D:\\tool\\python\\python.exe tools\\diagnose_perf.py com.example.app 192.168.0.3:5555

不带包名时只做不需要包名的检查（系统整体模式）。
输出直接贴回来即可。
"""
import os
import re
import subprocess
import sys

# Windows 控制台默认 GBK，输出中文会乱码 —— 强制 UTF-8 + 替换非法字符
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import perf_parsers as P
from modules.perf_locator import ProcessLocator


def sh(cmd: str, timeout: int = 15) -> tuple:
    """跑一条 adb 命令，返回 (输出, 是否成功)"""
    try:
        r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        out = r.stdout.decode('utf-8', errors='replace')
        return out, r.returncode == 0
    except subprocess.TimeoutExpired:
        return "<超时>", False
    except Exception as e:
        return f"<异常 {e}>", False


def section(title: str):
    print()
    print("=" * 74)
    print(f"  {title}")
    print("=" * 74)


def show(name: str, out: str, ok: bool, limit: int = 1800):
    print(f"\n--- {name}  [{'OK' if ok else 'FAIL'}] ---")
    text = out if len(out) <= limit else out[:limit] + f"\n... (共 {len(out)} 字符，已截断)"
    print(text.rstrip())


def adb_prefix(device):
    """有设备时统一加 -s"""
    return f"adb -s {device}" if device else "adb"


def main():
    pkg = sys.argv[1] if len(sys.argv) > 1 else None
    device = sys.argv[2] if len(sys.argv) > 2 else None
    A = adb_prefix(device)

    section("环境")
    out, ok = sh("adb version")
    if not ok and ("不是内部" in out or "not recognized" in out.lower()):
        print("\n  [!] 找不到 adb！请确认 adb 在 PATH 里，或用完整路径运行本脚本。")
        print("      （ADB Tool 本身也依赖系统 PATH 里的 adb）")
        return
    show("adb version", out, ok, 300)
    out, ok = sh("adb devices -l")
    show("adb devices -l", out, ok, 800)

    out, ok = sh(f"{A} shell getprop ro.build.version.release")
    print(f"\n  Android 版本: {out.strip()}")
    out, ok = sh(f"{A} shell getprop ro.build.version.sdk")
    print(f"  SDK         : {out.strip()}")
    out, ok = sh(f"{A} shell getconf CLK_TCK")
    m = re.search(r'(\d+)', out or '')
    print(f"  CLK_TCK     : {out.strip()}  (解析={m.group(1) if m else None})")
    print("  ↑ 注意：getconf 在部分设备（实测 Android 6）不存在，此时采集器"
          "回退到标准值 100（Android 内核 USER_HZ 常量）")
    out, ok = sh(f"{A} shell nproc")
    m = re.search(r'(\d+)', out or '')
    print(f"  CPU 核数    : {out.strip()}  (解析={m.group(1) if m else None})")
    if not m:
        out2, _ = sh(f"{A} shell cat /proc/cpuinfo")
        n = len([l for l in (out2 or '').splitlines() if l.startswith('processor')])
        print(f"  → nproc 不可用，回退 /proc/cpuinfo 数 processor 行: {n}")
    if device:
        print(f"  目标设备    : {device}")

    if pkg:
        section(f"应用 {pkg} —— PID 定位")
        out, ok = sh(f"{A} shell pidof {pkg}", timeout=10)
        show(f"pidof {pkg}", out, ok, 400)
        # ⚠️ 用新的多级回退定位器，而不是直接取 pidof 的第一个数字
        #    （实测某些设备 pidof 忽略包名参数，返回全部 PID → 取到 init）
        pids = ProcessLocator(device).find_pids(pkg)
        print(f"\n  → ProcessLocator 定位结果: {pids}")
        if len(pids) > 20 or (pids and 1 in pids):
            print("  [!] 该设备的 pidof 不可信（数量过多或含 PID 1），"
                  "已自动回退到 ps/dumpsys —— 这正是 v5.0 修的第一个致命 bug")

        pid = pids[0] if pids else None
        if pid:
            section(f"进程 {pid} —— /proc 采样")
            out, ok = sh(f"{A} shell cat /proc/{pid}/stat /proc/{pid}/task/*/stat "
                         f"/proc/{pid}/status", timeout=25)
            show("/proc/<pid>/stat + task/*/stat + status", out, ok, 3000)
            parsed = P.parse_proc_snapshot(out, pid)
            threads = parsed.get('threads') or {}
            group = parsed.get('group_ticks')
            tsum = sum(v[1] for v in threads.values())
            print(f"\n  → 进程级(线程组总量) jiffies = {group}")
            print(f"  → 线程表条数 = {len(threads)}（不含 pid 行）  求和 = {tsum}")
            print(f"  → VmRSS = {parsed.get('rss_mb')} MB")
            if group is not None and tsum:
                print(f"  → 差值 {group - tsum} jiffies = **主线程自己**的累计 CPU"
                      f"（线程表不含 pid 行，所以差值就是主线程）")
                print("     ⚠️ 若差值远大于主线程应有的量，或线程表求和 > 进程级，")
                print("        说明口径被覆盖了 —— 这是 v5.0 修的第二个致命 bug")

            section("CPU 差分实测（10 秒窗口）")
            import time as _t
            p1 = P.parse_proc_snapshot(
                sh(f"{A} shell cat /proc/{pid}/stat /proc/{pid}/task/*/stat",
                   timeout=20)[0], pid)
            t0 = _t.time()
            _t.sleep(10)
            p2 = P.parse_proc_snapshot(
                sh(f"{A} shell cat /proc/{pid}/stat /proc/{pid}/task/*/stat",
                   timeout=20)[0], pid)
            el = _t.time() - t0
            g1, g2 = p1.get('group_ticks'), p2.get('group_ticks')
            if g1 is not None and g2 is not None:
                cpu = (g2 - g1) / el / 100 * 100
                print(f"  窗口 {el:.1f}s  jiffies {g1} → {g2}  "
                      f"差分 {g2 - g1}  → CPU {cpu:.1f}%（单核百分比口径）")

        section(f"内存 —— dumpsys meminfo {pkg}")
        out, ok = sh(f"{A} shell dumpsys meminfo {pkg}", timeout=30)
        show(f"dumpsys meminfo {pkg}", out, ok, 3000)
        r = P.parse_meminfo(out)
        print(f"\n  → 解析: PSS={r.get('pss')} MB  Java={r.get('java')} MB  "
              f"Native={r.get('native')} MB")
        print("  ↑ 若 PSS 是 None，说明该机型 dumpsys 格式与已知样本都不同（需要适配）")

    section("gfxinfo（FPS / 卡顿率）")
    out, ok = sh(f"{A} shell dumpsys gfxinfo {pkg}" if pkg
                 else f"{A} shell dumpsys gfxinfo", timeout=30)
    show("dumpsys gfxinfo", out, ok, 3000)
    gfx = P.parse_gfxinfo(out)
    print(f"\n  → Total frames: {gfx.get('total_frames')}")
    print(f"  → Janky: {gfx.get('janky_frames')} ({gfx.get('janky_pct')}%)")
    print(f"  → 帧耗时百分位: p90={gfx.get('p90')}  p95={gfx.get('p95')}  "
          f"p99={gfx.get('p99')} ms")
    print("  ↑ 采集器用「总数差分 + janky 百分比反推」算**窗口内**真实卡顿率，"
          "而不是直接用这个累计百分比")

    section("framestats（逐帧，Android 10+ 才有）")
    out, ok = sh(f"{A} shell dumpsys gfxinfo {pkg} framestats" if pkg
                 else f"{A} shell dumpsys gfxinfo framestats", timeout=30)
    fs = P.parse_framestats(out)
    if fs and fs.get('frames'):
        _fr = fs['frames']
        _d = sorted(f['duration_ms'] for f in _fr)
        _n = len(_d)
        _p95 = _d[int(round(0.95 * (_n - 1)))]
        _p99 = _d[int(round(0.99 * (_n - 1)))]
        _jk = sum(1 for f in _fr if f.get('jank'))
        print(f"  → 逐帧数据 {_n} 帧  P95={_p95}ms  P99={_p99}ms  "
              f"卡顿 {_jk} 帧 ({_jk / _n * 100:.1f}%)")
    else:
        print("  → 该设备不支持 framestats（Android 10 以下），"
              "采集器自动降级到累计帧数差分")

    section("系统整体（/proc/stat、/proc/meminfo）")
    out, ok = sh(f"{A} shell cat /proc/stat")
    show("/proc/stat", out, ok, 600)
    print(f"  → 总 jiffies: {P.parse_proc_stat_cpu(out)}")
    out, ok = sh(f"{A} shell cat /proc/meminfo")
    show("/proc/meminfo", out, ok, 1200)

    out, ok = sh(f"{A} shell dumpsys cpuinfo", timeout=30)
    show("dumpsys cpuinfo", out, ok, 1500)
    if pkg:
        v = P.parse_cpuinfo_line(out, pkg)
        print(f"  → {pkg} CPU%: {v}")
        print("  ↑ 这是**降级模式**用的数据源：窗口由系统决定（实测滞后可达 24s），"
              "且应用静止时完全不列出该进程")

    section("结论提示")
    print("""
  1. 若「PSS」为 None 而原始输出里明明有 Total PSS → 解析器需要适配该格式
  2. 若 framestats 不可用 → 正常（Android 10 以下），采集器会自动降级
  3. 若 pidof 返回一堆 PID 且含 1 → 该设备 pidof 不可信（v5.0 已自动回退）
  4. 若「线程表求和」> 「进程级 jiffies」 → 口径被覆盖了，需要查 parse_proc_snapshot
     （正常情况：进程级 = 线程表求和 + 主线程自己）
  5. 若 nproc / getconf 不存在 → 正常（已多级回退），CLK_TCK 用标准值 100
""")


if __name__ == "__main__":
    main()
