@echo off
chcp 65001 >nul
echo ================================
echo ADB Tool Packaging Script
echo ================================

echo Cleaning old build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Generating SPEC configuration file...
python generate_spec.py

echo Executing packaging...
pyinstaller ADBTool.spec

echo.
echo ================================
echo Packaging completed!
echo Executable location: dist\ADBTool.exe
echo ================================

echo Press any key to open dist folder...
pause >nul
explorer dist