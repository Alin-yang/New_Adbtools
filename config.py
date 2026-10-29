"""
配置管理模块
统一管理应用的所有配置参数，避免硬编码
"""
import os

class Config:
    """应用配置类"""
    
    # 默认路径配置
    DEFAULT_LOG_PATH = "D:\\adbtool_log\\logs"
    DEFAULT_ANR_PATH = "D:\\adbtool_log\\anr_files"
    DEFAULT_SCREENSHOT_PATH = "D:\\adbtool_log\\screenshots"
    DEFAULT_RECORD_PATH = "D:\\adbtool_log\\records"
    
    @staticmethod
    def get_actual_path(default_path):
        """获取实际路径，如果D盘存在则使用D:\adbtool_log，否则使用当前目录"""
        import os
        if os.path.exists("D:\\") and default_path.startswith("D:\\adbtool_log"):
            # 如果是D:\adbtool_log开头的路径且D盘存在，则使用原路径
            base_path = "D:\\adbtool_log"
            subfolder = os.path.relpath(default_path, "D:\\adbtool_log")
            return os.path.join(base_path, subfolder)
        else:
            # 否则使用当前目录下的同名子目录
            base_path = os.getcwd()
            if default_path.startswith("D:\\adbtool_log"):
                subfolder = os.path.relpath(default_path, "D:\\adbtool_log")
                return os.path.join(base_path, subfolder)
            else:
                return default_path
    
    # 性能优化的缓存配置
    CACHE_TIMEOUT = 180  # 减少缓存超时时间到 3 分钟
    DEVICE_CACHE_TIMEOUT = 3  # 设备连接状态缓存超时减少到 3 秒
    MAX_CACHE_SIZE = 50  # 减少最大缓存条目数
    CACHE_CLEANUP_INTERVAL = 120  # 增加清理间隔到 2 分钟
        
    # 设备监控配置
    DEVICE_MONITOR_INTERVAL = 3  # 设备监控检查间隔（秒）
    DEVICE_MONITOR_ENABLED = True  # 默认启用设备监控
    # 连续多少次空快照才判定「设备真的断开」（去抖，防止 adb 查询抖动造成误报）
    DEVICE_DISCONNECT_STREAK = 3
    # 设备列表查询（adb devices）超时时间（秒）
    DEVICE_QUERY_TIMEOUT = 5
    
    # IP历史记录配置
    MAX_IP_HISTORY = 10  # 最大IP历史记录数
    IP_HISTORY_FILE = "ip_history.txt"
    
    # 包名历史记录配置
    MAX_PKG_HISTORY = 10  # 最大包名历史记录数（保留最近10个）
    PKG_HISTORY_FILE = "pkg_history.txt"
    
    # 界面配置
    # 窗口默认 1280x620：1080p 屏幕下 1078x464 会让右侧终端只剩 ~350px，
    # 日志里的长路径换行严重。放宽后左侧卡片和右侧终端都能铺开。
    # ⚠️ 高度不要低于 620：投屏 Tab 内容最多（含说明卡 + 4 组按键），
    #    高度不够会把底部「系统控制」卡片顶出窗口。
    # ⚠️ 宽度 1400：右栏终端要放得下搜索工具栏（搜索框+计数+导航+菜单
    #    约需 400px），加上左侧功能区最少 620px，1280 装不下会把右栏压扁。
    #    1080p 屏幕宽 1920，1400 完全放得下。
    WINDOW_GEOMETRY = "1400x620"
    MIN_WINDOW_SIZE = (1100, 520)

    # 应用版本号（标题栏显示，与 README 版本历史保持一致）
    APP_VERSION = "3.3"

    # 进度条配置
    PROGRESS_BAR_LENGTH = 150
    
    # 性能优化的线程池配置
    MIN_THREAD_WORKERS = 3  # 增加最小线程数
    MAX_THREAD_WORKERS = 8   # 减少最大线程数避免过度竞争
    THREAD_WORKERS_RATIO = 4  # 调整任务数/工作线程数比例
    
    # 文件操作配置
    MAX_INSTALL_RETRIES = 2  # 减少安装重试次数
    FILE_OPERATION_TIMEOUT = 20  # 减少文件操作超时时间

    # 安装配置
    INSTALL_TIMEOUT = 900        # 单次安装最长耗时（秒），15 分钟
    INSTALL_RETRIES = 2          # 安装失败后的重试次数
    INSTALL_REMOTE_TMP = "/data/local/tmp/_adbtool_install.apk"  # 设备端临时 APK 路径
    INSTALL_HEARTBEAT = 10       # 安装过程无输出时的心跳提示间隔（秒）
    
    # 性能优化的ADB命令配置
    ADB_COMMAND_TIMEOUT = 15  # 减少ADB命令超时时间
    MAX_ADB_RETRIES = 2  # 减少ADB命令最大重试次数
    
    # 国际化配置（仅保留中文）
    DEFAULT_LANGUAGE = "zh"
    
    @classmethod
    def get_history_file_path(cls, app_instance=None) -> str:
        """获取IP历史记录文件的完整路径（存储到日志路径下的history目录）
        
        Args:
            app_instance: 应用实例，用于获取用户定义的日志路径
        """
        from utils import get_user_defined_log_path
        log_path = get_user_defined_log_path(app_instance)
        history_dir = os.path.join(log_path, "history")
        return os.path.join(history_dir, cls.IP_HISTORY_FILE)
    
    @classmethod
    def get_pkg_history_file_path(cls, app_instance=None) -> str:
        """获取包名历史记录文件的完整路径（存储到日志路径下的history目录）
        
        Args:
            app_instance: 应用实例，用于获取用户定义的日志路径
        """
        from utils import get_user_defined_log_path
        log_path = get_user_defined_log_path(app_instance)
        history_dir = os.path.join(log_path, "history")
        return os.path.join(history_dir, cls.PKG_HISTORY_FILE)
    
    # 性能监控告警配置（连续超阈值若干次才告警，避免毛刺误报）
    PERF_ALERT_CPU_PERCENT = 80   # 进程 CPU% 告警线（多核设备可比 100% 高）
    PERF_ALERT_MEM_MB = 800       # PSS 内存(MB) 告警线
    PERF_ALERT_STREAK = 3         # 连续多少次采样超阈值才触发告警

    # 投屏配置
    SCRCPY_PATH = "tools\\scrcpy\\scrcpy.exe"  # scrcpy 可执行文件路径
    SCRCPY_BITRATE = "8M"  # 默认码率
    SCRCPY_MAX_SIZE = "1920"  # 最大尺寸
    SCRCPY_MAX_FPS = "30"  # 最大帧率

    # 投屏参数可选项（用户在「投屏」Tab 里选）
    # ⚠️ 之前这三个值写死在代码里，投屏卡顿/模糊时用户唯一能做的
    #    就是改代码重新打包 —— 没有任何自救手段。
    SCRCPY_BITRATE_OPTIONS = ["2M", "4M", "8M", "16M", "24M"]
    SCRCPY_MAX_SIZE_OPTIONS = ["720", "1080", "1440", "1920", "0"]  # 0 = 保持原始分辨率
    SCRCPY_MAX_FPS_OPTIONS = ["15", "24", "30", "60"]
    SCRCPY_SIZE_LABELS = {
        "720": "720p (标清)",
        "1080": "1080p (全高清)",
        "1440": "1440p (2K)",
        "1920": "1920 (全高清以上)",
        "0": "原始分辨率 (不缩放)",
    }
    
    @classmethod
    def ensure_directories(cls, app_instance=None) -> None:
        """确保所有必要的目录都存在
        
        Args:
            app_instance: 应用实例，用于获取用户定义的日志路径
        """
        from utils import get_user_defined_log_path
        log_path = get_user_defined_log_path(app_instance)
        history_dir = os.path.join(log_path, "history")  # 历史数据专用目录
        
        directories = [
            cls.get_actual_path(cls.DEFAULT_LOG_PATH),
            cls.get_actual_path(cls.DEFAULT_ANR_PATH),
            cls.get_actual_path(cls.DEFAULT_SCREENSHOT_PATH),
            cls.get_actual_path(cls.DEFAULT_RECORD_PATH),
            log_path,  # 用户定义的日志路径
            history_dir,  # 历史数据目录（存放IP和包名历史文件）
            "tools\\scrcpy"  # scrcpy 工具目录
        ]
        for directory in directories:
            os.makedirs(directory, exist_ok=True)

