@echo off
chcp 65001 >nul
echo ================================
echo ADB Tool Packaging Script (onedir)
echo ================================
REM 默认打 onedir：产物是 dist\ADBTool\ 文件夹，启动不需要解压。
REM 实测比 onefile 快约 12 秒（onefile 每次启动都要把内嵌 archive 解压到 %TEMP%）。
REM 需要单个 exe 文件时用 package_onefile.bat。

set "PYTHON=D:\tool\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo Using Python: %PYTHON%
echo.
echo Cleaning old build files...
if exist build rmdir /s /q build
if exist build_onedir rmdir /s /q build_onedir
if exist dist rmdir /s /q dist
if exist dist_onedir rmdir /s /q dist_onedir

echo.
echo Executing packaging (ADBTool_onedir.spec)...
"%PYTHON%" -m PyInstaller ADBTool_onedir.spec --noconfirm --clean

echo.
echo ================================
echo Packaging completed!
echo Executable location: dist\ADBTool\ADBTool.exe
echo NOTE: 分发时请把整个 dist\ADBTool 文件夹一起打包
echo ================================

echo.
echo Press any key to open dist folder...
pause >nul
explorer dist
