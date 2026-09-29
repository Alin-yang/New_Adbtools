"""
性能监控引擎（重写版）
=====================

设计要点：
1. 一次采样同时产出进程级 + 线程级数据：
   `adb shell cat /proc/<pid>/stat /proc/<pid>/task/*/stat` 单次调用读回
   进程与全部线程的 CPU jiffies，两次采样差分得到真实瞬时 CPU%（与采样间隔无关）。
2. 内存指标一次 dumpsys meminfo 同时解析 PSS / Java Heap / Native Heap。
3. FPS 用 gfxinfo 累计帧数两次差分（与采样间隔无关）。
4. 每个指标自动聚合 当前 / 均值 / 峰值，无需 UI 再做统计。
5. 智能降级：/proc 不可读（部分机型权限限制）自动回退 dumpsys cpuinfo（仅进程级）；
   未填包名时进入系统整体模式（/proc/stat + /proc/meminfo 差分）。
6. 采样点完整记录（时间/CPU/PSS/Java/Native/FPS）保留最近 600 条，供数值回看与 CSV 导出。
7. 采集线程与 UI 解耦：采样完成后通过 update_callback 投递 stats 快照，
   回调内部需自行保证在主线程执行（本模块用 root.after 调度）。

本模块不依赖 tkinter（除 app 引用用于 root.after），可离线单测。
"""

import concurrent.futures
import csv
import logging
import re
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional

from config import Config
from utils import run_adb_command

try:
    from utils import build_adb_command_with_device  # noqa: F401
except ImportError:  # pragma: no cover
    build_adb_command_with_device = None


# ---------------------------------------------------------------- 数据结构

class ThreadStat:
    """单个线程的 CPU 统计聚合"""

    __slots__ = ('tid', 'name', 'cur', 'avg', 'peak', '_sum', '_count')

    def __init__(self, tid: int, name: str, cur: float):
        self.tid = tid
        self.name = name
        self.cur = cur
        self._sum = cur
        self._count = 1
        self.avg = cur
        self.peak = cur

    def update(self, cur: float):
        self.cur = cur
        self._sum += cur
        self._count += 1
        self.avg = self._sum / self._count
        if cur > self.peak:
            self.peak = cur

    def to_dict(self) -> Dict[str, Any]:
        return {'tid': self.tid, 'name': self.name,
                'cur': round(self.cur, 2), 'avg': round(self.avg, 2),
                'peak': round(self.peak, 2)}


class _Metric:
    """通用指标聚合器（当前/均值/峰值/P95/P05）"""

    __slots__ = ('cur', 'avg', 'peak', 'p95', 'p05',
                 '_sum', '_count', '_values', 'valid')

    def __init__(self):
        self.cur: Optional[float] = None
        self.avg: Optional[float] = None
        self.peak: Optional[float] = None
        self.p95: Optional[float] = None
        self.p05: Optional[float] = None
        self._sum = 0.0
        self._count = 0
        self._values: List[float] = []
        self.valid = False

    def update(self, value: Optional[float]):
        if value is None:
            return  # 采集失败不更新，保留上一次的当前值
        self.valid = True
        self.cur = value
        self._sum += value
        self._count += 1
        self.avg = self._sum / self._count
        if self.peak is None or value > self.peak:
            self.peak = value

        # 分位数样本（与历史窗口同长，避免无限增长）
        self._values.append(value)
        if len(self._values) > 600:
            self._values.pop(0)
        ordered = sorted(self._values)
        n = len(ordered)
        self.p95 = ordered[int(round(0.95 * (n - 1)))]
        self.p05 = ordered[int(round(0.05 * (n - 1)))]

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {'cur': self.cur, 'avg': self.avg, 'peak': self.peak,
                'p95': self.p95, 'p05': self.p05}


# ---------------------------------------------------------------- 解析函数（静态，可单测）

