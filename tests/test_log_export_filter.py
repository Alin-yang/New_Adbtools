"""终端导出/复制跟随「只看错误」过滤（v5.4.8）

守护一个真实缺陷：
   「只看错误」用 `tag_configure(elide=True)` 隐藏非错误行，
   但 elide **只影响显示**；`text.get("1.0", tk.END)` 拿到的仍是**全部文本**。
   → 用户勾了「只看错误」再导出，导出的却是完整日志，
     以为导了错误日志其实没导。

⚠️ 这类「UI 说了、实际没做」的缺陷最消耗信任，必须有断言。

用法: python tests/test_log_export_filter.py
"""
import os
import sys
import tkinter as tk

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    extra = f"  -> {detail}" if detail and not cond else ""
    results.append((cond, label, detail))
    print(("  PASS  " if cond else "  FAIL  ") + label + extra)


print("=" * 68)
print("终端导出/复制跟随「只看错误」过滤")
print("=" * 68)

# ⚠️ 用**真实实现**的关键字表，别在这里另抄一份（否则测的就不是真代码）
from gui.layout_v4 import LayoutV4
ERROR_MARKERS = LayoutV4._error_markers()

# ── 1. 先证明 Tk 的 elide 语义（这正是 bug 的根源）────────────
print()
print("=== 1. 先证明 Tk 的 elide 语义（bug 的根源）===")
root = tk.Tk()
root.withdraw()
text = tk.Text(root)
lines = [
    "16:00:01  [✓] 连接成功",
    "16:00:02  [✗] 安装失败 code 1",
    "16:00:03  [i] 正在传输",
    "16:00:04  FATAL EXCEPTION: main",
    "16:00:05  [✓] 传输完成",
]
text.insert("1.0", "\n".join(lines))
root.update()

# 模拟现有的 _toggle_error_only：把非错误行标上 elide
for i, line in enumerate(lines):
    if not line.strip():
        continue
    if not any(m in line for m in ERROR_MARKERS):
        text.tag_add("hidden_line", f"{i + 1}.0", f"{i + 1}.end - 1c")
text.tag_configure("hidden_line", elide=True)
root.update()

raw = text.get("1.0", tk.END)
got_n = len([ln for ln in raw.split("\n") if ln.strip()])
check("elide 之后 get() 仍返回**全部**文本（bug 的根源）",
      got_n == len(lines), f"拿到 {got_n} 行，共 {len(lines)} 行")

# 正确做法：按过滤状态重新过滤一遍
filtered = "\n".join(
    ln for ln in raw.split("\n")
    if not ln.strip() or any(m in ln for m in ERROR_MARKERS))
kept = [ln for ln in filtered.split("\n") if ln.strip()]
check("按关键字过滤后只剩错误行", len(kept) == 2, kept)
check("过滤结果包含「安装失败」", any("安装失败" in ln for ln in kept), kept)
check("过滤结果包含「FATAL EXCEPTION」",
      any("FATAL EXCEPTION" in ln for ln in kept), kept)
check("过滤结果不含正常行", not any("连接成功" in ln for ln in kept), kept)
root.destroy()

# ── 1b. 关键字表必须覆盖 logcat 的真实格式 ─────────────────────
print()
print("=== 1b. 关键字表覆盖度（实测踩过的漏）===")
# 这些是 Android logcat 里**真实存在**的错误行格式，
# 原来只匹配首字母大写的 Exception → `FATAL EXCEPTION` 全漏
REAL_ERROR_LINES = [
    "E AndroidRuntime: FATAL EXCEPTION: main",
    "java.lang.NullPointerException: boom",
    "E AndroidRuntime: java.lang.OutOfMemoryError: Failed to allocate",
    "signal 11 (SIGSEGV), code 1, fault addr 0x0",
    "Fatal signal 11 (SIGSEGV)",
    "ANR in com.example.app (com.example.app/.MainActivity)",
    "Process com.example.app (pid 1234) has died",
    "adb: error: failed to copy '/data/local/tmp/x.apk'",
    "Traceback (most recent call last):",
    "E ActivityManager: ANR in com.example.app",
]
for _ln in REAL_ERROR_LINES:
    _hit = LayoutV4._is_error_line(_ln)
    check(f"能识别错误行：{_ln[:44]}", _hit)

# 反向：正常行不该被误判
NORMAL_LINES = [
    "16:00:01  [✓] 连接成功",
    "16:00:03  [i] 正在传输... 45%",
    "D ActivityManager: Start proc com.example.app",
    "I DisplayDevice: 显示器已连接",
]
for _ln in NORMAL_LINES:
    _hit = LayoutV4._is_error_line(_ln)
    check(f"不误判正常行：{_ln[:44]}", not _hit, _hit)

# ── 1c. logcat 级别前缀（E/ F/）是最可靠的信号 ──────────────
print()
print("=== 1c. logcat 级别前缀识别 ===")
# ⚠️ 真实 logcat 格式是 `E/Tag( 1234): msg`（斜杠，不是空格）
#    关键字表**永远会有漏的词**，但级别前缀不会漏 ——
#    哪怕消息里一个错误词都没有，E/ 开头的就是错误行。
LEVEL_ERROR_LINES = [
    "E/LocalSocketTransmitVoice(22503): connect to server failed",
    "F/libc     ( 1234): Fatal signal 11 (SIGSEGV)",
    "E/AndroidRuntime( 1234): 消息里没有任何英文错误词",
    "E/MyApp( 999): 中文日志：网络连接异常",
]
for _ln in LEVEL_ERROR_LINES:
    _hit = LayoutV4._is_error_line(_ln)
    check(f"级别前缀能识别：{_ln[:40]}", _hit)

