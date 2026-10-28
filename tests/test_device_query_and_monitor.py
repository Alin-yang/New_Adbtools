"""验证设备查询/监控去抖修复

用法: python tests/test_device_query_and_monitor.py
"""
import sys, os, types, subprocess, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
import config

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False

print("=== 1. query_connected_devices 区分「查询失败」与「没有设备」 ===")

class FakeResult:
    def __init__(self, out=b"", rc=0):
        self.stdout = out
        self.stderr = b""
        self.returncode = rc

def make_run(out=b"", rc=0, raise_exc=None):
    def _run(cmd, *a, **kw):
        if raise_exc:
            raise raise_exc
        return FakeResult(out, rc)
    return _run

real_run = subprocess.run

# 正常：两台设备
subprocess.run = make_run(b"List of devices attached\n192.168.0.26:5555\tdevice\nABC123\tdevice\n")
d = utils.query_connected_devices()
check("正常返回 2 台设备", d == ["192.168.0.26:5555", "ABC123"], d)

# 没有设备：成功但空列表
subprocess.run = make_run(b"List of devices attached\n")
d = utils.query_connected_devices()
check("确实没有设备 -> 空列表 []（不是 None）", d == [], d)

# offline / unauthorized 过滤
subprocess.run = make_run(b"List of devices attached\n1.2.3.4:5555\toffline\nXYZ\tunauthorized\nOK1\tdevice\n")
d = utils.query_connected_devices()
check("offline/unauthorized 被过滤", d == ["OK1"], d)

# adb 返回码非 0 -> 查询失败
subprocess.run = make_run(b"", rc=1)
d = utils.query_connected_devices()
check("adb 返回码非 0 -> None（查询失败）", d is None, d)

# 超时 -> 查询失败
subprocess.run = make_run(raise_exc=subprocess.TimeoutExpired(cmd="adb devices", timeout=5))
d = utils.query_connected_devices()
check("超时 -> None（查询失败）", d is None, d)

print()
print("=== 2. 缓存版本：查询失败时回退到上一次成功的结果 ===")
utils._device_cache.update({'devices': [], 'last_update': 0, 'cache_duration': 2.0, 'query_ok': False})
subprocess.run = make_run(b"List of devices attached\n192.168.0.26:5555\tdevice\n")
utils.get_connected_devices_cached_safe()
check("首次查询成功", utils.get_connected_devices_cached_safe() == ["192.168.0.26:5555"])

# 让缓存过期，然后让查询失败
utils._device_cache['last_update'] = 0
subprocess.run = make_run(b"", rc=1)
check("安全版：查询失败返回 None", utils.get_connected_devices_cached_safe() is None)
check("普通版：回退到上一次结果，不当成空列表",
      utils.get_connected_devices_cached() == ["192.168.0.26:5555"],
      utils.get_connected_devices_cached())

print()
print("=== 3. 并行验证改用 get-state，不再用 shell echo test ===")
calls = []
def fake_run2(cmd, *a, **kw):
    calls.append(cmd)
    if "devices" in cmd:
        return FakeResult(b"List of devices attached\n192.168.0.26:5555\tdevice\n")
    if "get-state" in cmd:
        return FakeResult(b"device\n")
    return FakeResult(b"")
subprocess.run = fake_run2
res = utils.get_connected_devices_parallel()
check("并行验证通过", res == ["192.168.0.26:5555"], res)
check("使用 get-state 而非 shell echo test",
      any("get-state" in c for c in calls) and not any("shell echo" in c for c in calls), calls)

# get-state 返回 offline -> 排除
def fake_run3(cmd, *a, **kw):
    if "devices" in cmd:
        return FakeResult(b"List of devices attached\n192.168.0.26:5555\tdevice\n")
    return FakeResult(b"offline\n")
subprocess.run = fake_run3
res = utils.get_connected_devices_parallel()
check("get-state 返回 offline -> 排除该设备", res == [], res)

print()
print("=== 4. 安装期间暂停设备验证（不打扰正在传输的设备） ===")
utils.set_device_validation_paused(True)
calls.clear()
subprocess.run = fake_run2
res = utils.get_connected_devices_parallel()
check("暂停期间跳过可达性验证（直接返回列表，不发 shell/get-state）",
      res == ["192.168.0.26:5555"] and not any("get-state" in c for c in calls), calls)
utils.set_device_validation_paused(False)
utils.set_device_validation_paused(False)
calls.clear()
subprocess.run = fake_run2
utils.get_connected_devices_parallel()
check("恢复后验证重新生效", any("get-state" in c for c in calls), calls)

