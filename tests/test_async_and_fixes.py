"""验证 P0 修复：grep 过滤、投屏端口、异步化不阻塞 UI

用法: python tests/test_async_and_fixes.py
"""
import sys, os, time, types, queue

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod
import utils
from utils import filter_lines, normalize_device_serial

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False


print("=" * 72)
print("=== 1. filter_lines（替代 shell grep）===")
check("多关键字命中", filter_lines("a level: 90\nb other\nc level: 50", "level") == ["a level: 90", "c level: 50"])
check("多个关键字任一命中", filter_lines("x mCurrentFocus\ny zzz\nw mResumedActivity", "mCurrentFocus", "mResumedActivity")
      == ["x mCurrentFocus", "w mResumedActivity"])
check("无关键字返回全部", filter_lines("a\nb") == ["a", "b"])
check("空输入返回空", filter_lines("") == [])
check("None 安全", filter_lines(None) == [])
check("包名过滤", filter_lines("com.a.b  123\nsystem  1\ncom.a.b  456", "com.a.b")
      == ["com.a.b  123", "com.a.b  456"])

print()
print("=" * 72)
print("=== 2. normalize_device_serial（投屏/ADB 设备名统一）===")
check("纯 IP 补 5555", normalize_device_serial("192.168.0.26") == "192.168.0.26:5555")
check("已带端口不动", normalize_device_serial("192.168.0.26:5555") == "192.168.0.26:5555")
check("其他端口不动", normalize_device_serial("192.168.0.26:6666") == "192.168.0.26:6666")
check("USB 序列号不动", normalize_device_serial("ABC123XYZ") == "ABC123XYZ")
check("去空格去引号", normalize_device_serial('  "192.168.0.26"  ') == "192.168.0.26:5555")
check("None 透传", normalize_device_serial(None) is None)
check("空串透传", normalize_device_serial("") == "")

print()
print("=" * 72)
print("=== 3. build_adb_command_with_device 仍正确补 -s ===")
cmd = utils.build_adb_command_with_device("adb shell ls", "192.168.0.26")
check("补 -s 和端口", cmd == "adb -s 192.168.0.26:5555 shell ls", cmd)

print()
print("=" * 72)
print("=== 4. 投屏命令含正确序列号 ===")
from modules.screen_mirror import ScreenMirrorManager
mgr = ScreenMirrorManager.__new__(ScreenMirrorManager)   # 不跑 __init__
scrcpy_cmd = mgr._build_scrcpy_command("scrcpy.exe", "192.168.0.26")
check("含 -s 192.168.0.26:5555", "-s" in scrcpy_cmd and "192.168.0.26:5555" in scrcpy_cmd, scrcpy_cmd)
scrcpy_cmd2 = mgr._build_scrcpy_command("scrcpy.exe", "192.168.0.26:5555")
check("已带端口不重复加", scrcpy_cmd2.count("192.168.0.26:5555") == 1, scrcpy_cmd2)

print()
print("=" * 72)
print("=== 5. 异步化：点击功能不应阻塞调用方 ===")

# 装饰器 @require_device_connected 会查设备列表，测试环境没有 adb 设备 -> mock 掉
utils.get_connected_devices_cached = lambda: ["192.168.0.26:5555"]

class FakeRoot:
    def after(self, ms, fn):
        fn()
        return "id"
    def after_cancel(self, tid):
        pass

class FakeStatusText:
    def __init__(self):
        self.lines = []
    def insert(self, idx, text, tag=None):
        self.lines.append((text.strip(), tag))
    def see(self, idx):
        pass
    def index(self, idx):
        return "1.0"

class FakeProgress:
    def __init__(self):
        self.state = {}
    def pack(self, **k): pass
    def pack_forget(self): pass
    def start(self, i=None): pass
    def stop(self): pass
    def __setitem__(self, k, v): self.state[k] = v
    def __getitem__(self, k): return self.state.get(k)

