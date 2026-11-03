"""
性能基线存储与对比

性能工具的真正价值在于**「和上次比」**：
改了代码重跑一次，一眼看出有没有变差 —— 这是盯数字做不到的。

存储位置：~/.adbtool_perf/history/<包名>/<时间戳>.json
每份基线是一���完整的采样快照，可与任意另一份对比。
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.join(os.path.expanduser('~'), '.adbtool_perf', 'history')


def _safe_name(name: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in name)


class BaselineStore:
    """基线存取"""

    def __init__(self, base_dir: str = BASE_DIR):
        self.base_dir = base_dir

    def _pkg_dir(self, package_name: str) -> str:
        return os.path.join(self.base_dir, _safe_name(package_name or 'system'))

    # ------------------------------------------------------------ 存
    def save(self, package_name: str, session: Dict[str, Any],
             label: str = '') -> Optional[str]:
        """存一份基线，返回文件路径"""
        try:
            d = self._pkg_dir(package_name)
            os.makedirs(d, exist_ok=True)
            stamp = time.strftime('%Y%m%d_%H%M%S')
            path = os.path.join(d, f'{stamp}.json')
            payload = {
                'package': package_name,
                'label': label,
                'saved_at': time.time(),
                'saved_at_text': time.strftime('%Y-%m-%d %H:%M:%S'),
                'session': session,
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            return path
        except Exception:
            return None

    # ------------------------------------------------------------ 读
    def list_baselines(self, package_name: str) -> List[Dict[str, Any]]:
        """列出该包名的所有基线（新 → 旧）"""
        d = self._pkg_dir(package_name)
        if not os.path.isdir(d):
            return []
        out = []
        for fn in sorted(os.listdir(d), reverse=True):
            if not fn.endswith('.json'):
                continue
            try:
                with open(os.path.join(d, fn), encoding='utf-8') as f:
                    data = json.load(f)
                data['_path'] = os.path.join(d, fn)
                data['_file'] = fn
                out.append(data)
            except Exception:
                continue
        return out

    def load(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def delete(self, path: str) -> bool:
        try:
            os.remove(path)
            return True
        except Exception:
            return False


# ====================================================================== #
# 对比
# ====================================================================== #

def compare(current: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    """对比两次测试

    Args:
        current: 当前 session
        baseline: 基线 session

    Returns:
        {
          'metrics': [{'key','label','cur','base','delta','pct','better'}],
          'threads': [{'name','cur','base','delta'}],   # 热点变化
        }
    """
    c_stats = current.get('stats', {})
    b_stats = baseline.get('stats', {})

    def get(stats, key, field='cur'):
        return (stats.get(key) or {}).get(field)

    metrics = []
    for key, label, unit, higher_is_better in (
            ('cpu', 'CPU 占用', '%', False),
            ('pss', '内存 PSS', ' MB', False),
            ('rss', 'RSS 内存', ' MB', False),
            ('java', 'Java Heap', ' MB', False),
            ('fps', '帧率', '', True),
            ('jank', '卡顿率', ' %', False),
            ('p95_frame', '帧耗时 P95', ' ms', False)):
        cur = get(c_stats, key)
        base = get(b_stats, key)
        if cur is None or base is None:
            continue
        delta = cur - base
        pct = (delta / base * 100.0) if base else None
        if abs(delta) < 1e-9:
            better = None
        else:
            better = (delta > 0) if higher_is_better else (delta < 0)
        metrics.append({
            'key': key, 'label': label, 'unit': unit,
            'cur': cur, 'base': base, 'delta': delta, 'pct': pct,
            'better': better,
        })

    # 线程热点变化
    c_threads = {t['name']: t for t in c_stats.get('threads', [])}
    b_threads = {t['name']: t for t in b_stats.get('threads', [])}
    thread_rows = []
    for name, t in c_threads.items():
        b = b_threads.get(name)
        base_cur = b['cur'] if b else 0.0
        thread_rows.append({
            'name': name,
            'cur': t['cur'],
            'base': base_cur,
            'delta': t['cur'] - base_cur,
            'new': b is None,
        })
    thread_rows.sort(key=lambda x: -abs(x['delta']))
    thread_rows = thread_rows[:12]

    return {'metrics': metrics, 'threads': thread_rows}


def summarize_comparison(cmp: Dict[str, Any]) -> str:
    """对比结果的一句话摘要"""
    improved = [m for m in cmp['metrics'] if m['better'] is True]
    worsened = [m for m in cmp['metrics'] if m['better'] is False]
    if not improved and not worsened:
        return '与基线基本持平'
    parts = []
    if worsened:
        parts.append('恶化: ' + '、'.join(
            f"{m['label']} {m['delta']:+.1f}{m['unit']}" for m in worsened[:3]))
    if improved:
        parts.append('改善: ' + '、'.join(
            f"{m['label']} {m['delta']:+.1f}{m['unit']}" for m in improved[:3]))
    return '；'.join(parts)