class PerfParsers:
    """ADB 输出解析器（全部为纯函数，便于离线测试）"""

    @staticmethod
    def parse_proc_stat_line(line: str):
        """解析 /proc/<pid>/stat 单行

        格式: pid (comm) state ppid ... utime(14) stime(15) ...
        comm 可能包含空格，因此取最后一个 ')' 之后的部分再按空格分割：
        rest[0] 对应第 3 个字段(state)，utime = rest[11]，stime = rest[12]。

        Returns:
            (tid, name, utime+stime) 或 None
        """
        try:
            tid = int(line[:line.find(' ')])
            rparen = line.rfind(')')
            name = line[line.find('(') + 1:rparen]
            rest = line[rparen + 2:].split()
            ticks = int(rest[11]) + int(rest[12])
            return tid, name, ticks
        except (ValueError, IndexError):
            return None

    @staticmethod
    def parse_proc_ticks(output: str) -> Dict[int, Any]:
        """解析 cat /proc/<pid>/stat /proc/<pid>/task/*/stat 的输出

        Returns:
            {tid: (name, ticks)}；pid 本身也在其中（线程组 leader）
        """
        result = {}
        for line in output.splitlines():
            parsed = PerfParsers.parse_proc_stat_line(line.strip())
            if parsed:
                tid, name, ticks = parsed
                result[tid] = (name, ticks)
        return result

    @staticmethod
    def parse_proc_snapshot(output: str):
        """解析一次 cat 混合输出：/proc/<pid>/stat、/proc/<pid>/task/*/stat、/proc/<pid>/status

        stat 行形如 "1234 (name) S ..."，status 行形如 "VmRSS:   123456 kB"。
        合并到一次 adb 调用可减少一次进程启动开销。

        Returns:
            (ticks_map, rss_mb)
            - ticks_map: {tid: (name, ticks)}
            - rss_mb: VmRSS 换算的 MB，取不到时为 None
        """
        ticks = {}
        rss_mb = None
        stat_pat = re.compile(r'^\d+ \(')
        for raw in output.splitlines():
            line = raw.strip()
            if not line:
                continue
            if stat_pat.match(line):
                parsed = PerfParsers.parse_proc_stat_line(line)
                if parsed:
                    tid, name, tick = parsed
                    ticks[tid] = (name, tick)
                continue
            if line.startswith('VmRSS:'):
                m = re.search(r'(\d+)\s*kB', line)
                if m:
                    rss_mb = round(int(m.group(1)) / 1024.0, 1)
        return ticks, rss_mb

    @staticmethod
    def parse_clk_tck(output: str) -> int:
        """解析 getconf CLK_TCK，失败默认 100"""
        m = re.search(r'(\d+)', output or '')
        return int(m.group(1)) if m else 100

    @staticmethod
    def parse_meminfo(output: str) -> Dict[str, Optional[float]]:
        """解析 dumpsys meminfo <pkg>，单位 KB → MB

        Returns:
            {'pss': MB, 'java': MB, 'native': MB}，缺失项为 None
        """
        def to_mb(kb_val):
            return round(kb_val / 1024.0, 1) if kb_val is not None else None

        pss = None
        java = native = None
        java_m = re.search(r'Java Heap:\s+(\d+)', output)
        native_m = re.search(r'Native Heap:\s+(\d+)', output)
        pss_m = re.search(r'TOTAL PSS:\s+(\d+)', output)
        if not pss_m:
            # 老版本格式："  TOTAL   123456  ..."
            pss_m = re.search(r'^\s*TOTAL\s+\d*\s*(\d+)', output, re.M)
        if java_m:
            java = int(java_m.group(1))
        if native_m:
            native = int(native_m.group(1))
        if pss_m:
            pss = int(pss_m.group(1))
        return {'pss': to_mb(pss), 'java': to_mb(java), 'native': to_mb(native)}

    @staticmethod
    def parse_system_meminfo(output: str) -> Dict[str, Optional[float]]:
        """解析 /proc/meminfo，返回系统已用内存 MB"""
        total = re.search(r'MemTotal:\s+(\d+)', output)
        avail = re.search(r'MemAvailable:\s+(\d+)', output)
        if not (total and avail):
            return {'pss': None, 'java': None, 'native': None}
        used_kb = int(total.group(1)) - int(avail.group(1))
        return {'pss': round(used_kb / 1024.0, 1), 'java': None, 'native': None}

    @staticmethod
    def parse_proc_stat_cpu(output: str) -> Optional[float]:
        """解析 /proc/stat 的整体 CPU jiffies（user+nice+system+idle+...）"""
        for line in output.splitlines():
            if line.startswith('cpu ') or (line.startswith('cpu') and ' ' in line):
                try:
                    values = [int(v) for v in line.split()[1:]]
                    if len(values) >= 4:
                        return float(sum(values))
                except ValueError:
                    return None
        return None

    @staticmethod
    def parse_cpuinfo_line(output: str, package_name: str) -> Optional[float]:
        """从 dumpsys cpuinfo 解析指定包名 CPU%（多进程累加）"""
        total = 0.0
        found = False
        for line in output.split('\n'):
            if package_name not in line:
                continue
            match = re.match(r'\s*([\d.]+)%\s', line)
            if match:
                try:
                    total += float(match.group(1))
                    found = True
                except ValueError:
                    continue
        return round(total, 2) if found else None

    @staticmethod
    def parse_total_frames(output: str) -> Optional[int]:
        """从 gfxinfo 输出解析累计渲染帧数"""
        match = re.search(
            r'(?:Total\s+frames\s+rendered|Frames\s+rendered|Total\s+frames)\s*:\s*(\d+)',
            output)
        return int(match.group(1)) if match else None

    @staticmethod
    def parse_janky_percent(output: str) -> Optional[float]:
        """解析 gfxinfo 的 Janky frames 占比（%）——比 FPS 更能说明卡顿"""
        m = re.search(r'Janky frames:\s*\d+\s*\(([\d.]+)%\)', output)
        return float(m.group(1)) if m else None

    @staticmethod
    def parse_pidof(output: str) -> Optional[int]:
        """解析 pidof 输出（可能有多个 pid，取第一个）"""
        parts = (output or '').split()
        for p in parts:
            if p.isdigit():
                return int(p)
        return None



