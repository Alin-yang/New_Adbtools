# ADB Tool 综合文档

## 一、项目概述

### 1.1 项目简介
ADB Tool 是一款基于 Python + Tkinter 开发的 Android 设备管理工具，提供图形化界面进行 ADB 设备连接、应用管理、日志调试、屏幕操作、scrcpy 投屏、性能监控等功能。界面采用现代化卡片式布局（参考 WOA AutoBot 风格），支持多设备管理与后台实时设备监控。

### 1.2 技术栈
- **开发语言**: Python 3.x
- **GUI 框架**: Tkinter (ttk) + tkinterdnd2（拖拽支持）
- **ADB 工具**: Android Debug Bridge
- **投屏工具**: scrcpy（已内置到 `tools/scrcpy/`）
- **打包工具**: PyInstaller
- **依赖**: psutil（进程/资源信息）、concurrent.futures（线程池）

### 1.3 项目结构
```
New_Adbtools/
├── main.py                      # 程序入口（加载 layout_modern 布局）
├── app.py                       # 主应用逻辑（ADBToolApp 类）
├── config.py                    # 配置管理（路径/缓存/性能/投屏配置）
├── utils.py                     # 工具函数（ADB 命令封装/设备检测/历史记录）
├── decorators.py                # 装饰器（require_device_connected 等）
├── cache_manager.py             # 缓存管理（TTL 缓存）
├── adaptive_cache.py            # 自适应 LRU 缓存（智能 TTL 调整）
├── device_monitor.py            # 设备状态实时后台监控
├── gui/
│   ├── __init__.py
│   └── layout_modern.py         # 现代化 UI 布局（当前使用）
├── modules/
│   ├── __init__.py
│   ├── app_manager.py           # 应用管理（安装/卸载/列表）
│   ├── device_manager.py        # 设备管理
│   ├── system_manager.py        # 系统管理
│   ├── screen_mirror.py         # 投屏管理（scrcpy 封装）
│   └── performance_monitor.py   # 性能监控（CPU/内存/FPS/温度）
├── tools/
│   └── scrcpy/                  # scrcpy 工具集（scrcpy.exe/adb.exe/各类 DLL）
├── ADBTool.spec                 # PyInstaller 打包配置
├── package.bat / package.ps1    # 打包脚本
├── run_tool.bat                 # 运行脚本
└── .gitignore
```

## 二、核心功能模块

应用顶部共 **7 个 Tab**，对应 7 大功能域：

### 2.1 设备管理模块（📱 设备管理）
**功能卡片**:
- **ADB 服务管理**: 连接 ADB / 断开所有连接 / 重启 ADB 服务
- **设备信息**: 查看设备 / 详细信息 / 获取串号
- **设备控制**: 重启设备 / 获取 Root 权限 / 重新挂载分区
- **系统工具**: 打开 CMD / 常用命令 / 获取 Android 版本号
- **文本输入**: 向设备发送文本输入（支持数字/中文/逐字符/输入法等多种发送策略）

**实现逻辑**:
```python
# 多设备支持：构建带 -s 参数的命令
def build_adb_command_with_device(base_cmd, target_ip):
    # USB 设备（序列号）与网络设备（IP:端口）统一处理
    if ":" not in target_ip:
        return f"adb -s {target_ip} {base_cmd[4:]}"
    return f"adb -s {target_ip} {base_cmd[4:]}"

# 装饰器确保操作前已选择并连接设备
@require_device_connected
def force_install(self): ...
```

### 2.2 应用管理模块（📦 应用管理）
**功能卡片**:
- **应用操作**: 强制安装 APK（带进度显示）/ 卸载应用 / 清除应用缓存
- **启动与进程**: 启动应用 / 终止进程 / 查看资源占用
- **应用信息**: 获取版本号 / 安装路径 / 当前打开应用包名
- **应用列表**: 获取已安装应用包名列表（异步获取版本）

**实现逻辑**:
```python
# 带进度的安装（后台线程 + 实时输出捕获）
def _run_install_with_progress(self, apk_path):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, ...)
    while True:
        output = process.stdout.readline()
        # 解析 "Performing Streamed Install" 计算进度百分比
        self.app.root.after(0, self._update_install_status, message)
```

### 2.3 日志录屏模块（📋 日志录屏）
**功能卡片**:
- **日志捕获**: 开始捕获 / 停止捕获 / 清除日志缓存
- **ANR 与命令**: 导出 ANR 文件 / 查看功能按键原始命令
- **屏幕操作**: 开始录制 / 停止录制 / 截屏
- **文件管理**: 打开存储文件夹

**实现逻辑**: 日志捕获/录屏均在后台线程持续运行，通过 `root.after()` 线程安全地更新 UI。

