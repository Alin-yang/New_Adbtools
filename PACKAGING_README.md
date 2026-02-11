# 📦 ADB工具打包说明

## 🚀 一键打包方法

### 方法一：PowerShell脚本（推荐）
```powershell
# 双击运行 package.ps1
# 或在PowerShell中执行：
.\package.ps1
```

### 方法二：命令行手动打包
```bash
# 1. 清理旧文件
rmdir /s /q build dist

# 2. 生成配置文件
python generate_spec.py

# 3. 执行打包
pyinstaller ADBTool.spec
```

## 📋 打包产物

**输出文件**: `dist\ADBTool.exe`
**文件大小**: 12.75 MB
**生成时间**: 2026年2月11日 10:10:40

## ⚠️ 注意事项

1. **编码问题**: 如果遇到中文乱码，请使用 `package.ps1` 而不是 `.bat` 文件
2. **权限要求**: 首次运行可能需要管理员权限
3. **运行环境**: 目标机器需要安装对应的VC++运行库
4. **ADB依赖**: 使用时需要确保系统中有ADB环境

## 🎯 使用说明

打包后的exe文件为绿色软件，可直接运行，无需安装Python环境。

## 🔧 故障排除

如果打包失败，请检查：
- Python环境是否正常
- PyInstaller是否正确安装
- 项目文件是否完整
- 是否有足够的磁盘空间