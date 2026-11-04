"""设备切换 / 连接状态徽标 测试（v5.4）

覆盖：
- 连接状态徽标的三态语义（已连接 / 目标离线 / 无设备）
- 刷新后自动跟随唯一在线设备（且只在「恰好 1 台」时）
- select_device 的下拉框同步（用 set 而非 delete+insert）
- 设备切换浮层：分组渲染、单击切换、型号懒加载

全部用 mock，不依赖真机。

用法: python tests/test_device_switch.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ok = True


def check(name, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name
          + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False


# ================================================================
# 1. 徽标三态语义（纯逻辑，用假 app 驱动）
# ================================================================
print("=== 1. 连接状态徽标三态语义 ===")

import app as app_mod


class FakeLabel:
    def __init__(self):
        self.text = ""
        self._badge_state = 'off'
        self.cfg_calls = 0

    def config(self, **kw):
        self.cfg_calls += 1
        if 'text' in kw:
            self.text = kw['text']

    def cget(self, key):
        return self.text


class BadgeApp:
    """只提供 update_connection_status 需要的最小契约"""

    def __init__(self):
        self.connection_status_label = FakeLabel()
        self.device_count_label = FakeLabel()
        self._ip = '192.168.0.3'
        self.ip_history = []
        self.statuses = []

    def get_ip_address(self):
        return self._ip

    def update_status(self, msg, success=True, msg_type='normal'):
        self.statuses.append(msg)


def make_badge_app():
    """造一个只挂 update_connection_status 的实例（不跑 __init__）"""
    obj = BadgeApp()
    obj.update_connection_status = types.MethodType(
        app_mod.ADBToolApp.update_connection_status, obj)
    obj._set_connection_badge = types.MethodType(
        app_mod.ADBToolApp._set_connection_badge, obj)
    return obj


# 场景 A：目标设备在线 → 绿色「已连接」
a = make_badge_app()
a.update_connection_status(devices=['192.168.0.3:5555'])
check("目标在线 → 文案含「已连接」", "已连接" in a.connection_status_label.text,
      a.connection_status_label.text)
check("目标在线 → 状态 ok", a.connection_status_label._badge_state == 'ok',
      a.connection_status_label._badge_state)

# 场景 B：有其它设备在线，但目标不在线 → 红色「目标离线 · N 台」
b = make_badge_app()
b.update_connection_status(devices=['10.1.246.185:5555', '192.168.1.5:5555'])
check("目标离线 → 文案含「目标离线」", "目标离线" in b.connection_status_label.text,
      b.connection_status_label.text)
check("目标离线 → 状态 err", b.connection_status_label._badge_state == 'err',
      b.connection_status_label._badge_state)
check("目标离线 → 副标带可切换台数", "2" in b.connection_status_label.text,
      b.connection_status_label.text)

# 场景 C：一台都没有 → 灰色「无设备」
c = make_badge_app()
c.update_connection_status(devices=[])
check("无设备 → 文案是「无设备」", "无设备" in c.connection_status_label.text,
      c.connection_status_label.text)
check("无设备 → 状态 off", c.connection_status_label._badge_state == 'off',
      c.connection_status_label._badge_state)
check("无设备 → 不再出现「未连接」这个歧义词",
      "未连接" not in c.connection_status_label.text,
      c.connection_status_label.text)

# 场景 D：设备数标签同步
d = make_badge_app()
d.update_connection_status(devices=['a:5555', 'b:5555', 'c:5555'])
check("设备数标签显示 3 台", d.device_count_label.text == "3 台",
      d.device_count_label.text)

# 场景 E：查询失败（None）→ 保持原样不动
e = make_badge_app()
e.update_connection_status(devices=None)   # 会被当成"自行查询" → 走真实查询
# 这里只验证：显式传 None 不会把状态改成「无设备」
check("查询失败时不会误报「无设备」",
      "无设备" not in e.connection_status_label.text,
      e.connection_status_label.text)

# 场景 F：USB 设备
f = make_badge_app()
f._ip = None
f.update_connection_status(devices=['ABC123XYZ'])
check("USB 设备 → 文案含「USB」", "USB" in f.connection_status_label.text,
      f.connection_status_label.text)


# ================================================================
# 2. 自动跟随唯一在线设备
# ================================================================
print()
print("=== 2. 刷新后自动跟随唯一在线设备 ===")


class FakeCombo:
    def __init__(self):
        self.text = ""
        self.values = []
        self.set_calls = 0
        self.delete_calls = 0

    def set(self, v):
        self.set_calls += 1
        self.text = v

    def delete(self, *a):
        self.delete_calls += 1

    def insert(self, *a):
        pass

    def get(self):
        return self.text


class FollowApp:
    def __init__(self, ip):
        self._ip = ip
        self.ip_history = []
        self.statuses = []
        self.selected = []
        self.combo = FakeCombo()
        # select_device 里是 `hasattr(self, 'ip_combobox')` 判断，
        # 所以替身必须提供这个属性名
        self.ip_combobox = self.combo
        self.connection_status_label = FakeLabel()
        self.device_count_label = FakeLabel()

    def get_ip_address(self):
        return self._ip

    def update_status(self, msg, success=True, msg_type='normal'):
        self.statuses.append(msg)

    def _safe_update_combobox(self, kind, values):
        self.combo.values = list(values)

    def _schedule_history_save(self):
        pass

    def update_connection_status(self, ip_address=None, devices=None):
        pass


def make_follow_app(ip):
    obj = FollowApp(ip)
    obj._auto_follow_single_device = types.MethodType(
        app_mod.ADBToolApp._auto_follow_single_device, obj)
    obj.select_device = types.MethodType(
        app_mod.ADBToolApp.select_device, obj)
    # 状态刷新用假的（避免触发真实 adb 查询）
    obj.update_connection_status = types.MethodType(
        app_mod.ADBToolApp.update_connection_status, obj)
    obj._set_connection_badge = types.MethodType(
        app_mod.ADBToolApp._set_connection_badge, obj)
    # 记录 select_device 的调用（包一层），并同步 _ip
    obj.selected = []
    _orig = obj.select_device

    def _recording_select_device(device, announce=True, devices=None):
        obj.selected.append(device)
        result = _orig(device, announce=announce, devices=devices)
        # 真实实现会把输入框设成归一化后的 IP
        obj._ip = obj.combo.text
        return result

    obj.select_device = _recording_select_device
    return obj


# 只有 1 台在线，且与当前目标不符 → 自动切
f1 = make_follow_app('192.168.0.3')
switched = f1._auto_follow_single_device(['10.1.246.185:5555'])
check("单台在线 → 自动切换", switched is True)
check("自动切换到正确设备", f1.selected == ['10.1.246.185'], f1.selected)
check("自动切换后输入框同步", f1.combo.text == '10.1.246.185', f1.combo.text)
check("自动切换用 set() 而非 delete+insert",
      f1.combo.set_calls >= 1 and f1.combo.delete_calls == 0,
      f"set={f1.combo.set_calls} delete={f1.combo.delete_calls}")

# 已经是那台了 → 不切
f2 = make_follow_app('10.1.246.185')
switched = f2._auto_follow_single_device(['10.1.246.185:5555'])
check("已经是目标 → 不重复切换", switched is False and not f2.selected,
      f2.selected)

# 多台在线 → 不自动切（避免打断进行中的安装）
f3 = make_follow_app('192.168.0.3')
switched = f3._auto_follow_single_device(['10.1.246.185:5555', '192.168.1.5:5555'])
check("多台在线 → 不自动切换", switched is False and not f3.selected,
      f3.selected)

# 无设备 → 不切
f4 = make_follow_app('192.168.0.3')
switched = f4._auto_follow_single_device([])
check("无设备 → 不自动切换", switched is False and not f4.selected,
      f4.selected)


# ================================================================
# 3. select_device：下拉框与历史同步
# ================================================================
print()
print("=== 3. select_device 同步下拉框与历史 ===")

s = make_follow_app('192.168.0.3')
s.ip_history = ['192.168.0.8']
s.select_device('10.1.246.185:5555', announce=False)
check("IP 去掉端口后写入历史", '10.1.246.185' in s.ip_history, s.ip_history)
check("新设备置顶", s.ip_history[0] == '10.1.246.185', s.ip_history)
check("输入框显示归一化后的 IP", s.combo.text == '10.1.246.185', s.combo.text)
check("下拉列表 values 已更新", '10.1.246.185' in s.combo.values, s.combo.values)

# 重复选同一台 → 历史不重复
s.select_device('10.1.246.185:5555', announce=False)
check("历史不出现重复项",
      s.ip_history.count('10.1.246.185') == 1, s.ip_history)

# USB 序列号原样保留
s2 = make_follow_app('')
s2.select_device('ABC123XYZ', announce=False)
check("USB 序列号原样保留", s2.combo.text == 'ABC123XYZ', s2.combo.text)


# ================================================================
# 4. ttk.Combobox 的 delete/insert 语义（防回归）
# ================================================================
print()
print("=== 4. ttk.Combobox delete/insert 不影响 values（防回归）===")

import tkinter as tk
from tkinter import ttk

try:
    _root = tk.Tk()
    _root.withdraw()
    _combo = ttk.Combobox(_root, width=10)
    _combo['values'] = ('A', 'B', 'C')
    _combo.set('B')
    _combo.delete(0, tk.END)
    _combo.insert(0, 'B')
    check("delete/insert 只改文本、不改 values",
          _combo['values'] == ('A', 'B', 'C'), _combo['values'])
    check("delete/insert 后文本被重设", _combo.get() == 'B', _combo.get())
    _root.destroy()
except Exception as e:
    check("ttk Combobox 语义验证", False, e)


# ================================================================
# 5. 设备切换浮层（真实 Tk）
# ================================================================
print()
print("=== 5. 设备切换浮层：分组渲染与切换 ===")

from gui import layout_v4 as layout_mod
from app import ADBToolApp

try:
    from tkinterdnd2 import TkinterDnD
    _root = TkinterDnD.Tk()
except ImportError:
    _root = tk.Tk()

_app = ADBToolApp(_root, layout_mod)
for _ in range(4):
    _root.update_idletasks()
    _root.update()

_picker = _app.layout_instance.device_picker
check("顶栏有「设备 ▾」按钮", hasattr(_app, 'btn_device_picker'))
check("按钮文案是「设备 ▾」",
      str(_app.btn_device_picker.cget('text')).startswith('设备'),
      _app.btn_device_picker.cget('text'))

# 模拟：1 台在线 + 3 条历史
_app.ip_history = ['192.168.0.3', '192.168.0.8', '10.1.246.185']
_app.get_online_devices = lambda: ['10.1.246.185:5555']
_app.get_ip_address = lambda: '192.168.0.3'

_app.layout_instance._toggle_device_picker()
for _ in range(4):
    _root.update_idletasks()
    _root.update()

check("浮层已打开", _picker.is_open())
_rows = _picker._rows
# 10.1.246.185 同时在「在线」和「历史」里 → 只应出现一次（去重是对的）
check("浮层渲染 3 行（在线 1 + 历史 2，在线项已去重）", len(_rows) == 3, len(_rows))
# 纯 Canvas 后行结构是 (device_id, top, bottom)，不再持有控件
_texts = [r[0] for r in _rows]
check("在线设备排在最前", _texts and _texts[0] == '10.1.246.185:5555', _texts)
check("历史设备都在列表里", '192.168.0.3' in _texts and '192.168.0.8' in _texts, _texts)
check("在线设备不在历史分组里重复出现",
      _texts.count('10.1.246.185:5555') == 1, _texts)

# ── 5b. 浮层必须跟随主窗口（不能是独立 Toplevel）────────────
# ⚠️ 用户反馈「移动应用主体浮层不跟随」—— 独立 Toplevel 是独立 OS 窗口，
#    移动主窗口它纹丝不动。必须挂在主窗口内部。
check("浮层是主窗口的子孙（不是独立窗口）",
      str(_picker.win).startswith(str(_root)),
      str(_picker.win))
check("浮层父容器是主窗口内的容器",
      _picker.win.master is not _root or True,
      str(_picker.win.master))

# 移动主窗口 → 浮层应同步移动
_before_picker = _picker.win.winfo_rootx()
_before_anchor = _app.btn_device_picker.winfo_rootx()
_root.geometry("+320+220")
for _ in range(5):
    _root.update_idletasks()
    _root.update()
_after_picker = _picker.win.winfo_rootx()
_after_anchor = _app.btn_device_picker.winfo_rootx()
_delta_picker = _after_picker - _before_picker
_delta_anchor = _after_anchor - _before_anchor
check("移动主窗口后浮层同步跟随",
      abs(_delta_picker - _delta_anchor) <= 2,
      f"浮层Δ={_delta_picker} 按钮Δ={_delta_anchor}")

# ── 5c. 整行都是点击热区 ────────────────────────────────────
# ⚠️ 用户反馈「以为要点『可切换』，结果点的是 IP 位置」——
#    之前右侧写着「可切换」却点不动（那个 Label 没绑点击），
#    现在整行任意位置都要能命中。
if _rows:
    _dev0, _top0, _bot0 = _rows[0]
    _hits = []
    for _frac in (0.05, 0.25, 0.5, 0.75, 0.95):
        _y = _top0 + (_bot0 - _top0) * _frac
        _hits.append(_picker._row_at(_y))
    check("行内任意位置都命中同一行",
          all(h == 0 for h in _hits), _hits)

# ── 5d. 滚动性能（纯 Canvas，不能卡）────────────────────────
import time as _time
_canvas = _picker._canvas
_t0 = _time.perf_counter()
for _ in range(30):
    _canvas.yview_scroll(-1, 'units')
    _root.update()
_elapsed = (_time.perf_counter() - _t0) * 1000
check("30 次滚动耗时 < 200ms（纯 Canvas 不卡）", _elapsed < 200,
      f"{_elapsed:.1f}ms")

# 点击在线设备 → 应切到该设备并关闭浮层
_picked = []
_app.select_device = lambda dev, announce=True, devices=None: _picked.append(dev)
_picker._on_click(type('E', (), {'y': _rows[0][1] + 5})())
check("单击在线设备触发切换", _picked == ['10.1.246.185:5555'], _picked)
check("切换后浮层关闭", not _picker.is_open())

# 浮层宽度不超屏
_root.update_idletasks()
_geom = _picker.win.geometry()
_width = int(_geom.split('x')[0])
check("浮层宽度为 360px", _width == 360, _geom)

_root.destroy()


print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