# 警告级别 W/ 不算错误（太宽松会让「只看错误」变成「只看警告」）
LEVEL_NOT_ERROR = [
    "W/MyApp( 1234): 只是警告",
    "I/MyApp( 1234): 普通信息",
    "D/MyApp( 1234): 调试信息",
]
for _ln in LEVEL_NOT_ERROR:
    _hit = LayoutV4._is_error_line(_ln)
    check(f"警告/信息级不算错误：{_ln[:40]}", not _hit, _hit)

# ── 1d. 中文错误词 ────────────────────────────────────────
print()
print("=== 1d. 中文错误词覆盖 ===")
CN_ERROR_LINES = [
    "16:00:01  [✗] 操作失败",
    "16:00:02  网络连接出错",
    "16:00:03  发生未知错误",
    "16:00:04  数据异常，请重试",
]
for _ln in CN_ERROR_LINES:
    _hit = LayoutV4._is_error_line(_ln)
    check(f"能识别中文错误行：{_ln[:40]}", _hit)

# 中文正常行不该被误判
CN_NORMAL_LINES = [
    "16:00:01  已连接设备",
    "16:00:02  安装成功",
    "16:00:03  正在启动应用",
]
for _ln in CN_NORMAL_LINES:
    _hit = LayoutV4._is_error_line(_ln)
    check(f"不误判中文正常行：{_ln[:40]}", not _hit, _hit)

# ── 2. 源码级守护：过滤逻辑必须共用同一份判定 ───────────────
print()
print("=== 2. 源码级守护 ===")
# ⚠️ 核心不变量：**显示过滤和导出过滤必须调用同一个判定方法**。
#    两处各写一份 → 迟早不一致 → 「界面只显示错误行，
#    导出的却是全量」这种「UI 说了、实际没做」的缺陷（v5.4.8 修的）。
_layout = os.path.join(_ROOT, 'gui', 'layout_v4.py')
with open(_layout, encoding='utf-8') as f:
    src = f.read()

check("有 _get_log_content() 方法", 'def _get_log_content' in src)
check("导出/复制用 _get_log_content()",
      src.count('self._get_log_content()') >= 2,
      src.count('self._get_log_content()'))
check("有 _error_markers() 供两处共用", 'def _error_markers' in src)
check("有 _is_error_line() 统一判定",
      'def _is_error_line' in src)
# ⚠️ **核心不变量**：显示过滤与导出过滤都必须走 _is_error_line
check("显示过滤与导出过滤共用同一判定方法",
      src.count('self._is_error_line(') >= 2,
      src.count('self._is_error_line('))
check("不再有第二份硬编码关键字列表",
      src.count('"✗", "失败"') <= 1, src.count('"✗", "失败"'))
check("识别 logcat 级别前缀 E/ F/",
      '_ERROR_LEVEL_RE' in src)

# ── 3. 单元级：直接调真实实现的 _get_log_content ─────────────
print()
print("=== 3. 直接验证 _get_log_content 的行为 ===")
from gui.layout_v4 import LayoutV4


class FakeVar:
    def __init__(self, v=False):
        self._v = v

    def get(self):
        return self._v


class FakeText:
    def __init__(self, content):
        self._content = content

    def get(self, a, b=None):
        return self._content


class FakeApp:
    def __init__(self, content, only_error=False):
        self.status_text = FakeText(content)
        self.log_error_only_var = FakeVar(only_error)
        self.statuses = []

    def update_status(self, msg, success=True, msg_type='normal'):
        self.statuses.append((msg, success))


class FakeLay:
    """只借 LayoutV4 的几个方法（不建真 Tk 界面）"""
    _get_log_content = LayoutV4._get_log_content
    _is_error_only = LayoutV4._is_error_only
    _error_markers = staticmethod(LayoutV4._error_markers)
    # ⚠️ _get_log_content 内部会调 self._is_error_line() → 必须一起借过来
    _is_error_line = classmethod(LayoutV4._is_error_line.__func__)
    # ⚠️ _is_error_line 内部用 cls._ERROR_LEVEL_RE → 类属性也要借
    _ERROR_LEVEL_RE = LayoutV4._ERROR_LEVEL_RE


CONTENT = ("16:00:01  [✓] 连接成功\n"
           "16:00:02  [✗] 安装失败 code 1\n"
           "16:00:03  [i] 正在传输\n"
           "16:00:04  FATAL EXCEPTION: main\n"
           "16:00:05  [✓] 传输完成\n")

app = FakeApp(CONTENT, only_error=False)
lay = FakeLay()
lay.app = app
out = lay._get_log_content()
n = len([ln for ln in out.split("\n") if ln.strip()])
check("未勾选「只看错误」→ 返回全部内容", n == 5, n)

app = FakeApp(CONTENT, only_error=True)
lay = FakeLay()
lay.app = app
out = lay._get_log_content()
kept = [ln for ln in out.split("\n") if ln.strip()]
check("勾选「只看错误」→ 只返回错误行", len(kept) == 2, kept)
check("勾选后不含正常行", "连接成功" not in out, out[:60])

app = FakeApp(CONTENT, only_error=True)
lay = FakeLay()
lay.app = app
out = lay._get_log_content(respect_filter=False)
n = len([ln for ln in out.split("\n") if ln.strip()])
check("respect_filter=False → 强制返回全量", n == 5, n)

print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
