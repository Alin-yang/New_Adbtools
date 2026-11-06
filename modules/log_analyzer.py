"""日志错误聚类与异常栈提取

⚠️ **为什么需要它**：
   原始 logcat 里同一个异常刷 500 次仍是 500 行 —— 人工翻找成本极高，
   而且**看不出哪个错误最频繁**（那才是优先要修的）。
   本模块把相同异常折叠成一条，统计频次，排出 Top N。

纯文本处理，**不依赖 adb、不依赖 Tk**（可直接单元测试）。

──────────── logcat 行格式（真机实测）────────────
    I/art     ( 2338): Explicit concurrent mark sweep GC freed ...
    E/LocalSocketTransmitVoice(22503): connect to server failed
    E/AndroidRuntime: FATAL EXCEPTION: main
        java.lang.NullPointerException: boom
            at com.foo.Bar.baz(Bar.java:42)
            at android.os.Looper.loop(Looper.java:223)
    W/ContextImpl( 2070): Calling a method ...

    级别 / 标签( PID): 内容
    栈帧行以**空白 + at ** 开头（缩进），不属于任何日志级别行

──────────── 聚类的关键：归一化 ─────────────
    同一个崩溃的栈里含**每次都变**的东西：
      行号（Bar.java:42）、地址（0x7f8e4c）、对象 hash（0x1234abcd）、
      线程 id、时间戳、pid
    不去掉它们，每个崩溃都是"不同"的 → 聚不出类。
"""
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

# ── logcat 主行 ────────────────────────────────────────────────
# 格式：<级别>/<标签>(<pid>): <内容>
# 标签里可能有空格（D/HiMW@SourceManagerImpl( 3119): ）
_MAIN_RE = re.compile(
    r'^(?P<time>[\d\-]{6,}[\d:.\s]*)?'
    r'(?P<level>[VDIWEFAS])\s*/\s*'
    r'(?P<tag>[^:]*?)\s*\(\s*(?P<pid>\d+)\s*\)\s*:\s*'
    r'(?P<msg>.*)$'
)

# 无 pid 变体：E/AndroidRuntime: FATAL EXCEPTION: main
_MAIN_NOPID_RE = re.compile(
    r'^(?P<time>[\d\-]{6,}[\d:.\s]*)?'
    r'(?P<level>[VDIWEFAS])\s*/\s*'
    r'(?P<tag>[^:]*?)\s*:\s*'
    r'(?P<msg>.*)$'
)

# Java 栈帧：    at com.foo.Bar.baz(Bar.java:42)
#             at com.foo.Bar.baz(Native Method)
_STACK_FRAME_RE = re.compile(r'^\s*at\s+([\w$.<>]+)\s*\((.*)\)\s*$')
# 异常行：java.lang.NullPointerException: boom
#         Caused by: java.lang.RuntimeException: xxx
#         java.lang.IllegalStateException
_EXCEPTION_RE = re.compile(
    r'^(?P<cause>Caused by:\s*)?'
    r'(?P<cls>(?:[a-z][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable)'
    r'(?:\$.*)?)\s*'
    r'(?::\s*(?P<msg>.*))?$'
)
# 兜底：任何含 Exception/Error 结尾的标识符
_EXCEPTION_LOOSE_RE = re.compile(
    r'^(?P<cause>Caused by:\s*)?'
    r'(?P<cls>[a-z][\w$]*(?:\.[a-z][\w$]*)*\.[A-Z][\w$]*)'
    r'\s*(?::\s*(?P<msg>.*))?$'
)
# native 崩溃：signal 11 (SIGSEGV), code 1, fault addr 0x0
_SIGNAL_RE = re.compile(
    r'.*?(?P<sig>signal\s+\d+\s*\(\s*(?P<signame>SIG[A-Z]+)\s*\))'
    r'(?P<rest>.*)$'
)
# ANR：ANR in com.example.app (com.example.app/.MainActivity)
_ANR_RE = re.compile(r'ANR in\s+(?P<pkg>[\w.]+)')
# 进程死亡：Process com.example.app (pid 1234) has died
_DIED_RE = re.compile(r'Process\s+(?P<pkg>[\w.]+)\s+\(pid\s+\d+\)\s+has\s+(?P<what>died|crashed)')

