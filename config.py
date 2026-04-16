"""
配置管理模块
统一管理应用的所有配置参数，避免硬编码
"""
import os
import sys
from typing import Dict, Any

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
    
    # IP历史记录配置
    MAX_IP_HISTORY = 10  # 最大IP历史记录数
    IP_HISTORY_FILE = "ip_history.txt"
    
    # 包名历史记录配置
    MAX_PKG_HISTORY = 10  # 最大包名历史记录数（保留最近10个）
    PKG_HISTORY_FILE = "pkg_history.txt"
    
    # 界面配置
    WINDOW_GEOMETRY = "1078x464"
    MIN_WINDOW_SIZE = (1026, 422)
    
    # 进度条配置
    PROGRESS_BAR_LENGTH = 150
    
    # 性能优化的线程池配置
    MIN_THREAD_WORKERS = 3  # 增加最小线程数
    MAX_THREAD_WORKERS = 8   # 减少最大线程数避免过度竞争
    THREAD_WORKERS_RATIO = 4  # 调整任务数/工作线程数比例
    
    # 文件操作配置
    MAX_INSTALL_RETRIES = 2  # 减少安装重试次数
    FILE_OPERATION_TIMEOUT = 20  # 减少文件操作超时时间
    
    # 性能优化的ADB命令配置
    ADB_COMMAND_TIMEOUT = 15  # 减少ADB命令超时时间
    MAX_ADB_RETRIES = 2  # 减少ADB命令最大重试次数
    
    # 国际化配置（仅保留中文）
    DEFAULT_LANGUAGE = "zh"
    
    @classmethod
    def get_config_dict(cls) -> Dict[str, Any]:
        """获取所有配置的字典形式"""
        config_dict = {}
        for attr_name in dir(cls):
            if not attr_name.startswith('_') and not callable(getattr(cls, attr_name)):
                config_dict[attr_name] = getattr(cls, attr_name)
        return config_dict
    
    @classmethod
    def get_history_file_path(cls) -> str:
        """获取IP历史记录文件的完整路径（存储到 D:\\adbtool_log 目录）"""
        # 使用统一的数据存储路径
        base_dir = cls.get_actual_path("D:\\adbtool_log")
        return os.path.join(base_dir, cls.IP_HISTORY_FILE)
    
    @classmethod
    def get_pkg_history_file_path(cls) -> str:
        """获取包名历史记录文件的完整路径（存储到 D:\\adbtool_log 目录）"""
        # 使用统一的数据存储路径
        base_dir = cls.get_actual_path("D:\\adbtool_log")
        return os.path.join(base_dir, cls.PKG_HISTORY_FILE)
    
    @classmethod
    def ensure_directories(cls) -> None:
        """确保所有必要的目录都存在"""
        directories = [
            cls.get_actual_path(cls.DEFAULT_LOG_PATH),
            cls.get_actual_path(cls.DEFAULT_ANR_PATH),
            cls.get_actual_path(cls.DEFAULT_SCREENSHOT_PATH),
            cls.get_actual_path(cls.DEFAULT_RECORD_PATH),
            cls.get_actual_path("D:\\adbtool_log")  # 历史记录文件根目录
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

def get_text(key: str) -> str:
    """
    获取界面文本
    
    Args:
        key: 文本键名
        
    Returns:
        str: 对应的中文文本，如果不存在则返回键名
    """
    return UI_TEXTS.get(key, key)