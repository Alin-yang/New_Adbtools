"""性能监控真机验证（开发辅助）

⚠️ 这台网络设备（192.168.0.50）**连接很不稳**：
   adb server 重启后不会自动重连，且会自己掉线。
   所以脚本自带「读不到就重连」的重试。

验证 v5.4.6 提速 + v5.4.7 CPU 公式修复：
  ① 核数从同一份 /proc/stat 数出（零额外 adb）
  ② **整机忙碌率 = 1 - Δidle/Δtotal**（不是 ÷核数）
  ③ 与设备自带 `top` 的口径对照
  ④ 首帧耗时
  ⑤ 导出功能

用法: python tests/verify_perf_live.py [设备IP]
"""
import subprocess
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEV = sys.argv[1] if len(sys.argv) > 1 else '192.168.0.50:5555'
OUT = []


def log(msg=''):
    OUT.append(str(msg))
    print(msg)


def ensure_connected():
    """确保设备在线（网络设备掉线后要手动重连）"""
    r = subprocess.run(['adb', 'devices'], capture_output=True, text=True,
                       timeout=20)
    if DEV in (r.stdout or ''):
        return True
    subprocess.run(['adb', 'connect', DEV], capture_output=True, text=True,
                   timeout=25)
    time.sleep(1.5)
    r = subprocess.run(['adb', 'devices'], capture_output=True, text=True,
                       timeout=20)
    return DEV in (r.stdout or '')


def sh(cmd, retries=3):
    """adb shell 带自动重连"""
    for _ in range(retries):
        if not ensure_connected():
            time.sleep(1)
            continue
        try:
            r = subprocess.run(['adb', 'shell', cmd], capture_output=True,
                               text=True, timeout=25)
            out = (r.stdout or '').replace('\r', '')
            if out.strip():
                return out
        except Exception:
            pass
        time.sleep(0.8)
    return ''


def main():
    from modules import perf_parsers as P
    from modules.perf_collector import PerfCollector

    log('=' * 68)
    log('性能监控真机验证')
    log('=' * 68)
    log(f'设备: {DEV}   连接: {"在线" if ensure_connected() else "离线"}')

    # ── 1. /proc/stat 结构 ─────────────────────────────────
    log('')
    log('=== 1. /proc/stat 结构 ===')
    raw = sh('cat /proc/stat')
    total, per = None, []
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == 'cpu':
            total = P.parse_proc_stat_cpu(raw)
        elif parts[0].startswith('cpu') and parts[0][3:].isdigit():
            per.append(sum(int(v) for v in parts[1:]))
    log(f'  总量行 = {total}')
    log(f'  各核行数 = {len(per)}  -> 核数 = {P.parse_proc_stat_cores(raw)}')
    f = P.parse_proc_stat_cpu_fields(raw) or {}
    log(f'  分项: user={f.get("user")} system={f.get("system")} '
        f'idle={f.get("idle")} iowait={f.get("iowait")}')

    # ── 2. 正确口径 vs 旧口径 vs top ───────────────────────
    log('')
    log('=== 2. 三种口径对照（同一时刻）===')
    s1 = P.parse_proc_stat_cpu_fields(sh('cat /proc/stat'))
    ncpu = P.parse_proc_stat_cores(sh('cat /proc/stat'))
    t0 = time.time()
    time.sleep(4)
    s2 = P.parse_proc_stat_cpu_fields(sh('cat /proc/stat'))
    el = time.time() - t0
    if not s1 or not s2:
        log('  ⚠️ 读不到 /proc/stat')
    else:
        d_total = s2['total'] - s1['total']
        d_idle = s2['idle'] - s1['idle']
        old_raw = d_total / max(ncpu, 1) / 100 * 100
        old_shown = min(old_raw, 100.0)
        new = (1.0 - d_idle / d_total) * 100.0
        log(f'  Δtotal={d_total}  Δidle={d_idle}  核数={ncpu}')
        log(f'  旧口径（÷核数，截断后） = {old_shown:.1f}%   <- bug')
        log(f'  新口径（1-idle/total）  = {new:.1f}%   <- 正确')
        log(f'  设备 top 口径：')
        top_out = sh("top -n 1 -m 1 2>/dev/null")
        for line in top_out.splitlines():
            if 'User' in line and ('+' in line or '%' in line):
                log(f'    {line.strip()}')

    # ── 3. PerfCollector 实测 ──────────────────────────────
    log('')
    log('=== 3. PerfCollector 实测（system 模式）===')
    c = PerfCollector()
    c.start(None, 1.0)
    t0 = time.time()
    first_ms = None
    for _ in range(90):
        time.sleep(0.1)
        st = c.stats()
        if st['sample_count'] >= 1 and first_ms is None:
            first_ms = (time.time() - t0) * 1000
            log(f'  首帧: {first_ms:.0f} ms')
        if st['sample_count'] >= 6:
            break
    time.sleep(1.5)
    c.stop()
    st = c.stats()
    log(f'  核数 = {c._cores}   CPU 上限 = {c._cpu_max}')
    log(f'  CPU 聚合 = {st["cpu"]}')
    log(f'  history（{len(c.history)} 条）:')
    for h in list(c.history):
        log(f'    {h}')
    cpu = st['cpu']['cur']
    if cpu is not None and cpu < 99.9:
        log(f'  ✅ CPU 不再饱和：{cpu}%')
    elif cpu is None:
        log('  (本次没采到 CPU)')
    else:
        log(f'  ⚠️ CPU 仍饱和：{cpu}%')

    # ── 4. 导出 ─────────────────────────────────────────────
    log('')
    log('=== 4. 导出 ===')
    try:
        d = os.path.join(r'D:\adbtool_log', 'verify')
        os.makedirs(d, exist_ok=True)
        csv_path = os.path.join(d, 'verify_perf.csv')
        c.export_csv(csv_path)
        log(f'  CSV: {csv_path} ({os.path.getsize(csv_path)} 字节)')
        rep_path = os.path.join(d, 'verify_perf.txt')
        c.export_report(rep_path)
        log(f'  报告: {rep_path} ({os.path.getsize(rep_path)} 字节)')
        with open(rep_path, encoding='utf-8') as fp:
            for h in fp.read().split('\n')[:10]:
                if h.strip():
                    log(f'    | {h}')
    except Exception as e:
        log(f'  ⚠️ 导出失败: {e}')

    log('')
    log('=' * 68)
    log('验证结束')
    log('=' * 68)

    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '_shots_v4', 'verify_perf_live.txt')
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write('\n'.join(OUT))
        print(f'\n报告已存: {path}')
    except Exception:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