# ── 归一化时要抹掉的变化量 ─────────────────────────────────────
# 行号
_LINENO_RE = re.compile(r'\.java:\d+|\.kt:\d+|\.cpp:\d+|\.c:\d+|\.h:\d+')
# 内存地址
_ADDR_RE = re.compile(r'0x[0-9a-fA-F]+')
# 对象 hash（Parcel/Object toString）
_OBJHASH_RE = re.compile(r'@[0-9a-fA-F]{6,}')
# 裸数字（可能是 id / 时间 / 计数）—— 只在括号参数里替换
_NUMBRACE_RE = re.compile(r'\((?P<pre>[^()]*?)\)(?=\s*$)')
# 线程名
_THREAD_RE = re.compile(r'\b(?:thread[- ]?\d+|tid[- ]?\d+|Thread-\d+)\b', re.I)


def _normalize_frame_args(arg: str) -> str:
    """抹掉栈帧参数里的行号/地址/数字"""
    out = _LINENO_RE.sub(':<LINE>', arg)
    out = _ADDR_RE.sub('<ADDR>', out)
    out = _NUMBRACE_RE.sub(lambda m: '(' + re.sub(r'\d+', '<N>', m.group('pre')) + ')', out)
    return out


def normalize_line(line: str) -> str:
    """归一化一行日志，用于聚类比对

    ⚠️ 归一化必须**保守**：抹掉的东西太多会把不同错误合并成一个类。
    """
    out = line.strip()
    out = _LINENO_RE.sub(':<LINE>', out)
    out = _ADDR_RE.sub('<ADDR>', out)
    out = _OBJHASH_RE.sub('@<HASH>', out)
    out = _THREAD_RE.sub('thread-<N>', out)
    # 消息里的长数字（时间戳/内存地址/ID）
    out = re.sub(r'\b\d{5,}\b', '<N>', out)
    return out


def parse_logcat(text: str) -> List[Dict[str, Any]]:
    """把 logcat 文本解析成结构化行列表

    Returns:
        [{'level','tag','pid','msg','raw','frame','exception'}, ...]
        - frame: True 表示这是 Java 栈帧行
        - exception: 异常类名（如果这行是异常声明）
    """
    out: List[Dict[str, Any]] = []
    for raw in (text or '').splitlines():
        if not raw.strip():
            continue
        # 栈帧行
        fm = _STACK_FRAME_RE.match(raw)
        if fm:
            out.append({
                'level': 'E', 'tag': '', 'pid': '', 'msg': raw.strip(),
                'raw': raw, 'frame': True,
                'method': fm.group(1), 'frame_arg': fm.group(2),
                'exception': None,
            })
            continue

        m = _MAIN_RE.match(raw)
        if not m:
            m = _MAIN_NOPID_RE.match(raw)
        if m:
            gd = m.groupdict()
            msg = (gd.get('msg') or '').strip()
            exc = None
            em = _EXCEPTION_RE.match(msg)
            if not em:
                em = _EXCEPTION_LOOSE_RE.match(msg)
            if em:
                exc = em.group('cls')
            out.append({
                'level': gd.get('level', ''),
                'tag': (gd.get('tag') or '').strip(),
                'pid': gd.get('pid') or '',
                'msg': msg,
                'raw': raw,
                'frame': False,
                'exception': exc,
                'caused_by': bool(em and em.groupdict().get('cause')) if em else False,
            })
            continue

        # ⚠️ **没有级别前缀的行**也可能是异常声明 ——
        #    logcat 里 Java 栈的异常行长这样（没有 E/ 前缀）：
        #        java.lang.NullPointerException: boom
        #        Caused by: java.lang.IllegalStateException: xxx
        #    之前这类行被当成"普通文本"丢掉 → 异常类型和 Caused by 链全丢，
        #    导致聚类根本认不出 Java 崩溃。
        em = _EXCEPTION_RE.match(raw.strip())
        if not em:
            em = _EXCEPTION_LOOSE_RE.match(raw.strip())
        if em:
            out.append({
                'level': 'E', 'tag': '', 'pid': '', 'msg': raw.strip(),
                'raw': raw, 'frame': False,
                'exception': em.group('cls'),
                'caused_by': bool(em.groupdict().get('cause')),
            })
            continue

        # 不是标准 logcat 行（可能是多行消息的续行）
        out.append({
            'level': '', 'tag': '', 'pid': '', 'msg': raw.strip(),
            'raw': raw, 'frame': False, 'exception': None,
        })
    return out


