# scrcpy 投屏工具安装说明

## 📥 下载步骤

1. **访问 GitHub 发布页面**
   - 地址: https://github.com/Genymobile/scrcpy/releases

2. **下载 Windows 版本**
   - 找到最新的 release（例如 v2.4）
   - 下载 `scrcpy-win64-v2.4.zip` (64位系统)
   - 或 `scrcpy-win32-v2.4.zip` (32位系统)

3. **解压文件**
   - 将压缩包解压到项目的 `tools/scrcpy/` 目录
   - 确保以下文件存在：
     ```
     tools/
     └── scrcpy/
         ├── scrcpy.exe          ← 主要可执行文件
         ├── scrcpy-server       ← 服务器组件
         ├── adb.exe             ← ADB 工具（可选）
         └── ...其他文件
     ```

## ✅ 验证安装

运行 ADB Tool，点击"🖥️ 投屏" Tab，然后点击"启动投屏"按钮。

如果看到投屏窗口打开，说明安装成功！

## 🔧 常见问题

### Q1: 提示"未找到 scrcpy.exe"
**解决方法**: 
- 确认已将 scrcpy 解压到 `tools/scrcpy/` 目录
- 检查文件名是否为 `scrcpy.exe`（不是 `scrcpy.exe.exe`）

### Q2: 投屏窗口无法打开
**解决方法**:
- 确保设备已通过 USB 或 WiFi 连接
- 在"设备管理" Tab 中先测试设备连接
- 检查设备是否开启了 USB 调试

### Q3: 投屏延迟较高
**解决方法**:
- 降低分辨率：修改 `config.py` 中的 `SCRCPY_MAX_SIZE`（例如改为 "1280"）
- 降低帧率：修改 `SCRCPY_MAX_FPS`（例如改为 "20"）
- 降低码率：修改 `SCRCPY_BITRATE`（例如改为 "4M"）

### Q4: 鼠标操作不灵敏
**解决方法**:
- scrcpy 默认支持完整的鼠标交互
- 确保设备屏幕已解锁
- 尝试重启 scrcpy 进程

## ⚙️ 高级配置

可以在 `config.py` 中修改以下参数：

```python
SCRCPY_BITRATE = "8M"      # 码率（越高画质越好，但带宽占用越大）
SCRCPY_MAX_SIZE = "1920"   # 最大尺寸（保持原始比例缩放）
SCRCPY_MAX_FPS = "30"      # 最大帧率（30-60 之间）
```

## 🎯 功能特性

- ✅ 实时屏幕镜像（低延迟 <100ms）
- ✅ 鼠标点击、滑动、长按
- ✅ 键盘输入转发
- ✅ 文件拖拽传输
- ✅ 多设备同时投屏
- ✅ 保持设备唤醒
- ✅ 显示触摸点位置

## 📚 更多资源

- 官方文档: https://github.com/Genymobile/scrcpy
- 使用教程: https://github.com/Genymobile/scrcpy/blob/master/doc/windows.md
- 快捷键列表: https://github.com/Genymobile/scrcpy#shortcuts

---

**提示**: 首次使用时，scrcpy 会在设备上安装一个小的服务程序（scrcpy-server），这是正常的，无需担心安全问题。
