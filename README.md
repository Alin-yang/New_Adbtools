# ADB Tool 综合文档

## 一、项目概述

### 1.1 项目简介
ADB Tool 是一款基于 Python + Tkinter 开发的 Android 设备管理工具，提供图形化界面进行 ADB 设备连接、应用管理、日志调试、屏幕操作等功能。

### 1.2 技术栈
- **开发语言**: Python 3.x
- **GUI 框架**: Tkinter (ttk)
- **ADB 工具**: Android Debug Bridge
- **打包工具**: PyInstaller

### 1.3 项目结构
```
New_Adbtools/
├── main.py                 # 程序入口
├── app.py                  # 主应用逻辑
├── config.py               # 配置管理
├── utils.py                # 工具函数
├── decorators.py           # 装饰器
├── cache_manager.py        # 缓存管理
├── gui/                    # GUI 布局模块
│   ├── layout_tab_view.py  # Tab 视图布局 (当前使用)
│   ├── layout_base.py      # 基础布局
│   ├── layout_tab.py       # Tab 布局
│   ├── layout_tab_zh.py    # 中文 Tab 布局
│   └── layout_zh.py        # 中文布局
├── modules/                # 功能模块
│   ├── device_manager.py   # 设备管理
│   ├── app_manager.py      # 应用管理
│   └── system_manager.py   # 系统管理
└── ip_history.txt          # IP 历史记录
```

## 二、核心功能模块

### 2.1 设备管理模块
**功能**:
- 连接/断开 ADB 设备 (网络/USB)
- 查看已连接设备列表
- 重启设备
- 获取 Root 权限
- 重新挂载分区
- 查看 Android 版本号
- 获取设备串号

**实现逻辑**:
```python
# 1. 设备连接检测
def check_device_connected(ip_address):
    # 执行 adb devices 命令
    # 解析输出，匹配设备 IP 或序列号
    # 更新缓存状态

# 2. 连接设备
def connect_adb():
    ip = get_ip_address()  # 从下拉框获取
    run_adb_command(f"adb connect {ip}")
    update_status("已连接", success=True)

# 3. 多设备支持
# - IP 下拉框显示所有设备 (包括 USB 序列号和网络 IP)
# - 装饰器确保操作前已选择设备
```

### 2.2 应用管理模块
**功能**:
- 强制安装 APK (带进度显示)
- 卸载应用
- 获取已安装应用列表
- 清除应用缓存
- 终止应用进程
- 获取应用版本号
- 获取应用安装路径
- 获取当前打开应用包名

**实现逻辑**:
```python
# 1. 强制安装 (带进度)
def force_install():
    apk_path = get_apk_path()
    # 构建多设备安装命令
    install_cmd = build_adb_command_with_device(
        f"adb install -r -d \"{apk_path}\"", 
        target_ip
    )
    # 启动线程执行安装
    # 实时捕获输出显示进度
    # 解析 "Performing Streamed Install" 计算进度百分比

# 2. 卸载应用
def uninstall():
    pkg_name = get_package_name()
    # 显示确认对话框
    # 执行 adb uninstall {pkg_name}
    # 清除缓存

# 3. 获取应用列表
def package_list():
    # 执行 adb shell pm list packages
    # 解析输出，提取包名
    # 异步获取每个包的版本信息
    # 更新下拉框
```

### 2.3 日志调试模块
**功能**:
- 启动/停止日志捕获
- 清除日志缓存
- 导出 ANR 文件
- 查看功能按键原始命令

**实现逻辑**:
```python
# 1. 日志捕获
def start_logcat():
    log_path = get_log_path()
    # 执行 adb logcat -v time > log_path
    # 后台线程持续捕获
    # 实时显示到输出窗口

# 2. 导出 ANR
def pull_anr_file():
    # 执行 adb pull /data/anr/ 到本地
    # 显示导出进度
```

### 2.4 屏幕操作模块
**功能**:
- 截取屏幕
- 开始/停止录屏

**实现逻辑**:
```python
# 1. 截屏
def screencap():
    # 执行 adb shell screencap -p
    # 保存为 PNG 文件
    # 显示预览

# 2. 录屏
def start_recording():
    # 执行 adb shell screenrecord /sdcard/video.mp4
    # 后台录制
    # 定时停止并拉取到本地
```

