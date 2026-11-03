"""
性能数据分析 —— 从原始采样里得出「结论」

工具的价值不在于显示 128 个数字，而在于告诉用户
**「这次有没有问题，问题在哪」**。这一层负责后者。

包含三件事：
1. **自动结论**：内存泄漏 / CPU 峰值过高 / 掉帧 / GC 频繁 / 采样不可信 …
2. **内存泄漏检测**：对 PSS 做线性回归算斜率（MB/min）
3. **线程角色归类**：把 200 多个线程名聚合成用户看得懂的几个角色

⚠️ 线程角色表是**基于真机真实线程名**整理的
   （小米盒子 MiBOX4 / com.gitvdemo.video，204 个线程实测）：
       PumaProgMgr / gala.SSDPSS / HeapTaskDaemon / Binder_N /
       AsyncTask #N / OTTPool-N-N / FinalizerDaemon / RenderThread …
   不是照抄别处的规则，是从这台设备的实际线程名里归纳的。
"""
import re
from typing import Any, Dict, List, Optional, Tuple


# ====================================================================== #
# 线程角色归类
# ====================================================================== #

# (正则, 角色名, 颜色角色)
# 顺序敏感：先匹配到的优先（更具体的规则放前面）
THREAD_ROLE_RULES: List[Tuple[str, str, str]] = [
    # ── 渲染 ──────────────────────────────────────────────
    (r'^RenderThread$|^GLThread|^hwuiTask|^RenderThread', '渲染', 'render'),
    (r'^gfxinfo|^SurfaceFlinger|^HWC', '渲染', 'render'),

    # ── 解码 / 音视频 ────────────────────────────────────
    (r'^Codec|Decoder|^OMX|^MediaCodec|^AudioFlinger|^AudioTrack',
     '音视频解码', 'decode'),
    (r'gala\.|puma\.|Puma', '业务 SDK', 'sdk'),

    # ── GC / 编译 ─────────────────────────────────────────
    (r'^HeapTaskDaemon|^GC$|Heap$|Jit|Compiler|ReferenceQueue',
     'GC / 编译', 'gc'),
    (r'^FinalizerDaemon|^FinalizerWatchdog', 'GC / 编译', 'gc'),

    # ── IPC ────────────────────────────────────────────────
    (r'^Binder:', 'IPC', 'ipc'),
    (r'^Signal Catcher|^ADJ|^AndroidRuntime', '系统', 'sys'),

    # ── 网络 ───────────────────────────────────────────────
    (r'^Curl|^QtpEngine|^Http|^OkHttp|^Netd|^Network', '网络', 'net'),

    # ── 线程池 ────────────────────────────────────────────
    (r'^pool-|^OTTPool-|^AsyncTask|^Thread-|^SimpleAsyncTask|^WorkThread',
     '线程池', 'pool'),

    # ── I/O / 其它后台 ────────────────────────────────────
    (r'^WifiManager|^HCDN_|^Advertiser|^PulseMgr|^apm_|^PBDevif|^Predeploy',
     '后台服务', 'bg'),
]

_COMPILED_ROLES = [(re.compile(p), name, color)
                   for p, name, color in THREAD_ROLE_RULES]


def classify_thread(name: str) -> Tuple[str, str]:
    """把线程名归类

    Returns:
        (角色名, 颜色角色)；未匹配返回 ('其它', 'other')
    """
    if not name:
        return '其它', 'other'
    for pat, role, color in _COMPILED_ROLES:
        if pat.search(name):
            return role, color
    return '其它', 'other'


