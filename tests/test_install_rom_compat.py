"""安装流程在**精简 ROM / 慢设备**上的修复回归测试

背景（真机实测：康佳电视 Android 5.1.1，36MB APK）：
  · 该 ROM **没有 head / wc / stat / sed / awk / od / toybox**（只有 busybox）
  · `pm install <路径>` 在这台设备上会挂死（连不存在的文件都卡 40 秒+）
  · `pm install` 持有**全局安装锁**，残留进程会让下一次排队等锁
  · 36MB APK：push 约 45 秒，pm install 约 180~430 秒

修复前的问题：
  1. 可读性探测硬编码 `head -c 4` → 精简 ROM 上误判「设备端文件不可读」
  2. push 超时固定值太小 → 传输中途被判失败，**残留进程还在跑**
  3. 回退去 `adb install` → 在这类 ROM 上必然失败（remote Is a directory）
  4. pm install 期间 `readline()` 阻塞 → 心跳不执行，界面像卡死
  5. pm 打完 Success 但进程不退出 → 一直等到超时，把成功误判成失败

本测试守护这 5 点（全部 mock，不依赖真机）。

用法: python tests/test_install_rom_compat.py
"""
import os
import queue
import subprocess
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod
from config import Config

ok = True


def check(name, cond, extra=''):
    global ok
    print(('  PASS  ' if cond else '  FAIL  ') + name
          + (('  -> ' + str(extra)) if extra else ''))
    if not cond:
        ok = False


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
        self.state = {"mode": "indeterminate", "maximum": 100, "value": 0}

    def pack(self, **kw):
        pass

    def pack_forget(self):
        pass

    def start(self, interval=None):
        pass

    def stop(self):
        pass

    def __setitem__(self, k, v):
        self.state[k] = v

    def __getitem__(self, k):
        return self.state.get(k)


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
    s._ui_pump_started = True
    s.messages = []
    s.install_msgs = []
    s.update_status = lambda msg, success, msg_type="normal": s.messages.append((msg, success))
    s._update_install_status = lambda msg: s.install_msgs.append(msg)
    s._set_progress_mode = lambda m: None
    s._set_progress_value = lambda v: None
    s._hide_progress = lambda: None
    s._show_progress = lambda: None
    for name in ('_check_remote_file_readable', '_remote_file_ready', '_remote_size',
                 '_run_pm_install', '_install_via_push_pm', '_install_on_device',
                 '_install_via_adb_install', '_install_with_retry'):
        setattr(s, name, getattr(appmod.ADBToolApp, name).__get__(s))
    # 静态方法要单独绑定
    s._first_meaningful_line = appmod.ADBToolApp.__dict__['_first_meaningful_line'].__func__
    s._kill_process = appmod.ADBToolApp.__dict__['_kill_process'].__func__
    s._run_adb_capture = lambda cmd, timeout=30: ""
    return s


real_run = subprocess.run
real_popen = subprocess.Popen


def restore():
    subprocess.run = real_run
    subprocess.Popen = real_popen


print("=" * 72)
print("=== 1. 超时按文件大小动态估算 ===")
# 36MB 真实 APK
SIZE_36M = 37883711
t_small = Config.install_push_timeout(1024 * 1024)
t_36 = Config.install_push_timeout(SIZE_36M)
t_huge = Config.install_push_timeout(200 * 1024 * 1024)
check("超时随文件大小递增", t_small < t_36 < t_huge, f"{t_small} < {t_36} < {t_huge}")
check("小文件也有下限（不小于 120s）", t_small >= 120, t_small)
check("push 超时有上限", t_huge <= Config.INSTALL_PUSH_MAX_TIMEOUT, t_huge)
p_small = Config.install_pm_timeout(1024 * 1024)
p_36 = Config.install_pm_timeout(SIZE_36M)
check("pm 超时随大小递增", p_small < p_36, f"{p_small} < {p_36}")
check("pm 超时比 push 宽松（设备端更慢）", p_36 > t_36, f"pm={p_36} push={t_36}")
check("36MB 的 pm 超时够覆盖实测 195~430 秒",
      p_36 >= 430, p_36)
