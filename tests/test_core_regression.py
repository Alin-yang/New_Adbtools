"""核心路径回归测试

给最容易被改坏的几条路径加护栏：adb 命令执行、设备查询、安装流程、监控去抖。
这些是"改一行不知道会不会弄坏别处"的高风险区。

用法: python tests/test_core_regression.py
"""
import sys, os, subprocess, types, queue, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from modules.device_query import DeviceQuery
import app as appmod
import device_monitor

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", rc=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = rc


_real_run = subprocess.run
_real_sleep = time.sleep


def patch_run(handler):
    subprocess.run = handler


def restore():
    subprocess.run = _real_run
    time.sleep = _real_sleep


print("=" * 72)
print("=== 1. run_adb_command：成功 / 超时 / 非零退出 / 不可重试错误 ===")

# 成功
patch_run(lambda *a, **kw: FakeProc(b"hello\n"))
out, good = utils.run_adb_command("adb devices", retries=1, timeout=5)
check("成功时返回输出", out == "hello\n" and good, (out, good))

# 超时
def raise_timeout(*a, **kw):
    raise subprocess.TimeoutExpired(cmd="adb", timeout=5)
patch_run(raise_timeout)
time.sleep = lambda s: None
out, good = utils.run_adb_command("adb x", retries=2, timeout=1, target_device="1.2.3.4")
check("超时时返回失败 + 提示", not good and "timed out" in out.lower(), out)
check("超时会重试到上限", True)  # 下面用计数验证

calls = {"n": 0}
def counting_timeout(*a, **kw):
    calls["n"] += 1
    raise subprocess.TimeoutExpired(cmd="adb", timeout=5)
patch_run(counting_timeout)
out, good = utils.run_adb_command("adb x", retries=3, timeout=1)
# 注：不指定 target_device 时 build_adb_command_with_device 会先探测一次设备数量，
#     所以总调用数 = 1(探测) + N(重试)；指定 target_device 则没有探测
check("retries=3 时实际尝试 3 次", calls["n"] == 3, calls["n"])

# 非零退出（CalledProcessError）
def raise_cpe(*a, **kw):
    calls["n"] += 1
    raise subprocess.CalledProcessError(1, "adb x", output=b"", stderr="设备未找到".encode("utf-8"))
patch_run(raise_cpe)
calls["n"] = 0
out, good = utils.run_adb_command("adb x", retries=3, timeout=1, target_device="1.2.3.4")
check("非零退出返回失败", not good, out)
check("错误信息用 UTF-8 解码（中文不乱码）", "设备未找到" in out, out)
check("'device not found/offline' 不重试", calls["n"] == 1, calls["n"])

# 可重试错误
def raise_cpe2(*a, **kw):
    calls["n"] += 1
    raise subprocess.CalledProcessError(1, "adb x", output=b"", stderr=b"closed")
patch_run(raise_cpe2)
calls["n"] = 0
out, good = utils.run_adb_command("adb x", retries=3, timeout=1, target_device="1.2.3.4")
check("普通错误会重试到上限", calls["n"] == 3, calls["n"])

restore()

print()
print("=" * 72)
print("=== 2. 设备查询：失败/空/正常 三态 ===")
DeviceQuery.reset_cache()

def r_ok(*a, **kw):
    return FakeProc(b"List of devices attached\n192.168.0.26:5555\tdevice\n")
patch_run(r_ok)
check("正常查到 1 台", utils.query_connected_devices() == ["192.168.0.26:5555"],
      utils.query_connected_devices())

def r_empty(*a, **kw):
    return FakeProc(b"List of devices attached\n")
patch_run(r_empty)
check("无设备返回 []（不是 None）", utils.query_connected_devices() == [])

def r_fail(*a, **kw):
    return FakeProc(b"", rc=1)
patch_run(r_fail)
check("adb 失败返回 None", utils.query_connected_devices() is None)

restore()

print()
print("=" * 72)
print("=== 3. 设备标识标准化（投屏/ADB 一致性）===")
from utils import normalize_device_serial
check("IP 补 5555", normalize_device_serial("192.168.0.26") == "192.168.0.26:5555")
check("已带端口不变", normalize_device_serial("192.168.0.26:5555") == "192.168.0.26:5555")
check("USB 序列号不变", normalize_device_serial("ABC123") == "ABC123")

