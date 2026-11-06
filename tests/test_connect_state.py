# -*- coding: utf-8 -*-
"""连接状态判定 —— 防回归测试（v5.4.9）

⚠️ **这个文件守护的是 v5.4.9 修的真实 bug**：
   用户反馈「我点击了连接，输出连接成功，实际并没有连接上」。

根因：`app.py` 用 `if "connected" in output.lower()` 判定连接成功，
而 `adb connect` 的输出之一是：

    already connected to 192.168.0.50:5555

**它也含 "connected"** → 旧代码直接报「✓ 连接成功」。
但 `already connected` 的真实含义是「adb server 里已有这个条目」
（transport 还在），**不代表设备可用**。
设备端 adbd 卡住时（网络通、5555 端口可达、但握手失败），
`adb connect` 返回的就是这一条，而 `adb devices` 里它是 **offline**。

正确流程：**connect → 用 `adb devices` 查实际状态 → 才报成功**。

⚠️ 另一个坑（本测试一并守护）：
   `adb devices` 和 `adb -s X get-state` 对同一设备**会给出不同答案** ——
   `devices` 显示 offline 时 `get-state` 可能说 `device not found`
   （两者查 transport 的路径不同）。所以状态判定必须用 `adb devices`。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(_ROOT))

FAILED = []
PASSED = 0


def check(name, cond, detail=''):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}   {detail}")


print("=" * 68)
print("连接状态判定 —— 防回归测试")
print("=" * 68)

# ====================================================================== #
# 1. 判定规则：adb connect 的三种输出
# ====================================================================== #
print()
print("=== 1. adb connect 输出的三种情况 ===")

# 各输出 → 是否应该判为成功
# ⚠️ 关键：**不能靠输出文本判定**，必须查实际状态
CONNECT_CASES = [
    # (adb connect 输出, 该设备在 adb devices 里的实际状态, 期望结果)
    ("connected to 192.168.0.50:5555", "device", True),
    ("already connected to 192.168.0.50:5555", "device", True),
    ("already connected to 192.168.0.50:5555", "offline", False),
    ("already connected to 192.168.0.50:5555", "notfound", False),
    ("failed to connect to 192.168.0.50:5555", "notfound", False),
    ("failed to connect to 192.168.0.50:5555", "offline", False),
]


def judge_by_output(output):
    """❌ 旧逻辑：只看输出里有没有 'connected'"""
    return "connected" in output.lower()


for out, state, expected in CONNECT_CASES:
    got = judge_by_output(out)
    if expected:
        # 设备确实可用 → 旧逻辑判成功是对的
        check(f"旧逻辑对 {out[:30]!r} 判成功（与实际一致）",
              got is True, f"旧逻辑={got}")
    elif 'already connected' in out:
        # ⚠️ **核心断言**：`already connected` 时旧逻辑一律判成功，
        #    但设备实际是 offline / notfound → **误报连接成功**
        check(f"旧逻辑对 'already connected' 会误判（实际={state}）",
              got is True,
              f"这就是 bug —— 旧逻辑={got}，设备实际不可用")
    else:
        # failed to connect → 旧逻辑判失败是对的
        check(f"旧逻辑对 'failed to connect' 判失败（正确）",
              got is False, f"旧逻辑={got}")

print()
print("  → 旧逻辑把 'already connected' 一律当成功，这就是 bug 根源")
print("  → 正确做法：无论输出是什么，都要用 adb devices 查实际状态")

# ====================================================================== #
# 2. DeviceQuery.get_device_state：必须用 adb devices
# ====================================================================== #
print()
print("=== 2. get_device_state 的实现要求 ===")

import inspect
from modules.device_query import DeviceQuery

_src = inspect.getsource(DeviceQuery.get_device_state)

check("get_device_state 存在", hasattr(DeviceQuery, 'get_device_state'))
check("用 `adb devices` 查状态（不是 get-state）",
      'adb devices' in _src, "必须用 adb devices —— get-state 会误报 not found")
# ⚠️ 用 **AST** 精确提取代码（去掉所有字符串常量与注释）——
#    逐行 strip('#') 是不够的：docstring 是**多行字符串**，
#    里面提到 get-state 会被误判成「代码里用了 get-state」。
import ast
import textwrap


def _code_only(src):
    """提取源码里的**真实代码**（去掉注释和所有字符串常量）

    ⚠️ 必须用 textwrap.dedent —— `inspect.getsource` 带缩进，
       直接 ast.parse 会 IndentationError → 静默返回原文 → 断言全误报。
    """
    try:
        tree = ast.parse(textwrap.dedent(src))
    except SyntaxError:
        return ''
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue
        if isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, ast.arg):
            out.append(node.arg)
    return ' '.join(out)


_state_code = _code_only(_src)
check("AST 提取有效（不是空串）", bool(_state_code.strip()),
      "extract 失败 → 断言是假绿")
check("get_device_state 里没有真的调用 `get-state`",
      'get-state' not in _state_code,
      "get-state 与 adb devices 的答案会不一致")
# ⚠️ 'adb devices' 是**字符串常量**（被 AST 排除）→ 要单独查字符串列表
_state_strs = [n.value for n in ast.walk(ast.parse(textwrap.dedent(_src)))
               if isinstance(n, ast.Constant) and isinstance(n.value, str)]
check("get_device_state 用了 adb devices",
      any('adb devices' in x for x in _state_strs),
      str([x for x in _state_strs if 'adb' in x][:3]))
check("能识别 offline", 'offline' in _src)
check("能识别 unauthorized", 'unauthorized' in _src)
check("能识别 device", "'device'" in _src)
check("设备不在列表时返回 notfound", 'notfound' in _src)
check("有 is_device_ready 便捷方法",
      hasattr(DeviceQuery, 'is_device_ready'))

# ====================================================================== #
# 3. app.py 的连接流程
# ====================================================================== #
print()
print("=== 3. app.py 连接流程 ===")

_app_src = io_open = open(os.path.join(os.path.dirname(_ROOT), 'app.py'),
                          encoding='utf-8').read()

# 3a. 不再用 "connected" in output 判定
# ⚠️ 用 AST 提取真实代码 —— docstring 里引用了这段旧代码来解释 bug，
#    字符串常量必须排除，否则永远查不到。
# ⚠️ AST 提取要 dedent（inspect.getsource 带缩进），
#    否则 parse 失败 → 静默返回空 → 断言恒真（假护栏）
_app_code = _code_only(_app_src)
check("AST 提取有效（不是空串）", bool(_app_code.strip()),
      "extract 失败 → 下面的断言都是假绿")

# ⚠️ **最精确的检查**：AST 里找「`'connected' in <某表达式>.lower()`」
#    这个 Compare 节点 —— 它就是旧 bug 的判定式。
#    比字符串搜索精确得多，不会被注释/文档字符串干扰。
_bad_compare = []
for _node in ast.walk(ast.parse(textwrap.dedent(_app_src))):
    if not isinstance(_node, ast.Compare):
        continue
    if not any(isinstance(_op, (ast.In, ast.NotIn)) for _op in _node.ops):
        continue
    # 左边是字符串常量 'connected'
    _left = _node.left
    if isinstance(_left, ast.Constant) and isinstance(_left.value, str) \
            and _left.value.lower() == 'connected':
        _bad_compare.append(ast.dump(_node)[:120])
check("AST 里没有 `'connected' in X.lower()` 这种判定",
      not _bad_compare, str(_bad_compare[:1]))
check("旧判定确实会误判（already connected 含 'connected'）",
      'connected' in 'already connected to x'.lower())

# 3b. 必须有验证步骤
check("有 _verify_device_state() 方法",
      'def _verify_device_state' in _app_src)
check("连接流程里调用了状态验证",
      'self._verify_device_state(' in _app_src)

# 3c. 必须有状态验证的分支处理
for st in ('offline', 'unauthorized', 'notfound'):
    check(f"处理了 {st} 状态", f"'{st}'" in _app_src)

# 3d. 失败提示要可操作
check("有失败提示生成方法",
      'def _build_connect_failure_msg' in _app_src)
check("offline 提示里说明了原因",
      'adbd' in _app_src)

# 3e. 时间预算
check("有连接时间预算常量 CONNECT_TOTAL_BUDGET",
      'CONNECT_TOTAL_BUDGET' in _app_src)
check("connect 单次超时不超过 8 秒",
      'CONNECT_CMD_TIMEOUT = 6' in _app_src
      or 'CONNECT_CMD_TIMEOUT = 5' in _app_src
      or 'CONNECT_CMD_TIMEOUT = 8' in _app_src,
      "设备端不响应时超时太长 → 用户干等")

# 3f. connect 用短超时 + 不重试
check("connect 显式指定 retries=1（不重试）",
      'retries=1' in _app_src,
      "默认 retries=2 → 最坏等 2 倍超时")
check("connect 显式指定 timeout",
      'timeout=self.CONNECT_CMD_TIMEOUT' in _app_src)

# ====================================================================== #
# 4. 线程安全：后台线程不能读 Tk 控件
# ====================================================================== #
print()
print("=== 4. 线程安全（后台线程读控件会抛 main thread is not in main loop）===")

check("run_adb_with_target 支持显式传 target_ip",
      'target_ip: Optional[str] = None' in _app_src,
      "不传就去读 Tk 控件 → 后台线程抛异常")
check("连接流程显式传了 target_ip",
      'target_ip=ip_address' in _app_src)
check("update_connection_status 有线程保护",
      'def update_connection_status' in _app_src)

# 精确检查 update_connection_status 里有没有线程判断
_i = _app_src.index('def update_connection_status')
_seg = _app_src[_i:_i + 2200]
check("update_connection_status 里有主线程判断",
      'threading.current_thread() is not threading.main_thread()' in _seg,
      "它在后台线程会直接操作 Tk 控件（device_count_label.config）")

check("update_connection_status 有 _run_in_ui 转投",
      '_run_in_ui' in _seg)

# ====================================================================== #
# 5. 状态解析函数本身的行为（用假数据）
# ====================================================================== #
print()
print("=== 5. adb devices 输出解析 ===")


# ⚠️ **直接用真实实现**，不要在这里复刻一份 ——
#    复刻的副本测的是副本，改了真实现测试还是绿的（假护栏）。
_parse_real = DeviceQuery.get_device_state


def parse_devices(output, target):
    """调**真实的** get_device_state（把 subprocess.run 换成假的）"""
    import subprocess

    class _R:
        returncode = 0
        stderr = b''

        def __init__(self, data):
            self.stdout = data.encode('utf-8')

    def _fake(cmd, **kwargs):
        return _R(output)

    orig = subprocess.run
    subprocess.run = _fake
    try:
        return _parse_real(target)
    finally:
        subprocess.run = orig


# ⚠️ 这些是**真实抓到的** adb devices 输出（v5.4.9 实测）
REAL_OUTPUTS = [
    # (adb devices 输出, 查询目标, 期望状态)
    ("List of devices attached\n192.168.0.50:5555\toffline transport_id:12\n",
     "192.168.0.50", 'offline'),
    ("List of devices attached\n192.168.0.50:5555\toffline transport_id:12\n",
     "192.168.0.50:5555", 'offline'),
    ("List of devices attached\n192.168.0.50:5555\tdevice product:x model:y\n",
     "192.168.0.50", 'device'),
    ("List of devices attached\n192.168.0.50:5555\tdevice product:x\n",
     "192.168.0.50:5555", 'device'),
    ("List of devices attached\n192.168.0.49:5555\tdevice\n",
     "192.168.0.50", 'notfound'),
    ("List of devices attached\n",
     "192.168.0.50", 'notfound'),
    ("List of devices attached\n192.168.0.50:5555\tunauthorized\n",
     "192.168.0.50", 'unauthorized'),
    # USB 设备（序列号，无 IP）
    ("List of devices attached\n0123456789ABCDEF\tdevice\n",
     "0123456789ABCDEF", 'device'),
]

for out, target, expected in REAL_OUTPUTS:
    got = parse_devices(out, target)
    check(f"解析 {out.splitlines()[-1][:40]!r} (查 {target})",
          got == expected, f"得到 {got!r}，期望 {expected!r}")

print()
print("=" * 68)
if FAILED:
    print(f"HAS FAILURES —— {len(FAILED)} 项失败：")
    for f in FAILED:
        print(f"  - {f}")
    print("=" * 68)
    sys.exit(1)
else:
    print(f"ALL PASS （{PASSED} 项）")
    print("=" * 68)