# ---------------------------------------------------------------- 监控引擎

class PerformanceMonitor:
    """性能监控引擎

    用法:
        monitor = PerformanceMonitor(app)
        monitor.update_callback = on_stats   # 在主线程被调用
        monitor.start('com.example.app', interval=2)
        monitor.stop()
    """

    FPS_BASELINE_INTERVAL = 1.0   # 无基准时补采等待
    HEAVY_EVERY = 2               # 内存/FPS 每 N 个周期采集一次（dumpsys 慢，避免拖慢 CPU 的实时性）
    HISTORY_MAX = 600             # 采样点保留上限
    THREAD_TABLE_MAX = 50         # 线程表最多展示条数

    def __init__(self, app=None):
        self.app = app
        self.monitoring = False
        self.stop_event = threading.Event()
        self.monitor_thread: Optional[threading.Thread] = None

        self.update_callback: Optional[Callable[[Dict], None]] = None

        # 目标
        self.package_name: Optional[str] = None
        self.interval = 2.0
        self.pid: Optional[int] = None
        self.mode = 'idle'   # idle / proc / cpuinfo / system

        # 聚合统计（UI 直接读取）
        self.stats: Dict[str, Any] = {
            'cpu': _Metric().to_dict(),
            'pss': _Metric().to_dict(),
            'rss': _Metric().to_dict(),
            'java': _Metric().to_dict(),
            'native': _Metric().to_dict(),
            'fps': _Metric().to_dict(),
            'jank': _Metric().to_dict(),
            'alert': False,
            'threads': [],          # List[Dict] 已按当前 CPU 降序
            'sample_count': 0,
            'elapsed': 0.0,
            'pid': None,
            'mode': 'idle',
        }

        # 采样点历史 (时间, CPU%, PSS MB, RSS MB, Java MB, Native MB, FPS, Jank%)
        self.history: deque = deque(maxlen=self.HISTORY_MAX)

        # 常驻线程池：避免每个采样周期新建/销毁线程池
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="PerfSample")

        # 内部状态
        self._start_time = 0.0
        self._clk_tck = 100
        self._cpu_max = 100.0   # 核数×100，start 时按设备探测
        self._fps_base_total: Optional[int] = None
        self._fps_base_time: Optional[float] = None
        self._sample_seq = 0
        self._alert_streak = 0
        self._alert_active = False
        self._clear_internal()

    # ------------------------------------------------ 对外 API

    def start(self, package_name: Optional[str] = None, interval: float = 2.0) -> bool:
        if self.monitoring:
            logging.warning("[性能监控] 监控已在运行中")
            return False

        self.package_name = (package_name or None)
        try:
            self.interval = max(1.0, float(interval))
        except (TypeError, ValueError):
            self.interval = 2.0

        self.monitoring = True
        self.stop_event.clear()
        self._clear_internal()
        self._start_time = time.time()

        self.monitor_thread = threading.Thread(
            target=self._sample_loop, daemon=True, name="PerformanceMonitor")
        self.monitor_thread.start()

        target = self.package_name or "系统整体"
        logging.info(f"[性能监控] 开始: {target}, 间隔 {self.interval}s")
        self._notify_status(f"✓ 开始性能监控: {target} (间隔 {self.interval:g}s)")
        return True

    def stop(self) -> bool:
        """停止监控

        不 join 采样线程：按钮回调在主线程，而采样线程可能正卡在一次 adb 调用里，
        join 会直接把 UI 卡住数秒。这里只置停止标志，线程在 wait 处立即返回，
        最多再跑完当前那一次 adb 调用后自行退出。
        """
        if not self.monitoring:
            return False
        self.monitoring = False
        self.stop_event.set()
        logging.info("[性能监控] 已停止")
        self._notify_status(f"⏹ 性能监控已停止 (共 {self.stats['sample_count']} 次采样)")
        return True

    # 兼容旧调用
    stop_monitoring = stop
    start_monitoring = start

    def clear(self):
        """清空统计与历史（保留运行状态）"""
        self._clear_internal()
        self._notify_status("🧹 性能数据已清空")

    def snapshot_once(self, package_name: Optional[str] = None) -> Dict[str, Any]:
        """单次快照：临时启动一轮采集（约 1 秒），返回最新 stats"""
        was_running = self.monitoring
        if was_running:
            return dict(self.stats)

        pkg = package_name if package_name is not None else self.package_name
        self.package_name = pkg or None
        self._clear_internal()
        self._start_time = time.time()
        self._sample_loop(single_shot=True)
        return dict(self.stats)

    def export_csv(self, file_path: str) -> str:
        """导出逐次采样明细到 CSV，返回实际写入路径"""
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['时间', '进程CPU(%)', 'PSS内存(MB)', 'RSS内存(MB)',
                             'Java Heap(MB)', 'Native Heap(MB)', 'FPS', '卡顿率(%)'])
            for ts, cpu, pss, rss, java, native, fps, jank in self.history:
                writer.writerow([ts,
                                 '' if cpu is None else f"{cpu:.2f}",
                                 '' if pss is None else f"{pss:.1f}",
                                 '' if rss is None else f"{rss:.1f}",
                                 '' if java is None else f"{java:.1f}",
                                 '' if native is None else f"{native:.1f}",
                                 '' if fps is None else f"{fps:.2f}",
                                 '' if jank is None else f"{jank:.2f}"])
        return file_path

    def export_report(self, file_path: str) -> str:
        """导出统计报告到文本文件，返回实际写入路径"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self.get_summary())
            f.write('\n')
        return file_path

    def get_summary(self) -> str:
        """生成文本统计报告"""
        s = self.stats
        if s['sample_count'] == 0:
            return "📊 暂无性能数据，请先开始监控"

        def fmt(m, unit='', digits=1):
            if not m.get('valid') and m.get('cur') is None:
                return '--'
            return (f"当前 {m['cur']:.{digits}f}{unit}    "
                    f"均值 {m['avg']:.{digits}f}{unit}    "
                    f"峰值 {m['peak']:.{digits}f}{unit}")

        def fmt_p(m, unit='', digits=1, q='p95'):
            """分位数：CPU/内存看 P95（稳态最差），FPS 看 P05（最差 5% 的帧率）"""
            v = m.get(q)
            if v is None:
                return '--'
            label = 'P95' if q == 'p95' else 'P05'
            return f"{label} {v:.{digits}f}{unit}"

        lines = [
            "📊 性能监控报告",
            "=" * 56,
            f"目标: {self.package_name or '系统整体'}    PID: {s['pid'] or '--'}"
            f"    模式: {s['mode']}",
            f"采样: {s['sample_count']} 次    时长 {self._fmt_duration(s['elapsed'])}"
            f"    间隔 {self.interval:g}s",
            "-" * 56,
            f"CPU 占用:    {fmt(s['cpu'], '%', 2)}",
            f"             {fmt_p(s['cpu'], '%', 2)}",
            f"PSS 内存:    {fmt(s['pss'], ' MB')}",
            f"             {fmt_p(s['pss'], ' MB')}",
            f"RSS 内存:    {fmt(s['rss'], ' MB')}",
            f"             {fmt_p(s['rss'], ' MB')}",
            f"Java Heap:   {fmt(s['java'], ' MB')}",
            f"Native Heap: {fmt(s['native'], ' MB')}",
            f"FPS:         {fmt(s['fps'], '', 2)}",
            f"             {fmt_p(s['fps'], '', 2, 'p05')}",
            f"卡顿率:      {fmt(s['jank'], ' %')}",
            "-" * 56,
        ]

        threads = s['threads']
        if threads:
            lines.append(f"CPU 热点线程 TOP {min(10, len(threads))} (按峰值):")
            for t in sorted(threads, key=lambda x: x['peak'], reverse=True)[:10]:
                lines.append(f"  [{t['tid']}] {t['name']:<24} "
                             f"当前 {t['cur']:6.2f}%  峰值 {t['peak']:6.2f}%")

        lines.append("=" * 56)
        return '\n'.join(lines)

    # ------------------------------------------------ 内部实现

    def _clear_internal(self):
        self._metric_cpu = _Metric()
        self._metric_pss = _Metric()
        self._metric_rss = _Metric()
        self._metric_java = _Metric()
        self._metric_native = _Metric()
        self._metric_fps = _Metric()
        self._metric_jank = _Metric()
        self._thread_stats: Dict[int, ThreadStat] = {}
        self.history.clear()
        self._fps_base_total = None
        self._fps_base_time = None
        self._sample_seq = 0
        self._alert_streak = 0
        self._alert_active = False
        self.pid = None
        self.mode = 'idle'
        self._publish_stats()

    def _notify_status(self, msg: str):
        if self.update_callback:
            try:
                self._post_main(self.update_callback, dict(self.stats), msg)
                return
            except Exception:
                pass
        # 无回调时直接打印
        logging.info(f"[性能监控] {msg}")

    def _post_main(self, fn, *args):
        """调度到主线程执行"""
        if self.app is not None and hasattr(self.app, 'root'):
            self.app.root.after(0, lambda: fn(*args))
        else:
            fn(*args)

    def _run(self, cmd: str):
        return run_adb_command(cmd)

    def _sample_loop(self, single_shot: bool = False):
        """采样主循环（后台线程）

        每个周期：读起点 → 等待差分窗口 → 终点采集（并行） → 差分计算 → 聚合 → 回调 UI。
        CPU 终点每次都采（/proc 读取极快）；内存/FPS 走 dumpsys 较慢（真机单次可达 1~2s），
        按 HEAVY_EVERY 降频，避免把整个采样周期拖到数秒。
        """
        try:
            # 设备探测并行执行：串行 4 次 adb 会让"开始监控"后首个数据点延迟数秒
            pkg = self.package_name
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                f_clk = ex.submit(self._detect_clk_tck)
                f_core = ex.submit(self._detect_cpu_max)
                f_pid = ex.submit(self._detect_pid, pkg) if pkg else None
                self._clk_tck = f_clk.result()
                self._cpu_max = f_core.result()
                pid = f_pid.result() if f_pid else None

            # 确定采集模式：proc（精确差分）/ cpuinfo（降级）/ system（整体）
            if pkg:
                self.pid = pid
                self.mode = 'proc' if self._check_proc_readable() else 'cpuinfo'
            else:
                self.mode = 'system'
            self._publish_stats()

            while True:
                self._sample_seq += 1
                point = self._read_cpu_point()
                t_a = time.time()

                wait = self.FPS_BASELINE_INTERVAL if single_shot else self.interval
                if self.stop_event.wait(wait):
                    return  # 收到停止信号
                if not single_shot and not self.monitoring:
                    return  # 停止发生在上一轮 adb 调用期间，不再继续采集

                # 首轮只采 CPU（/proc 读取极快），让第一个数字尽快出现；
                # 内存/FPS 这类 dumpsys 慢调用从第 2 轮开始按 HEAVY_EVERY 降频
                heavy = single_shot or (self._sample_seq % self.HEAVY_EVERY == 0)

                # 终点采集：CPU 终点与内存/渲染统计并行（复用常驻线程池）
                mem = None
                fps = jank = None
                if heavy:
                    f_end = self._pool.submit(self._read_cpu_point)
                    f_mem = self._pool.submit(self._read_memory)
                    f_render = self._pool.submit(self._read_render_stats)
                    endpoint = f_end.result()
                    mem = f_mem.result()
                    render = f_render.result()
                    fps, jank = render['fps'], render['jank']
                else:
                    endpoint = self._read_cpu_point()

                # RSS 来自同一份 /proc/status（与 CPU 同频，比 PSS 快得多）
                rss = endpoint[2] if self.mode == 'proc' else None

                cpu_val = self._diff_cpu(point, endpoint, t_a)
                alert, alert_msg = self._check_alerts(cpu_val, mem)
                self._aggregate(cpu_val, mem, rss, fps, jank)
                self._publish_stats(alert)

                # UI 回调（alert_msg 为 None 时不刷状态栏）
                if self.update_callback:
                    try:
                        self._post_main(self.update_callback, dict(self.stats), alert_msg)
                    except Exception as e:
                        logging.debug(f"[性能监控] 回调失败: {e}")

                if single_shot:
                    self.monitoring = False
                    return

        except Exception as e:
            logging.error(f"[性能监控] 采样循环异常: {e}", exc_info=True)
            self.monitoring = False
            try:
                self._post_main(self._notify_status, f"✗ 性能监控错误: {e}")
            except Exception:
                pass

    # --- 各项采集 ---

    def _detect_clk_tck(self) -> int:
        out, ok = self._run("adb shell getconf CLK_TCK")
        return PerfParsers.parse_clk_tck(out) if ok else 100

    def _detect_cpu_max(self) -> float:
        """CPU 上限 = 核数 × 100%（多核满载可超过 100%）"""
        out, ok = self._run("adb shell nproc")
        m = re.search(r'(\d+)', out or '')
        if ok and m:
            return int(m.group(1)) * 100.0
        return 100.0

    def _detect_pid(self, package_name: str) -> Optional[int]:
        out, ok = self._run(f"adb shell pidof {package_name}")
        if ok:
            pid = PerfParsers.parse_pidof(out)
            if pid:
                return pid
        return None

    def _check_proc_readable(self) -> bool:
        """探测 /proc/<pid>/stat 是否可读（决定 proc / cpuinfo 模式）"""
        if not self.pid:
            return False
        out, ok = self._run(f"adb shell cat /proc/{self.pid}/stat")
        return ok and bool(PerfParsers.parse_proc_ticks(out))

    def _read_cpu_point(self):
        """读取一个 CPU 采样点（起点与终点复用）

        Returns:
            (kind, payload, rss_mb)
            - sys:     payload = 整体 jiffies 总数，rss = None
            - proc:    payload = {tid: (name, ticks)}，rss = VmRSS(MB)
            - cpuinfo: payload = CPU 百分比（dumpsys 自带时间窗），rss = None
        """
        if self.mode == 'system':
            out, ok = self._run("adb shell cat /proc/stat")
            return ('sys', PerfParsers.parse_proc_stat_cpu(out) if ok else None, None)
        if self.mode == 'proc':
            ticks, rss = self._read_proc_snapshot()
            return ('proc', ticks, rss)
        if self.package_name:
            out, ok = self._run("adb shell dumpsys cpuinfo")
            return ('cpuinfo',
                    PerfParsers.parse_cpuinfo_line(out, self.package_name) if ok else None,
                    None)
        return ('cpuinfo', None, None)

    def _diff_cpu(self, point, endpoint, t_a: float) -> Optional[float]:
        """差分计算 CPU%（进程级返回值；线程级聚合在 proc 分支内完成）"""
        kind_a, payload = point[0], point[1]
        end = endpoint[1] if endpoint else None
        now = time.time()
        elapsed = now - t_a
        if elapsed <= 0.2:
            return None

        if kind_a == 'cpuinfo':
            return end if isinstance(end, (int, float)) else None

        if kind_a == 'sys':
            if payload is None or end is None:
                return None
            delta = end - payload
            if delta <= 0:
                return None
            return round(min(delta / elapsed / self._clk_tck * 100.0, 100.0), 2)

        # proc 模式：进程 + 全部线程差分
        ticks_b = end
        if not payload or not ticks_b:
            # 进程可能重启，尝试重新定位
            if self.package_name:
                self.pid = self._detect_pid(self.package_name)
            return None

        for tid, (name, ticks) in ticks_b.items():
            a = payload.get(tid)
            if not a:
                continue  # 新线程首个周期无基准，下一轮纳入
            delta = (ticks - a[1]) / elapsed / self._clk_tck * 100.0
            cur = min(max(delta, 0.0), self._cpu_max)
            stat = self._thread_stats.get(tid)
            if stat:
                stat.update(cur)
            else:
                self._thread_stats[tid] = ThreadStat(tid, name, cur)

        leader_a = payload.get(self.pid)
        leader_b = ticks_b.get(self.pid)
        if leader_a and leader_b:
            delta = (leader_b[1] - leader_a[1]) / elapsed / self._clk_tck * 100.0
            return round(min(max(delta, 0.0), self._cpu_max), 2)
        return None

    def _read_proc_snapshot(self):
        """一次读取进程+线程 CPU jiffies，并顺带读 /proc/<pid>/status 拿 VmRSS

        注意：命令里不能带 `2>/dev/null` 之类的 shell 重定向——
        run_adb_command 走 Windows 本机 cmd（shell=True），`2>` 会被本机解释成
        重定向到不存在的 \\dev\\null，导致整条命令直接失败。
        """
        if not self.pid:
            return None, None
        out, ok = self._run(
            f"adb shell cat /proc/{self.pid}/stat /proc/{self.pid}/task/*/stat "
            f"/proc/{self.pid}/status")
        if not ok:
            return None, None
        ticks, rss = PerfParsers.parse_proc_snapshot(out)
        return (ticks or None), rss

    def _read_memory(self) -> Dict[str, Optional[float]]:
        if self.mode == 'system':
            out, ok = self._run("adb shell cat /proc/meminfo")
            return PerfParsers.parse_system_meminfo(out) if ok else \
                {'pss': None, 'java': None, 'native': None}

        out, ok = self._run(f"adb shell dumpsys meminfo {self.package_name}")
        if not ok:
            return {'pss': None, 'java': None, 'native': None}
        return PerfParsers.parse_meminfo(out)

    def _read_render_stats(self) -> Dict[str, Optional[float]]:
        """一次 gfxinfo 同时拿 FPS（帧数差分）与 Janky 占比

        Returns:
            {'fps': ..., 'jank': ...}，取不到时为 None
        """
        now = time.time()
        cmd = "adb shell dumpsys gfxinfo"
        if self.package_name:
            cmd += f" {self.package_name}"

        out, ok = self._run(cmd)
        if not ok or not out.strip():
            return {'fps': None, 'jank': None}

        jank = PerfParsers.parse_janky_percent(out)
        total = PerfParsers.parse_total_frames(out)
        if total is None:
            return {'fps': None, 'jank': jank}

        fps = None
        if self._fps_base_total is not None and self._fps_base_time is not None:
            delta = total - self._fps_base_total
            elapsed = now - self._fps_base_time
            if delta < 0:
                logging.debug("[FPS监控] 帧计数回退，重置基准")
            elif elapsed > 0.2:
                fps = min(delta / elapsed, 240.0)
        else:
            # 无基准：本周期已在 _sample_loop 等过一个间隔（单次快照等 1s），
            # 直接补采一次
            out2, ok2 = self._run(cmd)
            if ok2 and out2.strip():
                total2 = PerfParsers.parse_total_frames(out2)
                now2 = time.time()
                if total2 is not None and total2 >= total:
                    elapsed2 = now2 - now
                    if elapsed2 > 0.2:
                        fps = min((total2 - total) / elapsed2, 240.0)
                    total = total2

        self._fps_base_total = total
        self._fps_base_time = now
        return {'fps': round(fps, 2) if fps is not None else None, 'jank': jank}

    # --- 聚合与发布 ---

    def _aggregate(self, cpu_val, mem, rss, fps, jank):
        """聚合一次采样；mem/rss/fps/jank 在非采集周期可能为 None（沿用上次读数）"""
        self._metric_cpu.update(cpu_val)
        self._metric_rss.update(rss)
        if mem is not None:
            self._metric_pss.update(mem.get('pss'))
            self._metric_java.update(mem.get('java'))
            self._metric_native.update(mem.get('native'))
        self._metric_fps.update(fps)
        self._metric_jank.update(jank)

        # 记录完整采样点（供数值回看与 CSV 导出）
        ts = time.strftime("%H:%M:%S")
        self.history.append((ts,
                             self._metric_cpu.cur,
                             self._metric_pss.cur,
                             self._metric_rss.cur,
                             self._metric_java.cur,
                             self._metric_native.cur,
                             self._metric_fps.cur,
                             self._metric_jank.cur))

    def _check_alerts(self, cpu_val, mem):
        """阈值告警：连续超阈值 N 次才提示一次，恢复后自动解除

        Returns:
            (alert_now, alert_msg)；alert_msg 仅在刚触发告警时非 None
        """
        # 用本次采样值判定，取不到时沿用上一次读数（降频周期内存不刷新）
        cpu = cpu_val if cpu_val is not None else self._metric_cpu.cur
        pss_new = mem.get('pss') if mem else None
        pss = pss_new if pss_new is not None else self._metric_pss.cur

        cpu_hit = cpu is not None and cpu >= Config.PERF_ALERT_CPU_PERCENT
        mem_hit = pss is not None and pss >= Config.PERF_ALERT_MEM_MB
        hit = cpu_hit or mem_hit

        msg = None
        if hit:
            self._alert_streak += 1
            if self._alert_streak >= Config.PERF_ALERT_STREAK and not self._alert_active:
                self._alert_active = True
                parts = []
                if cpu_hit:
                    parts.append(f"CPU {cpu:.1f}% (阈值 {Config.PERF_ALERT_CPU_PERCENT}%)")
                if mem_hit:
                    parts.append(f"内存 {pss:.0f}MB (阈值 {Config.PERF_ALERT_MEM_MB}MB)")
                msg = (f"⚠ 性能告警: {' / '.join(parts)}，"
                       f"已连续 {self._alert_streak} 次超过阈值")
        else:
            if self._alert_active:
                self._alert_active = False
            self._alert_streak = 0

        return hit, msg

    def _publish_stats(self, alert: bool = False):
        threads = sorted(self._thread_stats.values(),
                         key=lambda t: t.cur, reverse=True)[:self.THREAD_TABLE_MAX]
        self.stats = {
            'cpu': self._metric_cpu.to_dict(),
            'pss': self._metric_pss.to_dict(),
            'rss': self._metric_rss.to_dict(),
            'java': self._metric_java.to_dict(),
            'native': self._metric_native.to_dict(),
            'fps': self._metric_fps.to_dict(),
            'jank': self._metric_jank.to_dict(),
            'alert': alert,
            'threads': [t.to_dict() for t in threads],
            'sample_count': self._sample_seq,
            'elapsed': max(0.0, time.time() - self._start_time),
            'pid': self.pid,
            'mode': self.mode,
        }

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