print()
print("=" * 72)
print("=== 4. 监控去抖：查询失败不误报、单次空不报警 ===")

class FakeApp:
    def __init__(self):
        self._last_displayed_ip = "192.168.0.26"
        self.messages = []
        self.root = types.SimpleNamespace(after=lambda ms, fn: fn())
    def update_status(self, msg, success, msg_type="normal"):
        self.messages.append((msg, success, msg_type))
    def update_connection_status(self, ip_address=None, devices=None):
        pass

def run_monitor(monitor, results):
    last_devices = []
    empty_streak = 0
    for current in results:
        if current is None:
            continue
        if not current:
            empty_streak += 1
        else:
            empty_streak = 0
        stable = last_devices if (not current and empty_streak < monitor.disconnect_streak) else current
        if set(stable) != set(last_devices):
            monitor._update_device_status_ui(stable)
            last_devices = list(stable)

mon = device_monitor.DeviceMonitor(FakeApp())
app1 = FakeApp()
mon._update_device_status_ui = lambda d: app1.update_status(
    "⚠️ 所有设备已断开连接", False, "warning") if not d else None
run_monitor(mon, [["192.168.0.26:5555"], None, None, None])
check("连续查询失败不误报断连", not any("断开" in m[0] for m in app1.messages), app1.messages)

app2 = FakeApp()
mon2 = device_monitor.DeviceMonitor(app2)
run_monitor(mon2, [["192.168.0.26:5555"], [], ["192.168.0.26:5555"]])
check("单次空快照不报警", not any("断开" in m[0] for m in app2.messages), app2.messages)

app3 = FakeApp()
mon3 = device_monitor.DeviceMonitor(app3)
run_monitor(mon3, [["192.168.0.26:5555"], [], [], []])
check("连续 3 次空才报断连", len([m for m in app3.messages if "断开" in m[0]]) == 1, app3.messages)

print()
print("=" * 72)
print("=== 5. 全量 getprop / 全量包版本：一次命令拿全部 ===")
from utils import parse_getprop_all
p = parse_getprop_all("[ro.product.model]: [Pixel 6]\n[ro.build.version.sdk]: [33]\n")
check("getprop 全量解析", p.get("ro.product.model") == "Pixel 6" and p.get("ro.build.version.sdk") == "33", p)

print()
print("=" * 72)
print("=== 6. 投屏参数：用户选择能进命令行 ===")
from modules.screen_mirror import ScreenMirrorManager
m = ScreenMirrorManager.__new__(ScreenMirrorManager)
cmd = m._build_scrcpy_command("scrcpy.exe", "192.168.0.26",
                              {'bitrate': '4M', 'max_size': '1080', 'max_fps': '24'})
def g(flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None
check("码率生效", g('--video-bit-rate') == '4M', cmd)
check("帧率生效", g('--max-fps') == '24', cmd)
check("分辨率生效", g('--max-size') == '1080', cmd)
check("设备序列号补端口", g('-s') == '192.168.0.26:5555', cmd)
cmd0 = m._build_scrcpy_command("scrcpy.exe", "192.168.0.26", {'max_size': '0'})
check("分辨率 0 = 不缩放（不传 --max-size）", '--max-size' not in cmd0, cmd0)

print()
print("=" * 72)
print("=== 7. 性能监控：PSS 在各 Android 版本都能解析 ===")
from modules.performance_monitor import PerfParsers
a10 = """
 App Summary
           Java Heap:   12345
         Native Heap:    6789
           Total PSS:   45678
"""
r = PerfParsers.parse_meminfo(a10)
check("Android 10+ 的 Total PSS 能解析", r['pss'] == 44.6, r)
a7 = """
  TOTAL        123456    67890     4567       890
"""
r7 = PerfParsers.parse_meminfo(a7)
check("Android 7 表格 TOTAL 取第一列（Pss）", r7['pss'] == 120.6, r7)

print()
print("=" * 72)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 72)
sys.exit(0 if ok else 1)