### 2.5 高级工具模块
**功能**:
- 打开工厂菜单

## 三、界面布局设计

### 3.1 三栏布局结构
```
┌─────────────────────────────────────────────────────┐
│  ADB Tool                                    - □ X  │
├────────────┬──────────────────┬─────────────────────┤
│ 左侧 Tab   │ 中间功能按钮区域   │ 右侧输出窗口        │
│ (140px)    │ (内容自适应)     │ (占据剩余空间)      │
│            │                  │                     │
│ [设备管理] │ IP 地址：[下拉框] │ [12:00:00] ✓       │
│ [应用管理] │                  │ 已连接 2 台设备      │
│ [日志调试] │ [连接 ADB]       │ ...                │
│ [屏幕操作] │ [卸载应用]       │                     │
│ [高级工具] │ ...              │                     │
└────────────┴──────────────────┴─────────────────────┘
```

### 3.2 布局实现代码
```python
def create_three_column_layout(self):
    # 左侧 Tab (固定宽度)
    self.left_panel = ttk.Frame(self.main_frame, width=140)
    self.left_panel.grid(row=0, column=0, sticky=tk.NSEW)
    self.left_panel.grid_propagate(False)
    
    # 中间功能 (内容自适应)
    self.center_panel = ttk.Frame(self.main_frame)
    self.center_panel.grid(row=0, column=1, sticky=tk.NSEW)
    
    # 右侧输出 (弹性扩展)
    self.right_panel = ttk.Frame(self.main_frame)
    self.right_panel.grid(row=0, column=2, sticky=tk.NSEW)
    
    # 配置权重
    self.main_frame.grid_columnconfigure(0, weight=0)  # 固定
    self.main_frame.grid_columnconfigure(1, weight=0)  # 自适应
    self.main_frame.grid_columnconfigure(2, weight=1)  # 弹性
```

### 3.3 Tab 选中效果
```python
# 未选中：浅灰色背景
style.configure('LeftTab.TButton', 
               background='#e8e8e8',
               font=('Arial', 10, 'bold'))

# 选中：深蓝色背景 + 5px 粗边框
style.configure('SelectedTab.TButton',
               background='#0078d7',  # Windows 标准蓝
               relief='solid',
               borderwidth=5)
```

## 四、核心技术实现

### 4.1 设备检测与同步
**问题**: 启动时检测到的设备与 IP 下拉框不同步

**解决方案**:
```python
def _load_ip_history(self):
    # 1. 从文件加载历史记录
    file_history = load_ip_history()
    
    # 2. 合并已检测到的设备
    merged_history = []
    # 先添加设备检测结果
    for device in self.ip_history:
        if device not in merged_history:
            merged_history.append(device)
    # 再添加文件历史
    for item in file_history:
        if device not in merged_history:
            merged_history.append(item)
    
    # 3. 更新下拉框
    self.ip_history = merged_history[:MAX_IP_HISTORY]
    self.ip_combobox['values'] = self.ip_history
```

### 4.2 装饰器模式
**用途**: 统一前置条件检查

```python
def require_device_connected(func):
    """设备连接校验装饰器"""
    def wrapper(self):
        # 1. 强制刷新设备状态
        cache_manager.device_cache.clear()
        self.show_current_device_status(force_display=True)
        
        # 2. 检查连接
        if not self.ensure_device_connected():
            return  # 未连接则提前返回
        
        # 3. 执行原函数
        return func(self)
    return wrapper

# 使用示例
@require_device_connected
def force_install(self):
    # 无需手动检查连接状态
    ...
```

### 4.3 缓存管理
**缓存类型**:
- `device_cache`: 设备状态缓存 (TTL: 3 秒)
- `package_cache`: 包信息缓存 (TTL: 180 秒)
- `system_cache`: 系统信息缓存
- `ip_history`: IP 历史记录 (文件持久化)

**实现**:
```python
class CacheManager:
    def __init__(self):
        self.device_cache = TTLCache(maxsize=50, ttl=3)
        self.package_cache = TTLCache(maxsize=50, ttl=180)
    
    def get_device_status(self, ip):
        return self.device_cache.get(ip)
    
    def set_device_status(self, ip, status):
        self.device_cache[ip] = status
```

### 4.4 异步操作与 UI 刷新
**原则**: 耗时操作在后台线程，UI 更新在主线程