def aggregate_by_role(threads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按角色聚合线程 CPU

    Returns:
        [{'role': '渲染', 'color': 'render', 'cur': 12.3, 'avg': ..., 'peak': ...,
          'count': 5, 'top_thread': 'RenderThread'}]
    """
    buckets: Dict[str, Dict[str, Any]] = {}
    for t in threads:
        role, color = classify_thread(t.get('name', ''))
        b = buckets.setdefault(role, {
            'role': role, 'color': color, 'cur': 0.0, 'avg': 0.0,
            'peak': 0.0, 'count': 0, 'top_thread': '', 'top_cur': 0.0,
        })
        b['cur'] += t.get('cur', 0.0)
        b['avg'] += t.get('avg', 0.0)
        b['peak'] = max(b['peak'], t.get('peak', 0.0))
        b['count'] += 1
        if t.get('cur', 0.0) > b['top_cur']:
            b['top_cur'] = t.get('cur', 0.0)
            b['top_thread'] = t.get('name', '')
    result = list(buckets.values())
    result.sort(key=lambda x: x['cur'], reverse=True)
    return result


# ====================================================================== #
# 内存泄漏检测
# ====================================================================== #

def linear_slope(points: List[Tuple[float, float]]) -> Optional[float]:
    """最小二乘求斜率

    Args:
        points: [(x, y), ...]

    Returns:
        斜率；点数不足返回 None
    """
    n = len(points)
    if n < 3:
        return None
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return None
    return (n * sxy - sx * sy) / denom


def detect_memory_leak(history: List[Dict[str, Any]],
                        min_minutes: float = 2.0) -> Optional[Dict[str, Any]]:
    """内存泄漏检测

    ⚠️ history 里的 PSS 可能是 None（降频周期没采到），
       只能拿**真实采到的点**做回归，不能用沿用的旧值。

    Returns:
        {'slope_mb_per_min': float, 'duration_min': float,
         'growth_mb': float, 'r2': float} 或 None
    """
    samples = []
    base_ts = None
    for row in history:
        pss = row.get('pss')
        if pss is None:
            continue
        ts = row.get('ts')
        if not ts:
            continue
        # 把 HH:MM:SS 转成相对秒
        try:
            h, m, s = [int(x) for x in ts.split(':')]
            sec = h * 3600 + m * 60 + s
        except (ValueError, AttributeError):
            continue
        if base_ts is None:
            base_ts = sec
        samples.append((float(sec - base_ts) / 60.0, float(pss)))  # x=分钟

    if len(samples) < 6:
        return None
    duration_min = samples[-1][0] - samples[0][0]
    if duration_min < min_minutes:
        return None

    slope = linear_slope(samples)
    if slope is None:
        return None

    # R²（拟合优度）：太低说明不是线性增长，不算泄漏
    ys = [p[1] for p in samples]
    y_mean = sum(ys) / len(ys)
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + (y_mean - slope * (sum(p[0] for p in samples) / len(samples))))) ** 2
                 for x, y in samples)
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 1e-9 else 0.0

    growth = ys[-1] - ys[0]
    return {
        'slope_mb_per_min': round(slope, 3),
        'duration_min': round(duration_min, 1),
        'growth_mb': round(growth, 1),
        'r2': round(r2, 3),
    }


# ====================================================================== #
# 自动结论
# ====================================================================== #

# 结论等级
LEVEL_INFO = 'info'
LEVEL_GOOD = 'good'
LEVEL_WARN = 'warn'
LEVEL_BAD = 'bad'


def analyze(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """生成结论列表

    Args:
        session: 一次测试的完整数据（含 stats / history / quality）

    Returns:
        [{'level': 'bad'|'warn'|'good'|'info', 'title': str, 'detail': str}]
    """
    out: List[Dict[str, Any]] = []
    stats = session.get('stats', {})
    history = session.get('history', [])
    quality = session.get('quality', {})

    # ── 采样可信度（放最前：不可信的数据，其它结论都要打问号）──
    if quality.get('degraded'):
        out.append({
            'level': LEVEL_WARN,
            'title': '本次数据精度受限',
            'detail': f"采集模式降级为 {quality.get('mode')}，"
                      f"CPU 精度低于 /proc 精确差分",
        })
    rate = quality.get('success_rate')
    if rate is not None and rate < 90:
        out.append({
            'level': LEVEL_WARN,
            'title': '部分采样点缺失',
            'detail': f"有效采样率 {rate}%"
                      f"（{quality.get('fail_points')} 次采集失败）",
        })
    actual = quality.get('interval_actual')
    target = quality.get('interval_set')
    if actual and target and abs(actual - target) > max(1.0, target * 0.4):
        out.append({
            'level': LEVEL_INFO,
            'title': '实际采样间隔与设定不符',
            'detail': f"设定 {target}s，实际 {actual}s（受 dumpsys 耗时影响）",
        })

    # ── 内存泄漏 ────────────────────────────────────────────
    leak = detect_memory_leak(history)
    if leak and leak['slope_mb_per_min'] > 0.5 and leak['r2'] > 0.6:
        out.append({
            'level': LEVEL_BAD,
            'title': '内存疑似泄漏',
            'detail': f"PSS 以 {leak['slope_mb_per_min']:+.2f} MB/分 持续增长"
                      f"（{leak['duration_min']} 分钟内涨 {leak['growth_mb']:+.0f} MB，"
                      f"拟合度 {leak['r2']:.2f}）",
        })
    elif leak and leak['slope_mb_per_min'] < -0.5:
        out.append({
            'level': LEVEL_GOOD,
            'title': '内存稳定或已回收',
            'detail': f"PSS 呈下降趋势（{leak['slope_mb_per_min']:+.2f} MB/分）",
        })

    # ── CPU ─────────────────────────────────────────────────
    cpu = stats.get('cpu', {})
    if cpu.get('p95') is not None:
        if cpu['p95'] >= 80:
            out.append({
                'level': LEVEL_BAD,
                'title': 'CPU 峰值过高',
                'detail': f"P95 达 {cpu['p95']:.1f}%"
                          f"（阈值 {Config_cpu_alert()}%），"
                          f"峰值 {cpu['peak']:.1f}%",
            })
        elif cpu['p95'] >= 60:
            out.append({
                'level': LEVEL_WARN,
                'title': 'CPU 偏高',
                'detail': f"P95 {cpu['p95']:.1f}%，建议检查热点线程",
            })

    # ── 掉帧 ────────────────────────────────────────────────
    fps = stats.get('fps', {})
    jank = stats.get('jank', {})
    if fps.get('p05') is not None and fps['p05'] < 24:
        out.append({
            'level': LEVEL_BAD,
            'title': '存在明显掉帧',
            'detail': f"帧率 P05 仅 {fps['p05']:.1f}（均值的 5% 最差情况）",
        })
    if jank.get('cur') is not None and jank['cur'] > 5:
        out.append({
            'level': LEVEL_WARN if jank['cur'] <= 15 else LEVEL_BAD,
            'title': '卡顿率偏高',
            'detail': f"窗口内 {jank['cur']:.1f}% 的帧超时",
        })

    # ── 线程角色 ────────────────────────────────────────────
    threads = stats.get('threads', [])
    if threads:
        roles = aggregate_by_role(threads)
        gc_role = next((r for r in roles if r['role'] == 'GC / 编译'), None)
        if gc_role and gc_role['cur'] >= 8:
            out.append({
                'level': LEVEL_WARN,
                'title': 'GC 活动频繁',
                'detail': f"GC/编译类线程占用 {gc_role['cur']:.1f}%"
                          f"（{gc_role['count']} 个线程）",
            })

    # ── 帧耗时 ──────────────────────────────────────────────
    p95f = stats.get('p95_frame', {})
    if p95f.get('cur') is not None and p95f['cur'] > 20:
        out.append({
            'level': LEVEL_WARN,
            'title': '帧耗时偏高',
            'detail': f"P95 帧耗时 {p95f['cur']:.1f}ms"
                      f"（60fps 预算 16.7ms）",
        })

    # ── 场景检查（用场景自己的阈值，比全局默认更贴合场景）──
    scenario = session.get('scenario')
    if scenario:
        try:
            from modules import perf_scenario as S
            scn = S.get(scenario)
            hits = scn.check(stats)
            for hit in hits:
                metric_name = {'cpu': 'CPU', 'pss': '内存 PSS',
                               'fps': '帧率', 'jank': '卡顿率',
                               'p95_frame': '帧耗时 P95'}.get(
                                   hit['metric'], hit['metric'])
                if hit['direction'] == 'below':
                    detail = (f"{metric_name} {hit['value']:.1f}，"
                              f"低于「{scn.name}」场景要求的 {hit['limit']:g}")
                    level = LEVEL_BAD
                else:
                    detail = (f"{metric_name} {hit['value']:.1f}，"
                              f"超过「{scn.name}」场景的 {hit['limit']:g}")
                    level = LEVEL_WARN
                out.append({'level': level,
                            'title': f"{scn.name}场景不达标",
                            'detail': detail})
        except Exception:
            pass

    if not out:
        out.append({
            'level': LEVEL_GOOD,
            'title': '未发现明显问题',
            'detail': 'CPU、内存、帧率均在正常范围',
        })
    return out


def Config_cpu_alert() -> int:
    """CPU 告警阈值（延迟 import 避免循环依赖）"""
    try:
        from config import Config
        return Config.PERF_ALERT_CPU_PERCENT
    except Exception:
        return 80
