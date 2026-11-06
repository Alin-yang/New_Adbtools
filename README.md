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
│   ├── layout_v4.py             # v4 工作台布局（当前使用）
│   ├── theme.py                 # 主题系统（深/浅双套 + 运行时切换）
│   ├── win_render.py            # Windows 渲染优化（DPI 感知 + ClearType）
│   ├── device_picker.py         # 设备切换浮层（在线/离线分组 + 型号懒加载）
│   └── layout_modern.py         # v3 布局（回退用：ADBTOOL_LAYOUT=v3）
├── modules/
│   ├── __init__.py
│   ├── device_query.py          # 设备查询统一入口（6 个查询函数的实现都在这）
│   ├── screen_mirror.py         # 投屏管理（scrcpy 封装）
│   ├── perf_locator.py          # 性能：PID 定位（多级回退 + 校验）
│   ├── perf_parsers.py          # 性能：纯函数解析器（/proc/gfxinfo/framestats）
│   ├── perf_collector.py        # 性能：采集器（时间戳对齐，不碰 UI）
│   ├── perf_analysis.py         # 性能：自动结论 / 泄漏检测 / 线程角色归类
│   ├── perf_chart.py            # 性能：纯 Canvas 图表（零依赖）
│   ├── perf_report.py           # 性能：报告窗口 + HTML 导出
│   ├── perf_baseline.py         # 性能：基线存储与对比
│   └── perf_scenario.py         # 性能：场景模板（阈值）
├── tools/
│   ├── scrcpy/                  # scrcpy 工具集（scrcpy.exe/adb.exe/各类 DLL）
│   ├── lint.py                  # 零依赖代码质量检查（死代码/危险模式）
│   ├── lint_baseline.txt        # 存量问题基线（只报新增）
│   ├── diagnose_perf.py         # 性能监控真机诊断（采集原始输出对账，v5 新 API）
│   └── update_check_bat.py      # 更新 check.bat（保持 GBK + CRLF）
├── tests/
│   ├── test_core_regression.py          # 核心路径回归
│   ├── test_device_query_and_monitor.py # 设备查询与监控去抖
│   ├── test_device_switch.py            # 设备切换（徽标三态/自动跟随/切换浮层）
│   ├── test_install_flow.py             # 安装流程（含定制 ROM 场景）
│   ├── test_install_rom_compat.py       # 精简 ROM / 慢设备安装兼容（busybox/超时/心跳）
│   ├── test_async_and_fixes.py          # 线程安全
│   ├── test_perf_improvements.py        # 性能
│   ├── test_perf_v4.py                  # 性能 v5（口径分离/卡顿率/泄漏检测…）
│   ├── test_perf_live_refresh.py        # 性能实时刷新链路（后台线程→UI 队列泵）
│   ├── test_layout_v4.py                # v4 布局（主题/导航/终端/契约）
│   ├── test_log_search.py               # 终端搜索/过滤功能测试
│   ├── measure_layout.py                # 各 Tab 布局宽度量化
│   ├── screenshot_tabs.py               # 自动截图各 Tab（v3）
│   ├── screenshot_v4.py                 # v4 自动截图（深/浅 × 面板 + 报告 + 监控中）
│   ├── probe_device_tab.py              # 容器树宽度溯源
│   ├── profile_startup.py               # 启动耗时分解
│   ├── measure_tabs_vertical.py         # 各 Tab 纵向空白量化
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

界面左侧导航共 **6 个任务面板**，按「日常操作 / 进阶工具」两组组织：

> v3 曾是顶部 7 个 Tab（按技术分类），v4 改为按任务流分组，见第三章。

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

#### 顶部设备区（全局可用，不必切 Tab）
- **连接 / 断开**：连设备是最高频动作，放在顶栏随时可点
- **刷新设备**：真正重新扫描设备并更新下拉框（保持当前选中项不变）
- 设备下拉框显示完整 IP（历史上被截断成「192.168.」）

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

#### 终端输出区（全局右侧）
- **关键字搜索**：输入即高亮全部命中，回车定位，▼▲ 逐个跳转，显示命中计数
- **只看错误**：一键隐藏非错误行（✗ / Error / Exception / failed / 失败…）
- **⚙ 菜单**：只看错误开关 / 导出终端输出到文件 / 复制全部

> 以前 logcat 抓几千行后只能肉眼翻（`tk.Text` 连 Ctrl+F 都没有）。

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
实时监控 Android 设备的进程级 + 线程级 CPU、内存（PSS/RSS/Java/Native）、FPS、Jank 等性能指标。
**v5.0 完全重写采集引擎，v5.1 修复实时刷新失效。**

**功能**:
- 选择监控应用（支持下拉搜索/获取当前应用）；未填包名时进入**系统整体模式**
- 设置采样间隔（默认 2s）；**场景选择器**（视频播放 / 界面流畅 / 内存体检 / 省电 / 启动 / 通用），
  不同场景「什么算超标」不一样，阈值不再写死
- 开始/停止监控（停止时自动落盘 CSV **并弹出测试报告**）
- 单次快照
- 导出 CSV 原始采样点 / 导出文本性能报告 / **导出 HTML 报告**（自包含内联 SVG，可直接发给同事）
- 实时数据展示：CPU / PSS / RSS / Java Heap / Native Heap / FPS / Jank%，每项含**当前/均值/P95/P05/峰值**
  （CPU/内存看 P95，FPS 看 P05）
- **线程级 CPU 表**：展示 Top N 线程瞬时 CPU%，表头可点击排序
- **采样明细表**：保留最近 60 条（时间/CPU%/PSS/RSS/Java/Native/FPS/卡顿%），最新在上并高亮
- **告警机制**：进程 CPU% 或 PSS 连续 N 次超阈值时触发（阈值由场景决定）
- **基线对比**：每次测试自动存快照，可与任意一次历史并排比较

> ⚠️ 不采集设备温度（明确不做的功能）。

#### 测试报告（停止监控后弹出）
| 标签页 | 内容 |
|---|---|
| **顶部结论卡片** | CPU / 内存 / 帧率 + 与基线的对比 + 自动结论（如「内存疑似泄漏」） |
| **趋势曲线** | 多指标叠加，可叠加上次基线虚线 |
| **线程占用** | **按角色聚合**（渲染/音视频解码/GC/IPC/线程池/业务 SDK…），也可切回按线程 |
| **帧时间分布** | 直方图 + 16.7ms(60fps) / 33.3ms(30fps) 预算线 |
| **原始数据** | 逐次采样明细表 |

其它能力：**内存泄漏自动检测**（PSS 线性回归算斜率，拟合度不够就不判）、
**采样质量透明化**（报告显示实际间隔、有效率、是否降级、各项采集耗时）。

