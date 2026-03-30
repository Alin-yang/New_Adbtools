# 项目清理说明

## 已清理的文件

### 1. 构建临时文件
- `build/` - PyInstaller 构建过程中生成的临时目录，可重新生成

### 2. 日志文件
- `adb_tool_debug.log` - 调试日志文件，运行时会自动重新生成
- `dist/adb_tool_debug.log` - 打包输出目录中的日志文件

### 3. 重复的打包脚本
- `package_optimized.bat` - 优化的打包脚本（功能与 package.bat 重复）

## 保留的重要文件

### 1. 源代码文件
- `main.py` - 程序入口
- `app.py` - 主应用逻辑
- `config.py` - 配置管理
- `utils.py` - 工具函数
- `decorators.py` - 装饰器
- `cache_manager.py` - 缓存管理

### 2. GUI 模块
- `gui/layout_tab_view.py` - Tab 视图布局
- `gui/__init__.py` - 模块初始化

### 3. 功能模块
- `modules/device_manager.py` - 设备管理
- `modules/app_manager.py` - 应用管理
- `modules/system_manager.py` - 系统管理
- `modules/__init__.py` - 模块初始化

### 4. 打包配置
- `ADBTool.spec` - PyInstaller 配置文件
- `generate_spec.py` - SPEC 文件生成脚本
- `package.bat` - Windows 批处理打包脚本
- `package.ps1` - PowerShell 打包脚本

### 5. 运行脚本
- `run_tool.bat` - 快速运行脚本

### 6. 数据文件
- `ip_history.txt` - IP 历史记录（用户数据）
- `pkg_history.txt` - 包名历史记录（用户数据）

### 7. 文档
- `README.md` - 项目文档

## 清理规则

所有临时文件、日志文件和构建产物都已添加到 `.gitignore` 文件中，这些文件不应该被提交到版本控制系统。

### 自动清理（.gitignore 忽略）
- `*.log` - 所有日志文件
- `build/` - 构建目录
- `dist/` - 打包输出目录（仅包含临时构建产物）
- `__pycache__/` - Python 字节码缓存
- `*.pyc` - Python 编译文件
- `ip_history.txt` - IP 历史记录
- `pkg_history.txt` - 包名历史记录

## 清理命令

如果需要手动清理项目，可以运行以下命令：

```powershell
# PowerShell
Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
Remove-Item -Force "adb_tool_debug.log" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "__pycache__" -ErrorAction SilentlyContinue
```

或者使用批处理：

```batch
# 清理构建文件
rmdir /s /q build
del adb_tool_debug.log
```

## 打包输出

`dist/` 目录中的 `ADBTool.exe` 是最终的可执行文件，应该保留。其他临时文件应该被清理。

## 最后更新

2026-03-30
