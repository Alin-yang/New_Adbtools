@echo off
echo 正在检查Python环境...
python --version
if %errorlevel% neq 0 (
    echo 错误: 找不到Python解释器
    echo 请确保Python已正确安装并添加到PATH环境变量
    pause
    exit /b 1
)

echo 正在运行ADB工具...
python main.py
pause