#### 实现逻辑（v5.0 重写，8 个模块）
```
modules/perf_locator.py    PID 定位（pidof → ps → dumpsys 多级回退 + 合理性校验）
modules/perf_parsers.py   纯函数解析器（/proc / gfxinfo / framestats / meminfo）
modules/perf_collector.py  采集器（时间戳对齐、并行采集、不碰 UI）
modules/perf_analysis.py   分析（自动结论 / 泄漏检测 / 线程角色归类）
modules/perf_chart.py      纯 Canvas 图表（零依赖，128 点曲线 0.7ms）
modules/perf_report.py     报告窗口 + HTML 导出
modules/perf_baseline.py   基线存储与对比
modules/perf_scenario.py   场景模板（阈值）
```

**重写前修掉的三个致命 bug**（均在真机 192.168.0.3 验证）：

| Bug | 现象 | 根因 |
|---|---|---|
| **测错了进程** | CPU 恒为 0，线程表全是内核线程 | 该设备 `pidof <包名>` **忽略参数**，返回全部 155 个 PID → 取到 PID=1（init） |
| **进程 CPU 少算 94%** | 进程 CPU 与线程表对不上 | `/proc/pid/stat`（线程组**总量** 12626）与 `task/pid/stat`（**单线程** 776）tid 相同被覆盖 |
| **CPU 低估 38~56%** | 数值总是偏小 | 差分窗口把 `dumpsys` 的 1.5~3 秒阻塞算了进去 |

**关键口径约定**：
- **CPU 是单核百分比**（8 核可到 800%），与系统设置「占总 CPU」口径不同
- **无渲染活动时 FPS 记 `None`**（显示 `--`），不用 0 冒充真实测得值
- **卡顿率是窗口内的真实值**：用「总数差分 + janky 百分比反推」，
  而不是进程启动至今的累计百分比（那个数值几乎不变，毫无意义）
- **history 存原始值**（可为 None），不复制旧值（会造出伪造的平坦段）
- **CLK_TCK 恒用 100**（Android 内核 USER_HZ 常量），不用 `/proc/stat`
  自增速率推算（adb 传输延迟不可对齐，实测能推出 115~135，反而算错）
- **慢采集移出关键路径**：`dumpsys meminfo` / `framestats` 各用独立后台线程，
  否则会把采样周期从 2s 拖到 3.5s，并污染 CPU 差分窗口

> 采集解析只做「匹配失败就降级、不算错值」—— 宁可显示空，也不给错数字。

### 2.6 脚本运行模块（🔧 脚本运行）
**功能**:
- **Shell 脚本管理**: 浏览脚本 / 推送脚本 / 启动脚本 / 停止脚本 / 清空 tmp
  - 智能脚本推送：自动检测设备上是否存在脚本（通过文件大小比对），避免重复推送
- **Monkey 日志导出**: 导出设备上的 Monkey 测试日志

### 2.7 高级工具模块（⚙️ 高级工具）
- **工厂菜单**: 打开设备工厂菜单

## 三、界面布局设计（v4 工作台）

### 3.1 整体结构

v4 把 v3 的「顶部 Tab + 左右分栏」重构成「**左侧固定导航 + 顶栏全局上下文 + 可折叠终端**」：

```
┌──────────┬──────────────────────────────────────┬──────────────┐
│  侧边栏   │  顶栏：设备 ▾ │ 包名 ▾ │ 状态 │ 终端▸   │  终端         │
│  188px   ├──────────────────────────────────────┤  340px      │
│          │                                      │  可折叠       │
│ 日常操作  │  工作区（当前任务面板，可滚动）         │  ┌─────────┐ │
│  安装    │                                      │  │ 实时输出 │ │
│  诊断    │  安装应用                             │  │         │ │
│  设备    │  选择 APK，推送到目标设备              │  └─────────┘ │
│ 进阶工具  │                                      │  [搜索][复制] │
│  性能    │  [安装到设备] [卸载] [清除缓存]         │              │
│  投屏    │                                      │              │
│  脚本    │                                      │              │
│──────────┤                                      │              │
│ ☾ 深色模式│                                      │              │
└──────────┴──────────────────────────────────────┴──────────────┘
```

**为什么这样改**

| v3 的问题 | v4 的做法 |
|-----------|-----------|
| Tab 按**技术分类**（设备/应用/日志…），用户要先想功能属于哪个 Tab | 按**任务流**分组：日常操作（安装/诊断/设备）+ 进阶工具（性能/投屏/脚本） |
| 右侧终端**永久占位** 360px，长路径日志被迫换行 | 终端**可折叠**（Ctrl+B / 顶栏按钮），折叠后工作区横向铺满 |
| 卡片套卡片（LabelFrame 套 LabelFrame），层级弱 | 扁平化：分组标题 + 一行按钮，无卡片边框 |
| 顶栏 70px + Tab 条 40px = 110px 垂直开销 | 顶栏统一 46px，导航移到左侧，垂直省下 ~64px |
| 配色写死在布局里，`vista` 主题下大部分不生效 | **主题系统**统一管理，深/浅两套可运行时切换 |

### 3.2 主题系统（gui/theme.py）

**根因**：Tkinter 在 Windows 上默认用 `vista` 主题，会**忽略** `background`/`foreground` 配置 —— 这正是旧版 UI「配色怎么改都不生效、整体显得很 low」的真正原因。

v4 的做法：

```python
# 1) 切到 clam 主题（完全可配置）
style.theme_use('clam')

# 2) 颜色令牌集中管理，深浅两套
DARK  = {'bg_app': '#0E1116', 'bg_side': '#131720', 'accent': '#4C8DFF', ...}
LIGHT = {'bg_app': '#F4F5F7', 'bg_side': '#FFFFFF', 'accent': '#2563EB', ...}

# 3) ttk 样式按令牌批量重建（换肤时重跑一次即可全局生效）
theme._build_styles(theme.tokens)

# 4) 纯 tk 控件（Text/Label/Listbox）用「角色注册表」逐个重刷
theme.register(widget, 'terminal')   # 终端：底色 + tag 颜色
theme.register(widget, 'label')      # 文字标签：前景/背景
theme.register(widget, 'badge')      # 连接徽标：按设备状态上色
```

主题选择持久化在 `~/.adbtool_prefs.json`，下次启动自动恢复。

### 3.3 布局实现（gui/layout_v4.py）

