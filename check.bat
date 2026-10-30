@echo off
chcp 65001 >nul
echo ================================
echo ADB Tool 一键检查
echo ================================
REM 跑 lint + 全部单元测试。任何一步失败就返回非 0。
REM 注意：本文件是 GBK 编码（cmd.exe 按 ANSI 解码 UTF-8 会把命令行拆散）。
REM 改这个文件时用 tools 下同目录的编码写法，或改完后用：
REM   python -c "import io;s=io.open('check.bat',encoding='utf-8').read();io.open('check.bat','wb').write(s.replace(chr(10),chr(13)+chr(10)).encode('gbk'))"

set "PYTHON=D://tool//python//python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

set FAILED=0

echo.
echo [1/9] 代码质量检查 (lint)
"%PYTHON%" tools\lint.py
if errorlevel 1 set FAILED=1

echo.
echo [2/9] 核心路径回归测试
"%PYTHON%" tests\test_core_regression.py || set FAILED=1

echo.
echo [3/9] 设备查询与监控测试
"%PYTHON%" tests\test_device_query_and_monitor.py || set FAILED=1

echo.
echo [4/9] 安装流程测试
"%PYTHON%" tests\test_install_flow.py || set FAILED=1

echo.
echo [5/9] 异步与线程安全测试
"%PYTHON%" tests\test_async_and_fixes.py || set FAILED=1

echo.
echo [6/9] 性能优化测试
"%PYTHON%" tests\test_perf_improvements.py || set FAILED=1

echo.
echo [7/9] 性能监控解析器测试
"%PYTHON%" tests\test_perf_parsers.py || set FAILED=1

echo.
echo [8/9] 终端搜索功能测试
"%PYTHON%" tests\test_log_search.py || set FAILED=1

echo.
echo [9/9] v4 工作台布局测试
"%PYTHON%" tests\test_layout_v4.py || set FAILED=1

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
