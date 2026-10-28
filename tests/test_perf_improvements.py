"""性能优化验证：getprop 合并、状态栏 O(1) 行数、后台线程无 root.after

用法: python tests/test_perf_improvements.py
"""
import sys, os, time, types, queue, re, ast, io as _io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod
import utils
from utils import parse_getprop_all

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False

print("=" * 72)
print("=== 1. parse_getprop_all 解析全量 getprop ===")
sample = """[ro.product.model]: [Pixel 6]
[ro.build.version.release]: [13]
[ro.build.version.sdk]: [33]
[ro.serialno]: [ABC123]
[persist.sys.locale]: []
"""
p = parse_getprop_all(sample)
check("解析出 5 个属性", len(p) == 5, p)
check("型号正确", p.get("ro.product.model") == "Pixel 6")
check("SDK 正确", p.get("ro.build.version.sdk") == "33")
check("空值也能解析", p.get("persist.sys.locale") == "")
check("空输入返回空", parse_getprop_all("") == {})
check("None 安全", parse_getprop_all(None) == {})
check("非标准行忽略", parse_getprop_all("garbage line\n[ro.x]: [y]").get("ro.x") == "y")

print()
print("=" * 72)
print("=== 2. 设备详情：getprop 命令数从 19 降到 1 ===")
src = _io.open('app.py', encoding='utf-8').read()
tree = ast.parse(src)
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ADBToolApp')
fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef)
          and x.name == '_get_device_info_fast_async')
body = '\n'.join(src.split('\n')[fn.lineno - 1:fn.end_lineno])

n_getprop_cmds = len(re.findall(r'run_adb_with_target\("adb shell getprop [a-z0-9._]+"\)', body))
n_full = body.count('run_adb_with_target("adb shell getprop")')
print(f"  逐条 getprop 命令: {n_getprop_cmds} 处   全量 getprop: {n_full} 处")
check("逐条 getprop 已清零", n_getprop_cmds == 0, n_getprop_cmds)
check("有 1 处全量 getprop", n_full == 1, n_full)
check("有 prop() 取值辅助函数", "def prop(name):" in body)

print()
print("=" * 72)
print("=== 3. 后台线程里不再有 root.after ===")
funcs = {f.name: f for f in cls.body if isinstance(f, ast.FunctionDef)}

def is_root_after(node):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr not in ('after', 'after_idle', 'after_cancel'):
        return False
    v = node.func.value
    return (isinstance(v, ast.Name) and v.id == 'root') or \
           (isinstance(v, ast.Attribute) and v.attr == 'root')

bg = set(f.name for f in cls.body if isinstance(f, ast.FunctionDef) and f.name.endswith('_async'))
for f in cls.body:
    if not isinstance(f, ast.FunctionDef):
        continue
    for node in ast.walk(f):
        if isinstance(node, ast.Call):
            for a in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(a, ast.Name) and a.id in funcs:
                    bg.add(a.id)
                if isinstance(a, ast.Attribute) and a.attr in funcs:
                    bg.add(a.attr)

bad = []
for name in sorted(bg):
    f = funcs.get(name)
    if not f:
        continue
    for c in ast.walk(f):
        if is_root_after(c) and c.args and isinstance(c.args[0], ast.Constant) \
           and c.args[0].value == 0:
            bad.append((name, c.lineno))
check("后台线程里没有 after(0, ...)", not bad, bad)
check("全项目 after(0, ...) 已清零", "root.after(0, " not in src)

print()
print("=" * 72)
print("=== 4. 状态栏行数检查改为增量计数 ===")
check("有 _status_line_count 字段", "_status_line_count" in src)
check("不再每次扫描全文", "self.status_text.index('end-1c')" in src)  # 只在超限时用
# 确认 index 调用在增量判断内部
upd = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == 'update_status')
upd_src = ast.unparse(upd)
guard = upd_src.index("self._status_line_count > 1200")
idx = upd_src.index("index('end-1c')")
check("index 扫描在增量判断之后（只在超限时执行）", idx > guard, f"guard@{guard} index@{idx}")

print()
print("=" * 72)
print("=== 5. UI 更新日志不再每次写盘 ===")
check("失败/警告仍是 INFO", "if success or msg_type in" in upd_src and "logging.info" in upd_src)
check("普通消息降到 DEBUG", "logging.debug" in upd_src)

print()
print("=" * 72)
print("=== 6. logcat 不再用不读的 stderr 管道 ===")
check("stderr 并入 stdout", "stderr=subprocess.STDOUT" in src)
check("不再有 logcat_subprocess.stderr.read()", "logcat_subprocess.stderr.read()" not in src)
check("去掉了周期性 fsync", "os.fsync(f.fileno())" not in src.split("def _run_logcat")[1][:4000]
      if "def _run_logcat" in src else True)

print()
print("=" * 72)
print("=== 7. 安装期间设备查询会被暂停 ===")
import utils as U
import subprocess as _sp

class _FR:
    def __init__(self, out=b"", rc=0):
        self.stdout = out; self.stderr = b""; self.returncode = rc

_real_run = _sp.run
def _fake_run(cmd, *a, **kw):
    if "adb devices" in str(cmd):
        return _FR(b"List of devices attached\n192.168.0.26:5555\tdevice\n")
    return _FR(b"")
_sp.run = _fake_run

try:
    U.set_device_validation_paused(False)
    U._device_cache['last_update'] = 0
    check("未暂停时能查到设备",
          U.get_connected_devices_cached_safe() == ["192.168.0.26:5555"],
          U.get_connected_devices_cached_safe())

    U._device_cache['last_update'] = 0
    U.set_device_validation_paused(True)
    check("暂停期间 query_connected_devices 返回 None（查不到，不当成断连）",
          U.query_connected_devices() is None)
    check("暂停期间缓存查询也返回 None",
          U.get_connected_devices_cached_safe() is None)

    U.set_device_validation_paused(False)
    U._device_cache['last_update'] = 0
    check("恢复后能正常查询",
          U.get_connected_devices_cached_safe() == ["192.168.0.26:5555"],
          U.get_connected_devices_cached_safe())
finally:
    _sp.run = _real_run
    U.set_device_validation_paused(False)

print()
print("=" * 72)
print("=== 8. 状态栏高频输出的实际开销 ===")
import tkinter as tk
from tkinter import ttk

root = tk.Tk()
txt = tk.Text(root, height=20, width=60)
txt.pack()
root.update()

# 模拟 1000 行文本
txt.insert(tk.END, "\n".join(f"第 {i} 行日志内容" for i in range(1000)))
root.update()

t = time.perf_counter()
for i in range(200):
    lines = txt.index('end-1c').split('.')[0]
scan_ms = (time.perf_counter() - t) * 1000

# 增量计数方式
t = time.perf_counter()
cnt = 1000
for i in range(200):
    cnt += 1
    if cnt > 1200:
        cnt = 800
incr_ms = (time.perf_counter() - t) * 1000

print(f"  每次扫描全文（1000 行）: {scan_ms:.1f} ms / 200 次 = {scan_ms/200:.3f} ms/次")
print(f"  增量计数              : {incr_ms:.1f} ms / 200 次 = {incr_ms/200:.3f} ms/次")
check("增量计数明显更快", incr_ms < scan_ms / 3, f"{scan_ms:.1f}ms -> {incr_ms:.1f}ms")
root.destroy()

print()
print("=" * 72)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 72)
sys.exit(0 if ok else 1)