### 2.4 投屏模块（🖥️ 投屏）
基于 **scrcpy** 实现的设备屏幕镜像与交互，已内置 scrcpy 工具集，无需额外下载。
**功能**:
- 启动/停止投屏（后台进程管理，自动清理）
- 按键模拟：方向键（上下左右）/ 确认
- 系统按键：返回 / 主页 / 菜单
- 系统控制：音量+ / 音量- / 静音 / 电源 / 锁屏

**实现逻辑**:
```python
class ScreenMirrorManager:
    def _build_scrcpy_command(self, scrcpy_path, device_ip):
        cmd = [scrcpy_path,
               "--video-bit-rate", Config.SCRCPY_BITRATE,  # 8M
               "--max-size", Config.SCRCPY_MAX_SIZE,       # 1920
               "--max-fps", Config.SCRCPY_MAX_FPS,         # 30
               "--stay-awake", "--show-touches"]
        if device_ip:
            cmd.extend(["-s", device_ip])
        return cmd
```

### 2.5 性能监控模块（📊 性能监控）
实时监控 Android 设备的 CPU、内存、FPS、温度等性能指标。
**功能**:
- 选择监控应用（支持下拉搜索/获取当前应用）
- 设置采样间隔
- 开始/停止监控
- 单次快照
- 生成性能报告
- 实时数据展示（CPU/内存/FPS/温度）

**实现逻辑**:
```python
class PerformanceMonitor:
    # 采样线程循环采集，通过 adb 读取 /proc/stat、dumpsys 等数据
    # 回调函数更新 UI 的实时数据卡片
```

### 2.6 脚本运行模块（🔧 脚本运行）
**功能**:
- **Shell 脚本管理**: 浏览脚本 / 推送脚本 / 启动脚本 / 停止脚本 / 清空 tmp
  - 智能脚本推送：自动检测设备上是否存在脚本（通过文件大小比对），避免重复推送
- **Monkey 日志导出**: 导出设备上的 Monkey 测试日志

### 2.7 高级工具模块（⚙️ 高级工具）
- **工厂菜单**: 打开设备工厂菜单

## 三、界面布局设计

### 3.1 左右分栏布局结构
```
┌──────────────────────────────────────────────────────┐
│  ADB Tool  v2.0 · 现代化UI      📱当前设备 ● 未连接  │  ← 顶部栏
├──────────────────────────────────────────────────────┤
│ 📱设备管理 │ 📦应用管理 │ 📋日志录屏 │ 🖥️投屏 │ ...  │  ← Tab 导航
├──────────────────────┬───────────────────────────────┤
│  左侧功能按钮区域      │  右侧实时终端输出             │
│  (卡片式按钮组)       │  (弹性扩展，自动滚动)         │
│  ┌──────────────┐    │  [12:00:00] ✓ 已连接 2 台设备 │
│  │ 卡片标题       │    │  ...                         │
│  │ [按钮][按钮]   │    │                               │
│  └──────────────┘    │                               │
└──────────────────────┴───────────────────────────────┘
```

### 3.2 布局实现（layout_modern.py）
```python
class LayoutModern:
    COLORS = {
        "primary": "#0078D4",   # 主色调（Windows蓝）
        "success": "#107C10",
        "warning": "#FFB900",
        "error": "#E81123",
        "bg_main": "#F3F2F1",
        "bg_card": "#FFFFFF",
        ...
    }
    # 左右分栏：左列 weight=1（功能按钮），右列 weight=3（输出框）
    # Tab 选中：高亮背景 #E6F2FF + 蓝色文字
```

## 四、核心技术实现

### 4.1 设备检测与同步
启动时并行检测已连接设备（USB + 网络），合并历史记录，去重后更新下拉框。

### 4.2 装饰器模式
```python
def require_device_connected(func):
    """设备连接校验装饰器：强制刷新设备状态 → 检查连接 → 执行"""
    def wrapper(self):
        cache_manager.device_cache.clear()
        self.show_current_device_status(force_display=True)
        if not self.ensure_device_connected():
            return
        return func(self)
    return wrapper
```

### 4.3 缓存管理
- **cache_manager**: TTL 缓存（device_cache TTL=3s、package_cache TTL=180s）
- **AdaptiveLRUCache** (`adaptive_cache.py`): 自适应 LRU 缓存，根据访问频率动态调整 TTL，高频访问的缓存项自动延长有效期

### 4.4 异步操作与 UI 刷新
- 耗时操作在后台线程执行，UI 更新通过 `root.after()` 回到主线程
- 线程池 `ThreadPoolExecutor`（max_workers=10）并发执行功能操作
- 长时间运行任务（日志/录屏）使用独立线程，不占用线程池

### 4.5 多设备支持
IP 下拉框统一显示 USB 序列号和网络 IP，`build_adb_command_with_device()` 为命令自动添加 `-s` 参数。

### 4.6 设备实时监控
`DeviceMonitor` 后台线程定时检测设备连接状态，状态变化时触发回调更新 UI。