```python
def force_install(self):
    # 主线程：显示进度条
    self._show_progress()
    
    # 启动后台线程
    install_thread = threading.Thread(
        target=self._run_install_with_progress,
        args=(apk_path,),
        daemon=True
    )
    install_thread.start()

def _run_install_with_progress(self, apk_path):
    # 后台线程：执行安装
    process = subprocess.Popen(cmd, ...)
    
    while True:
        output = process.stdout.readline()
        # 更新进度 (线程安全)
        self.app.root.after(0, self._update_install_status, message)
```

### 4.5 多设备支持
**实现**:
```python
def build_adb_command_with_device(base_cmd, target_ip):
    """构建支持多设备的 ADB 命令"""
    if not target_ip:
        return base_cmd
    
    # 检查是否为 USB 设备 (序列号)
    if ":" not in target_ip:
        return f"adb -s {target_ip} {base_cmd[4:]}"
    
    # 网络设备，添加端口
    if ":" not in target_ip:
        target_ip = f"{target_ip}:5555"
    
    return f"adb -s {target_ip} {base_cmd[4:]}"
```

## 五、配置与优化

### 5.1 性能配置
```python
# config.py
CACHE_TIMEOUT = 180          # 缓存超时 (秒)
DEVICE_CACHE_TIMEOUT = 3     # 设备状态缓存 (秒)
MAX_CACHE_SIZE = 50          # 最大缓存数
MAX_IP_HISTORY = 10          # IP 历史记录数
```

### 5.2 UI 配置
```python
WINDOW_GEOMETRY = "1200x700"  # 窗口大小
MIN_WINDOW_SIZE = (800, 600)  # 最小尺寸
```

### 5.3 布局优化要点
1. **左侧 Tab**: 固定 140px，垂直排列
2. **中间区域**: 根据按钮内容自适应，不设置固定宽度
3. **右侧输出**: weight=1，占据剩余空间
4. **按钮布局**: 每行 3 个，无空格空缺
5. **进度条**: 使用 pack 布局，避免与 grid 混用

## 六、打包发布

### 6.1 打包配置
```python
# ADBTool.spec
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('gui/', 'gui'),
        ('modules/', 'modules'),
        ('ip_history.txt', '.'),
    ],
    ...
)
```

### 6.2 打包步骤
```bash
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
**原因**: ip_history.txt 旧数据覆盖异步检测结果

**解决**: 合并设备检测结果和文件历史，去重后显示

### 7.2 布局不生效
**原因**: 
1. Tkinter 缓存未刷新
2. grid 和 pack 混用

**解决**:
1. 调用 `update_idletasks()` 强制刷新
2. 统一使用 pack 或 grid

### 7.3 安装无反应
**原因**: 进度条布局冲突

**解决**: 将 `grid()` 改为 `pack()`

### 7.4 Tab 选中效果不明显
**原因**: 样式配置不够醒目

**解决**: 使用深蓝色背景 (#0078d7) + 5px 粗边框

## 八、开发规范

### 8.1 代码结构
- 主逻辑：`app.py`
- GUI 布局：`gui/` 目录，模块化
- 功能模块：`modules/` 目录
- 配置集中：`config.py`

### 8.2 命名规范
- 变量：驼峰式 (如 `ip_combobox`)
- 函数：下划线式 (如 `force_install`)
- 类：大驼峰 (如 `LayoutTabView`)

### 8.3 注释规范
- 函数必须有 docstring
- 复杂逻辑必须有注释
- 使用中文注释

### 8.4 Git 分支
- 主分支：`main`
- 开发分支：`new_view` (界面重构)
- 提交信息：使用中文，描述清晰

## 九、版本历史

### v2.0 (当前版本)
- ✅ 三栏布局重构 (左侧 Tab + 中间功能 + 右侧输出)
- ✅ 自适应宽度优化
- ✅ Tab 选中效果增强 (深蓝背景 +5px 边框)
- ✅ 功能按钮补齐 (无空格)
- ✅ 输出区域宽度优化 (500px)
- ✅ 修复布局管理器冲突
- ✅ 修复设备检测同步问题

### v1.0
- 基础功能实现
- 传统按钮布局

## 十、联系方式

项目位置：`D:\N_ADBtools\New_Adbtools-test_about\New_Adbtools`

---

**最后更新**: 2026-03-17
**文档版本**: v2.0