```python
class LayoutV4:
    # 导航结构：按任务流分组
    NAV_GROUPS = [
        ('日常操作', [('install', '安装应用', ...), ('diagnose', '问题诊断', ...),
                      ('device', '设备控制', ...)]),
        ('进阶工具', [('perf', '性能监控', ...), ('mirror', '投屏控制', ...),
                      ('script', '脚本执行', ...)]),
    ]

    # 面板懒加载：首次点开才构建（避免启动时建 6 套控件）
    PANEL_BUILDERS = {'install': 'build_install_panel', ...}

    def switch_nav(self, key):
        if key not in self.panels:      # 懒加载
            self.panels[key] = getattr(self, self.PANEL_BUILDERS[key])()
        self.panels[key].tkraise()      # tkraise 比 grid_remove 重建快得多
```

**关键实现细节（都是踩过的坑）**

- 网格行列**不能重叠**：顶栏在 `row=0`，工作区在 `row=1` —— 放同一格会被工作区盖住，设备/包名下拉框直接消失。
- 顶栏元素总需求宽度必须 ≤ 主区宽度，否则后面的控件被挤没（表现为「控件凭空消失」）。
  当前 **649px ≤ 712px**（余 63px）。新增控件时要从别处**等量**省出宽度，
  否则包名框会被挤到断言线（170px）以下 —— v5.4 加「设备 ▾」按钮时踩过这个坑。
- **`ttk.Combobox` 的 `delete(0, END)` / `insert(0, x)` 只改输入框里的文本，不改下拉列表**
  （values 要靠 `combo['values']` 单独设）—— 实测确认，别拿它当"设置下拉列表"用。
- 导航高亮条用 **place** 定位：pack/grid 的 width 切换在已布局容器里不生效，旧选中项的高亮条永远收不回去。
- 面板内容放进 **Canvas + 滚动条**：小窗口下内容不会被顶出窗口（v3 的投屏页就是这么被裁掉的）。
- 纯 tk 控件必须走 `theme.register()`：面板是懒加载的，换肤时不重刷就会残留上一套主题的配色。

### 3.4 兼容与回退

- v3 布局（`gui/layout_modern.py`）保留为回退路径：设环境变量 `ADBTOOL_LAYOUT=v3` 即可切回。
- app.py 与布局解耦：它只认 `app.ip_combobox` / `app.status_text` / `app.perf_samples_tree` 等控件契约，
  两套布局都满足（见 `tests/test_layout_v4.py` 的「app 契约保留」断言组）。

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
`root.after()`（Tk 的 `after()` 只能在主线程调用；主线程正忙、不进
事件循环时会抛 `main thread is not in main loop`）。机制是
「**队列 + 主线程常驻泵**」：

```
后台线程  →  只往 queue.Queue 塞 callable，绝不碰 after
主线程    →  常驻泵每 50ms 醒一次，批量取出执行
             （app._start_ui_pump / app._run_in_ui）
```

`update_status()` / `_update_operation_status()` 自带线程判断，
非主线程调用自动转投队列 —— 一处防护覆盖全部调用点。

> 之前散落着 100+ 处后台线程直调 `update_status()`、60+ 处后台线程
> 直调 `root.after()`，现已全部收口。

#### ⚠️ v5.1 修复的架构缺陷（血泪教训）

旧设计是「**谁投递谁 `after(20, pump)` 一次**」。这个设计有个致命前提：
**调用必须发生在主线程**。一旦某功能的 `_run_in_ui` 全部来自后台线程
（如性能采集），就会：

```
后台线程调 root.after → 抛 "main thread is not in main loop"
                      → 异常被 except 吞掉
                      → 队列永远不被消费
                      → 后台在采集，界面一动不动，且没有任何报错
```

表现就是「点了开始监控，指标卡全是 `--`，停止后报告里却有数据」。
其它功能没暴露，是因为它们的 `_run_in_ui` 大多在主线程触发。

**两条铁律**：

1. **常驻泵必须在主线程启动**（`_setup_gui` 里调 `_start_ui_pump()`），
   后台线程只管往队列塞东西。
2. **`_run_in_ui(func)` 只接受一个 callable 参数**。要带参数就用 lambda
   绑定：`app._run_in_ui(lambda snap=snapshot: cb(snap))`。
   传两个参数会 TypeError，若被 `except` 吞掉同样是静默失效。

