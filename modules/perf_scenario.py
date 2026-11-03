"""
场景化测试模板

不同场景该看什么指标、什么阈值，差别很大。
现在代码里阈值是硬编码的（CPU 80% / 内存 800MB），对视频播放和界面流畅
都不合适 —— 视频播放 CPU 80% 可能很正常，界面流畅时内存 800MB 才算问题。

模板定义：
    metrics   这次要重点看的指标（报告里置顶显示）
    thresholds 告警阈值（覆盖 Config 的全局默认值）
    advice    给用户的一句话提示
"""
from typing import Any, Dict, List


class Scenario:
    """场景定义"""

    def __init__(self, key: str, name: str, desc: str,
                 metrics: List[str], thresholds: Dict[str, float],
                 advice: str):
        self.key = key
        self.name = name
        self.desc = desc
        self.metrics = metrics
        self.thresholds = thresholds
        self.advice = advice

    def check(self, stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """按本场景的阈值检查，返回命中的项"""
        hits = []
        for metric_key, limit in self.thresholds.items():
            cur = (stats.get(metric_key) or {}).get('cur')
            if cur is None:
                continue
            # 帧率是越大越好，阈值是下限；其余是上限
            if metric_key in ('fps',):
                if cur < limit:
                    hits.append({'metric': metric_key, 'value': cur,
                                 'limit': limit, 'direction': 'below'})
            elif cur > limit:
                hits.append({'metric': metric_key, 'value': cur,
                             'limit': limit, 'direction': 'above'})
        return hits


SCENARIOS: Dict[str, Scenario] = {}


def _add(scn: Scenario):
    SCENARIOS[scn.key] = scn


_add(Scenario(
    key='video',
    name='视频播放',
    desc='长时间播放，关注解码与掉帧',
    metrics=['fps', 'jank', 'p95_frame', 'cpu'],
    thresholds={'fps': 24.0, 'jank': 5.0, 'p95_frame': 33.0},
    advice='掉帧多半出在解码环节：看「音视频解码」角色的线程占用，'
           '以及是否走了硬解码（软解会吃满 CPU）。',
))

_add(Scenario(
    key='ui',
    name='界面流畅',
    desc='滑动/动画，关注渲染线程与帧耗时',
    metrics=['fps', 'jank', 'p95_frame', 'cpu'],
    thresholds={'fps': 50.0, 'jank': 3.0, 'p95_frame': 20.0},
    advice='界面卡顿优先看「渲染」角色线程；帧耗时超过 16.7ms 就是漏了一帧。',
))

_add(Scenario(
    key='memory',
    name='内存体检',
    desc='长时间运行，关注内存增长趋势',
    metrics=['pss', 'java', 'native'],
    thresholds={'pss': 800.0},
    advice='重点看 PSS 曲线的**斜率**而不是绝对值：'
           '稳定在 300MB 没问题，每分钟涨 2MB 才是泄漏。',
))

_add(Scenario(
    key='power',
    name='省电测试',
    desc='后台驻留，关注平均 CPU',
    metrics=['cpu'],
    thresholds={'cpu': 15.0},
    advice='看 CPU 的**均值**而不是峰值；后台常驻应用的峰值参考意义不大。',
))

_add(Scenario(
    key='startup',
    name='启动性能',
    desc='冷/热启动耗时',
    metrics=['startup_cold', 'startup_warm'],
    thresholds={'startup_cold': 2000.0, 'startup_warm': 1000.0},
    advice='启动耗时用 `am start -W` 实测，冷启动要先 force-stop。',
))

_add(Scenario(
    key='general',
    name='通用',
    desc='不限场景，使用默认阈值',
    metrics=['cpu', 'pss', 'fps', 'jank'],
    thresholds={'cpu': 80.0, 'pss': 800.0, 'jank': 5.0},
    advice='通用观察；建议先选一个具体场景，阈值更有参考价值。',
))


def get(key: str) -> Scenario:
    return SCENARIOS.get(key, SCENARIOS['general'])