# 中文界面文本配置
UI_TEXTS = {
    "window_title": "ADB Tool",
    "ip_label": "IP 地址:",
    "package_label": "应用包名:",
    "apk_label": "APK 文件:",
    "log_path_label": "数据存储路径:",
    "browse_apk": "选择安装包路径",
    "browse_log": "选择数据存储路径",
    "connect_adb": "连接 ADB",
    "disconnect_adb": "断开所有ADB连接",
    "show_help": "查看使用说明",
    "force_install": "强制安装apk",
    "uninstall": "卸载当前包名应用",
    "package_list": "获取已安装应用包名列表",
    "clear_cache": "清除应用缓存",
    "root_device": "获取Root权限",
    "pull_anr": "导出ANR文件",
    "remount": "重新挂载分区",
    "get_version": "获取当前包名版本号",
    "reboot": "重启设备",
    "android_version": "获取Android版本号",
    "log_clear": "清除日志缓存",
    "get_package_name": "获取当前打开应用包名",
    "screencap": "截取当前屏幕",
    "get_serial": "获取设备串号",
    "start_logcat": "启动日志捕获",
    "stop_logcat": "停止日志捕获",
    "kill_process": "终止当前包名所有进程",
    "get_package_path": "获取当前包名应用安装路径",
    "show_commands": "功能按键原始执行命令",
}