def extract_incidents(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从解析后的行里提取「一次故障事件」

    一次故障 = 一个异常声明 + 后续的栈帧 + 可选的 Caused by 链。

    Returns:
        [{'kind','title','signature','frames','line_no','level','tag','pid'}, ...]
        kind: 'java' | 'native' | 'anr' | 'died' | 'fatal'
    """
    incidents: List[Dict[str, Any]] = []
    i = 0
    n = len(lines)

    while i < n:
        ln = lines[i]
        raw = ln['raw']
        msg = ln.get('msg', '')

        # ── 崩溃链的头（FATAL EXCEPTION）──────────────────────
        #    logcat 的 Java 崩溃长这样（三行一组）：
        #        E/AndroidRuntime: FATAL EXCEPTION: main      ← 头（无异常类名）
        #        java.lang.NullPointerException: boom       ← 真正的异常
        #            at com.foo.Bar.baz(Bar.java:42)         ← 栈帧
        #    「FATAL EXCEPTION」本身**不是 Java 类名**，异常正则匹配不到，
        #    所以它必须被**单独识别成链头**，再跟后面的异常+栈帧合并成一次事件。
        if 'FATAL EXCEPTION' in raw:
            frames: List[str] = []
            exc_name = ''
            exc_msg = ''
            chain: List[str] = []
            j = i + 1
            # 下一条若是真正的异常声明 → 取它当原因
            if j < n and lines[j].get('exception') and not lines[j].get('frame'):
                exc_name = lines[j]['exception']
                exc_msg = lines[j].get('message', '')
                j += 1
            # 吃栈帧
            while j < n and lines[j].get('frame'):
                frames.append(lines[j].get('method', ''))
                j += 1
            # 吃 Caused by 链
            k = j
            while k < n:
                _l = lines[k]
                if _l.get('exception') and _l.get('caused_by'):
                    chain.append(_l['exception'])
                    k += 1
                    while k < n and lines[k].get('frame'):
                        k += 1
                else:
                    break
            incidents.append({
                'kind': 'fatal',
                'title': exc_msg or exc_name or msg,
                'exception': exc_name or 'FATAL',
                'message': exc_msg or msg,
                'frames': frames,
                'causes': chain,
                'line_no': i + 1,
                'level': ln.get('level', ''),
                'tag': ln.get('tag', ''),
                'pid': ln.get('pid', ''),
            })
            i = k if k > j else j
            continue

        # ── Java 异常 ──────────────────────────────────────
        if ln.get('exception') and not ln.get('frame'):
            kind = 'java'
            frames: List[str] = []
            j = i + 1
            # 吃栈帧
            while j < n and lines[j].get('frame'):
                frames.append(lines[j].get('method', ''))
                j += 1
            # 吃 Caused by 链
            chain: List[str] = []
            k = j
            while k < n:
                _l = lines[k]
                if _l.get('exception') and _l.get('caused_by'):
                    chain.append(_l['exception'])
                    k += 1
                    while k < n and lines[k].get('frame'):
                        k += 1
                else:
                    break
            title = ln['exception']
            if ln.get('message'):
                title = ln['message']
            incidents.append({
                'kind': kind,
                'title': title,
                'exception': ln['exception'],
                'message': msg,
                'frames': frames,
                'causes': chain,
                'line_no': i + 1,
                'level': ln.get('level', ''),
                'tag': ln.get('tag', ''),
                'pid': ln.get('pid', ''),
            })
            i = k if k > j else j
            continue

        # ── native 崩溃 ────────────────────────────────────
        sm = _SIGNAL_RE.search(raw)
        if sm:
            sig = sm.group('sig').strip()
            frames = []
            j = i + 1
            while j < n and lines[j].get('frame'):
                frames.append(lines[j].get('method', ''))
                j += 1
            incidents.append({
                'kind': 'native',
                'title': f'{sig}（native 崩溃）',
                'exception': sig,
                'message': sm.group('rest').strip(),
                'frames': frames,
                'causes': [],
                'line_no': i + 1,
                'level': ln.get('level', ''),
                'tag': ln.get('tag', ''),
                'pid': ln.get('pid', ''),
            })
            i = j
            continue

        # ── ANR ────────────────────────────────────────────
        am = _ANR_RE.search(raw)
        if am:
            incidents.append({
                'kind': 'anr',
                'title': f'ANR: {am.group("pkg")}',
                'exception': 'ANR',
                'message': msg,
                'frames': [],
                'causes': [],
                'line_no': i + 1,
                'level': ln.get('level', ''),
                'tag': ln.get('tag', ''),
                'pid': ln.get('pid', ''),
            })
            i += 1
            continue

        # ── 进程死亡 ───────────────────────────────────────
        dm = _DIED_RE.search(raw)
        if dm:
            incidents.append({
                'kind': 'died',
                'title': f'进程死亡: {dm.group("pkg")} ({dm.group("what")})',
                'exception': 'ProcessDied',
                'message': msg,
                'frames': [],
                'causes': [],
                'line_no': i + 1,
                'level': ln.get('level', ''),
                'tag': ln.get('tag', ''),
                'pid': ln.get('pid', ''),
            })
            i += 1
            continue

        # ── 普通错误行（没有异常栈的那种）────────────────────
        #    E/LocalSocketTransmitVoice(22503): connect to server failed
        #    这类行没有栈，但**同样会重复刷屏**（连接失败重试 500 次）。
        #    也应该聚类 —— 否则 Top N 里只有崩溃，看不到"刷屏最多"的错误。
        if ln.get('level') in ('E', 'F') and msg:
            incidents.append({
                'kind': 'error',
                'title': msg,
                'exception': '',
                'message': msg,
                'frames': [],
                'causes': [],
                'line_no': i + 1,
                'level': ln.get('level', ''),
                'tag': ln.get('tag', ''),
                'pid': ln.get('pid', ''),
            })
            i += 1
            continue

        i += 1

    return incidents


def signature_of(inc: Dict[str, Any]) -> str:
    """给一次故障算「归一化签名」—— 相同签名 = 同一类故障

    ⚠️ 签名**只由异常类型 + 栈帧序列**决定：
       去掉行号/地址/数字后才能把"同一个 bug 的 N 次崩溃"聚成一类。
    """
    parts = [inc.get('exception', '') or inc.get('kind', '')]
    for f in (inc.get('frames') or [])[:6]:      # 只取前 6 帧（更深的栈容易变）
        parts.append(_normalize_frame_args(f))
    for c in (inc.get('causes') or [])[:3]:
        parts.append(c)
    return '|'.join(p for p in parts if p)


def cluster_incidents(incidents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把故障聚成类

    Returns:
        [{'signature','title','kind','count','first_line','last_line',
          'frames','sample_message','tags'}, ...]
        按 count 降序。
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for inc in incidents:
        sig = signature_of(inc)
        groups.setdefault(sig, []).append(inc)

    clusters: List[Dict[str, Any]] = []
    for sig, items in groups.items():
        first = items[0]
        last = items[-1]
        clusters.append({
            'signature': sig,
            'title': first.get('title', ''),
            'kind': first.get('kind', ''),
            'count': len(items),
            'first_line': first.get('line_no', 0),
            'last_line': last.get('line_no', 0),
            'frames': first.get('frames', []),
            'causes': first.get('causes', []),
            'sample_message': first.get('message', ''),
            'tags': sorted({i.get('tag', '') for i in items if i.get('tag')}),
        })
    clusters.sort(key=lambda c: (-c['count'], c['first_line']))
    return clusters


def analyze(text: str, top_n: int = 20) -> Dict[str, Any]:
    """一站式分析：logcat 文本 → 聚类结果

    Returns:
        {
          'total_lines': int,
          'incidents': [...],        # 每次故障（未聚类）
          'clusters': [...],         # 聚类后（按频次降序）
          'top': [...],              # clusters 的前 top_n
          'summary': str,            # 一句话摘要
          'kind_counts': {...},       # 各类故障的数量
        }
    """
    lines = parse_logcat(text)
    incidents = extract_incidents(lines)
    clusters = cluster_incidents(incidents)

    kind_counts: Dict[str, int] = {}
    for c in clusters:
        kind_counts[c['kind']] = kind_counts.get(c['kind'], 0) + c['count']

    top = clusters[:top_n]
    summary = _build_summary(clusters, kind_counts, len(lines))
    return {
        'total_lines': len(lines),
        'incidents': incidents,
        'clusters': clusters,
        'top': top,
        'summary': summary,
        'kind_counts': kind_counts,
    }


_KIND_NAMES = {
    'java': 'Java 异常',
    'fatal': '致命崩溃',
    'native': 'native 崩溃',
    'anr': 'ANR 卡死',
    'died': '进程死亡',
    'error': '普通错误',
}


def _build_summary(clusters: List[Dict[str, Any]],
                   kind_counts: Dict[str, int],
                   total_lines: int) -> str:
    """生成一句话摘要"""
    if not clusters:
        return f'未发现错误（共 {total_lines} 行日志）'
    parts = []
    for kind, cnt in sorted(kind_counts.items(), key=lambda kv: -kv[1]):
        parts.append(f'{_KIND_NAMES.get(kind, kind)} {cnt} 次')
    head = clusters[0]
    return (f'共 {len(clusters)} 类错误 / {sum(kind_counts.values())} 次'
            f'（{"、".join(parts)}）；'
            f'最频繁：{head["title"]} × {head["count"]}')
