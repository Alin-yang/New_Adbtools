"""更新 check.bat：加入性能实时刷新测试，保持 GBK + CRLF

check.bat 必须保持 GBK 编码 —— cmd.exe 按 ANSI(GBK) 解码，
UTF-8 会把命令行拆散导致脚本全坏。

⚠️ 注意：新步骤必须插在 `exit /b` **之前**，否则永远不会执行。

用法: python tools/update_check_bat.py
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, 'check.bat')

with io.open(BAT, encoding='gbk') as f:
    src = f.read()

NEW_STEP = ('echo [10/10] 性能实时刷新链路测试\n'
            '"%PYTHON%" tests\\test_perf_live_refresh.py || set FAILED=1\n')

# 1) 清掉上一次可能追加到末尾的残段（在 exit /b 之后，永远不会执行）
src = re.sub(r'\n*echo\.\s*\n*echo \[11/11\][^\n]*\n[^\n]*test_perf_live_refresh[^\n]*\n',
             '\n', src)

# 2) 步骤总数统一为 10（当前 9 个测试 + 新增 1 个）
src = re.sub(r'\[(\d+)/11\]', r'[\1/10]', src)
src = re.sub(r'\[(\d+)/10\]', r'[\1/10]', src)

# 3) 把新步骤插到最后一个测试步骤之后（即 "echo ====" 之前）
if 'test_perf_live_refresh.py' not in src:
    anchor = '"%PYTHON%" tests\\test_layout_v4.py || set FAILED=1\n'
    assert src.count(anchor) == 1, src.count(anchor)
    src = src.replace(anchor, anchor + '\necho.\n' + NEW_STEP)

# 4) 校验：步骤编号必须连续 1..N，且新测试在 exit /b 之前
steps = re.findall(r'\[(\d+)/(\d+)\]', src)
nums = [int(a) for a, b in steps]
total = int(steps[0][1]) if steps else 0
assert nums == list(range(1, total + 1)), f'步骤编号不连续: {nums}'
assert 'test_perf_live_refresh.py' in src.split('exit /b')[0], \
    '新测试必须位于 exit /b 之前'

# 写回：GBK + CRLF
out = src.replace('\r\n', '\n').replace('\n', '\r\n')
with io.open(BAT, 'wb') as f:
    f.write(out.encode('gbk'))

print('check.bat 已更新：')
print('  步骤:', re.findall(r'\[\d+/\d+\]', src))
print('  字节:', len(out.encode('gbk')))
