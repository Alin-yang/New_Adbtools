"""
性能采集器（重写版）

与旧版 `performance_monitor.py` 的根本区别
--------------------------------------
旧版有三个让数据失真的结构性问题，本版逐一修掉：

1. **时间基准错位** → CPU% 系统性低估
   旧版 `_diff_cpu` 里 `now = time.time()` 取在 `dumpsys` 阻塞**之后**，
   于是 dumpsys 的 1.5~3 秒被算进了 CPU 差分窗口 → 低估 38%~56%。
   本版：每个采集点自带**读取完成时刻**的时间戳，差分只用两个 CPU 点的
   读取完成时刻；dumpsys 采集与 CPU 差分**完全解耦**（并行执行，不进窗口）。

2. **进程口径与线程口径混淆** → 进程 CPU 少算 94%
   旧版把 `/proc/pid/stat`（线程组总量）和 `/proc/pid/task/*/stat`（单线程）
   存进同一个字典，后者覆盖前者 → 进程 CPU 实际取的是**主线程**的值。
   本版：`parse_proc_snapshot` 按 cat 的参数顺序**分离两种口径**，
   进程 CPU = 线程组总量；线程表**不含** pid 行（否则重复计算）。

3. **PID 定位不可靠** → 可能测的是 init 进程
   实测小米盒子 Android 6 上 `pidof <包名>` 忽略参数、返回全部 155 个 PID，
   旧实现取第一个数字 → PID=1（init）→ CPU 恒为 0、线程表全是内核线程。
   本版：`perf_locator.ProcessLocator` 多级回退 + 合理性校验。

另外新增：
- **帧数据两条路径**：Android 10+ 用 framestats 逐帧（能算帧时间分布）；
  老版本用「总数差分 + janky 百分比反推」得到窗口内真实卡顿率。
- **无渲染活动可表达**：帧数差分为 0 时，FPS 记为 None（未测得）而非 0。
- **采样质量元数据**：每次采样记录实际间隔、各采集耗时、降级情况，
  报告里展示，避免用户把不可信数据当结论。
"""
import concurrent.futures
import logging
import re
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import Config
from modules import perf_parsers as P
from modules.perf_locator import ProcessLocator
from utils import run_adb_command


# ====================================================================== #
# 聚合器
# ====================================================================== #

class Metric:
    """指标聚合器：当前 / 均值 / 峰值 / P95 / P05

    ⚠️ 分位数用**滑动窗口**（最近 600 个样本），
       而不是历史全量 —— 全量会让很久以前的一次尖峰永久污染 P95。
    """

    __slots__ = ('cur', 'avg', 'peak', 'p95', 'p05',
                 '_sum', '_count', '_values', 'valid')

    WINDOW = 600

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
        """更新一次采样

        ⚠️ value=None 表示「本周期未测得」（比如无渲染活动），
           此时**不更新**任何统计量 —— 保持上一次的读数，
           但 history 里记 None（不伪造数据）。
        """
        if value is None:
            return
        self.valid = True
        self.cur = value
        self._sum += value
        self._count += 1
        self.avg = self._sum / self._count
        if self.peak is None or value > self.peak:
            self.peak = value

        self._values.append(value)
        if len(self._values) > self.WINDOW:
            self._values.pop(0)
        ordered = sorted(self._values)
        n = len(ordered)
        self.p95 = ordered[int(round(0.95 * (n - 1)))]
        self.p05 = ordered[int(round(0.05 * (n - 1)))]

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {'cur': self.cur, 'avg': self.avg, 'peak': self.peak,
                'p95': self.p95, 'p05': self.p05}


class ThreadStat:
    """单个线程的 CPU 统计"""

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


# ====================================================================== #
# 一个采样点的原始数据
# ====================================================================== #

class CpuPoint:
    """一次 /proc 采集点

    ⚠️ ts 是**读取完成时刻** —— 差分必须用它，而不是「读之前」或
       「整轮采集结束后」的时刻，否则 dumpsys 的耗时会污染窗口。
    """

    __slots__ = ('ts', 'group_ticks', 'threads', 'rss_mb')

    def __init__(self, ts: float, group_ticks: Optional[int],
                 threads: Dict[int, Tuple[str, int]], rss_mb: Optional[float]):
        self.ts = ts
        self.group_ticks = group_ticks
        self.threads = threads
        self.rss_mb = rss_mb


# ====================================================================== #
# 采集器
# ====================================================================== #

