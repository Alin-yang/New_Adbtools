"""重建 check.bat 的测试步骤（保持 GBK + CRLF）

check.bat 必须保持 GBK 编码 —— cmd.exe 按 ANSI(GBK) 解码，
UTF-8 会把命令行拆散导致脚本全坏。

⚠️ 用**结构化重建**而不是正则替换：
   正则很容易误伤（之前一次把正常的那一步也删掉了），
   而且新步骤如果被追加到 `exit /b` 之后就永远不会执行。

用法: python tools/update_check_bat.py
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(ROOT, 'check.bat')

# (步骤标题, 测试脚本路径)  —— None 表示 lint（特殊处理）
STEPS = [
    ('代码质量检查 (lint)', None),
    ('核心路径回归测试', 'test_core_regression.py'),
    ('设备查询与监控测试', 'test_device_query_and_monitor.py'),
    ('设备切换与连接状态测试', 'test_device_switch.py'),
    ('安装流程测试', 'test_install_flow.py'),
    ('精简 ROM / 慢设备安装兼容测试', 'test_install_rom_compat.py'),
    ('异步与线程安全测试', 'test_async_and_fixes.py'),
    ('性能优化测试', 'test_perf_improvements.py'),
    ('性能监控 v4 解析与分析测试', 'test_perf_v4.py'),
    ('性能实时刷新链路测试', 'test_perf_live_refresh.py'),
    ('整机 CPU 忙碌率公式回归', 'test_perf_cpu_formula.py'),
    ('性能报告与图表回归', 'test_perf_report_chart.py'),
    ('性能基线入口回归', 'test_perf_baseline_entry.py'),
    ('终端搜索功能测试', 'test_log_search.py'),
    ('终端导出跟随过滤', 'test_log_export_filter.py'),
    ('连接状态判定回归', 'test_connect_state.py'),
    ('日志错误聚类测试', 'test_log_analyzer.py'),
    ('一键诊断包测试', 'test_diagnostic_package.py'),
    ('v4 工作台布局测试', 'test_layout_v4.py'),
]

HEAD = '''@echo off
chcp 65001 >nul
echo ================================
echo ADB Tool 一键检查
echo ================================
REM 跑 lint + 全部单元测试。任何一步失败就返回非 0。
REM 注意：本文件是 GBK 编码（cmd.exe 按 ANSI 解码 UTF-8 会把命令行拆散）。
REM 改这个文件时用 tools 下同目录的编码写法，或改完后用：
REM   python tools/update_check_bat.py

set "PYTHON=D://tool//python//python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set FAILED=0
'''

TAIL = '''
echo.
echo ================================
REM 必须显式 exit /b 0 或 1：
REM "exit /b %%FAILED%%" 在 if 块里是解析时展开的，拿到的还是初始空值。
if "%FAILED%"=="0" (
    echo 全部通过
    exit /b 0
) else (
    echo 存在失败项，请检查上面的输出
    exit /b 1
)
'''

total = len(STEPS)
body = []
for idx, (title, script) in enumerate(STEPS, 1):
    body.append(f'echo.\necho [{idx}/{total}] {title}')
    if script is None:
        body.append('"%PYTHON%" tools\\lint.py\nif errorlevel 1 set FAILED=1')
    else:
        body.append(f'"%PYTHON%" tests\\{script} || set FAILED=1')

src = HEAD + '\n' + '\n'.join(body) + '\n' + TAIL

# ── 校验：步骤编号连续、分母一致、测试都在 exit /b 之前 ──
steps = re.findall(r'\[(\d+)/(\d+)\]', src)
nums = [int(a) for a, b in steps]
assert nums == list(range(1, total + 1)), f'步骤编号不连续: {nums}'
assert all(int(b) == total for _, b in steps), '步数分母不一致'
before_exit = src.split('exit /b')[0]
for _, script in STEPS:
    if script:
        assert script in before_exit, f'缺少测试或位置错误: {script}'
# ⚠️ 用行首缩进匹配：注释里也有 "exit /b 0" 字样
assert len(re.findall(r'^\s+exit /b 0\s*$', src, re.M)) == 1
assert len(re.findall(r'^\s+exit /b 1\s*$', src, re.M)) == 1

# 写回：GBK + CRLF
out = src.replace('\r\n', '\n').replace('\n', '\r\n')
with io.open(BAT, 'wb') as f:
    f.write(out.encode('gbk'))

print('check.bat 已重建：')
print('  步骤:', re.findall(r'\[\d+/\d+\]', src))
print('  字节:', len(out.encode('gbk')))