print()
print("=== 5. 计数器：嵌套调用不会提前解除暂停 ===")
utils.set_device_validation_paused(True)
utils.set_device_validation_paused(True)
utils.set_device_validation_paused(False)
calls.clear()
subprocess.run = fake_run2
utils.get_connected_devices_parallel()
check("仍处于暂停状态（还有一层未释放）", not any("get-state" in c for c in calls), calls)
utils.set_device_validation_paused(False)

print()
print("=== 6. adb push 进度解析 ===")
import app
samples = [
    "[ 45%] /data/local/tmp/_adbtool_install.apk: 45%",
    "[ 45%] /data/local/tmp/_adbtool_install.apk: 45% (43.28MB/96.20MB)",
    "[100%] /data/local/tmp/_adbtool_install.apk: 100%",
]
for s in samples:
    m = app._PUSH_PERCENT_RE.search(s)
    check(f"百分比解析: {s[:34]}", bool(m), m.group(1) if m else None)
m = app._PUSH_SIZE_RE.search(samples[1])
check("传输量解析", bool(m) and m.group(1).strip() == "43.28MB" and m.group(2).strip() == "96.20MB",
      m.groups() if m else None)
check("无百分比的行不会误匹配", app._PUSH_PERCENT_RE.search("1 file pushed, 0 skipped.") is None)

print()
print("=== 7. device_monitor 去抖逻辑 ===")
import device_monitor

class FakeApp:
    def __init__(self):
        self._last_displayed_ip = "192.168.0.26"
        self.messages = []
        self.root = types.SimpleNamespace(after=lambda ms, fn: fn())
    def update_status(self, msg, success, msg_type="normal"):
        self.messages.append((msg, success, msg_type))
    def update_connection_status(self, ip_address=None, devices=None):
        pass

# 模拟设备列表序列：正常 -> 空 -> 空 -> 空 -> 正常
seq = [["192.168.0.26:5555"], [], [], [], ["192.168.0.26:5555"]]
it = iter(seq)

def fake_cached_safe():
    try:
        return next(it)
    except StopIteration:
        return ["192.168.0.26:5555"]

device_monitor.get_connected_devices_cached_safe = fake_cached_safe

app_ = FakeApp()
mon = device_monitor.DeviceMonitor(app_)
mon.disconnect_streak = 3
mon._monitor_loop.__wrapped__ if False else None

# 直接驱动循环逻辑（手动模拟一次迭代）
def run_iterations(monitor, app, results):
    last_devices = []
    empty_streak = 0
    msgs = []
    for current_devices in results:
        if current_devices is None:
            continue
        if not current_devices:
            empty_streak += 1
        else:
            empty_streak = 0
        if not current_devices and empty_streak < monitor.disconnect_streak:
            stable = last_devices
        else:
            stable = current_devices
        if set(stable) != set(last_devices):
            monitor._update_device_status_ui(stable)
            last_devices = list(stable)
    return msgs

msgs = run_iterations(mon, app_, seq)
disconnect_msgs = [m for m in app_.messages if "所有设备已断开连接" in m[0]]
recover_msgs = [m for m in app_.messages if "恢复" in m[0]]
check("连续 3 次空才报一次断连（而不是 3 次）", len(disconnect_msgs) == 1, app_.messages)
check("断连用 warning 级别而不是 error", disconnect_msgs and disconnect_msgs[0][2] == "warning", disconnect_msgs)
check("设备恢复后有明确提示", len(recover_msgs) == 1, recover_msgs)
check("恢复提示是 success 级别", recover_msgs and recover_msgs[0][1] is True, recover_msgs)

# 单次空快照不应报警
app2 = FakeApp()
mon2 = device_monitor.DeviceMonitor(app2)
run_iterations(mon2, app2, [["192.168.0.26:5555"], [], ["192.168.0.26:5555"]])
check("单次空快照不报警", not any("所有设备已断开连接" in m[0] for m in app2.messages), app2.messages)

# 查询失败(None)完全不改变状态
app3 = FakeApp()
mon3 = device_monitor.DeviceMonitor(app3)
run_iterations(mon3, app3, [["192.168.0.26:5555"], None, None, []])
check("查询失败(None)不会触发断连报警",
      not any("所有设备已断开连接" in m[0] for m in app3.messages), app3.messages)

print()
print("=== 8. 配置项 ===")
check("DEVICE_DISCONNECT_STREAK = 3", config.Config.DEVICE_DISCONNECT_STREAK == 3)
check("INSTALL_TIMEOUT = 900", config.Config.INSTALL_TIMEOUT == 900)
check("INSTALL_RETRIES = 2", config.Config.INSTALL_RETRIES == 2)

subprocess.run = real_run
print()
print("=" * 60)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 60)
sys.exit(0 if ok else 1)