> **凡是 catch 之后既不重试也不降级的，至少要 `logging.warning`**，
> 并且必须有一条断言测试覆盖「回调真的被执行了」。
> 静默吞掉的异常 = 永久的 bug。


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
D://tool//python//python.exe tools\diagnose_perf.py com.你的包名 192.168.0.3:5555
```
采集各条命令的**原始输出**并打印每个解析器的结果，拿回来对账用
（确认 PSS / 卡顿率 / CPU% 在你的机型上是否解析正确）。

输出会直接告诉你几件关键的事：
- `ProcessLocator` 定位到哪个 PID，以及**该设备的 `pidof` 是否可信**
- **进程级 jiffies vs 线程表求和**的差值（差值应等于主线程自己的量）
- 10 秒窗口的**实测 CPU%**
- `nproc` / `getconf` 是否存在（不存在会自动回退）
- `framestats` 是否可用（不可用会降级到累计帧数差分）

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
- **提交前跑 `check.bat`**（lint + 10 步检查，含 8 套单元测试 + 编译），任一步失败不提交
- ⚠️ `.bat` 文件必须是 **GBK 编码** —— cmd.exe 按 ANSI 解码 UTF-8 会把命令行拆散，
  emoji 也编不进 GBK

## 十、版本历史

### v5.4.8（当前版本）—— 日志错误聚类 + 一键诊断包 + 导出跟随过滤

针对 TV 测试的真实工作流（刷机 → 装 APK → 操作 → 出问题 → **抓日志发同事**），
补上「加工」这一环 —— 之前只有「采集」完整，日志拿到手还得自己看。

#### ① 「只看错误」的导出/复制跟随过滤（修缺陷）

`layout_v4.py` 的「只看错误」用 `tag_configure(elide=True)` 隐藏非错误行，
但 **elide 只影响显示**。而导出/复制取的是 `status_text.get("1.0", tk.END)`
—— **拿到的是全部文本**。用户勾了「只看错误」再导出，导出的还是全量。

修法：抽出共用方法 `_error_markers()` + `_visible_log_text()`，
显示过滤与导出过滤**共用同一份判定逻辑**，杜绝两处不一致。

顺带发现**错误关键字表漏了关键格式**（实测 logcat 样本）：
`FATAL EXCEPTION`（全大写，原表只有首字母大写的 `Exception`）、
`Fatal signal`、`ANR`、`has died` 全部漏判 —— 而这些恰恰是最关键的错误行。
已扩充关键字表并加「覆盖度」测试（真实 logcat 行 + 反向的正常行）。

#### ② 错误聚类与异常栈提取（新增 `modules/log_analyzer.py`）

**解决的痛点**：一个 `NullPointerException` 刷 500 次，仍是 500 行 —— 你还是得自己数。

能力：
- 解析 logcat（`级别/标签( PID): 内容` 格式）→ 结构化行
- 提取 5 类事件：`fatal`（FATAL EXCEPTION 崩溃链）/ `java`（Java 异常）/
  `native`（signal 崩溃）/ `anr`（卡死）/ `died`（进程死亡）
- **归一化聚类**：去掉行号、地址、时间戳、对象 hash →
  行号不同的两次 NPE 聚成同一类，统计频次，Top N 排序
- 保留完整栈帧 + `Caused by` 链
- 一句话摘要（纯中文）

UI：诊断页新增「智能分析」分区 → 「错误分析」按钮 → 弹窗展示
（摘要 + 按频次排序的列表 + 完整栈帧），可导出报告文本。

⚠️ 关键实现点：`FATAL EXCEPTION: main` 里的 "FATAL EXCEPTION" **不是 Java 类名**
（没有包前缀、也不以 Exception/Error 结尾），异常正则匹配不到 → 要单独识别，
否则整条崩溃链（异常类型 + 栈帧 + Caused by）都识别不出来。

#### ③ 一键诊断包（新增）

以前要一个一个导（导出 ANR、导出 Monkey…），发给同事得手动凑一堆文件。
现在一次打包成 zip：设备属性 / 系统日志(logcat) / dumpsys 三件套(meminfo、cpuinfo、
window) / 已安装包列表 / ANR 追踪。

⚠️ **每项收集失败不影响其它项** —— 设备可能没 root（拉不到 ANR）、
某个 dumpsys 不支持……**部分失败也要能出包**，并在包内 README 里说明缺了什么。

⚠️ 踩到的坑：`run_adb_command` 的参数名是 **`target_device`**（不是 `target`）；
`get_ip_address()` 读 Tk 控件，**必须在主线程取**，后台线程读控件会抛
"main thread is not in main loop"。

#### 新增防回归测试（check.bat 14 → 17 步）
- `tests/test_log_export_filter.py` —— 导出/复制跟随过滤 + 关键字覆盖度
- `tests/test_log_analyzer.py` —— 聚类算法（含「行号不同聚成同类」核心断言）
- `tests/test_diagnostic_package.py` —— 打包逻辑（mock adb）

### v5.4.7 —— 整机 CPU 公式修正 + 性能面板加基线入口

#### ① 整机 CPU 占用恒为 100%（真机验证发现的严重 bug）

这是项目记忆里挂了很久的待办「性能监控新引擎未在真机完整跑过」。
真机（192.168.0.50，2 核康佳电视）完整验证时发现：
**system（整机）模式的 CPU 占用恒定显示 100.00%**（当前/均值/峰值全是 100）。

**根因**：`/proc/stat` 的「cpu」行是**所有核的累加值**，且**含 idle**。
旧公式「Δtotal / CLK_TCK × 100」再 `min(..., 100)` →
多核设备上结果必然 ≥100% → 被截成恒定 100%。

**走过的弯路**：先试「Δtotal / 核数 / CLK_TCK」——**也是错的**。
Δtotal 里已经含 idle（idle 本身就隐含了「核数 × 窗口」），
再除以核数等于**重复除一次**。实测同一时刻旧公式 491.5%。

**正确公式：`1 - Δidle / Δtotal`**（用设备自带 `top` 交叉验证过）
| 口径 | 结果 |
|---|---|
| 旧（÷核数，截断后） | 100.0% ❌ |
| 新（1-idle/total） | **45.2%** ✅ 与 top 的 User 19% + System 25% 吻合 |

配套：`parse_proc_stat_cpu_fields()`（解析分项 jiffies）、
`parse_proc_stat_cores()`（从**同一份** /proc/stat 数 cpuN 行拿核数 ——
`nproc`/`cat /proc/cpuinfo` 在精简 Android 上经常不存在，零额外 adb 往返）。

#### ② 性能面板加基线入口

基线功能（`modules/perf_baseline.py`：存/选/对比/曲线叠加）**早就写好了**，
但入口只在报告窗口里 —— 用起来要「停止 → 报告窗口 → 点『与基线对比』」三步。
现在性能面板上直接能选基线、存基线，**报告一打开就自带对比结果**。

⚠️ 踩到的坑：`list_baselines()` 返回的是**存储包装**
（package/label/saved_at/session/_path/_file），
而 `compare()` 期望 **session 本体**（含 stats 键）—— 少取一层，对比结果全空。

#### 新增防回归测试（check.bat 12 → 14 步）
- `tests/test_perf_cpu_formula.py`（14 条）—— 用**真机录制的真实 /proc/stat**
- `tests/test_perf_baseline_entry.py`（30 条）—— 基线存取/对比/入口存在性

### v5.4.6 —— 性能监控提速 + 开始时清空选项 + 品牌区去图标

用户反馈三件事：① 性能监控缺少「清除上一次测试数据」的按钮，
可以选择清除还是不清除；② 点「开始监控」后要等好几秒才有数据，感觉慢；
③ ADB Tool v5.4.5 的图标不需要，只需要把字靠左或居中。

#### ① 「开始时清空」选项

「清空数据」按钮本来就有，但用户要的是**开始监控时**能选择是否清空上一轮数据。
新增复选框「开始时清空」（默认勾选 = 每次都是干净的一轮）：

- `app.perf_clear_on_start_var`（BooleanVar）+ `app._perf_should_clear_on_start()`
- `start_performance_monitor()` 里按勾选状态决定是否先 `clear_performance_data()`
- ⚠️ ttk.Checkbutton **不支持 font 参数**（报 `unknown option "-font"`），
  字体要在 style 里配
- ⚠️ 新样式名必须 `style.layout(name, style.layout('App.TCheckbutton'))`
  **clone layout**，否则报 `Layout App.TCheckbuttonFlat not found`
- 复选框底色要跟着所在面板走 → 新增 `App.TCheckbuttonFlat`（bg_app）

#### ② 启动提速：8.7 秒 → 2.8 秒

先量化，别凭感觉：

| 阶段 | 耗时 | 是否必需 |
|---|---|---|
| `adb shell nproc`（核数） | **2.2s** | ❌ 只作 CPU% 上限 |
| `adb shell getconf CLK_TCK` | 0.7s | ❌ Android USER_HZ 恒为 100 |
| `_estimate_clk_tck`（2×/proc/stat + 1s sleep） | **2.9s** | ❌ 纯诊断值，没人读 |
| 首轮等一个完整 interval | 2.0s | ❌ 首帧可以短窗口 |
| **合计** | **8.7s** | |

三处改动：
1. **彻底删掉启动期 adb 探测**（`_detect_clk_tck` / `_detect_cpu_max` /
   `_estimate_clk_tck` / `_detect_cpu_max_cached`）
   - CLK_TCK：Android 内核 USER_HZ **恒为 100**，直接用标准值
   - 核数：只作 CPU% 上限（核数×100），而 CPU% 天然不会超物理上限 →
     **宽松值等价**；多核满载显示 400% 本来就该是 400%（截到 100% 反而是低估）
2. **首帧用 0.6s 采样窗口**（`FIRST_SAMPLE_WINDOW`）而不是完整 interval
   —— CPU% 是「增量/窗口」的比值，窗口短只是噪声略大，但数据立刻可见
3. **状态标签加「● 启动中…」中间态** —— 数据要 2.8 秒才来，
   之前立刻显示「采集中」但指标卡是空的 → 用户以为卡死。
   现在**首帧到达时**才切「采集中」

⚠️ **试过「把探测挪到后台」，反而更慢（首帧 5.8 秒）**：
**adb 命令是串行的**，后台的 nproc/getconf 会和前台的 /proc/stat 采集
**抢同一条 adb 连接**，把首帧一起拖慢。这条路走不通，只能彻底不做。

#### ③ 品牌区去 logo

- 移除蓝色 logo 色块（+内部白点），改成**纯文字靠左**
- 左边缘 padx=**33**：与下方导航项的**文字**左边缘对齐
  （导航项图标占 10+16+7=33px）→ 「ADB Tool」和「安装应用」在同一条竖线上

### v5.4.5 —— 侧边栏品牌区左对齐 + 导航图标改为矢量绘制

用户反馈「ADB tool v5.4.4 为什么不左对齐或者居中显示呢，为什么要靠右显示，
很明显左边还有很多空间，tab 的表情符号感觉不清晰也不好看」。

**问题 1：品牌区「靠右」其实是 logo 隐形了**
- 根因：logo 色块被 `theme.register(logo, 'side')` 登记成侧边栏角色，
  换肤时 bg 被刷成**侧边栏底色** → 蓝色方块变成一个看不见的白块。
  视觉上就是「标题孤零零靠右」（其实左侧本该有个 logo）。
- 修法：新增主题角色 `'accent'`（主色块），logo 改用它。
- 附带：`brand_text` 原来 `fill=tk.BOTH, expand=True` 让文字区撑满侧边栏，
  Label 再 `fill=tk.X` 铺满 → 文字被推到右边。
  改成按内容自然宽度（`width=86`）+ `anchor=tk.W`，紧贴 logo 左对齐。

**问题 2：导航图标是 Unicode 符号，糊成一团**
- 原来用 `⇩ ⚕ ⌘ ◔ ▣ ⌘`：
  - 这些字符在「微软雅黑 UI」里**字形缺失/严重变形** → 渲染成模糊小方块
  - `⌘` 被「设备控制」和「脚本执行」**同时复用**，两个图标一模一样
- Unicode 符号区（U+2xxx / U+25xx）本就是「几何图形」，
  不是给字体渲染用的 —— 依赖它做 UI 图标在任何字体环境下都不可靠
- 修法：新增 `gui/nav_icons.py`，**纯 Canvas 手绘矢量图标**（16×16）
  - 下载箭头 / 放大镜 / 手机 / 折线图 / 屏幕 / 终端提示符，六个语义各异
  - 像素级可控、跨机器渲染一致、颜色能跟主题（悬停变主色、选中加粗变色）
- ⚠️ Canvas 图标**变色必须重绘**（`configure(fg=)` 对 Canvas 无效），
  悬停 / 选中 / 换主题三条路径都要重画

**新增防回归断言**（`tests/test_layout_v4.py`）：
- logo 色块 ≠ 侧边栏底色（不能隐形）、且必须是主色
- 品牌区标题 `winfo_x() == 0`（必须靠左）、宽度 < 侧边栏宽（未撑满）
- 每个图标 Canvas 至少有 2 个绘制 item（不是空白）
- **所有图标形状两两不同**（签名比对，防止再次复用同一个符号）

### v5.4.4 —— 横向空间重新分配

用户反馈「左侧的空间感觉有点多，包括 adb tool v5.4.3 的标题，
可以把多的横向空间给顶部的功能区域和对应 tab 的功能区域」。

**问题量化**（不凭感觉）：
| 元素 | 实测需求 | 实际占用 |
|---|---|---|
| 「ADB Tool」+「v5.4.3」横排 | 78 + 33 + padx ≈ **170px** | — |
| 导航项（图标 14 + 文字 52 + padx） | **≈ 100px** | — |
| 「☀ 浅色模式」+「0 台」横排 | 74 + 23 + padx ≈ **129px** | — |
| **侧边栏总计** | | **188px** |

也就是说：侧边栏 188px 里有 ~90px 被品牌区那一行浪费，
而导航项实际只需要 100px。

**改动**：
- **侧边栏 188 → 140px**，省出的 48px 全给主区（顶栏 + 工作区）
  - 品牌区改成**上下堆叠**（标题 / 版本号各占一行）
  - 底部改成**上下堆叠**（主题按钮 / 设备数各占一行）
- **顶栏**（主区 712 → 760px）：
  - 包名框 `width` 22 → **32 字符**（207 → 259px），
    能显示 28 个字符 —— 「com.example.myapp.debug」(24) 也完整可见
- **工作区**（同样 712 → 760px）：
  - 「系统按键」6 个按钮原来 6×118 + padx = **756px 超宽**，
    最后一个「静音」被压到 69px（半截）→ 显式设 `width=6`
  - 投屏参数下方的提示文字原来挤在同一行（req=314 被裁成半句）
    → 改成**单独占一行**，任何窗口宽度下都完整可读

**⚠️ 关键认知：ttk.Button 的 `width` 单位是「字符」，默认 20**
→ 一个只有两个中文字的按钮也会占 118px（文字 26px + padding 24px + 默认宽度）。
按钮排一行时**必须显式给 width**，否则最后一个必然被裁。

### v5.4.3 —— 浮层加滚动条 + 设备信息持久化

v5.4.2 的功能补齐 + 一个实测暴露的体验缺陷。

**新增：浮层滚动条**（`gui/device_picker.py`）
- 实测 10 台设备时内容 570px / 视口 278px，**只有 51% 可见**，
  底部条目被裁掉一半 —— 用户误以为是渲染 bug，更根本的是
  **完全看不出下面还有设备**，以为就这么多
- 右侧 6px 纯 Canvas 滚动条（滑块可拖、可点轨道跳转、悬停变主色）
- 底部提示文案随内容长度变：
  「点击任意一行即可切换」↔「点击任意一行即可切换 · 右侧滑块可滚动查看更多」
- ⚠️ 滚动条必须**先 pack**（`side=RIGHT`）—— pack 按调用顺序分配空间，
  canvas 在前会把宽度吃光，滚动条只剩 2px（等于没有）

**v5.4.2：设备信息保留**
- 浮层每行显示「型号 · Android 版本」，离线设备额外标「已离线」
- 型号缓存**持久化到磁盘**（`<日志路径>/history/device_info.json`）——
  离线设备查不到 getprop，只能靠之前在线时存下来的信息
- 缓存按**归一化 key** 存（去端口）：在线列表是「10.1.246.185:5555」，
  历史列表是「10.1.246.185」，同一把 key 才能命中同一台设备

### v5.4 —— 设备切换器 + 连接状态语义拆分

用户反馈「刷新后检查到已连接的，没有更新连接状态，还是显示未连接」。
排查后确认**不是没检测到，而是检测到了没人用**：
终端已经打印「已刷新：1 台设备在线（10.1.246.185）」，
但顶栏输入框仍是历史里的旧 IP `192.168.0.3`，徽标判红「未连接」。

**根因（四个叠加）**：
1. 徽标语义把两件事揉成一个标签 ——「当前目标设备连没连」和「adb 上有几台设备」
   以前都叫「未连接」，用户无法区分「没设备」和「设备在但不是我选的那个」
2. `refresh_device_list` 故意保留当前选中项（不自动切走）→ 刷出新设备后界面纹丝不动
3. 顶栏**没有「在线设备清单」入口**，唯一线索是终端日志和左下角 10px 的「1 台」
4. 监控回调只更新下拉 values，不刷新徽标

**改动**：
- **徽标拆三态**：`✓ 已连接` / `✗ 目标离线 · N 台` / `● 无设备`
  —— 「目标离线」明确告诉你有 N 台可以切，不再是「未连接」这种没法行动的提示
- **新增顶栏「设备 ▾」按钮**（`gui/device_picker.py`）：点开是分组浮层
  （在线设备 / 离线与历史），单击即设为当前目标并自动连接
  - 型号与 Android 版本**懒加载**：浮层秒开列出 IP，
    型号在后台用一次全量 `adb shell getprop` 补齐
    （逐条 getprop 每条要 spawn 一个 adb 进程，10 台设备要 4 秒）
  - 纯 Tkinter 无边框 Toplevel，主题感知（换肤时自动重刷），内容超高可滚动
  - 快捷键 `Ctrl+Shift+D`（`Ctrl+D` 已被「断开」占用）
- **刷新后自动跟随唯一在线设备**：恰好只有 1 台在线且与当前目标不符时自动切过去。
  多台在线时**不自动切** —— 那会打断正在跑的安装/录屏（目标设备会被换掉）
- **新增 `app.select_device()`**：统一切换逻辑（写历史 → 同步下拉框 → 刷徽标）

**顺带修掉四个 bug**：
- `refresh_device_list` 末尾 `update_connection_status()` 没传 `devices`
  → 多 spawn 一次 adb（`get_connected_devices_parallel` 走的是不带缓存的 `query()`）
- `ttk.Combobox.delete(0, END) + insert(0, x)` 只改**输入框文本**、不改下拉列表
  （实测确认）→ 全部改成语义直白的 `set()`
- 启动时选设备从 `ip_history` 里挑（历史里排第一的可能是早已离线的旧设备）
  → 改成从**本次实际检测到的**在线设备里挑
- `device_monitor._on_device_list_changed` 里 `[:15]` 与 `Config.MAX_IP_HISTORY(=10)`
  不一致 → 统一走 Config

**顶栏宽度预算**（硬约束，可用 712px）：
新增「设备 ▾」按钮（68px）后必须从别处省出同等宽度，否则包名框被压到 171px
（断言线 170px，只差 1px 就挂）。压缩方案：
刷新按钮 `width` 4→3、连接/断开 4→3、设备框 12→11 字符、徽标 `padx` 6→4
→ 最终总需求 649px，**余 63px**，包名框恢复 207px（完整显示 `com.gitvdemo.video`）。

### v5.3 —— 顶栏恢复「刷新」按钮 + 修复两处长期失败的测试
用户反馈「刷新功能怎么没有了」—— v4 重构时把顶栏的刷新按钮删了，
只剩设备控制面板里一个，用户找不到。v3 顶栏本来是有的。

**改动**：
- 顶栏右侧恢复「刷新」按钮（文字，不是小图标 —— 30px 的图标在深色主题下
  根本不显眼，等于没有），带 tooltip「刷新设备列表（重新扫描已连接设备）」
- 为腾出横向空间：**连接/断开按钮的 `width` 从默认 6 改成 4**
  （ttk.Button 的 width 单位是「字符数」，默认 6 让这两个两字按钮各占 **108px**）
  → 顶栏从「超宽 1px、包名框被挤到 149px」变成「余 95px、包名框 207px」
- 新增 `TopIcon.TButton` 样式（顶栏图标按钮专用，更紧凑的 padding）

**顺带修掉两处一直在失败的测试**（之前只看了 ALL PASS 计数，没看结论）：
- `tests/test_core_regression.py` 引用了 v5.0 已删除的 `modules/performance_monitor.py`
  → 改用 `modules/perf_parsers.py`
- `tests/test_install_flow.py` 的 stub 缺 v5.1 新增的 `_start_ui_pump`，
  且我加的同步 `_run_in_ui` 覆盖被后面的 `for` 循环覆盖回去
  → 修正顺序（覆盖必须在绑定之后）+ stub 补全 v5.2 新增的方法

**顺带修掉 `_run_pm_install` 的一个死循环**：stdout 关闭但进程未退出时，
原代码直接 `continue` → 进程不退出就永远循环（占满 CPU）。
现在改成 `process.wait(timeout=...)` 等它退出。

### v5.2 —— 修复精简 ROM / 慢设备上的安装失败
用户反馈安装 36MB APK 到康佳电视（Android 5.1.1）失败，日志里同时出现
`Command timed out after 15 seconds`、`head: not found`、
`remote Is a directory`，还重复传了两遍 36MB。真机排查后确认是**五个问题叠加**：

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 1 | 可读性探测误判「设备禁止 shell 读取」 | 硬编码 `head -c 4`，而该 ROM **连 head 都没有**（只有 busybox） | 多级回退：`head` → `busybox head` → `ls -l`，并统一校验文件大小 |
| 2 | push 15 秒超时 | 固定超时；实测该设备传 36MB 要 **45 秒** | 按文件大小动态估算（`Config.install_push_timeout`） |
| 3 | 回退 `adb install` 必然失败 | `adb install` 内部是 push-install 模式 → `pm install <路径>`，而该 ROM 的 `pm install <路径>` **会挂死**（连不存在的文件都卡 40 秒+） | 设备端文件完好时**优先重试 pm install**，不重新传输 |
| 4 | 界面像卡死 | `process.stdout.readline()` 在无输出时**阻塞**，心跳代码根本没机会执行 | 改用**独立读线程 + 主线程轮询**，每 10 秒报进度 |
| 5 | 已装成功却报失败 | pm 打完 `Success` 但进程不退出（ROM 收尾慢），一直等到超时 | 收到 `Success` **立即判定成功**，不等进程退出 |

另外还修了：
- **超时后必须杀掉 pm 进程**：`pm install` 持有**全局安装锁**，
  残留进程会让下一次安装排队等锁 → 双重超时
- **重试不重复传输**：36MB 重推一遍既慢又抢资源
- **文件不存在立即判不可读**（`No such file`），不再 fallback 到「假定可读」

真机验证（康佳电视 10.1.246.185 / com.gitvdemo.video / 36.1MB）：
```
[  0.4s] 正在传输 APK 到设备（36.1 MB）...
[ 45.2s] 传输完成，正在设备端安装（需要解包与优化，最大约 676 秒，慢设备可能需要几分钟）...
[ 46.2s] 设备端已收到安装请求，正在解包与优化...
[197.1s] 设备端安装中... 已用 151 秒（大包需要解包与优化，属正常，请耐心等待）
[227.2s] 设备端已确认安装成功
→ 228 秒一次成功，无误判、无回退、无重复传输
```

新增 `tests/test_install_rom_compat.py`（30+ 断言，全部 mock），
把上面 5 点固化成回归；`check.bat` 扩到 11 步。

### v5.1 —— 修复实时刷新失效
用户反馈「点开始监控后没有实时显示采集数据，只有点击停止后才从报告里体现」。
排查发现是**架构级缺陷**，静默失败：

#### 🔴 根因：UI 队列泵的线程模型错误
```
旧设计：谁投递谁 root.after(20, pump) 一次
  ├─ Tk 的 after() 只能在【主线程】调用
  ├─ 后台线程调用 → 抛 "main thread is not in main loop"
  └─ 异常被 except 吞掉 → 队列永远不被消费
      → 后台在采集，界面永远不刷新（且没有任何报错）