check("pm 超时有上限", Config.install_pm_timeout(500 * 1024 * 1024)
      <= Config.INSTALL_PM_MAX_TIMEOUT)

print()
print("=" * 72)
print("=== 2. 可读性探测：head 缺失时回退 busybox / ls ===")
stub = make_stub()
TMP = '/data/local/tmp/_adbtool_install.apk'

# 场景 A：标准设备（head 存在）
responses = {
    'head': "READABLE\n",
}


def fake_run_standard(cmd, **kw):
    return FakeResult("READABLE\n")


subprocess.run = fake_run_standard
r, detail = stub._check_remote_file_readable(TMP, 'dev', expect_size=100)
check("标准设备：head 探测成功", r is True, detail)

# 场景 B：精简 ROM（head 不存在，busybox 可用）
def fake_run_busybox(cmd, **kw):
    c = cmd if isinstance(cmd, str) else ' '.join(cmd)
    if 'busybox head' in c:
        return FakeResult("PK\x03\x04READABLE\n")
    if 'head -c' in c:
        return FakeResult("/system/bin/sh: head: not found\n")
    if 'ls -l' in c:
        return FakeResult("-rw-rw-rw- root root 100 2026-11-03 18:38 x.apk\n")
    return FakeResult("")


subprocess.run = fake_run_busybox
r, detail = stub._check_remote_file_readable(TMP, 'dev', expect_size=100)
check("精简 ROM：回退 busybox 成功", r is True, detail)
check("  且说明里体现了走的是 busybox", 'busybox' in detail, detail)

# 场景 C：连 busybox 都没有，只能靠 ls
def fake_run_ls_only(cmd, **kw):
    c = cmd if isinstance(cmd, str) else ' '.join(cmd)
    if 'ls -l' in c:
        return FakeResult("-rw-rw-rw- root root 100 2026-11-03 18:38 x.apk\n")
    if 'head' in c:
        return FakeResult("/system/bin/sh: head: not found\n")
    return FakeResult("")


subprocess.run = fake_run_ls_only
r, detail = stub._check_remote_file_readable(TMP, 'dev', expect_size=100)
check("无 head 无 busybox：回退 ls 成功", r is True, detail)

# 场景 D：大小不匹配 → 必须判不可读（否则白跑三分钟安装）
def fake_run_wrong_size(cmd, **kw):
    c = cmd if isinstance(cmd, str) else ' '.join(cmd)
    if 'ls -l' in c:
        return FakeResult("-rw-rw-rw- root root 999 2026-11-03 18:38 x.apk\n")
    if 'busybox head' in c:
        return FakeResult("PKREADABLE\n")
    if 'head' in c:
        return FakeResult("/system/bin/sh: head: not found\n")
    return FakeResult("")


subprocess.run = fake_run_wrong_size
r, detail = stub._check_remote_file_readable(TMP, 'dev', expect_size=100)
check("大小不匹配 → 判不可读", r is False, detail)
check("  且给出具体数字", '999' in detail and '100' in detail, detail)

# 场景 E：文件不存在
def fake_run_missing(cmd, **kw):
    c = cmd if isinstance(cmd, str) else ' '.join(cmd)
    if 'head' in c:
        return FakeResult("head: /data/local/tmp/__nope__.apk: No such file or directory\n")
    return FakeResult("")


subprocess.run = fake_run_missing
r, detail = stub._check_remote_file_readable('/data/local/tmp/__nope__.apk', 'dev',
                                            expect_size=100)
check("文件不存在 → 判不可读", r is False, detail)

# 场景 F：真正的权限拒绝
def fake_run_denied(cmd, **kw):
    c = cmd if isinstance(cmd, str) else ' '.join(cmd)
    if 'head' in c:
        return FakeResult("head: cannot open: Permission denied\n")
    return FakeResult("")


subprocess.run = fake_run_denied
r, detail = stub._check_remote_file_readable(TMP, 'dev', expect_size=100)
check("权限拒绝 → 判不可读", r is False, detail)