def make_stub(slow=2.0):
    s = types.SimpleNamespace()
    s.root = FakeRoot()
    s.status_text = FakeStatusText()
    s.progress = FakeProgress()
    s.messages = []
    s.adb_calls = []
    s.pkg_history = []
    s.ip_history = []
    s.version_display = None
    s._ui_queue = queue.Queue()
    s._ui_pump_scheduled = False
    s.pkg_combobox = None
    s.pkg_entry = None
    s.text_input_entry = None

    def fake_adb(cmd, retries=None, timeout=None, target_device=None):
        s.adb_calls.append(cmd)
        time.sleep(slow)             # 模拟慢设备
        return ("OK", True)
    s.run_adb_with_target = fake_adb
    s.get_package_name_from_input = lambda: "com.test.app"
    s.get_ip_address = lambda: "192.168.0.26"
    s._save_pkg_to_history = lambda p: None
    s.update_version_display = lambda v="": None
    s.run_adb_with_target = fake_adb

    for name in ('_run_in_ui', '_schedule_ui_pump', '_pump_ui_queue',
                 '_update_status_safe', 'run_in_background',
                 '_update_install_status', '_set_progress_mode', '_set_progress_value',
                 'kill_app_process', 'start_app', 'root_device', 'remount',
                 'get_android_version', 'get_version', 'log_clear',
                 'get_package_path', 'open_factory_menu', 'send_text_input'):
        setattr(s, name, getattr(appmod.ADBToolApp, name).__get__(s))
    s.update_status = lambda msg, success, msg_type="normal": s.messages.append((msg, success))
    return s


# ⚠️ root_device / remount 现在有二次确认弹窗（messagebox.askyesno）——
#    必须 mock，否则会弹出真实模态框阻塞测试（实测阻塞 69 秒）。
#    app.py 用模块级 messagebox，所以 patch 模块属性即可生效。
_real_askyesno = appmod.messagebox.askyesno
appmod.messagebox.askyesno = lambda *a, **kw: True

stub = make_stub(slow=2.0)
t0 = time.time()
stub.kill_app_process()
elapsed = time.time() - t0
check("kill_app_process 立即返回（不等 adb）", elapsed < 0.5, f"{elapsed:.3f}s")
check("确实发起了 adb 命令", len(stub.adb_calls) == 1, stub.adb_calls)

# 等后台线程完成，验证最终状态
time.sleep(2.4)
check("后台完成后有结果消息", any("成功终止" in m[0] for m in stub.messages), stub.messages)

print()
print("=" * 72)
print("=== 6. 各改造方法均不阻塞 ===")
for name in ('start_app', 'root_device', 'remount', 'get_android_version',
             'get_version', 'get_package_path', 'open_factory_menu'):
    st = make_stub(slow=1.5)
    t = time.time()
    getattr(st, name)()
    dt = time.time() - t
    check(f"{name}() 立即返回", dt < 0.4, f"{dt:.3f}s")

print()
print("=" * 72)
print("=== 6b. 危险操作取消确认时不执行命令 ===")
for name in ('root_device', 'remount'):
    st = make_stub(slow=0.1)
    appmod.messagebox.askyesno = lambda *a, **kw: False   # 用户点"取消"
    t = time.time()
    getattr(st, name)()
    elapsed = time.time() - t
    check(f"{name}() 取消后立即返回", elapsed < 0.5, f"{elapsed:.3f}s")
    check(f"{name}() 取消后不执行 adb 命令", len(st.adb_calls) == 0, st.adb_calls)
    check(f"{name}() 取消后有提示", any("取消" in m[0] for m in st.messages), st.messages)
appmod.messagebox.askyesno = _real_askyesno

print()
print("=" * 72)
print("=== 7. 异常不会逃逸到主线程 ===")
st = make_stub(slow=0.1)
def boom(cmd, retries=None, timeout=None, target_device=None):
    raise RuntimeError("设备掉线")
st.run_adb_with_target = boom
st.kill_app_process()
time.sleep(0.5)
check("异常被捕获并提示", any("失败" in m[0] or "未找到" in m[0] for m in st.messages), st.messages)

print()
print("=" * 72)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 72)
sys.exit(0 if ok else 1)