```
其它功能没暴露问题，是因为它们的 `_run_in_ui` 大多在主线程触发；
**性能采集是纯后台线程驱动，100% 命中**。

**修复**：主线程启动**常驻泵**（`_start_ui_pump`，50ms 一跳），
后台线程只往队列里塞东西，不再碰 `after`。

#### 顺带修掉的
- `PerfCollector._publish` 用 `app._run_in_ui(callback, snapshot)` **两参数**调用，
  而 `_run_in_ui` 只接受一个 callable → TypeError 被吞 → 同样静默失效。
  改成 `lambda snap=snapshot: ...` 绑定。
- 指标卡副标题：布局层是两行、UI 更新却写单行 → 窄卡片里被截断成「峰值 -」。
  现在两边统一为两行。
- 定位不到进程时，PID 标签明确显示「未找到进程（应用可能未启动）」，
  而不是让用户对着满屏「--」猜原因。

#### 🧪 新增回归测试
`tests/test_perf_live_refresh.py`：守护后台线程投递必须被执行、
`_publish` 的投递方式、副标题两行格式、mock 采集驱动 UI 刷新。
`check.bat` 扩到 10 步。

### v5.0 —— 性能监控模块完全重写 + 测试报告
用户反馈「性能测试的采集方式和数据结果都不行」，要求全改。排查后确认
**旧实现有三个致命 bug**，数据基本是错的，本版全部重写。

#### 🔴 修掉的三个致命 bug（均已在真机 192.168.0.3 验证）
| Bug | 现象 | 根因 | 修复 |
|-----|------|------|------|
| **测错了进程** | CPU 恒为 0，线程表全是内核线程 | 小米盒子 Android 6 的 `pidof <包名>` **忽略参数**，返回全部 155 个 PID → 取到 PID=1（init） | 新增 `perf_locator.py`：多级回退（pidof → ps → dumpsys）+ 合理性校验 |
| **进程 CPU 少算 94%** | 进程 CPU 与线程表对不上 | `/proc/pid/stat`（线程组**总量**）与 `/proc/pid/task/pid/stat`（**单线程**）tid 相同，覆盖式赋值后取到主线程的值 | `perf_parsers.parse_proc_snapshot` 按 cat 的参数顺序**分离两种口径** |
| **CPU 系统性低估 38~56%** | 数值总是偏小 | `_diff_cpu` 的 `now` 取在 `dumpsys` 阻塞**之后**，dumpsys 的 1.5~3 秒被算进了差分窗口 | 采集点自带**读取完成时刻**时间戳；dumpsys 采集移出关键路径 |

真机对照（MiBOX4 / com.gitvdemo.video / pid 27690）：
```
/proc/27690/stat             合计=12626   ← 线程组总量（进程真实 CPU）
/proc/27690/task/27690/stat  合计=  776   ← 仅主线程
                             差值 11850 = 其它 203 个线程的 CPU
