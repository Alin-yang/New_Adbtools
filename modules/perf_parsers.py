"""
性能数据解析器（纯函数，可离线单测）

这一层只负责「把 adb 输出变成结构化数据」，不碰线程、不碰 UI。

⚠️ 三个容易踩的坑（都已在真机上验证过）：

1. **`/proc/<pid>/stat` 与 `/proc/<pid>/task/<pid>/stat` 的 utime 含义不同**
   - `/proc/<pid>/stat`      → 内核 `do_task_stat(whole=true)`  → **整个线程组的累计 CPU**
   - `/proc/<pid>/task/<tid>/stat` → `whole=false` → **该线程自己的累计 CPU**

   两者 tid 都是 pid，用同一个字典存会被**后者覆盖**。
   真机实测（MiBOX4 / com.gitvdemo.video，pid 27690）：
       /proc/27690/stat            合计 = 12626   ← 线程组总量
       /proc/27690/task/27690/stat 合计 =   776   ← 仅主线程
   主线程只占 6%，94% 在其它 203 个线程上 —— 取错口径，进程 CPU 直接少 94%。

2. **`cat` 的输出顺序是确定的**：按参数顺序，所以**第一行 stat 一定是
   `/proc/<pid>/stat`**。据此可以无歧义地分离两种口径，无需额外分隔符。

3. **帧数差分可能为 0**（应用静止 / 视频走硬解码由 SurfaceFlinger 直接合成，
   不经过应用绘制）。此时不能用 0 冒充「测得的 FPS」，要表达「本周期无渲染活动」。
"""
import re
from typing import Any, Dict, List, Optional, Tuple


# ====================================================================== #
# /proc 解析
# ====================================================================== #

def parse_stat_line(line: str) -> Optional[Tuple[int, str, int]]:
    """解析一行 /proc/<pid>/stat

    格式: pid (comm) state ppid ... utime(14) stime(15) ...
    comm 可能含空格，故取最后一个 ')' 之后再按空格切分。

    Returns:
        (tid, name, utime + stime) 或 None
    """
    try:
        sp = line.find(' ')
        if sp <= 0:
            return None
        tid = int(line[:sp])
        lp = line.find('(')
        rp = line.rfind(')')
        if lp < 0 or rp < 0 or rp < lp:
            return None
        name = line[lp + 1:rp]
        rest = line[rp + 2:].split()
        if len(rest) < 13:
            return None
        ticks = int(rest[11]) + int(rest[12])
        return tid, name, ticks
    except (ValueError, IndexError):
        return None


def parse_proc_snapshot(output: str, pid: int) -> Dict[str, Any]:
    """解析一次 `cat /proc/<pid>/stat /proc/<pid>/task/*/stat /proc/<pid>/status`

    ⚠️ 关键：**按 cat 的参数顺序分离两种口径**
       第一条 stat 行 = /proc/<pid>/stat（线程组总量）→ group_ticks
       其余 stat 行 = /proc/<pid>/task/*/stat（各线程）→ threads
       线程表**不含** pid 本身（那是组总量，计进去会重复）。

    Returns:
        {
            'group_ticks': int | None,   进程级（线程组）累计 jiffies
            'threads': {tid: (name, ticks)},  各线程（不含 pid）
            'rss_mb': float | None,       VmRSS
        }
    """
    group_ticks: Optional[int] = None
    threads: Dict[int, Tuple[str, int]] = {}
    rss_mb: Optional[float] = None

    for raw in (output or '').splitlines():
        line = raw.strip()
        if not line:
            continue
        # stat 行：数字开头且含 '('
        if line[0].isdigit() and '(' in line:
            parsed = parse_stat_line(line)
            if not parsed:
                continue
            tid, name, ticks = parsed
            if tid == pid and group_ticks is None:
                group_ticks = ticks          # 线程组总量（第一次出现）
            elif tid != pid:
                threads[tid] = (name, ticks)
            else:
                # pid 第二次出现 = task/<pid>/stat（单线程），忽略
                pass
            continue
        if line.startswith('VmRSS:'):
            m = re.search(r'(\d+)\s*kB', line)
            if m:
                rss_mb = round(int(m.group(1)) / 1024.0, 1)

    return {'group_ticks': group_ticks, 'threads': threads, 'rss_mb': rss_mb}


