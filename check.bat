@echo off
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

echo.
echo [1/17] 代码质量检查 (lint)
"%PYTHON%" tools\lint.py
if errorlevel 1 set FAILED=1
echo.
echo [2/17] 核心路径回归测试
"%PYTHON%" tests\test_core_regression.py || set FAILED=1
echo.
echo [3/17] 设备查询与监控测试
"%PYTHON%" tests\test_device_query_and_monitor.py || set FAILED=1
echo.
echo [4/17] 设备切换与连接状态测试
"%PYTHON%" tests\test_device_switch.py || set FAILED=1
echo.
echo [5/17] 安装流程测试
"%PYTHON%" tests\test_install_flow.py || set FAILED=1
echo.
echo [6/17] 精简 ROM / 慢设备安装兼容测试
"%PYTHON%" tests\test_install_rom_compat.py || set FAILED=1
echo.
echo [7/17] 异步与线程安全测试
"%PYTHON%" tests\test_async_and_fixes.py || set FAILED=1
echo.
echo [8/17] 性能优化测试
"%PYTHON%" tests\test_perf_improvements.py || set FAILED=1
echo.
echo [9/17] 性能监控 v4 解析与分析测试
"%PYTHON%" tests\test_perf_v4.py || set FAILED=1
echo.
echo [10/17] 性能实时刷新链路测试
"%PYTHON%" tests\test_perf_live_refresh.py || set FAILED=1
echo.
echo [11/17] 整机 CPU 忙碌率公式回归
"%PYTHON%" tests\test_perf_cpu_formula.py || set FAILED=1
echo.
echo [12/17] 性能基线入口回归
"%PYTHON%" tests\test_perf_baseline_entry.py || set FAILED=1
echo.
echo [13/17] 终端搜索功能测试
"%PYTHON%" tests\test_log_search.py || set FAILED=1
echo.
echo [14/17] 终端导出跟随过滤
"%PYTHON%" tests\test_log_export_filter.py || set FAILED=1
echo.
echo [15/17] 日志错误聚类测试
"%PYTHON%" tests\test_log_analyzer.py || set FAILED=1
echo.
echo [16/17] 一键诊断包测试
"%PYTHON%" tests\test_diagnostic_package.py || set FAILED=1
echo.
echo [17/17] v4 工作台布局测试
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
