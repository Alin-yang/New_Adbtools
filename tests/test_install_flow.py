"""安装流程端到端模拟（mock adb）

用法: python tests/test_install_flow.py
"""
import sys, os, io, types, queue, subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod
from modules.device_query import DeviceQuery
import config

ok = True
def check(name, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False


class FakeRoot:
    def after(self, ms, fn):
        fn()
        return "id"

class FakeStatusText:
    def __init__(self):
        self.lines = []
    def insert(self, idx, text, tag=None):
        self.lines.append((text.strip(), tag))
    def see(self, idx):
        pass

class FakeProgress:
    def __init__(self):
        self.state = {"mode": "indeterminate", "maximum": 100, "value": 0}
    def pack(self, **kw): pass
    def pack_forget(self): pass
    def start(self, interval=None): pass
    def stop(self): pass
    def __setitem__(self, k, v): self.state[k] = v
    def __getitem__(self, k): return self.state.get(k)

class FakeProc:
    """模拟 subprocess.Popen：按顺序吐出输出行，EOF 时视为进程已退出"""
    def __init__(self, lines, rc=0):
        self._lines = list(lines)
        self._i = 0
        self._rc = rc
        self.returncode = None
        self.stdout = self
        self.terminated = False
    def readline(self):
        if self._i < len(self._lines):
            line = self._lines[self._i]
            self._i += 1
            return line
        self.returncode = self._rc
        return ''
    def poll(self):
        return self.returncode
    def wait(self, timeout=None):
        self.returncode = self._rc
        return self._rc
    def terminate(self): self.terminated = True
    def kill(self): self.terminated = True

class FakeResult:
    def __init__(self, out="", rc=0):
        self.stdout = out
        self.stderr = ""
        self.returncode = rc


def make_stub():
    s = types.SimpleNamespace()
    s.root = FakeRoot()
    s.status_text = FakeStatusText()
    s.progress = FakeProgress()
    s._ui_queue = queue.Queue()
    s._ui_pump_scheduled = False
    s.get_ip_address = lambda: "192.168.0.26"
    s.messages = []
    s.update_status = lambda msg, success, msg_type="normal": s.messages.append((msg, success))
    for name in ('_run_in_ui', '_schedule_ui_pump', '_pump_ui_queue',
                 '_update_install_status', '_update_status_safe',
                 '_set_progress_mode', '_set_progress_value', '_show_progress', '_hide_progress',
                 '_install_with_retry', '_install_via_push_pm', '_run_pm_install',
                 '_run_adb_capture', '_install_via_adb_install', '_run_install_with_progress',
                 '_check_remote_file_readable'):
        setattr(s, name, getattr(appmod.ADBToolApp, name).__get__(s))
    s._kill_process = appmod.ADBToolApp.__dict__['_kill_process'].__func__
    return s

real_popen = subprocess.Popen
real_run = subprocess.run
real_getsize = os.path.getsize


print("=== A. 正常安装：push 真实进度 + pm install ===")
stub = make_stub()
cmds = []

PUSH_LINES = [
    "[  0%] /data/local/tmp/_adbtool_install.apk: 0% (0B/96.20MB)\n",
    "[ 45%] /data/local/tmp/_adbtool_install.apk: 45% (43.28MB/96.20MB)\n",
    "[100%] /data/local/tmp/_adbtool_install.apk: 100% (96.20MB/96.20MB)\n",
    "1 file pushed, 0 skipped.\n",
]

def fake_popen(cmd, **kw):
    cmds.append(cmd)
    if "push" in cmd:
        return FakeProc(PUSH_LINES, rc=0)
    if "install" in cmd:
        return FakeProc(["Performing Streamed Install\n", "Success\n"], rc=0)
    return FakeProc([], rc=0)

def fake_run(cmd, **kw):
    cmds.append(cmd)
    if "pm install" in cmd:
        return FakeResult("Success\n", 0)
    if "READABLE" in cmd:
        # 设备端文件可读 → push 路径继续
        return FakeResult("READABLE\n", 0)
    if "rm -f" in cmd:
        return FakeResult("", 0)
    return FakeResult("", 0)

subprocess.Popen = fake_popen
subprocess.run = fake_run
os.path.getsize = lambda p: 100_922_880  # 96.2MB

stub._run_install_with_progress("D:\\work\\适配\\16.11\\需求测试包\\弹窗\\sample-app-debug.apk")

msgs = [t for t, _ in stub.status_text.lines]
tags = [g for _, g in stub.status_text.lines]

check("有 push 命令", any("push" in c for c in cmds), cmds)
check("push 带 -s 192.168.0.26:5555", any("adb -s 192.168.0.26:5555 push" in c for c in cmds), cmds)
check("push 路径带中文且被引号包裹", any('"D:\\work\\适配\\16.11' in c for c in cmds), cmds)
check("pm install 带 -s 与临时路径",
      any("adb -s 192.168.0.26:5555 shell pm install -r -d /data/local/tmp/_adbtool_install.apk" in c for c in cmds), cmds)
check("清理了设备端临时文件", any("rm -f /data/local/tmp/_adbtool_install.apk" in c for c in cmds), cmds)
check("push 后做了设备端可读性预检",
      any("READABLE" in c for c in cmds), cmds)

check("显示真实百分比 45%", any("45%" in m for m in msgs), msgs)
check("显示传输量", any("43.28MB" in m and "96.20MB" in m for m in msgs), msgs)
check("有设备端安装阶段提示", any("设备端安装" in m for m in msgs), msgs)
check("最终提示安装成功", any("安装成功" in m for m in msgs), msgs)
check("进度条到 100", stub.progress.state.get("value") == 100, stub.progress.state)

print()
print("=== B. push 失败 -> 自动回退 adb install ===")
stub = make_stub()
cmds2 = []

def fake_popen2(cmd, **kw):
    cmds2.append(cmd)
    if "push" in cmd:
        return FakeProc(["adb: error: failed to stat '/tmp/x'\n"], rc=1)
    if "install" in cmd:
        return FakeProc(["Performing Streamed Install\n", "Success\n"], rc=0)
    return FakeProc([], rc=0)

def fake_run2(cmd, **kw):
    cmds2.append(cmd)
    if "pm install" in cmd:
        return FakeResult("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n", 1)
    if "READABLE" in cmd:
        return FakeResult("READABLE\n", 0)
    return FakeResult("", 0)

subprocess.Popen = fake_popen2
subprocess.run = fake_run2
stub._run_install_with_progress("D:\\work\\app.apk")

msgs2 = [t for t, _ in stub.status_text.lines]
check("回退时执行了 adb install", any("install -r -d" in c and "push" not in c for c in cmds2), cmds2)
check("回退路径同样带 -s", any("adb -s 192.168.0.26:5555 install -r -d" in c for c in cmds2), cmds2)
check("回退成功时给出成功提示", any("安装成功" in m for m in msgs2), msgs2)
check("回退过程中有状态说明", any("回退" in m for m in msgs2), msgs2)

print()
print("=== C. 两条路径都失败 -> 报失败并清理 ===")
stub = make_stub()
cmds3 = []

def fake_popen3(cmd, **kw):
    cmds3.append(cmd)
    if "push" in cmd:
        return FakeProc(["adb: error: failed\n"], rc=1)
    return FakeProc(["Failure [INSTALL_FAILED_OLDER_SDK]\n"], rc=1)

def fake_run3(cmd, **kw):
    cmds3.append(cmd)
    return FakeResult("Failure [INSTALL_FAILED_OLDER_SDK]\n", 1)

subprocess.Popen = fake_popen3
subprocess.run = fake_run3
stub._run_install_with_progress("D:\\work\\app.apk")
msgs3 = [t for t, _ in stub.status_text.lines]
check("失败原因被带出来", any("INSTALL_FAILED" in m for m in msgs3), msgs3)
check("有失败提示", any("失败" in m for m in msgs3), msgs3)
check("失败后进度条被隐藏", stub.progress.state.get("value") is not None)

print()
print("=== D. 安装期间设备验证处于暂停状态 ===")
import utils
utils.set_device_validation_paused(False)
stub = make_stub()
subprocess.Popen = fake_popen
subprocess.run = fake_run
stub._run_install_with_progress("D:\\work\\app.apk")
check("安装结束后恢复验证（未残留暂停）", DeviceQuery._pause_count == 0,
      DeviceQuery._pause_count)

print()
print("=== E. 定制 ROM：adb install 返回码 1 但设备端打了 Success ===")
# 复现真机问题（TCL com.tcl.guard）：
#   adb install 实际安装成功，设备端输出 "install apk has been enabled from
#   pm by user!" + "Success"，但 adb 客户端退出码是 1。
#   旧实现只看 returncode → 误报失败。
stub = make_stub()
cmds4 = []

def fake_popen4(cmd, **kw):
    cmds4.append(cmd)
    if "push" in cmd:
        return FakeProc(PUSH_LINES, rc=0)
    if "install" in cmd:
        return FakeProc([
            "Performing Streamed Install\n",
            "adb.exe: failed to install xxx.apk: Get install_switch_flag: 1\n",
            "install apk has be enabled from pm by user!\n",
            "Success\n",
        ], rc=1)          # ← 关键：退出码 1
    return FakeProc([], rc=0)

def fake_run4(cmd, **kw):
    cmds4.append(cmd)
    if "pm install" in cmd:
        # pm 路径失败（设备拒绝）→ 才会回退到 adb install
        return FakeResult("Failure [INSTALL_FAILED_OLDER_SDK]\n", 1)
    if "READABLE" in cmd:
        return FakeResult("READABLE\n", 0)
    if "dumpsys package" in cmd:
        # 设备端确实装上了：versionCode 已更新
        return FakeResult("    versionCode=999999 minSdk=16 targetSdk=26\n", 0)
    if "rm -f" in cmd:
        return FakeResult("", 0)
    return FakeResult("", 0)

subprocess.Popen = fake_popen4
subprocess.run = fake_run4
os.path.getsize = lambda p: 100_922_880

# 让包名提取可控：真实 APK 不存在时 verify 会拿不到包名，这里 mock 掉
import utils as _U
_real_extract = _U.extract_package_name_from_apk
_U.extract_package_name_from_apk = lambda p: "com.example.app"
_U.get_apk_version_code = lambda p: 999999

stub._run_install_with_progress("D:\\work\\app.apk")

msgs4 = [t for t, _ in stub.status_text.lines]
check("设备端 Success 被识别为成功信号",
      any("设备端已确认安装成功" in m for m in msgs4), msgs4)
check("不再误报失败（没有 code 1 的失败结论）",
      not any("安装失败 (code 1)" in m for m in msgs4), msgs4)
check("提示了退出码不可信的原因",
      any("退出码" in m and "误报" in m for m in msgs4), msgs4)

subprocess.Popen = real_popen
subprocess.run = real_run
os.path.getsize = real_getsize
_U.extract_package_name_from_apk = _real_extract

print()
print("=" * 60)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 60)
sys.exit(0 if ok else 1)
