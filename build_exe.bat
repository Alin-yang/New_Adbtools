@echo off
chcp 65001 > nul
echo 🚀 ADB工具打包脚本
echo ====================
echo.

:: 清理之前的构建文件
echo 🧹 清理构建缓存...
if exist "build" rmdir /s /q "build"
if exist "dist\ADBTool.exe" del /q "dist\ADBTool.exe"
if exist "ADBTool.spec" del /q "ADBTool.spec"

:: 开始打包
echo 📦 开始打包ADB工具...
echo.

pyinstaller ^
--onefile ^
--noconsole ^
--name ADBTool ^
--hidden-import=decorators ^
--hidden-import=gui.layout_base ^
--hidden-import=gui.layout_zh ^
--hidden-import=utils ^
--hidden-import=config ^
--hidden-import=cache_manager ^
--hidden-import=modules.app_manager ^
--hidden-import=modules.device_manager ^
--hidden-import=modules.system_manager ^
--hidden-import=tkinterdnd2 ^
--add-data "gui;gui" ^
--add-data "modules;modules" ^
main.py

:: 检查打包结果
echo.
if exist "dist\ADBTool.exe" (
    echo ✅ 打包成功！
    echo 📁 可执行文件位置: dist\ADBTool.exe
    
    :: 显示文件大小
    for %%A in (dist\ADBTool.exe) do (
        set /a size=%%~zA/1024/1024
        echo 📊 文件大小: !size! MB
    )
    
    :: 询问是否打开文件夹
    echo.
    set /p opendir="是否打开dist文件夹？(y/n): "
    if /i "!opendir!"=="y" (
        explorer dist
    )
) else (
    echo ❌ 打包失败！请检查错误信息。
)

echo.
echo 🔧 打包参数说明:
echo   --onefile: 打包成单个exe文件
echo   --noconsole: 不显示控制台窗口
echo   --name: 指定输出文件名
echo   --hidden-import: 包含隐藏导入的模块
echo   --add-data: 添加数据文件到包中
echo.

pause