"""性能监控真机诊断脚本

在连接了 Android 设备的情况下运行，把各采集命令的**原始输出**打印出来，
用于验证解析器在真机上的行为（尤其是 PSS / 卡顿率 / CPU% 这几个指标）。

用法：
    D:\\tool\\python\\python.exe tools\\diagnose_perf.py [包名]
    D:\\tool\\python\\python.exe tools\\diagnose_perf.py com.example.app

不带包名时只做不需要包名的检查（系统整体模式）。
输出直接贴回来即可。
"""
import os
import re
import subprocess
import sys
import time

# Windows 控制台默认 GBK，输出中文会乱码 —— 强制 UTF-8 + 替换非法字符
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.performance_monitor import PerfParsers


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


def main():
    pkg = sys.argv[1] if len(sys.argv) > 1 else None

    section("环境")
    out, ok = sh("adb version")
    if not ok and ("不是内部" in out or "not recognized" in out.lower()):
        print("\n  ⚠️ 找不到 adb！请确认 adb 在 PATH 里，或用完整路径运行本脚本。")
        print("     （ADB Tool 本身也依赖系统 PATH 里的 adb）")
        return
    show("adb version", out, ok, 300)
    out, ok = sh("adb devices -l")
    show("adb devices -l", out, ok, 800)
    out, ok = sh("adb shell getprop ro.build.version.release")
    print(f"\n  Android 版本: {out.strip()}")
    out, ok = sh("adb shell getconf CLK_TCK")
    print(f"  CLK_TCK     : {out.strip()}  (解析={PerfParsers.parse_clk_tck(out)})")
    out, ok = sh("adb shell nproc")
    print(f"  CPU 核数    : {out.strip()}")
    out, ok = sh("adb shell getprop ro.build.version.sdk")
    print(f"  SDK         : {out.strip()}")

    if pkg:
        section(f"应用 {pkg}")
        out, ok = sh(f"adb shell pidof {pkg}")
        show(f"pidof {pkg}", out, ok, 300)
        pid = PerfParsers.parse_pidof(out)
        print(f"  → 解析出的 pid: {pid}")

        if pid:
            out, ok = sh(f"adb shell cat /proc/{pid}/stat /proc/{pid}/task/*/stat "
                         f"/proc/{pid}/status", timeout=20)
            show(f"/proc/{pid}/stat + task/*/stat + status", out, ok, 3000)
            ticks, rss = PerfParsers.parse_proc_snapshot(out)
            print(f"\n  → 解析: 线程数={len(ticks)}  VmRSS={rss} MB")
            if len(ticks) > 60:
                items = list(ticks.items())[:10]
                print(f"  → 前 10 个线程样例: {items}")

        out, ok = sh(f"adb shell dumpsys meminfo {pkg}", timeout=25)
        show(f"dumpsys meminfo {pkg}", out, ok, 3000)
        r = PerfParsers.parse_meminfo(out)
        print(f"\n  → 解析: PSS={r['pss']} MB  Java={r['java']} MB  Native={r['native']} MB")
        print("  ↑ 若 PSS 是 None，说明该机型 dumpsys 格式与已知样本都不同（需要适配）")

    section("gfxinfo（FPS / 卡顿率）")
    out, ok = sh("adb shell dumpsys gfxinfo", timeout=25)
    show("dumpsys gfxinfo", out, ok, 3000)
    print(f"\n  → Total frames: {PerfParsers.parse_total_frames(out)}")
    print(f"  → Janky percent: {PerfParsers.parse_janky_percent(out)}")
    print("  ↑ 若 Janky 是 None，说明该机型 gfxinfo 无此字段（Android 7 以下）")

    section("系统整体（/proc/stat、/proc/meminfo）")
    out, ok = sh("adb shell cat /proc/stat")
    show("/proc/stat", out, ok, 600)
    print(f"  → 总 jiffies: {PerfParsers.parse_proc_stat_cpu(out)}")
    out, ok = sh("adb shell cat /proc/meminfo")
    show("/proc/meminfo", out, ok, 1200)
    print(f"  → 已用内存: {PerfParsers.parse_system_meminfo(out)}")

    out, ok = sh("adb shell dumpsys cpuinfo", timeout=25)
    show("dumpsys cpuinfo", out, ok, 1500)
    if pkg:
        print(f"  → {pkg} CPU%: {PerfParsers.parse_cpuinfo_line(out, pkg)}")

    section("结论提示")
    print("""
  1. 若「PSS」为 None 而原始输出里明明有 Total PSS → 解析器需要适配该格式
  2. 若「Janky percent」为 None 且输出里没有 Janky frames → 正常（Android 7 以下没有）
  3. 若 CPU 核数为 1 而实际是多核 → nproc 解析有问题
  4. 若 /proc/<pid>/task/*/stat 读不到 → 该机型限制了 /proc 访问，需换 cpuinfo 模式
""")


if __name__ == "__main__":
    main()
