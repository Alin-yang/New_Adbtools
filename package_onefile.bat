@echo off
chcp 65001 >nul
echo ================================
echo ADB Tool Packaging Script (onefile)
echo ================================
REM 打单个 exe，方便单文件分发。
REM ⚠️ onefile 每次启动都要把内嵌 archive 解压到 %%TEMP%%，实测多花约 9.5 秒。
REM    日常使用建议用 package.bat（onedir），启动快 12 倍。

set "PYTHON=D:\tool\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo Using Python: %PYTHON%
echo.
echo Cleaning old build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo Executing packaging (ADBTool.spec)...
"%PYTHON%" -m PyInstaller ADBTool.spec --noconfirm --clean

echo.
echo ================================
echo Packaging completed!
echo Executable location: dist\ADBTool.exe
echo ================================

echo.
echo Press any key to open dist folder...
pause >nul
explorer dist
