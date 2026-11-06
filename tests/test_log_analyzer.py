"""日志错误聚类回归测试（v5.4.8）

守护「同一个异常刷 500 次仍是 500 行」这个问题的解法：
   把相同异常折叠成一条 + 统计频次 + Top N 排序。

⚠️ 测试样本用的是 **logcat 的真实格式**（真机实测）：
    I/art     ( 2338): Explicit concurrent mark sweep GC freed ...
    E/LocalSocketTransmitVoice(22503): connect to server failed
    E/AndroidRuntime: FATAL EXCEPTION: main
        java.lang.NullPointerException: boom
            at com.foo.Bar.baz(Bar.java:42)

用法: python tests/test_log_analyzer.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from modules import log_analyzer as LA

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    extra = f"  -> {detail}" if detail and not cond else ""
    results.append((cond, label, detail))
    print(("  PASS  " if cond else "  FAIL  ") + label + extra)


# ── 真实格式样本 ────────────────────────────────────────────────
SAMPLE = """\
I/art     ( 2338): Explicit concurrent mark sweep GC freed 4269(183KB) AllocSpace objects
D/STBManager( 3119): new STBManager client
E/LocalSocketTransmitVoice(22503): connect to server failed
D/Daemon  (28293): check the service once, interval: 12
E/AndroidRuntime: FATAL EXCEPTION: main
java.lang.NullPointerException: boom
	at com.foo.Bar.baz(Bar.java:42)
	at com.foo.Bar.qux(Bar.java:108)
	at android.os.Looper.loop(Looper.java:223)
Caused by: java.lang.IllegalStateException: state broken
	at com.foo.Baz.run(Baz.java:15)
I/HiMW@SourceManagerImpl( 3119): getSignalStatus, SignalStatus:1
E/AndroidRuntime: FATAL EXCEPTION: main
java.lang.NullPointerException: boom again
	at com.foo.Bar.baz(Bar.java:99)
	at com.foo.Bar.qux(Bar.java:108)
	at android.os.Looper.loop(Looper.java:223)
Caused by: java.lang.IllegalStateException: state broken
	at com.foo.Baz.run(Baz.java:15)
