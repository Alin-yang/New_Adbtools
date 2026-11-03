"""更新 check.bat：加入 v4 性能测试，保持 GBK + CRLF

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

# 1) 旧版性能解析器测试 → 换成 v4 版（测的是重写后的新模块）
src = src.replace(
    'echo [7/9] 性能监控解析器测试\n'
    '"%PYTHON%" tests\\test_perf_parsers.py || set FAILED=1',
    'echo [7/10] 性能监控 v4 解析与分析测试\n'
    '"%PYTHON%" tests\\test_perf_v4.py || set FAILED=1')

# 2) 步骤数 9 → 10
src = re.sub(r'\[(\d)/9\]', r'[\1/10]', src)

# 3) 在最后一步后追加新测试（如果还没有）
if 'test_perf_v4.py' not in src:
    old = ('echo [9/10] v4 工作台布局测试\n'
           '"%PYTHON%" tests\\test_layout_v4.py || set FAILED=1\n')
    new = old + ('\necho.\n'
                 'echo [10/10] 性能监控 v4 解析与分析测试\n'
                 '"%PYTHON%" tests\\test_perf_v4.py || set FAILED=1\n')
    assert src.count(old) == 1, src.count(old)
    src = src.replace(old, new)

# 写回：GBK + CRLF
out = src.replace('\r\n', '\n').replace('\n', '\r\n')
with io.open(BAT, 'wb') as f:
    f.write(out.encode('gbk'))

print('check.bat 已更新：')
print('  步骤:', re.findall(r'\[\d/\d\]', src))
print('  字节:', len(out.encode('gbk')))
