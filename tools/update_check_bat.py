"""把 v4 布局测试加进 check.bat（GBK 编码，CRLF 行尾）

check.bat 必须保持 GBK 编码 —— cmd.exe 按 ANSI(GBK) 解码，
UTF-8 会把命令行拆散导致脚本全坏。

用法: python tools/update_check_bat.py
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, 'check.bat')

with io.open(BAT, encoding='gbk') as f:
    src = f.read()

# 1) 在终端搜索测试之后插入 v4 布局测试
old = (
    'echo.\n'
    'echo [8/8] 终端搜索功能测试\n'
    '"%PYTHON%" tests\\test_log_search.py || set FAILED=1\n'
)
new = (
    'echo.\n'
    'echo [8/9] 终端搜索功能测试\n'
    '"%PYTHON%" tests\\test_log_search.py || set FAILED=1\n'
    '\n'
    'echo.\n'
    'echo [9/9] v4 工作台布局测试\n'
    '"%PYTHON%" tests\\test_layout_v4.py || set FAILED=1\n'
)
if 'test_layout_v4.py' not in src:
    assert src.count(old) == 1, src.count(old)
    src = src.replace(old, new)

# 2) 步骤编号统一改成 /9
src = re.sub(r'\[(\d)/8\]', r'[\1/9]', src)

# 写回：GBK + CRLF
out = src.replace('\r\n', '\n').replace('\n', '\r\n')
with io.open(BAT, 'wb') as f:
    f.write(out.encode('gbk'))

print('check.bat 已更新：')
print('  步骤:', re.findall(r'\[\d/\d\]', src))
print('  字节:', len(out.encode('gbk')))