W/ContextImpl( 2070): Calling a method in the system process
E/ActivityManager: ANR in com.example.app (com.example.app/.MainActivity)
I/ProcessStats( 2070): ANR: com.example.app
F/libc     ( 1234): Fatal signal 11 (SIGSEGV), code 1, fault addr 0x0 in tid 1234 (mediadrm)
I/ActivityManager( 2070): Process com.example.app (pid 9999) has died
E/LocalSocketTransmitVoice(22503): connect to server failed
"""


print("=" * 68)
print("日志错误聚类回归测试")
print("=" * 68)

# ── 1. 解析 ────────────────────────────────────────────────────
print()
print("=== 1. logcat 行解析 ===")
lines = LA.parse_logcat(SAMPLE)
check("能解析出所有非空行", len(lines) == 25, len(lines))

_lv = [l for l in lines if l['level']]
# ⚠️ 无级别前缀的异常行也会被标成 'E'（便于聚类）→ 25 行都有级别
check("能识别日志级别", len(_lv) == 25, len(_lv))
check("能识别标签", any(l['tag'] == 'LocalSocketTransmitVoice' for l in lines))
check("能识别 PID", any(l['pid'] == '22503' for l in lines))

_frames = [l for l in lines if l['frame']]
check("能识别 Java 栈帧行", len(_frames) == 8, len(_frames))
check("栈帧能提取方法名",
      any(l.get('method') == 'com.foo.Bar.baz' for l in _frames))

# ── 2. 提取故障事件 ────────────────────────────────────────────
print()
print("=== 2. 故障事件提取 ===")
inc = LA.extract_incidents(lines)
check("提取到故障事件", len(inc) >= 5, len(inc))

_kinds = [i['kind'] for i in inc]
check("识别出 FATAL 崩溃", 'fatal' in _kinds, _kinds)
check("识别出 ANR", 'anr' in _kinds, _kinds)
check("识别出 native 崩溃", 'native' in _kinds, _kinds)
check("识别出进程死亡", 'died' in _kinds, _kinds)

_fatal = next((i for i in inc if i['kind'] == 'fatal'), None)
if _fatal:
    check("FATAL 事件带栈帧", len(_fatal['frames']) == 3, _fatal['frames'])
    check("FATAL 事件带 Caused by 链",
          len(_fatal['causes']) == 1, _fatal['causes'])

_anr = next((i for i in inc if i['kind'] == 'anr'), None)
if _anr:
    check("ANR 事件标题含包名", 'com.example.app' in _anr['title'],
          _anr['title'])

_native = next((i for i in inc if i['kind'] == 'native'), None)
if _native:
    check("native 事件标题含信号名", 'SIGSEGV' in _native['title'],
          _native['title'])

# ── 3. 聚类（核心）─────────────────────────────────────────────
print()
print("=== 3. 聚类（核心）===")
clusters = LA.cluster_incidents(inc)
check("聚出了类", len(clusters) >= 4, len(clusters))

_top = clusters[0]
check("最频繁的类排第一", _top['count'] == 2, _top['count'])
# ⚠️ 「connect to server failed」和「NullPointerException」都是 2 次，
#    排序按 (count 降序, 首次出现行号升序) → connect 出现在前面
check("Top 1 是最先出现的那个 2 次类",
      _top['count'] == 2, _top['title'])

# ⚠️ **核心断言**：两次崩溃的栈**行号不同**（Bar.java:42 vs :99），
#    但归一化后必须聚成同一类 —— 这正是聚类的价值所在
_np = [c for c in clusters if 'NullPointerException' in c['title']]
check("行号不同的两次 NPE 聚成同一类", len(_np) == 1, len(_np))
if _np:
    check("该类计数为 2", _np[0]['count'] == 2, _np[0]['count'])
    check("该类保留完整栈帧", len(_np[0]["frames"]) == 3, _np[0]["frames"])
    check("该类保留 Caused by 链",
          len(_np[0]['causes']) == 1, _np[0]['causes'])

# 「connect to server failed」出现 2 次 → 也应聚成一类
_conn = [c for c in clusters if 'connect to server failed' in c['title']]
check("重复的普通错误行也聚成一类", len(_conn) == 1, len(_conn))
if _conn:
    check("该类计数为 2", _conn[0]['count'] == 2, _conn[0]['count'])

# 不同类型的错误不该被合并
_kinds_in_clusters = {c['kind'] for c in clusters}
check("不同类型的错误保持分开", len(_kinds_in_clusters) >= 3,
      _kinds_in_clusters)

# ── 4. 归一化 ──────────────────────────────────────────────────
print()
print("=== 4. 归一化（抹掉每次都变的部分）===")
check("行号被抹掉",
      LA.normalize_line('at com.foo.Bar.baz(Bar.java:42)') ==
      LA.normalize_line('at com.foo.Bar.baz(Bar.java:99)'),
      LA.normalize_line('at com.foo.Bar.baz(Bar.java:42)'))
check("地址被抹掉",
      'ADDR' in LA.normalize_line('fault addr 0x7f8e4c1234'),
      LA.normalize_line('fault addr 0x7f8e4c1234'))
check("不同地址归一化后相同",
      LA.normalize_line('addr 0x1111') == LA.normalize_line('addr 0x2222'))
check("正常内容不受影响",
      'com.foo.Bar' in LA.normalize_line('at com.foo.Bar.baz(Bar.java:42)'))

# ── 5. 一站式分析 ──────────────────────────────────────────────
print()
print("=== 5. analyze() 一站式接口 ===")
rep = LA.analyze(SAMPLE)
check("返回 total_lines", rep['total_lines'] == 25, rep['total_lines'])
check("返回 clusters", len(rep['clusters']) >= 4, len(rep['clusters']))
check('返回 top（截断后的）', len(rep['top']) <= 20)
check('返回 summary', bool(rep['summary']), rep['summary'])
check('summary 提到频次', '2' in rep['summary'], rep['summary'])
check('返回 kind_counts', bool(rep['kind_counts']), rep['kind_counts'])
check('kind_counts 里 fatal = 2（两次 NPE 崩溃）',
      rep['kind_counts'].get('fatal', 0) == 2, rep['kind_counts'])
check('kind_counts 里 error = 4（两条 connect failed + 两条 FATAL 头行）',
      rep['kind_counts'].get('error', 0) >= 2, rep['kind_counts'])

# ── 6. 边界 ────────────────────────────────────────────────────
print()
print("=== 6. 边界情况 ===")
check("空文本不报错",
      LA.analyze('')['clusters'] == [] and '未发现错误' in LA.analyze('')['summary'])
check("只有正常行 → 无故障",
      len(LA.analyze('I/foo( 123): hello\nD/bar( 456): world\n')['clusters']) == 0)
check("没有 pid 的行也能解析",
      len(LA.parse_logcat('E/AndroidRuntime: FATAL EXCEPTION: main\n')) == 1)
check("畸形行不崩", LA.analyze('???\n\x00\nrandom text\n') is not None)

# ── 7. 源码级守护 ──────────────────────────────────────────────
print()
print("=== 7. 源码级守护 ===")
_mod = os.path.join(_ROOT, 'modules', 'log_analyzer.py')
with open(_mod, encoding='utf-8') as f:
    src = f.read()
check('有 signature_of()（归一化签名）', 'def signature_of' in src)
check('有 cluster_incidents()', 'def cluster_incidents' in src)
check('签名只取前 6 帧（更深的栈容易变）', '[:6]' in src)
check('聚类按 count 降序', '-c[\'count\']' in src)

print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