class PerfCollector:
    """性能数据采集（不碰 UI）"""

    HISTORY_MAX = 600
    THREAD_TABLE_MAX = 50

    def __init__(self, app=None, device: Optional[str] = None,
                 update_callback: Optional[Callable] = None):
        # ⚠️ app 必须第一个参数：app.py 里是 PerfCollector(self, device=...)
        self.app = app
        self.device = device
        self.update_callback = update_callback
        self.locator = ProcessLocator(device)

        self.monitoring = False
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

        self.package_name: Optional[str] = None
        self.interval = 2.0
        # 告警阈值（可被场景模板覆盖）：cpu% / pss MB
        self.thresholds: Dict[str, float] = {
            'cpu': Config.PERF_ALERT_CPU_PERCENT,
            'pss': Config.PERF_ALERT_MEM_MB,
        }
        self._alert_streak = 0
        self._alert_active = False
        self._alert_msg: Optional[str] = None
        self.pid: Optional[int] = None
        self.pids: List[int] = []
        self.mode = 'idle'          # idle / proc / cpuinfo / system

        self._clk_tck = 100
        self._clk_tck_estimated = False
        self._clk_tck_estimate = 100
        self._cpu_max = 100.0
        self._start_time = 0.0

        self._metrics: Dict[str, Metric] = {}
        self._thread_stats: Dict[int, ThreadStat] = {}

        # 帧数据基准（用于差分）
        self._gfx_base: Optional[Dict[str, Any]] = None
        self._gfx_base_ts: Optional[float] = None
        self._last_render: Optional[Dict[str, Any]] = None
        self._last_frames: Optional[List[Dict[str, Any]]] = None
        self._last_mem: Optional[Dict[str, Optional[float]]] = None
        self._last_mem_ts: Optional[float] = None
        self._frame_samples: List[Dict[str, Any]] = []

        # 采样质量
        self._seq = 0
        self._ok_points = 0
        self._fail_points = 0
        self._last_interval_actual = 0.0
        self._collect_costs: Dict[str, float] = {}
        self._degraded = False

        self.history: deque = deque(maxlen=self.HISTORY_MAX)
        self._reset_metrics()

    # ------------------------------------------------------------ 对外
    def start(self, package_name: Optional[str] = None,
              interval: float = 2.0) -> bool:
        if self.monitoring:
            return False
        self.package_name = (package_name or None)
        try:
            self.interval = max(1.0, float(interval))
        except (TypeError, ValueError):
            self.interval = 2.0
        self.monitoring = True
        self.stop_event.clear()
        self._reset_metrics()
        self._start_time = time.time()
        self.thread = threading.Thread(target=self._loop, daemon=True,
                                       name="PerfCollector")
        self.thread.start()
        return True

    def stop(self) -> bool:
        """停止（不 join —— 采样线程可能正卡在 adb 调用里，join 会卡 UI）"""
        if not self.monitoring:
            return False
        self.monitoring = False
        self.stop_event.set()
        return True

    # 兼容旧调用点（app.py 里用了 stop_monitoring）
    stop_monitoring = stop
    start_monitoring = start

    def set_scenario(self, key: str):
        """应用场景模板的阈值

        场景决定「什么算超标」—— 视频播放 CPU 80% 可能很正常，
        界面流畅时内存 800MB 才算问题。所以阈值不该写死。
        """
        try:
            from modules import perf_scenario as S
            scn = S.get(key)
            for metric, limit in scn.thresholds.items():
                if metric in ('cpu', 'pss'):
                    self.thresholds[metric] = limit
        except Exception:
            pass

    def clear(self):
        self._reset_metrics()

    def snapshot_once(self, package_name: Optional[str] = None) -> Dict[str, Any]:
        """单次快照

        ⚠️ 旧实现这里有个 bug：没清 stop_event，用户点过「停止」后
           stop_event 一直是 set，wait() 立即返回 → 采到空数据。
        """
        if self.monitoring:
            return self._stats_snapshot()
        pkg = package_name if package_name is not None else self.package_name
        self.package_name = pkg or None
        self._reset_metrics()
        self._start_time = time.time()
        # 单次快照用独立的一次性流程，不复用循环里的 stop_event 等待
        self.stop_event.clear()
        try:
            self._collect_once()
        finally:
            self.stop_event.set()
        return self._stats_snapshot()

    # ------------------------------------------------------------ 内部
    def _reset_metrics(self):
        self._metrics = {k: Metric() for k in
                         ('cpu', 'pss', 'rss', 'java', 'native',
                          'fps', 'jank', 'p95_frame', 'p99_frame')}
        self._thread_stats = {}
        self.history.clear()
        self._gfx_base = None
        self._gfx_base_ts = None
        self._frame_samples = []
        self._seq = 0
        self._alert_streak = 0
        self._alert_active = False
        self._alert_msg = None
        self._ok_points = 0
        self._fail_points = 0
        self._last_interval_actual = 0.0
        self._collect_costs = {}
        self._degraded = False
        self.pid = None
        self.pids = []
        self.mode = 'idle'

    def _run(self, cmd: str) -> Tuple[str, bool]:
        return run_adb_command(cmd, target_device=self.device)

    # ---------------------------------------------------------- 环境探测
    def _detect_env(self):
        """探测 CLK_TCK / 核数 / PID，并确定采集模式

        ⚠️ 顺序有依赖：核数必须**先**于 CLK_TCK 探测 ——
           推算 CLK_TCK 时要用核数把 /proc/stat 的多核累加值除回去。
           PID 定位与核数无依赖，可以并行。
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_core = ex.submit(self._detect_cpu_max)
            f_pid = ex.submit(self._locate_pid)
            self._cpu_max = f_core.result()
            self.pids = f_pid.result() or []
            self.pid = self.pids[0] if self.pids else None
        # 依赖核数，必须放在并行块之后
        self._clk_tck = self._detect_clk_tck()
        self._resolve_mode()

    def _resolve_mode(self):
        """确定采集模式

        proc     —— /proc 可读，精确差分
        cpuinfo  —— /proc 不可读，降级（精度较低，报告里会提示）
        system   —— 没填包名，监控整机
        """
        if self.package_name:
            self.mode = 'proc' if self.pid else 'cpuinfo'
            if not self.pid:
                self._degraded = True
        else:
            self.mode = 'system'

    def _detect_clk_tck(self) -> int:
        """CLK_TCK（每秒 tick 数）

        ⚠️ Android 内核的 USER_HZ 恒为 100（CONFIG_HZ=100），
           这是标准值，优先用它。

           `getconf CLK_TCK` 在部分 Android 上不存在（实测小米盒子
           Android 6 就报 "getconf: not found"），此时直接用 100。

           ⚠️ 不要试图用 /proc/stat 的自增速率去「推算」CLK_TCK：
              adb 命令的数据采集时刻在**命令执行期间**，
              而返回时刻在传输完成之后，两者差一个不可对齐的传输延迟
              （实测能推出 115~135，明显偏离 100），反而把 CPU 算错。
              推算值只作诊断参考，不参与计算。
        """
        out, ok = self._run("adb shell getconf CLK_TCK")
        m = re.search(r'(\d+)', out or '')
        if ok and m:
            val = int(m.group(1))
            if 1 <= val <= 1000:
                self._clk_tck_estimated = False
                return val
        self._clk_tck_estimated = True
        self._clk_tck_estimate = self._estimate_clk_tck()
        return 100

    def _estimate_clk_tck(self) -> int:
        """估算 CLK_TCK（**仅作诊断参考，不参与 CPU 计算**）

        用 /proc/stat 的自增速率粗略推算，误差可达 ±30%
        （adb 传输延迟不可对齐），所以只用来在报告里提示
        「本机 getconf 不可用，已按标准值 100 计算」。
        """
        try:
            cores = max(1, int(self._cpu_max // 100))
            first = self._read_proc_stat_cpu(self._run("adb shell cat /proc/stat")[0])
            if first is None:
                return 100
            time.sleep(1.0)
            second = self._read_proc_stat_cpu(self._run("adb shell cat /proc/stat")[0])
            if second is None or second <= first:
                return 100
            val = int(round((second - first) / cores))
            if 24 <= val <= 1000:
                return val
        except Exception:
            pass
        return 100

    @staticmethod
    def _read_proc_stat_cpu(output: str) -> Optional[float]:
        for line in (output or '').splitlines():
            if line.startswith('cpu'):
                try:
                    values = [int(v) for v in line.split()[1:]]
                    if len(values) >= 4:
                        return float(sum(values))
                except ValueError:
                    return None
        return None

    def _detect_cpu_max(self) -> float:
        """CPU 上限 = 核数 × 100（单核百分比口径，多核可超过 100）

        ⚠️ `nproc` 在部分 Android 上不存在（实测小米盒子就没有），
           这时回退到数 /proc/cpuinfo 里的 processor 行。
        """
        out, ok = self._run("adb shell nproc")
        m = re.search(r'(\d+)', out or '')
        if ok and m:
            cores = int(m.group(1))
            if cores > 0:
                return cores * 100.0
        # 回退：数 /proc/cpuinfo 的 processor 行
        out, ok = self._run("adb shell cat /proc/cpuinfo")
        if ok and out:
            cores = len(re.findall(r'^processor\s*:', out, re.M))
            if cores > 0:
                return cores * 100.0
        return 100.0

    def _locate_pid(self) -> List[int]:
        return self.locator.find_pids(self.package_name) if self.package_name else []

    # ---------------------------------------------------------- /proc 采集
    def _read_point(self) -> Optional[CpuPoint]:
        """按当前模式读取一个 CPU 采集点"""
        if self.mode == 'system':
            return self._read_system_point()
        if self.mode == 'cpuinfo':
            return self._read_cpuinfo_point()
        return self._read_proc_point()

    def _read_cpuinfo_point(self) -> Optional[CpuPoint]:
        """降级路径：/proc 不可读时用 dumpsys cpuinfo

        ⚠️ dumpsys cpuinfo 自带时间窗（通常是上次采样后 3 秒），
           所以它给的是**绝对百分比**而不是差分值 ——
           直接当采样点用，差分逻辑要单独走（见 _diff_cpuinfo）。
        """
        t0 = time.time()
        out, ok = self._run("adb shell dumpsys cpuinfo")
        ts = time.time()
        self._collect_costs['cpuinfo'] = (self._collect_costs.get('cpuinfo', 0)
                                          + (ts - t0))
        if not ok or not out:
            self._fail_points += 1
            return None
        value = P.parse_cpuinfo_line(out, self.package_name or '')
        if value is None:
            self._fail_points += 1
            return None
        self._ok_points += 1
        # 用绝对值承载，_diff_cpuinfo 直接取用
        return CpuPoint(ts, int(value * 100), {}, None)

    def _read_system_point(self) -> Optional[CpuPoint]:
        """整机模式：/proc/stat 的整体 CPU 忙碌率"""
        t0 = time.time()
        out, ok = self._run("adb shell cat /proc/stat")
        ts = time.time()
        self._collect_costs['proc'] = (self._collect_costs.get('proc', 0)
                                       + (ts - t0))
        if not ok:
            self._fail_points += 1
            return None
        total = P.parse_proc_stat_cpu(out)
        if total is None:
            self._fail_points += 1
            return None
        self._ok_points += 1
        return CpuPoint(ts, int(total), {}, None)

    def _read_proc_point(self) -> Optional[CpuPoint]:
        """读一次 /proc（进程 + 全部线程 + RSS）"""
        if not self.pid:
            return None
        t0 = time.time()
        out, ok = self._run(
            f"adb shell cat /proc/{self.pid}/stat "
            f"/proc/{self.pid}/task/*/stat "
            f"/proc/{self.pid}/status")
        if not ok:
            self._fail_points += 1
            return None
        parsed = P.parse_proc_snapshot(out, self.pid)
        # ⚠️ ts 取在**读取完成**的瞬间
        ts = time.time()
        self._collect_costs['proc'] = self._collect_costs.get('proc', 0) + (ts - t0)
        if parsed['group_ticks'] is None and not parsed['threads']:
            self._fail_points += 1
            return None
        self._ok_points += 1
        return CpuPoint(ts, parsed['group_ticks'], parsed['threads'],
                        parsed['rss_mb'])

    # ---------------------------------------------------------- dumpsys 采集
    def _mem_worker(self):
        """内存采集后台线程

        ⚠️ dumpsys meminfo 要 1~2 秒，若放在采样周期里同步等，
           会把采样周期从 2 秒拖到 3.5 秒。
           所以让它在**独立线程**里持续跑，主循环只读缓存。
        """
        while not self.stop_event.is_set():
            try:
                res, cost = self._read_memory()
                if res:
                    self._last_mem = res
                    self._last_mem_ts = time.time()
            except Exception as e:
                logging.debug(f"[性能采集] 内存采集异常: {e}")
            # 内存变化慢，间隔比主采样周期长一点即可
            if self.stop_event.wait(max(2.0, self.interval * 1.5)):
                return

    def _read_memory(self) -> Tuple[Dict[str, Optional[float]], float]:
        t0 = time.time()
        if self.mode == 'system':
            out, ok = self._run("adb shell cat /proc/meminfo")
            res = (P.parse_system_meminfo(out) if ok
                   else {'pss': None, 'java': None, 'native': None})
        else:
            out, ok = self._run(f"adb shell dumpsys meminfo {self.package_name}")
            res = (P.parse_meminfo(out) if ok
                   else {'pss': None, 'java': None, 'native': None})
        cost = time.time() - t0
        self._collect_costs['meminfo'] = self._collect_costs.get('meminfo', 0) + cost
        return res, cost

    def _read_render(self) -> Dict[str, Any]:
        """读渲染统计（累计部分）

        返回 {'gfx': {...}, 'frames': [...]|None, 'cost': float}
        - gfx   ：gfxinfo 累计统计（total_frames / janky / 百分位…）
        - frames ：framestats 逐帧数据（由独立线程采集，见 _framestats_worker）

        ⚠️ 这里**只读一次** gfxinfo（累计统计）——
           framestats 那次调用要 1.5 秒，放在关键路径上会拖长采样周期。
        """
        t0 = time.time()
        out, ok = self._run(f"adb shell dumpsys gfxinfo {self.package_name}")
        gfx = P.parse_gfxinfo(out) if ok and out else {}
        cost = time.time() - t0
        self._collect_costs['gfxinfo'] = self._collect_costs.get('gfxinfo', 0) + cost
        return {'gfx': gfx, 'frames': self._last_frames, 'cost': cost}

    def _framestats_worker(self):
        """framestats 逐帧采集后台线程

        ⚠️ dumpsys gfxinfo <pkg> framestats 要 1.5 秒以上，
           放在采样关键路径上会把周期从 2 秒拖到 3.5 秒。
           这里独立跑，主循环只读缓存。
        """
        while not self.stop_event.is_set():
            try:
                out, ok = self._run(
                    f"adb shell dumpsys gfxinfo {self.package_name} framestats")
                if ok and out:
                    parsed = P.parse_framestats(out)
                    if parsed:
                        self._last_frames = parsed['frames']
            except Exception as e:
                logging.debug(f"[性能采集] framestats 采集异常: {e}")
            if self.stop_event.wait(max(3.0, self.interval * 2)):
                return

    # ---------------------------------------------------------- 差分
    def _diff_cpu(self, a: CpuPoint, b: CpuPoint) -> Optional[float]:
        """进程 CPU% 差分（线程组口径）

        ⚠️ elapsed = b.ts - a.ts，两个 ts 都是**读取完成时刻**，
           窗口里不含任何 dumpsys 耗时。
        """
        if a.group_ticks is None or b.group_ticks is None:
            return None
        # cpuinfo 模式：值本身就是绝对百分比，直接取终点值
        if self.mode == 'cpuinfo':
            return round(b.group_ticks / 100.0, 2)
        # system 模式：整体忙碌率，按比例缩放到 0~100
        if self.mode == 'system':
            elapsed = b.ts - a.ts
            if elapsed <= 0.2:
                return None
            delta = b.group_ticks - a.group_ticks
            if delta <= 0:
                return None
            return round(min(delta / elapsed / self._clk_tck * 100.0, 100.0), 2)
        elapsed = b.ts - a.ts
        if elapsed <= 0.2:
            return None
        delta = b.group_ticks - a.group_ticks
        if delta < 0:
            return None
        return round(min(delta / elapsed / self._clk_tck * 100.0, self._cpu_max), 2)

    def _diff_threads(self, a: CpuPoint, b: CpuPoint) -> None:
        """更新各线程的 CPU 统计（线程表不含 pid 行，避免与进程级重复）"""
        elapsed = b.ts - a.ts
        if elapsed <= 0.2:
            return
        for tid, (name, tb) in b.threads.items():
            ta = a.threads.get(tid)
            if not ta:
                continue                      # 新线程，下轮才有基准
            delta = tb - ta[1]
            if delta < 0:
                continue
            cur = min(max(delta / elapsed / self._clk_tck * 100.0, 0.0),
                      self._cpu_max)
            stat = self._thread_stats.get(tid)
            if stat:
                stat.update(cur)
            else:
                self._thread_stats[tid] = ThreadStat(tid, name, cur)

    def _diff_render(self, gfx: Dict[str, Any], frames, ts: float) -> Dict[str, Any]:
        """帧数据差分 → 窗口内 FPS 与卡顿率

        ⚠️ **FPS 一律用「累计帧数差分」算**，两条路径都一样：
           framestats 给的是「进程启动至今的全部帧」，不是窗口内的，
           直接拿它算 FPS 会得到历史平均值（毫无意义）。
           framestats 只用来**补充**帧耗时分布与精确 jank 比例。
        """
        result = {'fps': None, 'jank': None, 'p95_frame': None,
                  'p99_frame': None, 'frame_durations': []}

        # ── FPS 与卡顿率：累计值差分（两条路径共用）────────────
        total = gfx.get('total_frames')
        base = self._gfx_base
        base_ts = self._gfx_base_ts
        self._gfx_base = gfx
        self._gfx_base_ts = ts

        if total is not None and base is not None and base_ts is not None \
                and base.get('total_frames') is not None:
            elapsed = ts - base_ts
            d_total = total - base['total_frames']
            if d_total > 0 and elapsed > 0.2:
                result['fps'] = round(min(d_total / elapsed, 240.0), 2)
                # janky 绝对数差分 → 窗口内真实卡顿率
                j_now = gfx.get('janky_frames')
                j_base = base.get('janky_frames')
                if j_now is not None and j_base is not None:
                    d_janky = j_now - j_base
                    if 0 <= d_janky <= d_total:
                        result['jank'] = round(d_janky / d_total * 100.0, 2)
            # d_total == 0 → 本周期**没有任何绘制活动**，
            #   不能上报 FPS=0（会被误读成"应用卡死"），保持 None

        # ── framestats 增强：帧耗时分布 + 精确 jank ─────────────
        if frames:
            durations = [f['duration_ms'] for f in frames]
            if durations:
                ordered = sorted(durations)
                n = len(ordered)
                result['p95_frame'] = round(
                    ordered[int(round(0.95 * (n - 1)))], 2)
                result['p99_frame'] = round(
                    ordered[int(round(0.99 * (n - 1)))], 2)
                result['frame_durations'] = durations
                # framestats 的 jank 判定更准（有 deadline），
                # 但它是「全部历史帧」的统计，仅作参考；
                # 窗口内卡顿率以上面的差分值为准。
                if result['jank'] is None:
                    janky = sum(1 for f in frames if f['jank'])
                    result['jank'] = round(janky / len(frames) * 100.0, 2)
        return result

    # ---------------------------------------------------------- 主循环
    def _loop(self):
        try:
            self._detect_env()
            # 内存采集独立线程（dumpsys 慢，不能占采样周期）
            mem_thread = threading.Thread(target=self._mem_worker, daemon=True,
                                         name="PerfMem")
            mem_thread.start()
            frames_thread = threading.Thread(target=self._framestats_worker,
                                            daemon=True, name="PerfFrames")
            frames_thread.start()

            while True:
                cycle_start = time.time()

                # ── 起点 CPU 采集 ─────────────────────────────
                point_a = self._read_point()
                if point_a is None and self.mode == 'proc':
                    # 进程可能重启了 → 重新定位
                    self.pids = self._locate_pid()
                    self.pid = self.pids[0] if self.pids else None
                    if not self.pid:
                        self.mode = 'cpuinfo'
                        self._degraded = True

                # ── dumpsys 与等待并行（**不进** CPU 差分窗口）──
                # 内存每 HEAVY_EVERY 周期采一次；渲染每周期都采（要差分）
                ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                f_render = ex.submit(self._read_render)

                wait_left = self.interval - (time.time() - cycle_start)
                if wait_left > 0 and self.stop_event.wait(wait_left):
                    ex.shutdown(wait=False)
                    return

                # ── ⚠️ 先读 CPU 终点，**立刻锁定时间戳** ──────────
                #    这一步必须在等 dumpsys **之前**：
                #    dumpsys 要 1.5~3 秒，若等它再读终点，
                #    CPU 差分窗口会被拉长到 interval + dumpsys 耗时，
                #    采样周期也跟着失真（实测设 2 秒实际 3.1 秒）。
                point_b = self._read_point()

                # ── 再取 dumpsys 结果（可能还没跑完，用上一轮兜底）─
                render = self._render_or_cached(f_render)
                mem = self._last_mem      # 内存由独立线程采集，这里只读缓存
                ex.shutdown(wait=False)

                # ── 计算 ────────────────────────────────────────
                cpu_val = None
                if point_a and point_b:
                    cpu_val = self._diff_cpu(point_a, point_b)
                    self._diff_threads(point_a, point_b)

                rss = point_b.rss_mb if point_b else None
                frame = self._diff_render(render['gfx'], render['frames'],
                                          time.time())
                self._seq += 1
                self._last_interval_actual = time.time() - cycle_start

                self._aggregate(cpu_val, mem, rss, frame)
                self._check_alert(cpu_val, mem)
                self._publish()

                if self.stop_event.is_set():
                    return
        except Exception as e:
            logging.error(f"[性能采集] 循环异常: {e}", exc_info=True)
            self.monitoring = False

    _heavy_every = 2      # 内存降频：dumpsys meminfo 较慢

    def _render_or_cached(self, future) -> Dict[str, Any]:
        """取渲染统计；dumpsys 还没跑完就用上一轮的缓存

        ⚠️ 不能阻塞等 dumpsys —— 那会把 CPU 差分窗口和采样周期一起拉长。
           用上一轮的数据略滞后，但不影响 CPU 精度。
        """
        try:
            result = future.result(timeout=0.02)
            self._last_render = result
            return result
        except Exception:
            return (self._last_render
                    or {'gfx': {}, 'frames': None, 'cost': 0.0})

    def _collect_once(self):
        """单次采集（快照用）"""
        self._detect_env()
        point_a = self._read_point()
        time.sleep(1.0)
        point_b = self._read_point()
        cpu_val = None
        if point_a and point_b:
            cpu_val = self._diff_cpu(point_a, point_b)
            self._diff_threads(point_a, point_b)
        mem, _ = self._read_memory()
        self._last_mem = mem
        render = self._read_render()
        frame = self._diff_render(render['gfx'], render['frames'], time.time())
        self._aggregate(cpu_val, mem, point_b.rss_mb if point_b else None, frame)
        self._check_alert(cpu_val, mem)
        self._publish()

    # ---------------------------------------------------------- 聚合
    def _check_alert(self, cpu_val, mem) -> bool:
        """阈值告警：连续超阈值 N 次才提示，恢复后自动解除

        用**本次采样值**判定（不是上一次的），内存降频周期沿用上次读数。
        """
        cpu = cpu_val if cpu_val is not None else self._metrics['cpu'].cur
        pss = mem.get('pss') if mem else None
        if pss is None:
            pss = self._metrics['pss'].cur

        cpu_hit = cpu is not None and cpu >= self.thresholds.get('cpu', 999)
        mem_hit = pss is not None and pss >= self.thresholds.get('pss', 10 ** 9)
        hit = cpu_hit or mem_hit

        if hit:
            self._alert_streak += 1
            if self._alert_streak >= Config.PERF_ALERT_STREAK \
                    and not self._alert_active:
                self._alert_active = True
                parts = []
                if cpu_hit:
                    parts.append(f"CPU {cpu:.1f}% "
                                 f"(阈值 {self.thresholds['cpu']:g}%)")
                if mem_hit:
                    parts.append(f"内存 {pss:.0f}MB "
                                 f"(阈值 {self.thresholds['pss']:g}MB)")
                self._alert_msg = (f"⚠ 性能告警: {' / '.join(parts)}，"
                                   f"已连续 {self._alert_streak} 次超过阈值")
        else:
            self._alert_active = False
            self._alert_streak = 0
            self._alert_msg = None
        return hit

    def _aggregate(self, cpu_val, mem, rss, frame):
        m = self._metrics
        m['cpu'].update(cpu_val)
        m['rss'].update(rss)
        if mem:
            m['pss'].update(mem.get('pss'))
            m['java'].update(mem.get('java'))
            m['native'].update(mem.get('native'))
        m['fps'].update(frame.get('fps'))
        m['jank'].update(frame.get('jank'))
        m['p95_frame'].update(frame.get('p95_frame'))
        m['p99_frame'].update(frame.get('p99_frame'))

        # ⚠️ history 记**本周期原始值**（可能是 None），
        #    不用「沿用上次读数」—— 那会在 CSV 里造出伪造的平坦段。
        ts = time.strftime("%H:%M:%S")
        self.history.append((ts,
                             cpu_val,
                             (mem or {}).get('pss') if mem else None,
                             rss,
                             (mem or {}).get('java') if mem else None,
                             (mem or {}).get('native') if mem else None,
                             frame.get('fps'),
                             frame.get('jank')))

        durations = frame.get('frame_durations') or []
        if durations:
            self._frame_samples.append({
                'ts': ts,
                'durations': durations,
                'jank_pct': frame.get('jank'),
            })
            if len(self._frame_samples) > 60:
                self._frame_samples.pop(0)

    # ---------------------------------------------------------- 输出
    def stats(self) -> Dict[str, Any]:
        """当前统计快照（方法形式，与旧接口一致）"""
        return self._stats_snapshot()

    def _stats_snapshot(self) -> Dict[str, Any]:
        threads = sorted(self._thread_stats.values(),
                         key=lambda t: t.cur, reverse=True)[:self.THREAD_TABLE_MAX]
        thread_sum = sum(t.cur for t in self._thread_stats.values())
        return {
            'cpu': self._metrics['cpu'].to_dict(),
            'pss': self._metrics['pss'].to_dict(),
            'rss': self._metrics['rss'].to_dict(),
            'java': self._metrics['java'].to_dict(),
            'native': self._metrics['native'].to_dict(),
            'fps': self._metrics['fps'].to_dict(),
            'jank': self._metrics['jank'].to_dict(),
            'p95_frame': self._metrics['p95_frame'].to_dict(),
            'p99_frame': self._metrics['p99_frame'].to_dict(),
            'alert': self._alert_active,
            'threads': [t.to_dict() for t in threads],
            'thread_sum': round(thread_sum, 2),
            'sample_count': self._seq,
            'elapsed': max(0.0, time.time() - self._start_time),
            'pid': self.pid,
            'pids': list(self.pids),
            'mode': self.mode,
            'quality': self.quality(),
        }

    def export_csv(self, file_path: str) -> str:
        """导出逐次采样明细到 CSV

        ⚠️ 本周期未测得的指标写**空**（不是上一次的旧值）——
           否则 CSV 里会出现大片伪造的平坦段。
        """
        import csv
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['时间', '进程CPU(%)', 'PSS内存(MB)', 'RSS内存(MB)',
                             'Java Heap(MB)', 'Native Heap(MB)', 'FPS',
                             '卡顿率(%)'])
            for row in self.history:
                writer.writerow([
                    row[0],
                    '' if row[1] is None else f"{row[1]:.2f}",
                    '' if row[2] is None else f"{row[2]:.1f}",
                    '' if row[3] is None else f"{row[3]:.1f}",
                    '' if row[4] is None else f"{row[4]:.1f}",
                    '' if row[5] is None else f"{row[5]:.1f}",
                    '' if row[6] is None else f"{row[6]:.2f}",
                    '' if row[7] is None else f"{row[7]:.2f}",
                ])
        return file_path

    def export_report(self, file_path: str) -> str:
        """导出文本报告"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self.get_summary())
            f.write('\n')
        return file_path

    def quality(self) -> Dict[str, Any]:
        """采样质量元数据 —— 报告里要展示，防止把不可信数据当结论"""
        total = self._ok_points + self._fail_points
        return {
            'ok_points': self._ok_points,
            'fail_points': self._fail_points,
            'total_points': total,
            'success_rate': round(self._ok_points / total * 100.0, 1) if total else None,
            'interval_actual': round(self._last_interval_actual, 2),
            'interval_set': self.interval,
            'costs': {k: round(v, 2) for k, v in self._collect_costs.items()},
            'degraded': self._degraded or self.mode == 'cpuinfo',
            'mode': self.mode,
            'clk_tck': self._clk_tck,
            'clk_tck_estimated': self._clk_tck_estimated,
            'clk_tck_estimate_raw': self._clk_tck_estimate,
            'cpu_max': self._cpu_max,
        }

    def _publish(self):
        """把统计快照推给 UI

        ⚠️ 采集在后台线程，直接调 UI 回调会抛
           "main thread is not in main loop"。
           这里统一通过 app._run_in_ui() 投递到主线程。
        """
        if not self.update_callback:
            return
        snapshot = self._stats_snapshot()
        app = self.app
        if app is not None and hasattr(app, '_run_in_ui'):
            try:
                # ⚠️ app._run_in_ui 只接受**一个** callable 参数。
                #    直接传 (callback, snapshot) 会抛 TypeError，
                #    而这里的 except 会把它吞掉 —— 结果是
                #    「采到数据但界面永远不刷新」，且没有任何报错。
                #    所以用 lambda 把 snapshot 绑进去。
                app._run_in_ui(lambda snap=snapshot: self.update_callback(snap))
                return
            except Exception as e:
                logging.warning(f"[性能采集] UI 调度失败: {e}")
                return
        try:
            self.update_callback(snapshot)
        except Exception as e:
            logging.debug(f"[性能采集] 回调失败: {e}")

    def get_summary(self) -> str:
        """文本摘要"""
        s = self._stats_snapshot()
        if s['sample_count'] == 0:
            return "📊 暂无性能数据，请先开始监控"
        q = s['quality']
        lines = [
            "📊 性能监控报告",
            "=" * 56,
            f"目标: {self.package_name or '系统整体'}    PID: {s['pid'] or '--'}",
            f"模式: {s['mode']}    采样: {s['sample_count']} 次    "
            f"时长 {self._fmt_duration(s['elapsed'])}",
            f"实际间隔: {q['interval_actual']}s（设定 {q['interval_set']}s）    "
            f"有效率: {q['success_rate']}%",
            "-" * 56,
        ]
        for key, name, unit, digits in (
                ('cpu', 'CPU 占用', '%', 2),
                ('pss', 'PSS 内存', ' MB', 1),
                ('rss', 'RSS 内存', ' MB', 1),
                ('java', 'Java Heap', ' MB', 1),
                ('native', 'Native Heap', ' MB', 1),
                ('fps', 'FPS', '', 2),
                ('jank', '卡顿率', ' %', 2),
                ('p95_frame', '帧耗时 P95', ' ms', 1)):
            m = s[key]
            if m['cur'] is None:
                lines.append(f"{name:12s} --")
                continue
            lines.append(f"{name:12s} 当前 {m['cur']:.{digits}f}{unit}    "
                         f"均值 {m['avg']:.{digits}f}{unit}    "
                         f"峰值 {m['peak']:.{digits}f}{unit}")
        if s['threads']:
            lines.append("-" * 56)
            lines.append(f"CPU 热点线程 TOP 10（线程合计 {s['thread_sum']:.1f}%）:")
            for t in sorted(s['threads'], key=lambda x: x['peak'],
                            reverse=True)[:10]:
                lines.append(f"  [{t['tid']}] {t['name'][:28]:<28} "
                             f"当前 {t['cur']:6.2f}%  峰值 {t['peak']:6.2f}%")
        lines.append("=" * 56)
        return '\n'.join(lines)

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