print()
print("=" * 72)
print("=== 3. _remote_file_ready：设备端文件大小比对 ===")
subprocess.run = fake_run_busybox
check("大小一致 → True", stub._remote_file_ready('dev', 100) is True)
check("大小不一致 → False", stub._remote_file_ready('dev', 999) is False)

print()
print("=" * 72)
print("=== 4. pm install：收到 Success 立即判定成功（不等进程退出）===")


class HangingProc:
    """打完 Success 后**不退出**（实测某些 ROM 的收尾行为）"""

    def __init__(self, lines):
        self._lines = list(lines)
        self.returncode = None
        self.stdout = self
        self.terminated = False
        self._done = False

    def __iter__(self):
        for l in self._lines:
            yield l
        self._done = True

    def readline(self):
        return ''

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -1

    def kill(self):
        self.terminated = True
        self.returncode = -1


stub2 = make_stub()
captured = {}


def fake_popen_success(cmd, **kw):
    captured['cmd'] = cmd
    return HangingProc(["pkg: /data/local/tmp/_adbtool_install.apk\n", "Success\n"])


subprocess.Popen = fake_popen_success
out, good = stub2._run_pm_install(TMP, 'dev', timeout=30, apk_size=1024 * 1024)
check("收到 Success 即返回 True", good is True, out[:120])
check("  输出里含 Success", 'Success' in out, out[:120])

print()
print("=" * 72)
print("=== 5. pm install：超时必须杀掉进程（否则残留进程持安装锁）===")
stub3 = make_stub()
killed = {'v': False}


class SlowProc:
    """什么都不输出，永远不退出"""

    def __init__(self):
        self.returncode = None
        self.stdout = self
        self.terminated = False

    def __iter__(self):
        return iter([])

    def readline(self):
        return ''

    def poll(self):
        return None

    def wait(self, timeout=None):
        return None

    def terminate(self):
        self.terminated = True
        self.returncode = -1

    def kill(self):
        self.terminated = True
        self.returncode = -1


def fake_popen_slow(cmd, **kw):
    return SlowProc()


def fake_kill(proc):
    killed['v'] = True
    proc.kill()


stub3._kill_process = fake_kill
subprocess.Popen = fake_popen_slow
out, good = stub3._run_pm_install(TMP, 'dev', timeout=1, apk_size=1024)
check("超时判定为失败", good is False)
check("  超时后杀掉了进程（防残留持锁）", killed['v'] is True)
check("  提示里说明了残留安装进程的风险",
      '安装锁' in out or '仍在运行' in out, out[:160])

print()
print("=" * 72)
print("=== 6. 回退策略：设备端文件完好时优先重试 pm install ===")
stub4 = make_stub()
stub4._install_via_push_pm = lambda *a, **kw: (False, "pm install 失败: 模拟失败")
stub4._install_via_adb_install = lambda *a, **kw: (False, "adb install 失败")
stub4._remote_file_ready = lambda *a, **kw: True
stub4._run_pm_install = lambda *a, **kw: ("pkg: x\nSuccess\n", True)
stub4._set_progress_value = lambda v: None

ok4, msg4 = stub4._install_with_retry('/tmp/a.apk', 100, 'dev')
check("设备端文件完好 → 走 pm install 重试并成功", ok4 is True, msg4)
check("  没有退回 adb install", 'adb install' not in msg4, msg4)

# 设备端文件不在 → 才退回 adb install
stub5 = make_stub()
stub5._install_via_push_pm = lambda *a, **kw: (False, "push 失败")
called = {'adb': False}


def fake_adb_install(*a, **kw):
    called['adb'] = True
    return True, "安装成功（adb install）"


stub5._install_via_adb_install = fake_adb_install
stub5._remote_file_ready = lambda *a, **kw: False
ok5, msg5 = stub5._install_with_retry('/tmp/a.apk', 100, 'dev')
check("设备端无文件 → 回退 adb install", called['adb'] is True and ok5 is True, msg5)

restore()
print()
print('=' * 72)
print('ALL PASS' if ok else 'HAS FAIL')
sys.exit(0 if ok else 1)