def parse_meminfo(output: str) -> Dict[str, Optional[float]]:
    """解析 dumpsys meminfo <pkg>，单位 KB → MB

    兼容三种格式：
      - Android 8+  App Summary：`Total PSS:   45678`（首字母大写）
      - Android 7-  表格格式    ：`  TOTAL   45678  ...`（第一列才是 PSS）
      - Android 10+ 多一列 Rss  ：`Java Heap: 12345   23456`（取第一列 Pss）
    """
    def to_mb(kb):
        return round(kb / 1024.0, 1) if kb is not None else None

    pss = java = native = None

    # App Summary 汇总行："Total PSS by process:" / "  TOTAL PSS:   45678"
    m = re.search(r'(?i)total\s+pss\s*:\s*(\d+)', output or '')
    if not m:
        # 单进程表格里的 PSS 行："Pss  Total:   45678    Private Dirty: ..."
        # ⚠️ "Pss" 与 "Total" 之间可能有多个空格，必须用 (\s+) 而非 \s
        m = re.search(r'(?i)\bpss\s+total\s*:\s*(\d+)', output or '')
    if not m:
        # 老版本表格格式："  TOTAL   123456   67890   4567   ..."
        # ⚠️ 第一列是 PSS Total，后面是 Private Dirty/Clean/SwapPss
        m = re.search(r'(?i)^\s*total\s+(\d+)', output or '', re.M)
    if m:
        pss = int(m.group(1))

    # ── Java Heap ────────────────────────────────────────
    # ⚠️ **两种命名**（v5.4.10 真机验证发现）：
    #    Android 8+  ：`Java Heap:   12345`            （App Summary 格式）
    #    Android 7-  ：`  Dalvik Heap    32257    32056`（表格格式）
    #    老版本把 Java 堆叫 **Dalvik**（ART 之前的时代）。
    #    只认 `Java Heap` → 老设备上 java 永远是 None。
    m = re.search(r'(?i)java\s+heap:\s+(\d+)', output or '')
    if not m:
        m = re.search(r'(?i)^\s*dalvik\s+heap\s+(\d+)', output or '', re.M)
    if m:
        java = int(m.group(1))

    # ── Native Heap ──────────────────────────────────────
    # ⚠️ 表格格式是 `  Native Heap    22261    22204 ...`（无冒号，第一列即 PSS）
    m = re.search(r'(?i)native\s+heap:\s+(\d+)', output or '')
    if not m:
        m = re.search(r'(?i)^\s*native\s+heap\s+(\d+)', output or '', re.M)
    if m:
        native = int(m.group(1))

    # ── 表格格式的 TOTAL 行 ──────────────────────────────
    # ⚠️ 表格格式里没有 `Total PSS:`，PSS 在 `        TOTAL    70309    58856` 那行
    # ⚠️ **两种 TOTAL 写法都要认**：
    #    表格格式 `  TOTAL    70309    58856`（无冒号）
    #    App Summary `  TOTAL:   70309`（有冒号）
    if pss is None:
        m = re.search(r'(?i)^\s*total\s*:?\s+(\d+)', output or '', re.M)
        if m:
            pss = int(m.group(1))

    return {'pss': to_mb(pss), 'java': to_mb(java), 'native': to_mb(native)}


def parse_system_meminfo(output: str) -> Dict[str, Optional[float]]:
    """解析 /proc/meminfo，返回系统已用内存 MB"""
    total = re.search(r'MemTotal:\s+(\d+)', output or '')
    avail = re.search(r'MemAvailable:\s+(\d+)', output or '')
    if not (total and avail):
        return {'pss': None, 'java': None, 'native': None}
    return {'pss': round((int(total.group(1)) - int(avail.group(1))) / 1024.0, 1),
            'java': None, 'native': None}


def parse_proc_stat_cpu(output: str) -> Optional[float]:
    """解析 /proc/stat 的整体 CPU jiffies 总数

    ⚠️ **这个「总量」是所有核的累加值**（实测 2 核设备：
       总量差值 678 ≈ cpu0 差值 339 + cpu1 差值 338，误差 0.1%）。
       要算整机忙碌率**必须除以核数**，否则结果必然 >= 100%。
    """
    for line in (output or '').splitlines():
        if line.startswith('cpu'):
            try:
                values = [int(v) for v in line.split()[1:]]
                if len(values) >= 4:
                    return float(sum(values))
            except ValueError:
                return None
    return None