### 4.7 拖拽支持
通过 `tkinterdnd2` 支持 APK/脚本文件拖拽到输入框，自动提取包名与版本信息。

## 五、配置说明（config.py）

### 5.1 路径配置
```python
DEFAULT_LOG_PATH = "D:\\adbtool_log\\logs"        # 日志
DEFAULT_ANR_PATH = "D:\\adbtool_log\\anr_files"  # ANR 文件
DEFAULT_SCREENSHOT_PATH = "D:\\adbtool_log\\screenshots"  # 截图
DEFAULT_RECORD_PATH = "D:\\adbtool_log\\records"          # 录屏
# D 盘不存在时自动回退到当前工作目录
```

### 5.2 性能与缓存配置
```python
CACHE_TIMEOUT = 180           # 缓存超时（秒）
DEVICE_CACHE_TIMEOUT = 3     # 设备状态缓存（秒）
MAX_CACHE_SIZE = 50
DEVICE_MONITOR_INTERVAL = 3   # 设备监控间隔（秒）
```

### 5.3 投屏配置
```python
SCRCPY_PATH = "tools\\scrcpy\\scrcpy.exe"
SCRCPY_BITRATE = "8M"        # 码率
SCRCPY_MAX_SIZE = "1920"     # 最大尺寸
SCRCPY_MAX_FPS = "30"       # 最大帧率
```

### 5.4 界面配置
```python
WINDOW_GEOMETRY = "1078x464"   # 窗口大小
MIN_WINDOW_SIZE = (1026, 422)  # 最小尺寸
```

## 六、打包发布

### 6.1 打包配置（ADBTool.spec）
- 入口：`main.py`
- 包含数据：`gui/`、`modules/`、`config.py`、`decorators.py`、`utils.py`、`cache_manager.py`、`device_monitor.py`、`adaptive_cache.py`
- 自动收集 `tools/scrcpy/` 下所有文件
- 包含 tkinterdnd2 各平台二进制（linux/osx/win × x64/x86/arm64）
- 输出：单文件无控制台窗口的 `ADBTool.exe`

### 6.2 打包步骤
```powershell
# Windows PowerShell
.\package.ps1
# 或手动执行
pyinstaller --onefile --windowed ADBTool.spec
```

### 6.3 打包产物
```
dist/
└── ADBTool.exe    # 独立可执行文件
```

## 七、常见问题

### 7.1 设备不显示
启动时检测到的设备与 IP 下拉框不同步 → 已通过合并设备检测结果和文件历史、去重后显示解决。

### 7.2 安装无反应
进度条布局冲突 → 将 `grid()` 改为 `pack()` 解决。

### 7.3 投屏无法启动
确认 `tools/scrcpy/scrcpy.exe` 存在；打包后路径会自动从 `_MEIPASS` 解析。

## 八、开发规范

### 8.1 代码结构
- 主逻辑：`app.py`（ADBToolApp 类）
- GUI 布局：`gui/layout_modern.py`
- 功能模块：`modules/` 目录
- 配置集中：`config.py`

### 8.2 命名规范
- 变量：驼峰式（如 `ip_combobox`）
- 函数：下划线式（如 `force_install`）
- 类：大驼峰（如 `LayoutModern`）

### 8.3 Git 分支
- 默认分支：`test_about`
- 开发分支：`new_view`（界面重构 + 新功能）
- 提交信息：使用中文，描述清晰

## 九、版本历史

### v3.0（当前版本）
- 🆕 **scrcpy 投屏功能**：集成 scrcpy 工具集，支持屏幕镜像与按键模拟
- 🆕 **性能监控模块**：实时监控 CPU/内存/FPS/温度，支持快照与报告
- 🆕 **自适应 LRU 缓存**：根据访问频率智能调整 TTL
- 🆕 **设备实时监控**：后台线程定时检测设备连接状态
- ✅ **现代化 UI 布局**（layout_modern.py）：卡片式设计、左右分栏、彩色状态标签
- ✅ **多设备支持**：USB 序列号与网络 IP 统一管理
- ✅ **拖拽支持**：APK/脚本文件拖拽自动解析
- ✅ **轮转日志**：10MB 滚动、保留 5 个备份
- ✅ **线程池并发**：max_workers=10，长时间任务独立线程

### v2.3
- 🆕 智能脚本推送：自动检测设备脚本、文件大小比对、避免重复推送

### v2.0
- ✅ 三栏布局重构（左侧 Tab + 中间功能 + 右侧输出）
- ✅ Tab 选中效果增强（深蓝背景 +5px 边框）
- ✅ 修复设备检测同步问题

### v1.0
- 基础功能实现

## 十、联系方式

项目位置：`D:\N_ADBtools\New_Adbtools-test_about\New_Adbtools`
GitHub：https://github.com/Alin-yang/New_Adbtools

---

**最后更新**: 2026-08-29
**文档版本**: v3.0