→ 旧实现取到的正是 776：进程 CPU 只算了 6%
```

#### 🆕 新增：测试结束弹出结果报告
- **顶部结论卡片**：CPU / 内存 / 帧率 + **与基线对比** + 自动结论
- **四个标签页**：
  - 趋势曲线（可切指标、可叠加上次基线）
  - 线程占用（**按角色聚合**：渲染/音视频解码/GC/IPC/线程池…）
  - 帧时间分布（直方图 + 16.7ms/33.3ms 预算线）
  - 原始数据（表格）
- **导出 HTML 报告**（自包含内联 SVG，可直接发给同事）/ CSV
- **基线对比系统**：自动存快照，可与任意一次历史对比

#### 🆕 新增：其它能力
- **场景化阈值**（视频播放/界面流畅/内存体检/省电/启动/通用）——
  不同场景「什么算超标」不一样，不再写死 80%/800MB
- **内存泄漏自动检测**：PSS 线性回归算斜率（MB/min），拟合度不够就不判
- **采样质量透明化**：报告里显示实际间隔、有效率、是否降级、各项采集耗时
- **无渲染活动可表达**：帧数差分为 0 时 FPS 记 None（显示 `--`），
  不用 0 冒充真实测得值（0 会被误读成"应用卡死"）
- **卡顿率是窗口内的真实值**：用「总数差分 + janky 百分比反推」算，
  而不是直接用进程启动至今的累计百分比（那个数值几乎不变，毫无意义）

#### 📁 模块拆分（职责分离）
```
modules/perf_locator.py    PID 定位（多级回退 + 校验）
modules/perf_parsers.py   纯函数解析器（/proc / gfxinfo / framestats / meminfo）
modules/perf_collector.py  采集器（时间戳对齐、并行采集、不碰 UI）
modules/perf_analysis.py   分析（自动结论 / 泄漏检测 / 线程角色归类）
modules/perf_chart.py      纯 Canvas 图表（零依赖，128 点曲线 0.7ms）
modules/perf_report.py     报告窗口 + HTML 导出
modules/perf_baseline.py   基线存储与对比
modules/perf_scenario.py   场景模板
```
旧模块 `modules/performance_monitor.py` 已删除。

#### 🧪 测试
新增 `tests/test_perf_v4.py`（60+ 断言），把每个真机验证过的行为固化成回归断言。

### v4.2 —— 顶栏精简 + 包名框加宽
- 🚫 **去掉重复的终端折叠按钮**
  - 顶栏的「终端 ▸」改为**只在终端折叠后出现**（常态彻底不占横向空间）
  - 终端面板标题栏里的「⌄」负责收起，顶栏那个负责展开 —— 职责不同，不是重复
  - 动机：`pack(RIGHT)` 会**优先占位**，把包名框挤窄；
    移除后腾出 ~78px
- 📏 **包名框加宽**：字符数 15 → 22，实际宽度 151px → **190px**，
  能显示完整包名（如 `com.gitvdemo.video`）；折叠终端时还能涨到 207px

### v4.1 —— 字体锐化 + 按钮可见性
- 🔤 **字体锐化**（用户反馈「字体模糊不清晰不锐利」）
  - 新增 `gui/win_render.py`：**DPI 感知**（Per-Monitor V2）——
    之前进程是 DPI-unaware，Windows 会用**位图拉伸**整个窗口，文字必然发虚
  - 字号全面改为**像素单位**（Tk 里负值=像素）：点会随 DPI 缩放，
    在 125%/150% 非整数缩放下被舍入到不同像素高度，小字号字形被压扁
  - 引入语义化字号常量 `FS_XS ~ FS_XXL` / `FSM_SM ~ FSM_LG`，全应用统一
- 🎨 **配色按 WCAG 对比度重调**
  - 三级文字 `fg_dim` 从 3.62:1 提到 **4.9:1**（深色）/ **4.6:1**（浅色），达 AA 标准
  - 主要文字提到接近纯白/纯黑，进一步提升锐利感
- 🔘 **按钮可见性**（用户反馈「功能按钮只有几个字浮在那」）
  - 根因量化：次要按钮底色与面板底色对比度仅 **1.08:1**（完全分不出来）
  - 新增 `btn` / `btn_hover` / `btn_pressed` / `btn_border` 令牌，
    按钮底色与面板拉开到 **1.35:1** 并加描边
  - 新增 `Action.TButton` / `ActionDanger.TButton` 样式：
    功能按钮用**明显底色 + 描边 + 三态可分**（常态/悬停/按下）
  - 危险操作改为**淡红底 + 红字 + 红边**，与普通按钮一眼可分
- 🧭 **导航选中态加强**：整行主色淡底 + 3px 主色条 + 文字加粗变主色；
  悬停时也出现 2px 指示条 + 图标变主色
- 🧪 **新增防回归断言**：顶栏总宽 ≤ 可用宽、包名/设备框最小宽度、
  所有按钮文字不被截断（这几类问题反复出现过，必须由测试守住）
- 📐 终端宽度 340 → **300**（像素字号后控件变宽 ~15%，不调整会把包名框压到 73px）

### v4.0 —— 界面完全重构
- 🏗️ **布局重写**：新增 `gui/layout_v4.py`，从「顶部 Tab + 左右分栏」改为
  「左侧固定导航 + 顶栏全局上下文 + 可折叠终端」；导航按**任务流**重新分组
  （日常操作：安装/诊断/设备；进阶工具：性能/投屏/脚本）
- 🎨 **主题系统**：新增 `gui/theme.py`，深色/浅色两套配色，**运行时一键切换**
  （侧边栏底部按钮 或 Ctrl+T），选择持久化到 `~/.adbtool_prefs.json`
  - 修复根因：Windows 默认 `vista` 主题会忽略 `background`/`foreground` 配置，
    切到 `clam` 后配色才真正生效（这正是旧版「换色不生效、显得 low」的原因）
- 🗜️ **终端可折叠**：Ctrl+B 或顶栏按钮折叠，工作区横向铺满，长路径日志不再换行
- 📐 **紧凑化**：窗口 1200x680（v3 为 1400x620）；顶栏统一 46px，省掉 Tab 条的 40px
- 🧹 **app.py 去硬编码色**：性能阈值色、连接徽标、拖放高亮、终端 tag 全部改走主题
- 🧪 **新增测试** `tests/test_layout_v4.py`（60+ 断言）：面板懒加载、主题切换、
  终端折叠、导航选中态、终端搜索、app 控件契约完整性
- 🖼️ **新增截图脚本** `tests/screenshot_v4.py`：自动输出深/浅两套 × 6 面板截图
- 🔁 **保留 v3 回退**：`ADBTOOL_LAYOUT=v3` 环境变量切回旧布局

### v3.3
- 🎯 **顶部设备区**：新增「连接」「断开」按钮（连设备不必再跨 Tab）；
  修「🔄 刷新设备」绑错功能（之前实际执行的是「查看设备信息」）；
  修设备下拉框被截断成「192.168.」
- 🔍 **终端输出区可搜索**：关键字高亮 + 上下跳转 + 命中计数 + 只看错误过滤
  + 导出/复制（新增 tests/test_log_search.py，19 项断言）
- 🛡️ **危险操作加二次确认**：获取 Root、重新挂载分区（原来单击即执行）
- 📐 **消除纵向空白**：各 Tab 空白占比从 47~82% 降到 1~34%；
  删除只含一个按钮的「高级工具」Tab（功能并入设备管理），Tab 从 7 个减为 6 个
- 🪟 **窗口默认宽度 1280 → 1400**：右栏终端要放得下搜索工具栏

### v3.2
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

**最后更新**: 2026-11-05
**文档版本**: v5.4.8