def parse_proc_stat_cpu_fields(output: str) -> Optional[Dict[str, float]]:
    """解析 /proc/stat 的 cpu 总量行的**分项** jiffies

    ⚠️ **字段顺序（Linux 标准，Android 同样是这 10 个）**：
       user nice system **idle** iowait irq softirq steal guest guest_nice
       Android 是 10 字段（比标准少一个 guest_nice），但**前 7 个含义相同**。

    ⚠️ **为什么要分项而不是只用总量**（v5.4.7 真机验证发现）：
       整机 CPU 忙碌率的正确公式是 **1 - Δidle / Δtotal**，
       不是「Δtotal / 核数 / CLK_TCK」。
       原因：Δtotal 里含 idle，而 idle 已经隐含了「核数 × 窗口」的信息；
       再除以核数会**重复除一次** → 结果离谱
       （实测同一时刻：旧公式 491.5%，正确公式 21.0%）。

       对照验证（真机 2 核）：
         /proc/stat 增量 = User 58 + Nice 2 + Sys 145 + Idle 777 + IOW 0 + IRQ 0 + SIRQ 1 = 983
         top  输出      = User 58 + Nice 0 + Sys 179 + Idle 189 + IOW 103 + IRQ 0 + SIRQ 59 = 563
       （同一份内核计数器，字段一一对应）

    Returns:
        含 user/nice/system/idle/iowait/irq/softirq/total 的 dict；
        解析失败返回 None
    """
    for line in (output or '').splitlines():
        parts = line.split()
        if not parts or parts[0] != 'cpu':
            continue
        try:
            vals = [int(v) for v in parts[1:]]
        except ValueError:
            return None
        if len(vals) < 4:
            return None

        def _g(i, default=0):
            return float(vals[i]) if len(vals) > i else default

        return {
            'user': _g(0),
            'nice': _g(1),
            'system': _g(2),
            'idle': _g(3),
            'iowait': _g(4),
            'irq': _g(5),
            'softirq': _g(6),
            'total': float(sum(vals)),
        }
    return None


def parse_proc_stat_cores(output: str) -> int:
    """从 /proc/stat 数出**在线核数**（数 cpuN 行的个数）

    ⚠️ **为什么从 /proc/stat 数而不用 `nproc`**：
       - `nproc` 在精简 Android 上**经常不存在**
         （实测小米盒子 Android 5.1.1 和本机 192.168.0.50 都没有）
       - `cat /proc/cpuinfo` 在某些 ROM 上也没有 cat
       - 而 /proc/stat 是**采集 CPU 时本来就要读的那一份数据** →
         数它的 cpuN 行 = **零额外 adb 往返**

    Returns:
        核数；解析不出来时返回 0（调用方应回退到 1）
    """
    n = 0
    for line in (output or '').splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        # cpu0 / cpu1 …（排除总量行 "cpu" 和其它 "cpuXxx"）
        if name.startswith('cpu') and name[3:].isdigit():
            n += 1
    return n


def parse_cpuinfo_line(output: str, package_name: str) -> Optional[float]:
    """从 dumpsys cpuinfo 解析指定包名 CPU%（多进程累加）—— proc 不可读时的降级路径"""
    total = 0.0
    found = False
    for line in (output or '').split('\n'):
        if package_name not in line:
            continue
        m = re.match(r'\s*([\d.]+)%\s', line)
        if m:
            try:
                total += float(m.group(1))
                found = True
            except ValueError:
                continue
    return round(total, 2) if found else None


# ====================================================================== #
# 渲染统计（gfxinfo）
# ====================================================================== #

