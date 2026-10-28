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
│   ├── device_query.py          # 设备查询统一入口（6 个查询函数的实现都在这）
│   ├── screen_mirror.py         # 投屏管理（scrcpy 封装）
│   └── performance_monitor.py   # 性能监控（CPU/内存/FPS/卡顿率）
├── tools/
│   ├── scrcpy/                  # scrcpy 工具集（scrcpy.exe/adb.exe/各类 DLL）
│   ├── lint.py                  # 零依赖代码质量检查（死代码/危险模式）
│   ├── lint_baseline.txt        # 存量问题基线（只报新增）
│   └── diagnose_perf.py         # 性能监控真机诊断（采集原始输出对账）
├── tests/
│   ├── test_core_regression.py          # 核心路径回归
│   ├── test_device_query_and_monitor.py # 设备查询与监控去抖
│   ├── test_install_flow.py             # 安装流程（含定制 ROM 场景）
│   ├── test_async_and_fixes.py          # 线程安全
│   ├── test_perf_improvements.py        # 性能
│   ├── test_perf_parsers.py             # 性能监控解析器（各 Android 版本格式）
│   ├── measure_layout.py                # 各 Tab 布局宽度量化
│   ├── screenshot_tabs.py               # 自动截图各 Tab
│   ├── probe_device_tab.py              # 容器树宽度溯源
│   ├── profile_startup.py               # 启动耗时分解
│   └── verify_install_real_device.py    # 真机验证安装判定（需 adb）
├── ADBTool.spec                 # PyInstaller 打包配置（onefile）
├── ADBTool_onedir.spec          # PyInstaller 打包配置（onedir，启动更快）
├── package.bat / package.ps1    # 打包脚本（onedir）
├── package_onefile.bat          # 打包脚本（单文件 exe）
├── check.bat                    # 一键检查（lint + 全部单元测试）
├── run_tool.bat                 # 运行脚本
└── .gitignore
```

> ⚠️ `.bat` 文件必须是 **GBK 编码** —— cmd.exe 按 ANSI 解码 UTF-8 会把命令行拆散，
> 导致脚本直接坏掉（emoji 也编不进 GBK）。改完记得转码。

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
# 安装主路径：adb push（真实百分比进度）+ pm install，失败回退 adb install
def _install_via_push_pm(self, apk_path, apk_size, target_ip):
    process = subprocess.Popen(push_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, ...)
    while True:
        output = process.stdout.readline()
        # 解析 "[ 45%] /data/local/tmp/x.apk: 45% (43.28MB/96.20MB)" 计算真实进度
        self._update_install_status(f"正在传输... {percent}%（{size_text}）")
```

要点：
- **主路径用 `adb push` + `pm install`**：push 的百分比写在 stderr（实时到达），能显示真实进度；
  `adb install` 不吐进度，是回退路径。
- **push 后先探测可读性**：部分设备禁止 shell 读取 `/data/local/tmp`
  （push 显示成功但 `pm install` 打不开文件），不可读就直接走 `adb install`，
  省掉一次白跑的完整传输。