def parse_gfxinfo(output: str) -> Dict[str, Any]:
    """解析 dumpsys gfxinfo 输出

    提取的字段：
      total_frames   累计渲染帧数（进程启动至今）
      janky_frames   累计卡顿帧数（由百分比反推，见下）
      janky_pct      累计卡顿百分比
      p90/p95/p99    帧耗时百分位（ms）—— 现有实现完全没用上
      missed_vsync   丢 Vsync 次数
      slow_ui        UI 线程慢帧数
      slow_draw      绘制命令慢帧数

    ⚠️ **janky_frames 是反推出来的**：gfxinfo 只给百分比
       `Janky frames: 8513 (28.87%)`，用 round(total × pct/100) 反推绝对数。
       这样才能对 janky 做**差分**，得到「窗口内」的真实卡顿率 ——
       直接用累计百分比当"当前卡顿率"是错的（数值几乎不变，无意义）。

    Returns:
        各项为 None 表示该字段不可用
    """
    out = output or ''
    total = janky_pct = None
    p90 = p95 = p99 = None
    missed_vsync = slow_ui = slow_draw = None

    m = re.search(r'Total\s+frames\s+rendered:\s*(\d+)', out)
    if m:
        total = int(m.group(1))

    m = re.search(r'Janky\s+frames:\s*(\d+)\s*\(([\d.]+)%\)', out)
    if m:
        janky_pct = float(m.group(2))

    for key, name in (('90th', 'p90'), ('95th', 'p95'), ('99th', 'p99')):
        m = re.search(key + r'\s+percentile:\s*(\d+)ms', out)
        if m:
            if name == 'p90':
                p90 = int(m.group(1))
            elif name == 'p95':
                p95 = int(m.group(1))
            else:
                p99 = int(m.group(1))

    for pat, name in (
            (r'Number Missed Vsync:\s*(\d+)', 'missed_vsync'),
            (r'Number Slow UI thread:\s*(\d+)', 'slow_ui'),
            (r'Number Slow issue draw commands:\s*(\d+)', 'slow_draw')):
        m = re.search(pat, out)
        if m:
            if name == 'missed_vsync':
                missed_vsync = int(m.group(1))
            elif name == 'slow_ui':
                slow_ui = int(m.group(1))
            else:
                slow_draw = int(m.group(1))

    janky_frames = None
    if total is not None and janky_pct is not None:
        janky_frames = int(round(total * janky_pct / 100.0))

    return {
        'total_frames': total,
        'janky_frames': janky_frames,
        'janky_pct': janky_pct,
        'p90': p90, 'p95': p95, 'p99': p99,
        'missed_vsync': missed_vsync,
        'slow_ui': slow_ui, 'slow_draw': slow_draw,
    }


def parse_framestats(output: str) -> Optional[Dict[str, Any]]:
    """解析 dumpsys gfxinfo <pkg> framestats 的逐帧数据（Android 10+）

    输出结构：
        ---PROFILEDATA---
        Flags,IntendedVsync,Vsync,...,FrameInterval,FrameDeadline,FrameCompleted,...
        0,123456789,123456789,...,

    ⚠️ **列数与列名随 Android 版本变化**，所以按**表头名**定位列索引，
       不能写死下标。

    Returns:
        {'frames': [{'duration_ms': float, 'jank': bool, 'interval_ms': float}, ...]}
        或 None（不支持 framestats 的设备返回 None）
    """
    out = output or ''
    idx = out.find('---PROFILEDATA---')
    if idx < 0:
        return None

    lines = out[idx:].splitlines()
    header = None
    frames: List[Dict[str, Any]] = []

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if header is None:
            if line.lower().startswith('flags,'):
                header = [c.strip() for c in line.split(',')]
            continue
        if not line[0].isdigit():
            break
        cols = line.split(',')
        if len(cols) < len(header):
            continue
        try:
            def num(col_name):
                pos = header.index(col_name)
                return int(cols[pos])
            intended = num('IntendedVsync')
            completed = num('FrameCompleted')
        except (ValueError, IndexError):
            continue
        if intended <= 0 or completed <= 0 or completed < intended:
            continue
        duration_ms = (completed - intended) / 1_000_000.0
        interval_ms = 0.0
        deadline = 0
        try:
            interval_ms = num('FrameInterval') / 1_000_000.0
            deadline = num('FrameDeadline')
        except (ValueError, IndexError):
            pass
        # Android 的 jank 判定：帧完成时间超过 deadline
        is_jank = bool(deadline and completed > deadline)
        frames.append({'duration_ms': duration_ms,
                       'jank': is_jank,
                       'interval_ms': interval_ms})

    if not frames:
        return None
    return {'frames': frames}