- **成功判定不只看退出码**：定制 ROM 上 `adb install` 可能在成功后仍返回 1，
  详见 [4.9 安装结果的判定](#49-安装结果的判定)。
- 传输与设备端安装（解包 + dexopt）分两个阶段提示，后者可能耗时 30~90 秒。
- 安装期间**暂停设备可达性验证**，避免 `adb shell` 打扰正在传输的设备。
- 全程 15 分钟超时保护，失败自动重试；UI 更新统一走 `_run_in_ui()` 队列。

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
- **投屏参数可调**：码率 / 帧率 / 分辨率三个下拉框（投屏卡顿或模糊时可自救，
  不用改代码重新打包）
- 按键模拟：方向键（上下左右）/ 确认
- 系统按键：返回 / 主页 / 菜单
- 系统控制：音量+ / 音量- / 静音 / 电源 / 锁屏

**实现逻辑**:
```python
class ScreenMirrorManager:
    def _build_scrcpy_command(self, scrcpy_path, device_ip, options=None):
        opts = options or {}
        cmd = [
            scrcpy_path,
            "--video-bit-rate", opts.get("bitrate") or Config.SCRCPY_BITRATE,
            "--max-size",      opts.get("max_size") or Config.SCRCPY_MAX_SIZE,
            "--max-fps",       opts.get("max_fps") or Config.SCRCPY_MAX_FPS,
            "--stay-awake", "--show-touches",
        ]
        if device_ip:
            # ⚠️ 必须补齐端口：scrcpy 要求 -s 与 `adb devices` 完全一致
            #    （网络设备是 "192.168.0.26:5555"），只给 IP 会选不中设备
            serial = normalize_device_serial(device_ip)
            if serial:
                cmd.extend(["-s", serial])
        return cmd
```
> 分辨率选「原始分辨率」= 不传 `--max-size`（不缩放）。

### 2.5 性能监控模块（📊 性能监控）
实时监控 Android 设备的进程级 + 线程级 CPU、内存（PSS/RSS/Java/Native）、FPS、Jank 等性能指标。v3.1 全面重写采集引擎。
**功能**:
- 选择监控应用（支持下拉搜索/获取当前应用）；未填包名时进入**系统整体模式**
- 设置采样间隔（默认 2s）
- 开始/停止监控（停止时自动落盘一份 CSV，避免忘记导出丢失数据）
- 单次快照
- 导出 CSV 原始采样点 / 导出文本性能报告（落到 `<数据存储路径>/perf_reports/`）
- 实时数据展示：CPU / PSS / RSS / Java Heap / Native Heap / FPS / Jank%，每项含**当前/均值/P95/P05/峰值**
  （CPU/内存看 P95，FPS 看 P05）
- **线程级 CPU 表**：展示 Top N 线程瞬时 CPU%，表头可点击排序
- **采样明细表**：保留最近 60 条（时间/CPU%/PSS/RSS/Java/Native/FPS/卡顿%），最新在上并高亮
- **告警机制**：进程 CPU% 或 PSS 连续 N 次（可配置）超阈值时触发告警回调，避免毛刺误报

> ⚠️ 不采集设备温度（明确不做的功能）。

**实现逻辑**:
```python
class PerformanceMonitor:
    # 一次采样同时产出进程级 + 线程级数据：
    # adb shell cat /proc/<pid>/stat /proc/<pid>/task/*/stat 单次调用读回
    # 进程与全部线程的 CPU jiffies，两次采样差分得到真实瞬时 CPU%（与采样间隔无关）
    # 内存：一次 dumpsys meminfo 同时解析 PSS / RSS / Java Heap / Native Heap
    # FPS：gfxinfo 累计帧数两次差分（与采样间隔无关）
    # 卡顿率：同一次 gfxinfo 解析 "Janky frames: N (x%)"，零额外开销
    # 智能降级：/proc 不可读自动回退 dumpsys cpuinfo（仅进程级）
    # 系统整体模式：/proc/stat + /proc/meminfo 差分
    # CLK_TCK 与 CPU 最大值自动探测，兼容多核设备
```
> **采集解析只做「匹配失败就降级、不算错值」** —— 宁可显示空，也不给错数字。
> 真机格式对账用 `tools/diagnose_perf.py`（见 5.3）。

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
    """设备连接校验装饰器：查缓存 → 校验当前设备 → 执行"""
    def wrapper(self, *args, **kwargs):
        devices = get_connected_devices_cached()   # 带缓存，不重复 spawn adb
        if not devices:
            self.root.after(0, lambda: self.update_status(
                "⚠️ 设备未连接，请先连接设备后再执行此操作", False, "warning"))
            return None
        current_ip = self.get_ip_address()
        if current_ip and current_ip != "192.168.":
            # 校验下拉框里选中的那台确实在线
            if not any(d == current_ip or d.startswith(current_ip + ':')
                       for d in devices):
                self.root.after(0, lambda: self.update_status(
                    f"⚠️ 设备 {current_ip} 未连接，请检查连接状态", False, "warning"))
                return None
        return func(self, *args, **kwargs)
    return wrapper
```
> 覆盖 26 处设备相关操作。**注意语义**：查不到设备 ≠ 没有设备，
> 详见 [4.8 设备查询的三种状态](#48-设备查询的三种状态)。

### 4.3 缓存管理
- **cache_manager**: TTL 缓存（device_cache TTL=3s、package_cache TTL=180s）
- **AdaptiveLRUCache** (`adaptive_cache.py`): 自适应 LRU 缓存，根据访问频率动态调整 TTL，高频访问的缓存项自动延长有效期
- **设备列表缓存**（`DeviceQuery`）: 2 秒 TTL，查询失败时回退上一次成功的结果

### 4.4 异步操作与 UI 刷新

**后台执行**：`app.run_in_background(task)` —— 所有耗时操作统一走这里，
不再有游离的 `threading.Thread`。

**UI 线程安全**：后台线程**不允许**直接碰 Tk 控件，也不允许直接调
`root.after()`（主线程正忙、不进事件循环时会抛
`main thread is not in main loop`）。机制是「队列 + 主线程定时泵」：

```
后台线程  →  只往 queue.Queue 塞 callable
主线程    →  20ms 定时器取出批量执行（app._run_in_ui）
```

`update_status()` / `_update_operation_status()` 自带线程判断，
非主线程调用自动转投队列 —— 一处防护覆盖全部调用点。

> 之前散落着 100+ 处后台线程直调 `update_status()`、60+ 处后台线程
> 直调 `root.after()`，现已全部收口。

### 4.5 多设备支持
IP 下拉框统一显示 USB 序列号和网络 IP，`build_adb_command_with_device()` 为命令自动添加 `-s` 参数。

### 4.6 设备实时监控
`DeviceMonitor` 后台线程定时检测设备连接状态，状态变化时触发回调更新 UI。

### 4.7 拖拽支持
通过 `tkinterdnd2` 支持 APK/脚本文件拖拽到输入框，自动提取包名与版本信息。

### 4.8 设备查询的三种状态
设备查询函数统一收敛到 `modules/device_query.py::DeviceQuery`，
但**三个语义必须分清**，混淆会导致「误报设备已断开」：

| 函数 | 查询失败 | 真的没设备 | 用途 |
|---|---|---|---|
| `query_connected_devices()` | 返回 `None` | 返回 `[]` | 纯查询 |
| `get_connected_devices_cached_safe()` | 返回 `None` | 返回 `[]` | **设备监控用** |
| `get_connected_devices_cached()` | 回退上次结果 | 返回 `[]` | 装饰器等宽松场景 |

> `None` = 「查不到」，调用方应**跳过本轮**而不是判定为断连。
> 设备监控另有去抖：连续 3 次空快照才判定断连。

### 4.9 安装结果的判定
**adb 的退出码在定制 ROM 上不可信。** 某些设备（如装了 `com.tcl.guard`
的 TCL 电视盒子）会让 `adb install` 在**实际安装成功后**仍以退出码 1 结束
（`Get install_switch_flag: 1`），而设备端明明打印了 `Success`。

因此判定成功有三条依据，任一成立即算成功：
1. adb 退出码为 0；
2. 设备端输出里出现独立的 `Success` 行；
3. 安装后用 `dumpsys package` 查设备上的 `versionCode`，
   若 ≥ APK 的 versionCode → 确认已安装（`utils.verify_install_result`）。

安装路径也有两条：`adb push` + `pm install`（有真实进度）优先，
失败回退 `adb install`。**push 后会先探测设备端文件可读性** ——
部分设备禁止 shell 读取 `/data/local/tmp`，不可读就直接走 `adb install`，
不浪费一次完整传输。

## 五、开发与质量工具

### 5.1 一键检查
```bat
check.bat
```
依次跑：代码质量检查 → 6 套单元测试 → 编译检查。任一步失败返回非 0。

### 5.2 代码质量门禁（零依赖）
```bat
D://tool//python//python.exe tools\lint.py          # 报告
D://tool//python//python.exe tools\lint.py --strict  # 有新增问题就返回非 0
```
检查项：死代码（含传递死代码）、未使用 import、shell 管道过滤、裸 `except`、
后台线程里的 `root.after`、超大文件。

存量问题记在 `tools/lint_baseline.txt`，**只报新增的** —— 这样门禁立刻可用，
又能防止继续劣化。清理完某条后把基线里对应行删掉即可。

> 不用 ruff/flake8：团队里每个人的 Python 路径都不一样，引入外部工具反而跑不起来。

### 5.3 性能监控真机诊断
```bat
D://tool//python//python.exe tools\diagnose_perf.py com.你的包名
```
采集各条命令的**原始输出**并打印每个解析器的结果，拿回来对账用
（确认 PSS / 卡顿率 / CPU% 在你的机型上是否解析正确）。

---

## 六、配置说明（config.py）

### 6.1 路径配置
```python
DEFAULT_LOG_PATH = "D:\\adbtool_log\\logs"        # 日志
DEFAULT_ANR_PATH = "D:\\adbtool_log\\anr_files"  # ANR 文件
DEFAULT_SCREENSHOT_PATH = "D:\\adbtool_log\\screenshots"  # 截图
DEFAULT_RECORD_PATH = "D:\\adbtool_log\\records"          # 录屏
# D 盘不存在时自动回退到当前工作目录
```

### 6.2 性能与缓存配置
```python
CACHE_TIMEOUT = 180           # 缓存超时（秒）
DEVICE_CACHE_TIMEOUT = 3     # 设备状态缓存（秒）
MAX_CACHE_SIZE = 50
DEVICE_MONITOR_INTERVAL = 3   # 设备监控间隔（秒）

# 性能监控告警配置（连续超阈值若干次才告警，避免毛刺误报）
PERF_ALERT_CPU_PERCENT = 80   # 进程 CPU% 告警线（多核设备可比 100% 高）
PERF_ALERT_MEM_MB = 800       # PSS 内存(MB) 告警线
PERF_ALERT_STREAK = 3         # 连续多少次采样超阈值才触发告警
```

### 6.3 投屏配置
```python
SCRCPY_PATH = "tools\\scrcpy\\scrcpy.exe"
SCRCPY_BITRATE = "8M"        # 默认码率
SCRCPY_MAX_SIZE = "1920"     # 最大尺寸
SCRCPY_MAX_FPS = "30"       # 最大帧率

# 下拉框的可选值（用户在投屏 Tab 里切换）
SCRCPY_BITRATE_OPTIONS = ["2M", "4M", "8M", "16M", "24M"]
SCRCPY_MAX_SIZE_OPTIONS  = ["720", "1080", "1440", "1920", "0"]  # 0 = 保持原始分辨率
SCRCPY_MAX_FPS_OPTIONS   = ["15", "24", "30", "60"]
```

### 6.4 界面配置
```python
WINDOW_GEOMETRY = "1280x620"   # 窗口大小（唯一来源，布局里不再硬编码覆盖）
MIN_WINDOW_SIZE = (1026, 520)  # 最小尺寸
```

### 6.5 安装与命令配置
```python
INSTALL_TIMEOUT  = 900   # 单次安装最长耗时（秒），15 分钟
INSTALL_RETRIES  = 2     # 安装失败后的重试次数
INSTALL_REMOTE_TMP = "/data/local/tmp/_adbtool_install.apk"
INSTALL_HEARTBEAT = 10   # 安装过程无输出时的心跳提示间隔（秒）

ADB_COMMAND_TIMEOUT = 15  # 单条 adb 命令超时
DEVICE_QUERY_TIMEOUT = 5 # 设备查询超时
```

## 七、打包发布

### 7.1 两种打包方式
| 脚本 | spec | 产物 | 特点 |
|---|---|---|---|
| `package.bat` / `package.ps1` | `ADBTool_onedir.spec` | `dist\ADBTool\` 文件夹 | **启动更快**（不需每次解压），分发要整个文件夹 |
| `package_onefile.bat` | `ADBTool.spec` | `dist\ADBTool.exe` 单文件 | 分发方便，启动时要把内嵌 archive 解压到 `%TEMP%` |

> 实测（1920×1080 机器）：onedir 首帧约 2.2s，onefile 约 3.6s。
> onefile 首次运行还会被杀软全量扫描，达到 16s。

### 7.2 打包配置要点
- 入口：`main.py`
- 包含数据：`gui/`、`modules/`、`config.py`、`decorators.py`、`utils.py`、
  `cache_manager.py`、`device_monitor.py`、`adaptive_cache.py`
- 自动收集 `tools/scrcpy/` 下所有文件
- 包含 tkinterdnd2 各平台二进制（linux/osx/win × x64/x86/arm64）
- 输出：无控制台窗口的 exe

### 7.3 打包步骤
```bat
:: Windows 批处理
package.bat              :: onedir（推荐）
package_onefile.bat      :: 单文件 exe

:: 或手动
D://tool//python//python.exe -m PyInstaller ADBTool_onedir.spec --noconfirm --clean
```

> ⚠️ 必须用 `D://tool//python//python.exe` 打包 —— PATH 里的 python 没有
> tkinter 也没有 psutil。

## 八、常见问题

### 8.1 设备不显示
- 确认设备上已勾选「USB 调试」，且授权弹窗点了允许
- 网络设备要在**设备端**用 `adb connect <IP>:5555` 连上（工具的「🔌连接ADB」按钮同此）
- `adb devices` 里显示 `unauthorized` → 设备上还没确认授权，重插数据线或撤销授权后重试
- 工具的设备监控有 3 次去抖：偶发的一次空快照不会误报断连

### 8.2 安装无反应
先看终端有没有 `Performing Streamed Install`。若有但一直卡着，
多半是 38MB+ 的大包在 WiFi 上传输（`adb push` 有真实百分比进度）。
传输完成后设备端还要解包 + dexopt，可能再花 30~90 秒（此时进度条停在 96%）。

### 8.3 安装显示失败，但设备上其实装上了
部分定制 ROM 会让 `adb install` 在成功后仍返回退出码 1，
终端里会看到 `Get install_switch_flag: 1` + `Success` 这样的矛盾输出。

**判断方法**（工具已内置，装完会自动核对）：
```bat
adb -s <设备IP>:5555 shell dumpsys package <包名> | findstr versionCode
```
若设备上的 `versionCode` 已经是你要装的版本 → **安装成功**，只是退出码不可信。
若还是旧版本 → 确实没装上，常见原因是设备禁止 ADB 安装
（需在设备上打开「USB 安装 / 安装未知应用」）。

### 8.4 投屏无法启动
确认 `tools/scrcpy/scrcpy.exe` 存在；打包后路径会自动从 `_MEIPASS` 解析。
设备选择有要求：scrcpy 的 `-s` 必须与 `adb devices` 里完全一致
（网络设备要带 `:5555`），工具会自动补齐。

### 8.5 文本输入不支持中文
`adb shell input text` 只走 ASCII，不经过输入法 —— 中文**必须**靠设备上
安装的 ADBKeyBoard 之类第三方输入法（走广播通道）：
```bat
adb shell am broadcast -a ADB_INPUT_TEXT --es msg "你好"
```

## 九、开发规范

### 9.1 代码结构
- 主逻辑：`app.py`（ADBToolApp 类）
- GUI 布局：`gui/layout_modern.py`
- 功能模块：`modules/` 目录
- 配置集中：`config.py`

### 9.2 命名规范
- 变量：驼峰式（如 `ip_combobox`）
- 函数：下划线式（如 `force_install`）
- 类：大驼峰（如 `LayoutModern`）

### 9.3 线程安全约定（重要）
- 后台线程**不得**直接操作 Tk 控件，也**不得**直接调 `root.after()`
  （主线程正忙时会抛 `main thread is not in main loop`）
- UI 更新统一走 `app._run_in_ui(func)`；状态栏可用 `app._update_status_safe(msg, ok)`
- 读输入框等 Tk 操作必须在**主线程**里做完，再把值传给后台任务
- 新增后台任务用 `app.run_in_background(task)`，不要自己 `threading.Thread`

### 9.4 命令行约定（重要）
- **命令里禁止 shell 管道过滤**（`| grep` / `| findstr`）：管道由**本机 cmd** 解析，
  过滤发生在你电脑上而不是设备上；用户环境 PATH 里通常没有 grep → 整条命令失败
- 一律用 `utils.filter_lines(text, *keywords)` 在 Python 侧过滤
- 同样禁止 `2>/dev/null`（本机 cmd 会解析成重定向到不存在的路径）
- 命令统一走 `utils.run_adb_command()` / `build_adb_command_with_device()`，
  自动补 `-s <设备>` 与 `:5555` 端口，别自己拼

### 9.5 Git 分支
- 默认分支：`test_about`
- 开发分支：`new_view`（界面重构 + 新功能）
- 提交信息：使用中文，描述清晰
- **提交前跑 `check.bat`**（lint + 7 套单元测试），任一步失败不提交
- ⚠️ `.bat` 文件必须是 **GBK 编码** —— cmd.exe 按 ANSI 解码 UTF-8 会把命令行拆散，
  emoji 也编不进 GBK

## 十、版本历史

### v3.2（当前版本）
- 🐛 **修复安装成功被误报为失败**：某些定制 ROM（TCL 的 `com.tcl.guard` 等）会让
  `adb install` 在实际安装成功后仍以退出码 1 结束（`Get install_switch_flag: 1`），
  设备端却打印了 `Success`。现在有三重判定：退出码 / 设备端 `Success` 行 /
  安装后用 `dumpsys package` 比对 versionCode
- 🐛 **push 路径加可读性预检**：部分设备禁止 shell 读取 `/data/local/tmp`，
  push 显示成功但 `pm install` 打不开文件。不可读时直接回退 `adb install`，
  省掉一次白跑的完整传输
- 🐛 **修掉 8 处 `| grep` / 9 处 `| findstr`**：管道由**本机 cmd** 解析，
  用户环境 PATH 里通常没有 grep → 整条命令失败。改用 `utils.filter_lines()` 在 Python 侧过滤
- 🐛 **修掉投屏必然选不中设备**：scrcpy 要求 `-s` 与 `adb devices` 完全一致
  （网络设备要带 `:5555`），与 ADB 命令路径行为不一致
- ⚡ **启动速度 13.8s → 2.2~3.5s**：7 个 Tab 改为懒加载（同一时刻只显示一个），
  窗口先出、内容后填（`update_idletasks` + `after(50, ...)`，不能用 `update()`）
- ⚡ **应用列表加载 90s → 0.5s**：原来每个包查版本要跑 3 条 adb（其中 `adb devices`
  每个包都重跑一遍）。改为一条 `dumpsys package packages` 拿全部 versionName
- ⚡ **设备详情 3~4s → 0.2s**：19 条串行 `getprop` 改为一条 `adb shell getprop` 全量解析
- 🛡️ **消除 100+ 处跨线程 UI 调用**：后台线程直调 `update_status()` / `root.after()`
  会在主线程忙时抛 `main thread is not in main loop`。改为「队列 + 主线程 20ms 定时泵」
- 🛡️ **15 个功能点从 UI 冻结改为异步**：原本同步跑 adb（最坏 31 秒无响应）
- 🧹 **清理 1021 行死代码**（含 293 行建立在错误前提上的「中文输入」实现 ——
  `adb shell input text` 根本不经过输入法）
- 🧹 **6 个设备查询函数收敛为 1 个实现**（`modules/device_query.py::DeviceQuery`）
- 📐 **消除设备管理 Tab 的空白**：双列卡片布局 + 修掉「空列吃一半宽度」的 grid 坑；
  左面板/右终端从 906/344 调整为 782/468
- 🧪 **新增 7 套单元测试 + 零依赖 lint 门禁**（`tools/lint.py`，含基线机制）
- ⚙️ **投屏参数可调**：码率/帧率/分辨率三个下拉框，不再写死 8M/1920/30

### v3.1
- 🆕 **性能监控引擎重写**：一次采样同时产出进程级 + 线程级 CPU（/proc/<pid>/task/*/stat 差分），内存一次 dumpsys 同时解析 PSS/Java/Native，FPS 用 gfxinfo 累计帧数差分
- 🆕 **线程级 CPU 表**：Top N 线程瞬时 CPU%，表头可点击排序
- 🆕 **系统整体模式**：未填包名时用 /proc/stat + /proc/meminfo 差分监控整机
- 🆕 **智能降级**：/proc 不可读自动回退 dumpsys cpuinfo；CLK_TCK 与 CPU 最大值自动探测
- 🆕 **告警机制**：进程 CPU%/PSS 连续 N 次超阈值才告警，避免毛刺误报（阈值可配置）
- 🆕 **采样点回看**：保留最近 600 条采样记录，支持 CSV 导出与文本报告
- 🆕 **停止自动落盘**：停止监控时自动保存一份 CSV，避免忘记导出丢失数据
- ✅ **拖拽识别版本号脱离设备依赖**：直接从 APK 内 AndroidManifest.xml（二进制 AXML）解析 versionName/versionCode，不再依赖 adb pm dump
- ✅ **Tab 切换优化**：switch_tab 改用 tkraise 替代 grid_remove+grid，避免布局重算卡顿
- ✅ **IP 自动连接**：下拉选择有效 IP 时自动发起连接，无需手动点"立即连接"

### v3.0
- 🆕 **scrcpy 投屏功能**：集成 scrcpy 工具集，支持屏幕镜像与按键模拟
- 🆕 **性能监控模块**：实时监控 CPU/内存/FPS（v3.1 起不再采集温度），支持快照与报告
- 🆕 **自适应 LRU 缓存**：根据访问频率智能调整 TTL
- 🆕 **设备实时监控**：后台线程定时检测设备连接状态
- ✅ **现代化 UI 布局**（layout_modern.py）：卡片式设计、左右分栏、彩色状态标签
- ✅ **多设备支持**：USB 序列号与网络 IP 统一管理
- ✅ **拖拽支持**：APK/脚本文件拖拽自动解析
- ✅ **轮转日志**：10MB 滚动、保留 5 个备份
- ✅ **线程池并发**：长时间任务独立线程（v3.2 起统一改用 `app.run_in_background()`）

### v2.3
- 🆕 智能脚本推送：自动检测设备脚本、文件大小比对、避免重复推送

### v2.0
- ✅ 三栏布局重构（左侧 Tab + 中间功能 + 右侧输出）
- ✅ Tab 选中效果增强（深蓝背景 +5px 边框）
- ✅ 修复设备检测同步问题

### v1.0
- 基础功能实现

## 十一、联系方式

项目位置：`D:\Projects\New_Adbtools`
GitHub：https://github.com/Alin-yang/New_Adbtools
分支：`test_about`（默认）、`master`、`new_view`

---

**最后更新**: 2026-10-28
**文档版本**: v3.2
