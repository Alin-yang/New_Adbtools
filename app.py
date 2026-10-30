import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import psutil
import subprocess
import os
import re
import queue
import io
import logging
from typing import Optional, Tuple
from decorators import require_device_connected
from utils import (
    run_adb_command, timestamp_time,
    extract_version_info, ensure_directory,
    get_next_filename, load_ip_history, save_ip_history,
    load_pkg_history, save_pkg_history, is_valid_package_name,
    get_accurate_package_version, calculate_optimal_workers, format_file_size,
    get_connected_devices, get_connected_devices_simple,
    extract_package_name_from_apk, get_connected_devices_parallel,
    get_connected_devices_cached,  # 🆕 新增缓存版本
    get_connected_devices_cached_safe,  # 🆕 安全版：查询失败返回 None
    set_device_validation_paused,  # 🆕 重负载操作期间暂停设备可达性验证
    filter_lines,  # 🆕 Python 侧按关键字过滤输出（替代 shell grep）
    parse_getprop_all,  # 🆕 解析全量 getprop 输出（一次拿全部属性）
    get_all_package_versions,  # 🆕 一条命令拿全部包的版本号
    verify_install_result,  # 🆕 安装后用设备端版本号校验真实结果
)
from config import Config
from cache_manager import cache_manager
import concurrent.futures
from device_monitor import DeviceStatusManager
from modules.performance_monitor import PerformanceMonitor

# 配置日志输出（使用轮转日志处理器）
from logging.handlers import RotatingFileHandler
import os

# adb push 进度输出格式: "[ 45%] /data/local/tmp/x.apk: 45%"
_PUSH_PERCENT_RE = re.compile(r'(\d{1,3})\s*%')
# 传输量格式: "12.34MB/96.20MB"
_PUSH_SIZE_RE = re.compile(r'([\d.]+\s*[KMGT]?B)\s*/\s*([\d.]+\s*[KMGT]?B)', re.IGNORECASE)

# 获取用户定义的日志路径
log_dir = Config.get_actual_path(Config.DEFAULT_LOG_PATH)
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'adb_tool_debug.log')

# 创建轮转日志处理器（最大10MB，保留5个备份）
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)

# 控制台 handler：Windows 控制台默认 GBK，遇到 ✓ / ⚠ 这类字符会抛
# UnicodeEncodeError 并**丢掉整条日志**。这里强制 UTF-8 + 替换非法字符。
console_handler = logging.StreamHandler(sys.stdout)
try:
    console_handler.stream = io.TextIOWrapper(
        console_handler.stream.buffer, encoding='utf-8', errors='replace',
        line_buffering=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        console_handler,
        file_handler
    ]
)

class ADBToolApp:
    # 预先声明所有动态绑定的GUI组件
    apk_entry:ttk.Entry
    ip_combobox:ttk.Combobox  # 修改为Combobox
    pkg_entry:ttk.Entry  # 页面上实际为Combobox，但为了兼容性声明为Entry
    pkg_combobox:ttk.Combobox  # 包名下拉框
    log_path_entry:ttk.Entry
    status_text:tk.Text
    progress: ttk.Progressbar # 进度条声明

    def __init__(self, root: tk.Tk, layout_module) -> None:
        """
        初始化ADB工具应用
        
        Args:
            root: Tkinter根窗口
            layout_module: GUI布局模块
        """
        self.root = root
        self._start_ts = time.perf_counter()
        self.root.title("ADB Tool")
        self.root.geometry(Config.WINDOW_GEOMETRY)
        if hasattr(Config, 'MIN_WINDOW_SIZE'):
            self.root.minsize(*Config.MIN_WINDOW_SIZE)
        self.layout_module = layout_module
                
        # 性能优化：添加防抖机制
        self._status_update_timer = None
        self._pending_status_message = None
        self._last_status_time = 0
        self._status_throttle_interval = 0.1  # 100ms 节流间隔
                
        # 长时间运行任务的独立线程管理（不占用线程池）
        self._long_running_threads = []  # 跟踪日志、录屏等长时间运行的线程
        self._cleanup_interval = 300  # 清理已完成线程的间隔（秒）
        self._last_cleanup_time = time.time()
        
        # 设备监控管理器
        self.device_monitor_manager = None
                
        self._init_variables()
        self._setup_gui()
        self._setup_window_close_handler()  # 设置窗口关闭清理逻辑
        # 注意：_delayed_initialization 已经在_setup_gui 中调用，不需要在此重复调用
        logging.info(f"[启动] __init__ 耗时 {(time.perf_counter() - self._start_ts) * 1000:.0f} ms")

    def _setup_window_close_handler(self):
        """设置窗口关闭时的清理逻辑"""
        # 绑定窗口最小化/切换后台事件
        self.root.bind('<Unmap>', lambda e: self._hide_perf_dropdown())
        
        def on_closing():
            import logging
            logging.info("[窗口关闭] 开始清理资源...")
            
            # 隐藏性能监控下拉列表
            if hasattr(self, 'perf_dropdown_toplevel') and self.perf_dropdown_toplevel:
                try:
                    self._hide_perf_dropdown()
                    logging.info("[窗口关闭] 性能监控下拉列表已隐藏")
                except Exception as e:
                    logging.error(f"[窗口关闭] 隐藏下拉列表失败: {e}")
            
            # 停止设备监控
            if self.device_monitor_manager:
                try:
                    self.device_monitor_manager.stop_auto_monitor()
                    logging.info("[窗口关闭] 设备监控已停止")
                except Exception as e:
                    logging.error(f"[窗口关闭] 停止设备监控失败: {e}")
            
            # 停止日志捕获
            if self.logging_active:
                try:
                    self.stop_logcat()
                    logging.info("[窗口关闭] 日志捕获已停止")
                except Exception as e:
                    logging.error(f"[窗口关闭] 停止日志捕获失败: {e}")
            
            # 停止录屏
            if self.recording_active:
                try:
                    self.stop_recording()
                    logging.info("[窗口关闭] 录屏已停止")
                except Exception as e:
                    logging.error(f"[窗口关闭] 停止录屏失败: {e}")
            
            # 停止性能监控
            if hasattr(self, 'performance_monitor') and self.performance_monitor.monitoring:
                try:
                    self.performance_monitor.stop_monitoring()
                    logging.info("[窗口关闭] 性能监控已停止")
                except Exception as e:
                    logging.error(f"[窗口关闭] 停止性能监控失败: {e}")
            
            # 关闭线程池（不等待任务完成，快速退出）
                    logging.info("[窗口关闭] 线程池已关闭")
                except Exception as e:
                    logging.error(f"[窗口关闭] 关闭线程池失败: {e}")
            
            logging.info("[窗口关闭] 清理完成，准备退出")
            # 销毁窗口
            self.root.destroy()
        
        # 注册窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", on_closing)

    def _delayed_initialization(self):
        """延迟初始化非关键组件（极致优化版）"""
        # 立即在后台启动设备检测（使用并行检测策略）
        device_thread = threading.Thread(target=self._async_device_detection_parallel, daemon=True)
        device_thread.start()
        
        # 合并历史记录加载，减少延迟次数（从 100ms 减少到 30ms）
        self.root.after(30, self._load_all_history_async)
        
        # 目录创建移到更晚且异步执行（从 200ms 减少到 80ms）
        self.root.after(80, self._ensure_directories_async)
        
        # 启动设备监控（延迟 200ms）
        self.root.after(200, self._start_device_monitoring)

    def _async_device_detection_parallel(self):
        """并行的异步设备检测（优化版本，使用并行验证）"""
        try:
            # 使用并行检测设备，不进行深度验证
            connected_devices = get_connected_devices_parallel()
            # 在主线程中更新 UI
            self._run_in_ui(lambda: self._handle_detected_devices(connected_devices))
        except Exception as error:
            error_msg = str(error)
            self._run_in_ui(lambda msg=error_msg: self.update_status(f"启动时设备检测失败：{msg}", False))

    def refresh_device_list(self):
        """刷新设备列表（顶栏「🔄 刷新设备」按钮）

        ⚠️ 之前这个按钮绑的是 `show_device_info`（查看设备信息），
        点下去只是往终端刷一堆信息，设备列表根本没刷新 —— 按钮与行为不符。
        现在真正重新扫描设备并更新下拉框 + 连接状态。
        """
        self.update_status("正在刷新设备列表...", True, "info")

        def _work():
            try:
                devices = get_connected_devices_parallel()
            except Exception as e:
                self._update_status_safe(f"刷新设备列表失败：{e}", False)
                return

            def _apply():
                if not devices:
                    self.update_status("未检测到已连接设备", False)
                    # 仍要更新连接状态（可能显示"未连接"）
                    self.update_connection_status()
                    return

                # 把检测到的设备并入历史（去重，保持当前选中项不变）
                current = self.get_ip_address()
                for device in devices:
                    normalized = device
                    if ':' in device and '.' in device:
                        normalized = device.split(':')[0]
                    if normalized not in self.ip_history:
                        self.ip_history.insert(0, normalized)

                self.ip_history = self.ip_history[:Config.MAX_IP_HISTORY]
                self._schedule_history_save()
                self._safe_update_combobox('ip', self.ip_history)

                # 保持用户当前选中的设备（不要被自动切走）
                if current:
                    try:
                        self.ip_combobox.delete(0, tk.END)
                        self.ip_combobox.insert(0, current)
                    except Exception:
                        pass

                self.update_connection_status()
                names = "、".join(
                    d.split(':')[0] if (':' in d and '.' in d) else d
                    for d in devices
                )
                self.update_status(f"已刷新：{len(devices)} 台设备在线（{names}）", True)

            self._run_in_ui(_apply)

        self.run_in_background(_work)

    def _start_device_monitoring(self):
        """启动后台设备监控"""
        try:
            # 初始化设备监控管理器
            self.device_monitor_manager = DeviceStatusManager(self)
            # 启动自动监控模式
            self.device_monitor_manager.start_auto_monitor()
            self.update_status("✓ 设备监控已启动", True)
        except Exception as error:
            error_msg = str(error)
            self.update_status(f"启动设备监控失败：{error_msg}", False)

    def _init_variables(self) -> None:
        """
        初始化实例变量
        
        初始化所有必要的实例变量，包括进程管理、路径配置、
        状态标志等。
        """
        self.logcat_process = None
        self.default_log_path = Config.DEFAULT_LOG_PATH
        self.log_file_path = None
        self.logging_active = False
        self.logcat_subprocess = None
        self.stop_event = threading.Event()
        self.progress = None
        # IP历史记录列表
        self.ip_history = []
        # 包名历史记录列表
        self.pkg_history = []
        
        # 屏幕录制相关变量
        self.recording_active = False
        self.recording_subprocess = None
        self.recording_thread = None
        self.recording_file_path = None
        
        # 设备状态显示控制变量
        self.last_device_status_time = 0
        self.device_status_cooldown = 0.5  # 缩短冷却时间到0.5秒，提高响应性
        
        self._last_displayed_ip = ""  # 记录上次显示的IP地址

        # 状态栏文本框的行数计数（增量维护，避免每次扫描全文）
        self._status_line_count = 0

        # 数据存储路径的线程安全快照（由 log_path_entry 的 trace 回调在主线程更新，
        # 后台线程只读这个副本，不直接访问 Tk 控件）
        self._user_log_path = ""

        # UI 任务队列：后台线程把 UI 操作塞进来，主线程的定时器负责执行。
        # ⚠️ 不能用 root.after() 从后台线程调度（主线程忙时会抛
        #    "main thread is not in main loop"）。
        self._ui_queue = queue.Queue()
        self._ui_pump_scheduled = False
        
        # 历史记录防抖保存
        self._history_save_timer = None
        self._pending_history_save = False
        
        # 性能监控器
        self.performance_monitor = PerformanceMonitor(self)

    def _load_all_history_async(self):
        """异步加载所有历史记录（合并 IP 和 pkg 历史）"""
        # 在后台线程中同时加载两种历史记录
        def load_history():
            try:
                # 加载 IP 历史
                file_history = load_ip_history(self)
                merged_history = []
                for device in self.ip_history:
                    if device not in merged_history:
                        merged_history.append(device)
                for item in file_history:
                    if item not in merged_history:
                        merged_history.append(item)
                merged_history = merged_history[:Config.MAX_IP_HISTORY]
                
                # 加载 pkg 历史
                pkg_history = load_pkg_history(self)
                
                # 在主线程中更新 UI
                self._run_in_ui(lambda: self._update_history_ui(merged_history, pkg_history))
            except Exception as error:
                error_msg = str(error)
                self._run_in_ui(lambda msg=error_msg: self.update_status(f"加载历史记录失败：{msg}", False))
        
        # 启动后台线程
        thread = threading.Thread(target=load_history, daemon=True)
        thread.start()
    
    def _schedule_history_save(self):
        """调度历史记录保存（防抖）"""
        # ⚠️ 可能从后台线程调用，after / after_cancel 必须回主线程执行
        def _do():
            if self._history_save_timer:
                try:
                    self.root.after_cancel(self._history_save_timer)
                except Exception:
                    pass
            # 2秒后保存
            self._history_save_timer = self.root.after(2000, self._save_all_history)

        self._run_in_ui(_do)
    
    def _save_all_history(self):
        """保存所有历史记录"""
        try:
            save_ip_history(self.ip_history, self)
            save_pkg_history(self.pkg_history, self)
        except Exception as e:
            logging.error(f"保存历史记录失败: {e}")
        finally:
            self._history_save_timer = None
    
    def _update_history_ui(self, ip_history, pkg_history):
        """更新历史记录 UI（优化版 - 避免不必要的刷新）"""
        # 只在数据真正变化时才更新
        if self.ip_history != ip_history:
            self.ip_history = ip_history
            if hasattr(self, 'ip_combobox'):
                # 使用 after_idle 延迟更新，避免阻塞 Tab 切换
                self._run_in_ui(lambda: self._safe_update_combobox('ip', self.ip_history))
        
        if self.pkg_history != pkg_history:
            self.pkg_history = pkg_history
            if hasattr(self, 'pkg_combobox'):
                # 使用 after_idle 延迟更新，避免阻塞 Tab 切换
                self._run_in_ui(lambda: self._safe_update_combobox('pkg', self.pkg_history))
    
    def _safe_update_combobox(self, combo_type: str, values):
        """安全更新 Combobox（带异常处理）"""
        try:
            if combo_type == 'ip' and hasattr(self, 'ip_combobox'):
                self.ip_combobox['values'] = values
            elif combo_type == 'pkg' and hasattr(self, 'pkg_combobox'):
                self.pkg_combobox['values'] = values
            elif combo_type == 'apk' and hasattr(self, 'apk_combobox'):
                self.apk_combobox['values'] = values
            elif combo_type == 'quick_cmd' and hasattr(self, 'quick_cmd_combobox'):
                self.quick_cmd_combobox['values'] = values
        except Exception as e:
            import logging
            logging.error(f"更新 Combobox 失败: {e}")
    
    def _ensure_directories_async(self):
        """异步创建必要目录"""
        try:
            Config.ensure_directories(self)
        except Exception as e:
            self.update_status(f"创建目录失败：{str(e)}", False)
    
    def _handle_detected_devices(self, devices):
        """处理检测到的设备（增强版 - 同步 IP 输入框）"""
        import logging
        
        if devices:
            self.update_status(f"启动时检测到 {len(devices)} 台已连接设备", True)
            
            # 【新增】将设备添加到历史记录并更新 IP 输入框
            try:
                detected_devices = []
                for device in devices:
                    if device not in detected_devices:
                        detected_devices.append(device)
                
                # 将所有设备添加到历史记录中
                for device in detected_devices:
                    normalized_device = device
                    if ':' in device and '.' in device:  # IP地址格式
                        normalized_device = device.split(':')[0]
                    
                    if normalized_device not in self.ip_history:
                        self.ip_history.insert(0, normalized_device)
                
                # 限制历史记录数量
                self.ip_history = self.ip_history[:Config.MAX_IP_HISTORY]
                
                # 调度保存到文件
                self._schedule_history_save()
                
                # 更新下拉框和 IP 输入框
                if hasattr(self, 'ip_combobox'):
                    logging.info(f"[启动检测] ip_combobox 存在，准备更新IP")
                    
                    # 【关键修复】优先选择 USB 设备，其次才是网络 IP
                    first_device = None
                    usb_device = None
                    network_device = None
                    
                    for device in self.ip_history:
                        # 判断是否为 USB 设备（不包含点号和冒号）
                        if '.' not in device and ':' not in device:
                            usb_device = device
                            break
                        # 记录第一个网络 IP
                        elif network_device is None and ('.' in device or ':' in device):
                            network_device = device
                    
                    # 优先使用 USB 设备，如果没有则使用网络 IP
                    first_device = usb_device if usb_device else network_device
                    
                    logging.info(f"[启动检测] USB设备={usb_device}, 网络IP={network_device}, 最终选择={first_device}")
                    
                    if first_device:
                        def update_ip_ui():
                            """在主线程中更新 IP UI"""
                            try:
                                logging.info(f"[启动检测] 开始更新 IP UI, first_device={first_device}")
                                # 更新下拉框
                                self._safe_update_combobox('ip', self.ip_history)
                                # 如果输入框为空或只有默认值，设置第一个检测到的设备
                                current_value = self.ip_combobox.get().strip()
                                logging.info(f"[启动检测] 当前 IP 输入框值: '{current_value}', 长度: {len(current_value)}")
                                
                                should_update = False
                                if not current_value:
                                    should_update = True
                                    logging.info("[启动检测] 条件匹配: 输入框为空")
                                elif current_value == "192.168.":
                                    should_update = True
                                    logging.info("[启动检测] 条件匹配: 默认值 '192.168.'")
                                elif current_value.startswith("192.168") and len(current_value) < 8:
                                    should_update = True
                                    logging.info(f"[启动检测] 条件匹配: 不完整的IP '{current_value}'")
                                
                                if first_device and should_update:
                                    logging.info(f"[启动检测] 正在更新 IP 输入框为: {first_device}")
                                    self.ip_combobox.delete(0, tk.END)
                                    self.ip_combobox.insert(0, first_device)
                                    logging.info(f"[启动检测] IP 输入框已更新，当前值: {self.ip_combobox.get()}")
                                    # 延迟调用 update_connection_status 确保 UI 已更新
                                    self.root.after(100, lambda: self.update_connection_status(first_device))
                                    logging.info(f"[启动检测] 已调度 update_connection_status")
                                else:
                                    logging.info(f"[启动检测] 跳过更新 (first_device={first_device}, should_update={should_update})")
                            except Exception as e:
                                logging.error(f"[启动检测] 更新 IP UI 失败: {e}", exc_info=True)
                        
                        self.root.after(50, update_ip_ui)
                    else:
                        logging.warning("[启动检测] 没有找到合适的设备")
                else:
                    logging.warning("[启动检测] ip_combobox 不存在，无法更新IP")
            except Exception as e:
                logging.error(f"[启动检测] 处理设备失败: {e}", exc_info=True)
        else:
            self.update_status("启动时未检测到已连接的设备", True)

    def _save_pkg_to_history(self, pkg_name: str) -> None:
        """保存包名到历史记录（保持最近使用的10个包名）
        
        Args:
            pkg_name: 要保存的包名
        """
        if pkg_name and pkg_name.strip() and is_valid_package_name(pkg_name.strip()):
            pkg_name = pkg_name.strip()
            # 如果包名已存在，先移除旧位置
            if pkg_name in self.pkg_history:
                self.pkg_history.remove(pkg_name)
            # 将包名插入到最前面（最新使用）
            self.pkg_history.insert(0, pkg_name)
            # 只保留最近10个包名
            self.pkg_history = self.pkg_history[:Config.MAX_PKG_HISTORY]
            # 调度保存到文件（防抖）
            self._schedule_history_save()
            # 延迟更新下拉框，避免阻塞主线程
            if hasattr(self, 'pkg_combobox'):
                self._run_in_ui(lambda: self._safe_update_combobox('pkg', self.pkg_history))
    
    def _save_apk_to_history(self, apk_path: str) -> None:
        """保存 APK 路径到历史记录（增强版 - 同时更新下拉框）"""
        try:
            if not hasattr(self, 'apk_combobox'):
                return
                
            current_values = list(self.apk_combobox['values'])
            
            # 如果路径已存在，先移除
            if apk_path in current_values:
                current_values.remove(apk_path)
            
            # 添加到最前面
            current_values.insert(0, apk_path)
            
            # 限制历史记录数量（最多 20 条）
            if len(current_values) > 20:
                current_values = current_values[:20]
            
            # 延迟更新下拉框，避免阻塞主线程
            self._run_in_ui(lambda vals=tuple(current_values): self._safe_update_combobox('apk', vals))
        except Exception as e:
            import logging
            logging.error(f"保存 APK 历史失败: {e}")
                    
    def update_version_display(self, version: str = "") -> None:
        """更新版本展示框"""
        if hasattr(self, 'version_display'):
            # 如果是空字符串，则清空显示
            if not version:
                self.version_display.config(state='normal')
                self.version_display.delete(0, tk.END)
                self.version_display.insert(0, "")
                self.version_display.config(state='readonly')
            else:
                # 显示版本号
                self.version_display.config(state='normal')
                self.version_display.delete(0, tk.END)
                self.version_display.insert(0, version)
                self.version_display.config(state='readonly')
    
    def get_package_name_from_input(self) -> Optional[str]:
        """从输入框获取包名
        
        Returns:
            Optional[str]: 包名字符串，如果未输入则返回None
        """
        if hasattr(self, 'pkg_combobox'):
            return self.pkg_combobox.get().strip()
        elif hasattr(self, 'pkg_entry'):
            return self.pkg_entry.get().strip()
        return None

    def run_adb_with_target(self, command: str, retries: int = None, timeout: int = None) -> Tuple[str, bool]:
        """执行ADB命令（支持多设备）
        
        自动从IP输入框获取目标设备IP，并传递给底层命令执行函数
        
        Args:
            command: ADB命令字符串
            retries: 重试次数
            timeout: 超时时间
            
        Returns:
            Tuple[str, bool]: (输出结果, 是否成功)
        """
        target_ip = self.get_ip_address()
        return run_adb_command(command, retries=retries, timeout=timeout, target_device=target_ip)
    
    def on_ip_changed(self, event=None):
        """当 IP 地址改变时触发，刷新连接状态与设备显示

        注：下拉选择的自动连接由 LayoutModern._on_ip_selected 直接处理，
        此方法仅负责状态刷新（供设备同步等场景调用）。
        """
        self.update_connection_status()
        self.show_current_device_status(force_display=True)

    def update_connection_status(self, ip_address: Optional[str] = None, devices=None):
        """更新连接状态标签（支持 USB 设备）

        Args:
            ip_address: 目标设备 IP/序列号，None 表示取输入框当前值
            devices: 已知的设备列表；传 None 时自行查询（查询失败则保持显示不变）
        """
        if not hasattr(self, 'connection_status_label'):
            return

        if not ip_address:
            ip_address = self.get_ip_address()

        if devices is None:
            # 使用缓存版查询（2 秒缓存），避免每次都 spawn adb 进程
            # 查询失败返回 None —— 此时保持现有显示不变，避免把"查不到"显示成"未连接"
            devices = get_connected_devices_cached_safe()
            if devices is None:
                return

        # 【新增】更新设备数量标签
        if hasattr(self, 'device_count_label'):
            device_count = len(devices)
            # 文案要短：顶栏空间紧张（见 layout_v4 的 _build_topbar 注释）
            self.device_count_label.config(text=f"{device_count} 台")

        # ⚠️ 连接徽标的配色走主题系统（深/浅两套）——
        #    这里只设「状态」，具体颜色由布局层根据主题渲染，
        #    换肤时才能自动跟着变。
        if not devices:
            self._set_connection_badge("● 未连接", 'off')
            return

        # 如果没有输入 IP 地址，检查是否有 USB 设备
        if not ip_address or ip_address == "192.168.":
            # 查找 USB 设备（非 IP 格式的设备标识）
            usb_device = None
            for device in devices:
                # USB 设备序列号通常不包含冒号（端口号）或点号（IP 地址）
                if ':' not in device and '.' not in device:
                    usb_device = device
                    break

            if usb_device:
                self._set_connection_badge("✓ USB 设备", 'ok')
            else:
                self._set_connection_badge("● 未连接", 'off')
            return

        # 有 IP 地址时，检查是否匹配任何已连接设备
        is_connected = False
        for device in devices:
            if device == ip_address or device.startswith(ip_address + ':'):
                is_connected = True
                break

        if is_connected:
            self._set_connection_badge("✓ 已连接", 'ok')
        else:
            self._set_connection_badge("✗ 未连接", 'err')

    def _set_connection_badge(self, text: str, state: str) -> None:
        """设置连接状态徽标

        Args:
            text: 显示文案
            state: 状态标识（ok / err / warn / off），具体颜色由主题决定
        """
        label = getattr(self, 'connection_status_label', None)
        if label is None:
            return
        try:
            label.config(text=text)
            label._badge_state = state
        except Exception:
            return
        # 交给布局层按当前主题上色（v4 有主题感知，v3 保持原样）
        painter = getattr(self, '_paint_connection_badge', None)
        if callable(painter):
            try:
                painter(label)
            except Exception:
                pass

    def show_device_info(self):
        """显示当前连接的设备详细信息（异步优化版）"""
        # 【日志】记录按钮点击
        import logging
        logging.info("[按钮点击] show_device_info 开始执行")
        
        # 立即显示提示，不阻塞
        self.update_status("⏳ 正在获取设备列表...", True, "info")
        
        # 【日志】记录启动异步线程
        logging.info("[异步线程] 启动 _show_device_info_async")
        
        # 启动异步线程获取设备信息
        import threading
        thread = threading.Thread(target=self._show_device_info_async, daemon=True)
        thread.start()
        logging.info(f"[异步线程] 线程已启动，线程 ID: {thread.ident}")
    
    def _show_device_info_async(self):
        """异步获取并显示设备信息（优化版 - 使用快速检测）"""
        import logging
        start_time = time.time()  # 【修复】记录开始时间
        logging.info("[后台线程] _show_device_info_async 开始执行")
        
        try:
            # 【优化】使用快速检测，不进行深度验证（从 220ms 减少到 50ms）
            from utils import get_connected_devices_simple
            logging.info("[后台线程] 调用 get_connected_devices_simple()")
            devices = get_connected_devices_simple()
            current_ip = self.get_ip_address()
            elapsed = (time.time() - start_time) * 1000  # 【修复】计算实际耗时
            logging.info(f"[后台线程] 获取到 {len(devices)} 台设备，耗时：{elapsed:.2f}ms")
            
            if not devices:
                logging.info("[后台线程] 没有设备，准备更新 UI")
                self.update_status("当前没有连接的设备", False)
                return
            
            # 【新增】如果有设备但当前 IP 输入框为空或不完整，自动同步第一个设备
            if hasattr(self, 'ip_combobox') and devices:
                current_ip = self.get_ip_address()
                # 检查当前 IP 是否是有效的完整 IP 或 USB 序列号
                is_valid_current_ip = (
                    current_ip and  # 不是空值
                    current_ip != "192.168." and  # 不是默认占位符
                    (':' in current_ip or '.' in current_ip or len(current_ip) > 10)  # 是完整 IP 或序列号
                )
                
                # 如果当前 IP 无效，自动选择第一个设备
                if not is_valid_current_ip:
                    first_device = devices[0]
                    logging.info(f"[后台线程] 检测到无效 IP '{current_ip}'，准备同步设备：{first_device}")
                    self._run_in_ui(lambda: self._sync_device_to_ip_input(first_device))
                    current_ip = first_device  # 更新 current_ip 用于后续显示
            
            # 构建设备列表信息
            device_info = f"📱 已连接 {len(devices)} 台设备:\n"
            for i, device in enumerate(devices, 1):
                marker = ""
                if current_ip:
                    normalized_current_ip = current_ip
                    if ':' not in current_ip:
                        normalized_current_ip = f"{current_ip}:5555"
                        
                    if device == normalized_current_ip or device == current_ip:
                        marker = " ← 当前选中"
                    elif device.startswith(current_ip + ':'):
                        marker = " ← 当前选中"
                    
                device_info += f"  {i}. {device}{marker}\n"
            
            # 【优化】直接更新 UI，不使用 after
            logging.info("[后台线程] 直接显示设备列表（不使用 after）")
            self.update_status(device_info, True)
            
            # 【新增】自动更新连接状态标签
            self._run_in_ui(self.update_connection_status)
            
            # 【优化】移除详细设备信息获取（这个太耗时，用户需要时可以单独点击"获取设备信息"）
            # self.root.after(100, lambda: self._get_detailed_device_info())
            logging.info("[后台线程] 执行完成（不获取详细信息）")
        except Exception as e:
            logging.error(f"[后台线程] 异常：{str(e)}")
            self.update_status(f"获取设备信息失败：{str(e)}", False)
    
    def _sync_device_to_ip_input(self, device: str):
        """同步设备到 IP 输入框（优化版 - 统一IP格式，不重复记录端口）"""
        import logging
        logging.info(f"[同步操作] 开始同步设备到 IP 输入框：{device}")
        
        # 统一格式：如果是IP地址则去除端口号，USB设备序列号直接保存
        normalized_device = device
        if ':' in device and '.' in device:  # IP地址格式（包含冒号和点号）
            normalized_device = device.split(':')[0]  # 只保留IP部分
        
        if hasattr(self, 'ip_combobox'):
            # 将设备添加到下拉框历史记录（使用统一格式）
            if normalized_device not in self.ip_history:
                self.ip_history.insert(0, normalized_device)
                self.ip_history = self.ip_history[:Config.MAX_IP_HISTORY]
                # 调度保存（防抖）
                self._schedule_history_save()
                # 延迟更新，避免阻塞
                self._run_in_ui(lambda: self._safe_update_combobox('ip', self.ip_history))
                logging.info(f"[同步操作] 已更新下拉框历史记录：{self.ip_history}")
            
            # 设置当前选中的设备（使用统一格式）
            self.ip_combobox.delete(0, tk.END)
            self.ip_combobox.insert(0, normalized_device)
            logging.info(f"[同步操作] 已设置 IP 输入框值为：{normalized_device}")
            
            # 触发 IP 变更事件
            self.on_ip_changed()
            logging.info(f"[同步操作] 已触发 IP 变更事件")
    
    def get_device_info_fast(self):
        """快速获取设备信息（极速版 - 真正异步不阻塞）"""
        devices = get_connected_devices()
        current_ip = self.get_ip_address()
            
        if not devices:
            self.update_status("当前没有连接的设备", False)
            return
        
        # 立即显示设备列表（0 延迟）
        device_info = f"📱 已连接 {len(devices)} 台设备:\n"
        for i, device in enumerate(devices, 1):
            marker = ""
            if current_ip:
                normalized_current_ip = current_ip
                if ':' not in current_ip:
                    normalized_current_ip = f"{current_ip}:5555"
                    
                if device == normalized_current_ip or device == current_ip:
                    marker = " ← 当前选中"
                elif device.startswith(current_ip + ':'):
                    marker = " ← 当前选中"
                
            device_info += f"  {i}. {device}{marker}\n"
        
        self.update_status(device_info, True)
        
        # 使用后台线程异步获取详细设备信息（真正不阻塞）
        import threading
        thread = threading.Thread(target=self._get_device_info_fast_async, daemon=True)
        thread.start()
    
    def _get_device_info_fast_async(self):
        """异步获取设备详细信息（增强版 - 更多设备信息）"""
        try:
            current_ip = self.get_ip_address()
            if not current_ip:
                return
            
            # 显示正在获取的提示
            self._run_in_ui(lambda: self.update_status("⏳ 正在获取设备信息...", True, "info"))
            
            # 使用线程池并行获取（最大速度）
            import concurrent.futures
            import re
            
            def get_prop_quick(prop_name):
                """超快速获取单个属性（1.5 秒超时）"""
                try:
                    output, _ = self.run_adb_with_target(f"adb shell getprop {prop_name}")
                    return output.strip() if output else None
                except Exception:
                    return None

            # ⚠️ 一次 `adb shell getprop`（不带参数）拿全部属性，
            #    取代原来 19 条逐个 getprop（每条一个 adb 进程，~200ms → 4 秒）。
            _all_out, _ = self.run_adb_with_target("adb shell getprop")
            _props = parse_getprop_all(_all_out)

            def prop(name):
                """取属性值：优先用全量 getprop 的结果，取不到再单独查"""
                v = _props.get(name)
                if v is None:
                    v = get_prop_quick(name)
                return v
            
            # 核心信息（6 个，必获取）
            core_props = {
                "Android 版本": "ro.build.version.release",
                "SDK 版本": "ro.build.version.sdk",
                "设备型号": "ro.product.model",
                "品牌": "ro.product.brand",
                "安全补丁": "ro.build.version.security_patch",
                "CPU ABI": "ro.product.cpu.abi",
            }
            
            # 核心属性：从全量 getprop 结果取（取不到才单独查）
            core_results = {}
            for name, prop_name in core_props.items():
                value = prop(prop_name)
                if value:
                    core_results[name] = value

            # 额外信息（更详细的设备信息，同样走全量 getprop）
            extra_info = {}
            
            # 1. 设备串号（优化版 - 使用更快的命令）
            try:
                # 方式 1：尝试获取 IMEI（更快）
                output, _ = self.run_adb_with_target("adb shell service call iphonesubinfo 1")
                if output:
                    imei_match = re.search(r'[0-9]{15}', output.replace('.', '').replace("'", ''))
                    if imei_match:
                        extra_info["设备串号"] = imei_match.group()
                else:
                    # 方式 2：尝试获取序列号（备用）
                    output = prop("ro.serialno")
                    if output and output.strip():
                        extra_info["设备序列号"] = output.strip()
            except Exception:
                # 失败时尝试获取序列号
                try:
                    output = prop("ro.serialno")
                    if output and output.strip():
                        extra_info["设备序列号"] = output.strip()
                except Exception:
                    pass
            
            # 2. 软件版本号
            try:
                output = prop("ro.build.display.id")
                if output and output.strip():
                    extra_info["软件版本"] = output.strip()
            except Exception:
                pass
            
            # 3. 硬件平台
            try:
                output = prop("ro.hardware")
                if output and output.strip():
                    extra_info["硬件平台"] = output.strip()
            except Exception:
                pass
            
            # 4. 构建 ID
            try:
                output = prop("ro.build.id")
                if output and output.strip():
                    extra_info["构建 ID"] = output.strip()
            except Exception:
                pass
            
            # 5. 基带版本
            try:
                output = prop("gsm.version.baseband")
                if output and output.strip():
                    extra_info["基带版本"] = output.strip()
            except Exception:
                pass
            
            # 6. 内核版本（精简）
            try:
                output, _ = self.run_adb_with_target("adb shell uname -r")
                if output and output.strip():
                    extra_info["内核版本"] = output.strip()
            except Exception:
                pass
            
            # 7. 屏幕密度
            try:
                output = prop("ro.sf.lcd_density")
                if output and output.strip():
                    extra_info["屏幕密度"] = output.strip() + " dpi"
            except Exception:
                pass
            
            # 8. 电池电量
            try:
                # ⚠️ 不能写 `| grep level`：管道由本机 cmd 解析，用户环境没有 grep 会整条失败
                output, _ = self.run_adb_with_target("adb shell dumpsys battery")
                if output and "level" in output:
                    match = re.search(r'level:\s*(\d+)', output)
                    if match:
                        extra_info["电池电量"] = match.group(1) + "%"
            except Exception:
                pass
            
            # 9. 设备制造商
            try:
                output = prop("ro.product.manufacturer")
                if output and output.strip():
                    extra_info["制造商"] = output.strip()
            except Exception:
                pass
            
            # 10. 产品名称
            try:
                output = prop("ro.product.name")
                if output and output.strip():
                    extra_info["产品名称"] = output.strip()
            except Exception:
                pass
            
            # 11. 设备代号
            try:
                output = prop("ro.product.device")
                if output and output.strip():
                    extra_info["设备代号"] = output.strip()
            except Exception:
                pass
            
            # 12. 构建时间
            try:
                output = prop("ro.build.date.utc")
                if output and output.strip():
                    import datetime
                    timestamp = int(output.strip())
                    build_date = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    extra_info["构建时间"] = build_date
            except Exception:
                pass
            
            # 13. 系统版本
            try:
                output = prop("ro.build.version.incremental")
                if output and output.strip():
                    extra_info["系统版本号"] = output.strip()
            except Exception:
                pass
            
            # 14. 用户版本
            try:
                output = prop("ro.build.user")
                if output and output.strip():
                    extra_info["构建用户"] = output.strip()
            except Exception:
                pass
            
            # 15. 主机信息
            try:
                output = prop("ro.build.host")
                if output and output.strip():
                    extra_info["构建主机"] = output.strip()
            except Exception:
                pass
            
            # 16. 主板信息
            try:
                output = prop("ro.board.platform")
                if output and output.strip():
                    extra_info["主板平台"] = output.strip()
            except Exception:
                pass
            
            # 17. Bootloader 版本
            try:
                output = prop("ro.bootloader")
                if output and output.strip():
                    extra_info["Bootloader"] = output.strip()
            except Exception:
                pass
            
            # 18. 蓝牙版本
            try:
                output = prop("ro.bluetooth.version")
                if output and output.strip():
                    extra_info["蓝牙版本"] = output.strip()
            except Exception:
                pass
            
            # 19. WiFi 芯片版本
            try:
                output = prop("ro.wifi.version")
                if output and output.strip():
                    extra_info["WiFi 版本"] = output.strip()
            except Exception:
                pass
            
            # 20. 屏幕分辨率（如果支持）
            try:
                output, _ = self.run_adb_with_target("adb shell wm size")
                if output and "Physical size" in output:
                    match = re.search(r'Physical size: (\d+x\d+)', output)
                    if match:
                        extra_info["屏幕分辨率"] = match.group(1)
            except Exception:
                pass
            
            # 构建显示信息（分类显示）
            info_lines = []
            info_lines.append("\n" + "="*50)
            info_lines.append("📋 设备核心信息")
            info_lines.append("="*50)
            
            # 显示核心信息
            for name, value in core_results.items():
                info_lines.append(f"  {name}: {value}")
            
            # 显示额外信息（如果获取到了）
            if extra_info:
                info_lines.append("\n📋 扩展信息")
                for name, value in extra_info.items():
                    info_lines.append(f"  {name}: {value}")
            
            info_lines.append("="*50)
            
            # 在 UI 线程中显示
            detailed_info = "\n".join(info_lines)
            self._run_in_ui(lambda: self.update_status(detailed_info, True, "info"))
            
        except Exception as e:
            self._run_in_ui(lambda: self.update_status(f"获取设备信息失败：{str(e)}", False))
    
    def _get_detailed_device_info(self):
        """异步获取详细的设备信息（优化版 - 并行获取 + 精简数据）"""
        try:
            current_ip = self.get_ip_address()
            if not current_ip:
                return
            
            # 显示正在获取的提示
            self._run_in_ui(lambda: self.update_status("⏳ 正在快速获取设备信息...", True, "info"))
            
            # 使用线程池并行获取（提升速度）
            import concurrent.futures
            
            def get_prop(prop_name):
                """快速获取单个属性（带超时）"""
                try:
                    output, _ = self.run_adb_with_target(f"adb shell getprop {prop_name}")
                    return output.strip() if output else "未知"
                except Exception:
                    return "获取失败"
            
            # 关键信息优先（先显示这些）
            quick_info = {
                "Android 版本": "ro.build.version.release",
                "SDK 版本": "ro.build.version.sdk",
                "设备型号": "ro.product.model",
                "品牌": "ro.product.brand",
            }
            
            # 并行获取关键信息
            results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_to_name = {
                    executor.submit(get_prop, prop): name 
                    for name, prop in quick_info.items()
                }
                for future in concurrent.futures.as_completed(future_to_name):
                    name = future_to_name[future]
                    try:
                        results[name] = future.result(timeout=2)
                    except Exception:
                        results[name] = "超时"
            
            # 立即显示关键信息（快速响应）
            quick_lines = []
            quick_lines.append("\n" + "="*50)
            quick_lines.append("📱 设备关键信息 (快速获取)")
            quick_lines.append("="*50)
            for name, value in results.items():
                quick_lines.append(f"  {name}: {value}")
            
            quick_info_text = "\n".join(quick_lines)
            self._run_in_ui(lambda: self.update_status(quick_info_text, True, "info"))
            
            # 后台继续获取详细信息（可选）
            def get_full_info():
                info_lines = []
                
                # 安全补丁级别（重要）
                security_patch = get_prop("ro.build.version.security_patch")
                if security_patch != "获取失败":
                    info_lines.append(f"  安全补丁：{security_patch}")
                
                # 硬件信息（快速）
                cpu_abi = get_prop("ro.product.cpu.abi")
                hardware = get_prop("ro.hardware")
                if cpu_abi != "获取失败":
                    info_lines.append(f"  CPU ABI: {cpu_abi}")
                if hardware != "获取失败":
                    info_lines.append(f"  硬件平台：{hardware}")
                
                # 存储信息（较慢，选择性获取）
                try:
                    output, _ = self.run_adb_with_target("adb shell df /data | tail -1")
                    if output:
                        parts = output.split()
                        if len(parts) >= 4:
                            available = self._format_storage_size(parts[3])
                            info_lines.append(f"  可用存储：{available}")
                except Exception:
                    pass
                
                # 电池信息（可选）
                try:
                    # ⚠️ 不能写 `| grep level`：管道由本机 cmd 解析，用户环境没有 grep 会整条失败
                    output, _ = self.run_adb_with_target("adb shell dumpsys battery")
                    if output and "level" in output:
                        import re
                        match = re.search(r'level:\s*(\d+)', output)
                        if match:
                            info_lines.append(f"  电池电量：{match.group(1)}%")
                except Exception:
                    pass
                
                info_lines.append("="*50)
                detailed_info = "\n".join(info_lines)
                
                # 追加显示
                if info_lines:
                    self._run_in_ui(lambda info=detailed_info: self.update_status(f"\n📋 更多设备信息:\n{info}", True, "info"))
            
            # 异步获取完整信息（不阻塞）
            detail_thread = threading.Thread(target=get_full_info, daemon=True)
            detail_thread.start()
            
        except Exception as e:
            self._run_in_ui(lambda: self.update_status(f"获取设备信息失败：{str(e)}", False))
    
    def _format_storage_size(self, size_str: str) -> str:
        """格式化存储大小字符串"""
        try:
            size_kb = int(size_str)
            if size_kb >= 1024 * 1024:
                return f"{size_kb / (1024 * 1024):.1f} GB"
            elif size_kb >= 1024:
                return f"{size_kb / 1024:.1f} MB"
            else:
                return f"{size_kb} KB"
        except Exception:
            return size_str
    
    def show_current_device_status(self, force_display=False, decorator_call=False):
        """显示当前连接设备状态，用于在执行功能前显示设备信息
        
        Args:
            force_display: 是否强制显示，绕过冷却机制
            decorator_call: 是否来自装饰器调用，需要特殊处理
        """
        # 检查冷却时间，避免频繁重复显示
        import time
        current_time = time.time()
        # 获取当前IP地址用于比较
        current_ip = self.get_ip_address()
        
        # 对于强制显示的情况，检查IP是否发生变化，如果未变化且时间间隔很短则跳过
        if not force_display and (current_time - self.last_device_status_time) < self.device_status_cooldown:
            return
        
        # 如果是强制显示，根据不同情况进行处理
        if force_display:
            # 装饰器调用总是显示，不管IP是否变化
            if decorator_call:
                pass  # 不跳过
            # 检查是否为不完整的IP地址
            elif current_ip and (current_ip == "192.168." or not ('.' in current_ip and current_ip.count('.') >= 3)):
                # 不完整的IP地址总是显示
                pass  # 不跳过
            elif current_ip == self._last_displayed_ip and (current_time - self.last_device_status_time) < 0.05:
                # 完整IP且完全相同且时间间隔极短才跳过
                return
        
        # 强制刷新设备列表，确保获取最新状态
        # 用缓存版：查询失败时回退到上一次结果，不会误判为"没有设备"
        all_devices = get_connected_devices_cached()
        
        # 构造状态信息
        status_info = f"📱 设备状态: 已连接 {len(all_devices)} 台设备"
        
        # 标识当前控制的设备
        if current_ip:
            # 查找与当前IP精确匹配的设备
            current_device = None
            # 标准化当前IP（确保包含端口号）
            normalized_current_ip = current_ip
            if ':' not in current_ip:
                normalized_current_ip = f"{current_ip}:5555"
            
            # 精确匹配：优先完全匹配，其次前缀匹配
            for device in all_devices:
                # 完全匹配（包括端口号）
                if device == normalized_current_ip or device == current_ip:
                    current_device = device
                    break
                # IP前缀匹配（但要确保不是部分匹配）
                elif device.startswith(current_ip + ':'):
                    current_device = device
                    break
            
            if current_device:
                status_info += f", 当前控制: {current_device}"
            else:
                # 只有在IP格式有效时才显示未连接信息
                import re
                ip_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?::\d+)?$'
                if re.match(ip_pattern, current_ip) or current_ip.startswith('192.168.'):
                    status_info += f", 当前选中IP: {current_ip} (未连接)"
                else:
                    status_info += ", 未选择目标设备或IP格式无效"
        else:
            # 没有输入 IP 时，检查是否有 USB 设备
            usb_device = None
            for device in all_devices:
                if ':' not in device and '.' not in device:
                    usb_device = device
                    break
            
            if usb_device:
                status_info += f", 当前控制：{usb_device} (USB 设备)"
            else:
                status_info += ", 未选择目标设备"
        
        self.update_status(status_info, True)
        # 更新上次显示时间
        self.last_device_status_time = current_time
        # 保存当前显示的IP地址用于下次比较
        self._last_displayed_ip = current_ip if current_ip else ""



    def _setup_gui(self) -> None:
        """
        设置图形用户界面
            
        动态调用布局模块的 setup_gui 方法，配置状态文本框的
        标签样式，并设置默认日志路径。
        """
        # 动态调用布局模块的 setup_gui 方法
        self.layout_module.setup_gui(self)

        # ⚠️ 终端的 tag 颜色**由主题系统统一接管**（见 gui/theme.py 的 TAG_ROLE）。
        #    旧代码在这里硬编码 green/red/blue/orange，会把深色主题的配色覆盖掉，
        #    导致换肤后终端颜色对不上。这里改成向布局层要当前主题色。
        self._apply_terminal_tag_colors()

        # 立即设置默认值和拖拽功能（不延迟）
        self._setup_post_components()

        # 延迟加载非关键组件以提高启动速度（从 100ms 减少到 50ms）
        self.root.after(50, self._delayed_initialization)

    def _apply_terminal_tag_colors(self) -> None:
        """按当前主题给终端的 tag 上色

        v4 布局有主题管理器，直接用它；v3 布局没有则退回经典配色。
        """
        text = getattr(self, 'status_text', None)
        if text is None:
            return
        # ⚠️ 用 _ui_theme 而不是 layout_instance.theme：
        #    app._setup_gui() 调用布局后还会继续执行，
        #    那时 layout_instance 尚未赋值（setup_gui 内部才赋）。
        theme = getattr(self, '_ui_theme', None)
        if theme is not None:
            theme._paint(text, 'terminal', theme.tokens)
            return
        # 旧版布局的兜底配色
        text.tag_configure("success", foreground="green")
        text.tag_configure("error", foreground="red")
        text.tag_configure("info", foreground="blue")
        text.tag_configure("warning", foreground="orange")
    
    def _setup_post_components(self):
        """设置 GUI 组件创建完成后的操作"""
        # 设置默认值
        try:
            if hasattr(self, 'log_path_entry') and self.log_path_entry.winfo_exists():
                self.log_path_entry.delete(0, tk.END)
                self.log_path_entry.insert(0, self.default_log_path)
        except Exception:
            pass

        # ⚠️ 拖放注册依赖 apk_entry（在「应用管理」Tab 里），
        #    而 Tab 是懒加载的 —— 改由 _create_app_input_card 创建 apk_entry 后触发。
    
    def _extract_and_update_package_name(self, apk_path: str):
        """从 APK 文件中提取包名和版本号并更新到输入框（增强版）"""
        import logging
        try:
            logging.info(f"[_extract_and_update_package_name] 开始处理：{apk_path}")
            
            # 使用新函数提取包名和版本信息
            from utils import extract_package_name_from_apk
            package_name = extract_package_name_from_apk(apk_path)
            logging.info(f"[_extract_and_update_package_name] 提取结果：{package_name}")
            
            if package_name:
                # ✅ extract_package_name_from_apk 返回的是字符串，不是字典
                pkg_name = package_name
                version = ""  # aapt2/aapt 不直接返回版本号，需要另外获取
                logging.info(f"[_extract_and_update_package_name] 包名：{pkg_name}")
                
                # 更新包名输入框
                if hasattr(self, 'pkg_combobox'):
                    self.pkg_combobox.delete(0, tk.END)
                    self.pkg_combobox.insert(0, pkg_name)
                elif hasattr(self, 'pkg_entry'):
                    self.pkg_entry.delete(0, tk.END)
                    self.pkg_entry.insert(0, pkg_name)
                
                # 【新增】尝试从设备获取该包名的版本号（如果设备已连接）
                if self.check_device_connected():
                    try:
                        logging.info(f"[_extract_and_update_package_name] 设备已连接，尝试获取版本号")
                        output, success = self.run_adb_with_target(f"adb shell pm dump {pkg_name}")
                        if success:
                            from utils import extract_version_info
                            version = extract_version_info(output)
                            if version:
                                logging.info(f"[_extract_and_update_package_name] 获取到版本号：{version}")
                    except Exception as e:
                        logging.warning(f"[_extract_and_update_package_name] 获取版本号失败：{str(e)}")
                
                # 【新增】更新版本展示框（如果有版本号）
                if version:
                    logging.info(f"[_extract_and_update_package_name] 更新版本展示框：{version}")
                    self.update_version_display(version)
                
                # 在输出框显示包名信息
                file_name = os.path.basename(apk_path)
                if version:
                    self.update_status(f"✅ 自动识别到应用包名：{pkg_name} (版本：{version})\n📦 来源文件：{file_name}", True)
                else:
                    self.update_status(f"✅ 自动识别到应用包名：{pkg_name}\n📦 来源文件：{file_name}\n💡 点击'获取包名版本号'查看版本", True)
                
                # 保存包名到历史记录
                self._save_pkg_to_history(pkg_name)
            else:
                logging.warning(f"[_extract_and_update_package_name] 未找到包名信息")
                # 提取失败，不显示错误，让用户手动输入
                pass
        except Exception as error:
            logging.error(f"[_extract_and_update_package_name] 异常：{str(error)}")
            # 静默失败，不影响其他功能
            pass
    
    def _extract_and_update_package_name_async(self, apk_path: str):
        """异步提取包名和版本号（后台线程执行，不阻塞UI）"""
        import logging
        try:
            logging.info(f"[_extract_and_update_package_name_async] 开始后台处理：{apk_path}")
            
            # 一次性从 APK 本地解析 package/versionName/versionCode（不依赖设备连接，更快更稳）
            from utils import extract_apk_info
            info = extract_apk_info(apk_path)
            package_name = info.get('package')
            version_name = info.get('versionName') or ''
            logging.info(
                f"[_extract_and_update_package_name_async] 提取结果：pkg={package_name}, "
                f"versionName={version_name}, versionCode={info.get('versionCode')}"
            )
            
            if package_name:
                pkg_name = package_name
                version = version_name
                logging.info(f"[_extract_and_update_package_name_async] 包名：{pkg_name}")
                
                # 兜底：APK 内 versionName 为空且设备已连接时，再尝试从设备查询
                if not version:
                    try:
                        if self.check_device_connected():
                            logging.info(f"[_extract_and_update_package_name_async] APK 无 versionName，设备已连接，尝试 pm dump 获取")
                            output, success = self.run_adb_with_target(f"adb shell pm dump {pkg_name}")
                            if success:
                                from utils import extract_version_info
                                version = extract_version_info(output) or ''
                                if version:
                                    logging.info(f"[_extract_and_update_package_name_async] 获取到版本号：{version}")
                    except Exception as e:
                        logging.warning(f"[_extract_and_update_package_name_async] 获取版本号失败：{str(e)}")
                
                # 在主线程中更新UI
                self._run_in_ui(lambda: self._update_package_info_ui(pkg_name, version, apk_path))
            else:
                logging.warning(f"[_extract_and_update_package_name_async] 未找到包名信息")
        except Exception as error:
            logging.error(f"[_extract_and_update_package_name_async] 异常：{str(error)}")
    
    def _update_package_info_ui(self, pkg_name: str, version: str, apk_path: str):
        """在主线程中更新包名信息UI"""
        try:
            # 更新包名输入框
            if hasattr(self, 'pkg_combobox'):
                self.pkg_combobox.delete(0, tk.END)
                self.pkg_combobox.insert(0, pkg_name)
            elif hasattr(self, 'pkg_entry'):
                self.pkg_entry.delete(0, tk.END)
                self.pkg_entry.insert(0, pkg_name)
            
            # 更新版本展示框
            if version:
                self.update_version_display(version)
            
            # 在输出框显示包名信息
            file_name = os.path.basename(apk_path)
            if version:
                self.update_status(f"✅ 自动识别到应用包名：{pkg_name} (版本：{version})\n📦 来源文件：{file_name}", True)
            else:
                self.update_status(f"✅ 自动识别到应用包名：{pkg_name}\n📦 来源文件：{file_name}\n💡 点击'获取包名版本号'查看版本", True)
            
            # 保存包名到历史记录
            self._save_pkg_to_history(pkg_name)
        except Exception as e:
            import logging
            logging.error(f"[_update_package_info_ui] 更新UI失败：{str(e)}")

    # 状态更新方法
    def update_status(self, message: str, success: bool, msg_type: str = "normal") -> None:
        """
        更新状态文本框（极致优化版 - 零阻塞 + 行数限制）

        ⚠️ 线程安全：全项目有 100+ 处在后台线程里调用本方法，
        而 status_text 是 Tk 控件，只能在主线程操作。
        所以非主线程调用时自动转投 UI 队列，由主线程执行。

        Args:
            message: 要显示的消息
            success: 是否为成功状态
            msg_type: 消息类型 (normal/success/error/warning/info/system)
        """
        # 非主线程 -> 转投 UI 队列（主线程取出后重新调用本方法）
        if threading.current_thread() is not threading.main_thread():
            self._run_in_ui(lambda: self.update_status(message, success, msg_type))
            return

        # 🆕 限制日志行数，防止内存泄漏
        # 用增量计数：index('end-1c') 本身是 O(1)，但增量计数能顺带避免
        # 裁剪后的计数漂移，也让"是否超限"这个判断不依赖 Tk 调用。
        try:
            self._status_line_count += message.count('\n') + 2
            if self._status_line_count > 1200:
                # 只有超限才做一次裁剪 + 重新计数
                lines = int(self.status_text.index('end-1c').split('.')[0])
                if lines > 1000:
                    # 删除最早的 200 行，保留最近 800 行
                    self.status_text.delete(1.0, f"{lines - 800}.0")
                    self._status_line_count = 800
        except Exception:
            pass

        # 【日志】记录 UI 更新
        # ⚠️ 只有失败/警告才记 INFO：每次 UI 更新都写一次磁盘（RotatingFileHandler
        #    会 flush），高频输出时是明显的 IO 损耗。普通消息降到 DEBUG。
        if success or msg_type in ("error", "warning"):
            logging.info(f"[UI 更新] 类型:{msg_type}, 成功:{success}, 消息:{message[:50]}...")
        else:
            logging.debug(f"[UI 更新] 类型:{msg_type}, 成功:{success}, 消息:{message[:50]}...")
        
        # 生成带时间戳的格式化消息
        timestamp = time.strftime("[%H:%M:%S] ", time.localtime())
            
        # 根据消息类型选择标签和格式
        tag_map = {
            "system": "info",
            "warning": "warning",
            "info": "info",
            "success": "success",
            "error": "error"
        }
            
        if msg_type == "system":
            formatted_message = f"{timestamp}[系统] {message}"
        elif msg_type == "warning":
            formatted_message = f"{timestamp}[警告] {message}"
        elif msg_type == "info":
            formatted_message = f"{timestamp}[信息] {message}"
        elif success and msg_type == "success":
            formatted_message = f"{timestamp}[✓] {message}"
        elif not success and msg_type == "error":
            formatted_message = f"{timestamp}[✗] {message}"
        else:
            prefix = "[✓] " if success else "[✗] "
            formatted_message = f"{timestamp}{prefix}{message}"
            
        tag = tag_map.get(msg_type, "success" if success else "error")
            
        # 插入消息到状态文本框（不阻塞）
        self.status_text.insert(tk.END, f"\n{formatted_message}\n", tag)
        self.status_text.see(tk.END)
        # ✅ 移除 update_idletasks，让事件循环自然处理

    # 文件选择方法
    def browse_apk(self) -> None:
        """
        选择 APK 文件（增强版 - 异步提取包名和版本号，不阻塞UI）
            
        打开文件对话框让用户选择 APK 文件，并将文件路径
        填入到 APK 输入框中，然后异步提取包名和版本号。
        """
        import logging
        import threading
        
        file_path = filedialog.askopenfilename(filetypes=[("APK files", "*.apk")])
        if file_path:
            logging.info(f"[browse_apk] 选择了文件：{file_path}")
            self.apk_entry.delete(0, tk.END)
            self.apk_entry.insert(0, file_path)
            
            # 显示文件信息（立即显示）
            try:
                file_size = format_file_size(os.path.getsize(file_path))
                file_name = os.path.basename(file_path)
                self.update_status(f"📦 已选择APK文件: {file_name}\n📊 文件大小: {file_size}\n⏳ 正在提取包名信息...", True)
            except Exception:
                self.update_status(f"📦 已选择 APK 文件：{os.path.basename(file_path)}\n⏳ 正在提取包名信息...", True)
                
            # 🆕 优化：使用后台线程异步提取包名，不阻塞界面
            extract_thread = threading.Thread(
                target=lambda: self._extract_and_update_package_name_async(file_path),
                daemon=True
            )
            extract_thread.start()
            
            # 🆕 新增：保存 APK 路径到历史记录
            self._save_apk_to_history(file_path)

    def _on_log_path_changed(self, *args) -> None:
        """数据存储路径输入框内容变化时更新缓存。

        trace 回调在主线程触发，这里只做纯 Python 赋值；
        后台线程（历史记录加载、截图/录屏保存等）通过
        `utils.get_user_defined_log_path()` 读缓存，避免跨线程访问 Tk 控件。
        """
        try:
            self._user_log_path = self.log_path_entry.get().strip()
        except Exception:
            pass

    def choose_log_path(self) -> None:
        """
        选择数据存储路径
        
        打开目录选择对话框让用户选择数据存储目录，
        并更新路径输入框。
        """
        selected_path = filedialog.askdirectory(
            initialdir=self.log_path_entry.get(),
            title="选择日志存储路径"
        )

        # 仅当用户选择有效路径时更新输入框
        if selected_path:
            # 标准化路径（去除末尾斜杠）
            cleaned_path = os.path.normpath(selected_path)
            self.log_path_entry.delete(0, tk.END)
            self.log_path_entry.insert(0, cleaned_path + os.sep)  # 添加分隔符
            self._on_log_path_changed()  # 同步缓存给后台线程用

    @require_device_connected
    def kill_app_process(self):
        """强制停止应用进程"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入需要终止进程的应用包名", False)
            return

        def _work():
            try:
                output, success = self.run_adb_with_target(f"adb shell am force-stop {pkg_name}")
            except Exception:
                self._update_status_safe(f"未找到{pkg_name}所属进程:", False)
                return
            if success:
                # 保存包名到历史记录（会操作 Tk，必须回主线程）
                self._run_in_ui(lambda: self._save_pkg_to_history(pkg_name))
                self._update_status_safe(f"成功终止{pkg_name}应用所处进程", True)
            else:
                self._update_status_safe(f"终止{pkg_name}进程失败", False)

        self.run_in_background(_work)

    @require_device_connected
    def start_app(self):
        """启动当前包名应用"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入要启动的应用包名", False)
            return

        def _work():
            try:
                output, success = self.run_adb_with_target(
                    f"adb shell monkey -p {pkg_name} -c android.intent.category.LAUNCHER 1"
                )
            except Exception as e:
                self._update_status_safe(f"启动应用失败：{str(e)}", False)
                return
            if success:
                # 保存包名到历史记录（会操作 Tk，必须回主线程）
                self._run_in_ui(lambda: self._save_pkg_to_history(pkg_name))
                self._update_status_safe(f"成功启动{pkg_name}应用", True)
            else:
                self._update_status_safe(f"启动{pkg_name}应用失败", False)

        self.run_in_background(_work)


    def get_ip_address(self) -> Optional[str]:
        """
        获取 IP 地址或设备标识（支持 USB 设备）
            
        Returns:
            Optional[str]: IP 地址或设备序列号，如果未输入则返回 None
        """
        if hasattr(self, 'ip_combobox'):
            value = self.ip_combobox.get().strip()
            # 如果是完整的 IP 地址或设备序列号，则返回
            if value and value != "192.168.":
                return value
        return None

    # @require_device_connected
    def connect_adb(self):
        """连接 ADB 设备（异步优化版）"""
        # 【日志】记录按钮点击
        import logging
        logging.info("[按钮点击] connect_adb 开始执行")
        
        # 显示当前设备状态
        self.show_current_device_status()
            
        ip_address = self.get_ip_address()
        if not ip_address:
            self.update_status(f"请输入 IP 地址", False)
            self.update_connection_status()
            return False
            
        # 显示正在连接
        self.update_status(f"⏳ 正在连接 {ip_address}...", True, "info")
            
        # 【日志】记录启动异步线程
        logging.info(f"[异步线程] 启动 _connect_adb_async, IP: {ip_address}")
        
        # 启动异步线程执行连接
        import threading
        thread = threading.Thread(target=lambda: self._connect_adb_async(ip_address), daemon=True)
        thread.start()
        logging.info(f"[异步线程] 线程已启动，线程 ID: {thread.ident}")
        
    def _connect_adb_async(self, ip_address: str):
        """异步执行 ADB 连接"""
        import logging
        logging.info(f"[后台线程] _connect_adb_async 开始执行，IP: {ip_address}")
        
        try:
            logging.info(f"[ADB 命令] 执行 adb connect {ip_address}")
            output, success = self.run_adb_with_target(f"adb connect {ip_address}")
            logging.info(f"[ADB 命令] 执行完成，成功:{success}, 输出长度:{len(output)}")
                
            # 在 UI 线程中更新结果
            if "connected" in output.lower():
                logging.info("[后台线程] 连接成功，准备更新 UI")
                # 保存新的 IP 到历史记录（统一格式不带端口）
                # 统一格式：如果是IP地址则去除端口号，USB设备序列号直接保存
                normalized_ip = ip_address
                if ':' in ip_address and '.' in ip_address:  # IP地址格式（包含冒号和点号）
                    normalized_ip = ip_address.split(':')[0]  # 只保留IP部分
                
                if normalized_ip not in self.ip_history:
                    self.ip_history.insert(0, normalized_ip)
                    # 调度保存（防抖）
                    self._schedule_history_save()
                    # ✅ 直接更新，不使用 after
                    if hasattr(self, 'ip_combobox'):
                        logging.info("[后台线程] 更新 IP 下拉框")
                        self.ip_combobox['values'] = self.ip_history
                # ✅ 直接更新状态，不使用 after
                logging.info("[后台线程] 调用 update_status")
                self.update_status(output, True)
                logging.info("[后台线程] 调用 update_connection_status")
                self.update_connection_status(ip_address)
                logging.info("[后台线程] UI 更新完成")
            else:
                logging.info("[后台线程] 连接失败，准备更新 UI")
                self.update_status(output, False)
                self.update_connection_status(ip_address)
        except Exception as e:
            logging.error(f"[后台线程] 异常：{str(e)}")
            self.update_status(f"连接失败：{str(e)}", False)


    @require_device_connected
    def disconnect_adb(self):
        """断开 ADB 连接（异步优化版）"""
        # 强制显示当前设备状态
        self.show_current_device_status(force_display=True)
            
        # 显示正在断开
        self.update_status("⏳ 正在断开所有连接...", True, "info")
            
        # 启动异步线程执行断开
        import threading
        thread = threading.Thread(target=lambda: self._disconnect_adb_async(), daemon=True)
        thread.start()
        
    def _disconnect_adb_async(self):
        """异步执行 ADB 断开"""
        try:
            output, success = self.run_adb_with_target("adb disconnect")
                
            # 在 UI 线程中更新结果
            if "disconnected" in output.lower():
                self.update_status(output, True)
            else:
                self.update_status(output, False)
            self.update_connection_status()
        except Exception as e:
            self.update_status(f"断开失败：{str(e)}", False)
    
    def restart_adb_server(self):
        """重启 ADB 服务（异步优化版）"""
        # 【日志】记录按钮点击
        import logging
        logging.info("[按钮点击] restart_adb_server 开始执行")
        
        # 显示正在重启
        self.update_status("⏳ 正在重启 ADB 服务...", True, "info")
        
        # 启动异步线程执行重启
        import threading
        thread = threading.Thread(target=self._restart_adb_server_async, daemon=True)
        thread.start()
        logging.info(f"[异步线程] 线程已启动，线程 ID: {thread.ident}")
    
    def _restart_adb_server_async(self):
        """异步执行 ADB 服务重启"""
        import logging
        import time
        
        try:
            # 步骤 1: 停止 ADB 服务
            logging.info("[后台线程] 开始停止 ADB 服务...")
            self._run_in_ui(lambda: self.update_status("⏳ 正在停止 ADB 服务...", True, "info"))
            
            kill_output, kill_success = run_adb_command("adb kill-server")
            logging.info(f"[后台线程] adb kill-server 完成，成功:{kill_success}")
            
            if not kill_success:
                # kill-server 失败也继续执行 start-server
                logging.warning(f"[后台线程] adb kill-server 失败，继续执行 start-server: {kill_output}")
            
            # 等待一小段时间确保服务完全停止
            time.sleep(0.5)
            
            # 步骤 2: 启动 ADB 服务
            logging.info("[后台线程] 开始启动 ADB 服务...")
            self._run_in_ui(lambda: self.update_status("⏳ 正在启动 ADB 服务...", True, "info"))
            
            start_output, start_success = run_adb_command("adb start-server")
            logging.info(f"[后台线程] adb start-server 完成，成功:{start_success}")
            
            # 构建最终输出信息
            if start_success:
                # 重启成功
                final_message = "ADB 服务重启成功！\n\n"
                final_message += "建议操作：\n"
                final_message += "1. 重新连接设备\n"
                final_message += "2. 查看已连接设备列表\n"
                final_message += "3. 如仍无法连接，请检查 USB 连接或网络设置"
                
                self._run_in_ui(lambda: self.update_status(final_message, True))
                self._run_in_ui(self.update_connection_status)
                
                # 清空设备缓存，因为重启后所有连接都会断开
                cache_manager.device_cache.clear()
            else:
                # 启动失败
                error_message = f"ADB 服务重启失败\n\n停止服务：{kill_output if kill_output else '无输出'}\n"
                error_message += f"启动服务：{start_output if start_output else '无输出'}\n\n"
                error_message += "请检查：\n"
                error_message += "1. ADB 是否正确安装\n"
                error_message += "2. 是否有其他程序占用 ADB\n"
                error_message += "3. 以管理员身份运行本程序"
                
                self._run_in_ui(lambda msg=error_message: self.update_status(msg, False))
                
        except Exception as e:
            logging.error(f"[后台线程] 异常：{str(e)}")
            error_msg = f"重启 ADB 服务过程出错：{str(e)}\n\n请尝试：\n1. 关闭其他 ADB 相关程序\n2. 以管理员身份运行本程序"
            self._run_in_ui(lambda msg=error_msg: self.update_status(msg, False))

    def check_device_connected(self, ip_address: Optional[str] = None) -> bool:
        """检查设备连接状态（复用 2 秒缓存，与装饰器/设备监控共用同一数据源）"""
        if not ip_address:
            ip_address = self.get_ip_address()

        if not ip_address:
            return False

        # 复用缓存版设备列表，避免每次调用都 spawn adb 进程
        # 缓存版会自动排除 unauthorized/offline 状态，比原实现的字符串包含判断更准确
        devices = get_connected_devices_cached()
        ip_with_port = f"{ip_address}:5555" if ip_address else None

        is_connected = any(
            device == ip_address or device == ip_with_port or device.startswith(ip_address + ':')
            for device in devices
        )

        # 同步状态缓存
        cache_manager.set_device_status(ip_address, is_connected)
        return is_connected

    def _run_in_ui(self, func):
        """把 UI 操作调度到主线程执行（后台线程操作 Tk 控件的唯一入口）

        ⚠️ 不能直接用 root.after()：
        从后台线程调用 Tcl（after/insert/config…）在主线程正忙时不进事件循环时
        会抛 "main thread is not in main loop"，而且会阻塞后台线程。
        所以改成：后台线程只把 callable 塞进队列，主线程的定时器负责取出执行。
        """
        try:
            self._ui_queue.put_nowait(func)
        except Exception:
            pass
        self._schedule_ui_pump()

    def _schedule_ui_pump(self):
        """安排主线程的 UI 队列泵（只调度一次）"""
        if getattr(self, '_ui_pump_scheduled', False):
            return
        self._ui_pump_scheduled = True
        try:
            self.root.after(20, self._pump_ui_queue)
        except Exception:
            self._ui_pump_scheduled = False

    def _pump_ui_queue(self):
        """主线程：从队列取出 UI 操作批量执行"""
        self._ui_pump_scheduled = False
        try:
            while True:
                func = self._ui_queue.get_nowait()
                try:
                    func()
                except Exception:
                    logging.exception("[UI 队列] 执行失败")
        except queue.Empty:
            pass
        # 期间又来了新任务则继续排程
        try:
            if not self._ui_queue.empty():
                self._schedule_ui_pump()
        except Exception:
            pass

    def _update_status_safe(self, message, success: bool):
        """跨线程安全的状态栏更新（后台线程调用）"""
        self._run_in_ui(lambda: self.update_status(message, success))

    def run_in_background(self, task, *args, **kwargs) -> threading.Thread:
        """在后台线程执行耗时任务，避免阻塞 UI

        ⚠️ 约定：
        - 任务内部**不要**直接操作 Tk 控件或调用 self.update_status()；
          统一用 self._update_status_safe() / self._run_in_ui()。
        - 需要在主线程做的事（如读输入框、弹确认框）要在调用本方法**之前**做完。

        Args:
            task: 要执行的函数
            *args, **kwargs: 传给 task 的参数

        Returns:
            threading.Thread: 已启动的线程
        """
        def worker():
            try:
                task(*args, **kwargs)
            except Exception as e:
                logging.exception("[后台任务] 执行异常")
                self._update_status_safe(f"操作失败：{e}", False)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def _show_progress(self):
        """显示进度条动画（线程安全）"""
        def _do():
            try:
                self.progress.pack(fill=tk.X, pady=5)
                self.progress.start(12)
            except Exception:
                pass
        self._run_in_ui(_do)

    def _hide_progress(self):
        """隐藏进度条（线程安全）"""
        def _do():
            try:
                self.progress.stop()
                self.progress.pack_forget()
            except Exception:
                pass
        self._run_in_ui(_do)

    def _set_progress_mode(self, mode: str):
        """设置进度条模式（线程安全）"""
        def _do():
            try:
                if mode == "determinate":
                    # 从 indeterminate 切过来前先停掉动画，否则 ttk 会打架
                    self.progress.stop()
                self.progress["mode"] = mode
                self.progress["maximum"] = 100
            except Exception:
                pass
        self._run_in_ui(_do)

    def _set_progress_value(self, value: int):
        """设置进度条数值（线程安全）"""
        def _do():
            try:
                self.progress["value"] = value
            except Exception:
                pass
        self._run_in_ui(_do)

    @staticmethod
    def _kill_process(process):
        """强制结束子进程（不阻塞调用线程）"""
        try:
            if process is None or process.poll() is not None:
                return
            process.terminate()
            try:
                process.wait(timeout=3)
            except Exception:
                process.kill()
        except Exception:
            pass

    @require_device_connected
    def force_install(self):
        """带进度显示的强制安装"""
        apk_path = self.apk_entry.get()
        if not apk_path:
            self.update_status("请选择APK文件", False)
            return

        if not os.path.isfile(apk_path):
            self.update_status(f"APK 文件不存在: {apk_path}", False)
            return

        # 显示进度条
        self._show_progress()
        self.update_status("开始安装应用...", True)

        # 启动安装线程
        install_thread = threading.Thread(
            target=self._run_install_with_progress,
            args=(apk_path,),
            daemon=True
        )
        install_thread.start()

    def _run_install_with_progress(self, apk_path):
        """执行安装（主路径 push + pm install，失败回退 adb install）"""
        target_ip = self.get_ip_address()

        try:
            apk_size = os.path.getsize(apk_path)
        except OSError as e:
            self._update_install_status(f"读取 APK 失败: {e}")
            self._hide_progress()
            return

        self._update_install_status(
            f"[调试] 开始安装，APK 路径：{apk_path}, 目标设备：{target_ip}"
        )
        self._update_install_status(
            f"[调试] APK 大小：{format_file_size(apk_size)}"
        )

        # 安装期间暂停设备可达性验证：
        # 设备正忙着收大包时，adb shell 验证必然超时，反而会把设备踢出设备列表
        set_device_validation_paused(True)
        try:
            ok, message = self._install_with_retry(apk_path, apk_size, target_ip)
        finally:
            set_device_validation_paused(False)

        self._set_progress_mode("indeterminate")
        self._hide_progress()

        if ok:
            file_size = format_file_size(apk_size)
            apk_name = os.path.basename(apk_path)
            self._update_install_status(message)
            self._update_status_safe(
                f"安装完成\n文件: {apk_name}\n大小: {file_size}\n"
                f"目标设备: {target_ip if target_ip else '未知'}",
                True
            )
        else:
            self._update_install_status(message)
            self._update_status_safe(f"安装失败\n{message}", False)

    def _install_with_retry(self, apk_path, apk_size, target_ip):
        """安装主流程：优先 push + pm install（真实进度），失败回退 adb install

        ⚠️ 关键：某些定制 ROM（TCL 的 com.tcl.guard 等）上，`adb install`
        会**实际安装成功**（设备端输出 "install apk has been enabled from pm
        by user!" + "Success"），但 adb 客户端仍以退出码 1 结束
        （"Get install_switch_flag: 1"）。只看 returncode 会把成功误报成失败。
        所以两条路径结束后都要用设备端事实校验一遍。
        """
        # 提前取包名（安装后要靠它校验）
        package_name = None
        try:
            package_name = extract_package_name_from_apk(apk_path)
        except Exception:
            package_name = None

        last_message = ""
        for attempt in range(1, Config.INSTALL_RETRIES + 1):
            if attempt > 1:
                self._update_install_status(
                    f"第 {attempt}/{Config.INSTALL_RETRIES} 次尝试（间隔 2 秒）..."
                )
                time.sleep(2)

            ok, message = self._install_via_push_pm(apk_path, apk_size, target_ip)
            if ok:
                return True, message
            last_message = message

            # push 方式失败（网络抖动 / 设备拒绝等）→ 换 adb install 再试一次
            self._update_install_status(
                f"push 方式未成功（{message}），回退到 adb install ..."
            )
            ok, message = self._install_via_adb_install(apk_path, apk_size, target_ip)
            if ok:
                return True, message
            last_message = message

            # ⚠️ 命令都"失败"了，但设备端可能其实装成功了（定制 ROM 的坑）
            #    用设备端事实校验：设备上的 versionCode 是否已更新
            self._update_install_status(
                "命令返回失败，正在核对设备上的实际安装状态..."
            )
            verified, verify_msg = verify_install_result(
                apk_path, package_name, target_ip
            )
            if verified:
                self._update_install_status(
                    f"核对结果：{verify_msg}（命令返回码不可信，以设备实际状态为准）"
                )
                return True, f"安装成功（{verify_msg}；命令返回码异常但实际已安装）"
            last_message = f"{last_message}\n核对设备状态：{verify_msg}"

        return False, last_message

    def _check_remote_file_readable(self, remote_path: str, target_ip: str = None) -> Tuple[bool, str]:
        """检查设备端文件是否能被 shell 读取（用于 push 安装路径的前置校验）

        某些定制 ROM 装了安全管控软件（如 TCL 的 com.tcl.guard），
        会禁止 shell 用户读取 /data/local/tmp 下的文件 —— 此时
        `adb push` 仍然显示成功，但 `pm install` 会报
        "Error: Unable to open file"，白白浪费一次完整传输。

        Args:
            remote_path: 设备端文件路径
            target_ip: 目标设备

        Returns:
            Tuple[bool, str]: (是否可读, 说明文字)
        """
        from utils import build_adb_command_with_device

        cmd = build_adb_command_with_device(
            f'adb shell "head -c 4 {remote_path} > /dev/null && echo READABLE"',
            target_ip
        )
        try:
            result = subprocess.run(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                timeout=15
            )
        except subprocess.TimeoutExpired:
            return False, "读取检查超时"
        except Exception as e:
            return False, f"读取检查失败: {e}"

        output = (result.stdout or "").strip()
        if "READABLE" in output:
            return True, "可读"

        # 提取最有信息量的一行（Permission denied / No such file 等）
        detail = ""
        for line in output.splitlines():
            line = line.strip()
            if line and line != "READABLE":
                detail = line
                break
        return False, detail or "设备拒绝读取"

    def _install_via_push_pm(self, apk_path: str, apk_size: int, target_ip: str = None) -> Tuple[bool, str]:
        """主安装路径：adb push 到设备临时目录 + pm install 安装。

        相比 `adb install` 的优势：
          1. `adb push` 会输出真实百分比进度（写在 stderr，实时到达），可以展示；
          2. 手动指定临时文件名，绕过 adb install 内部生成设备端路径的 bug；
          3. 能把「传输」与「设备端安装」分成两个阶段分别提示，不再全程黑箱。
        """
        from utils import build_adb_command_with_device

        remote_tmp = Config.INSTALL_REMOTE_TMP
        push_cmd = build_adb_command_with_device(
            f'adb push "{apk_path}" {remote_tmp}', target_ip
        )

        self._update_install_status(
            f"正在传输 APK 到设备（{format_file_size(apk_size)}）..."
        )
        self._set_progress_mode("determinate")
        self._set_progress_value(0)

        push_lines = []
        percent = 0
        size_text = ""
        try:
            process = subprocess.Popen(
                push_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace'
            )
        except Exception as e:
            self._set_progress_mode("indeterminate")
            self._hide_progress()
            return False, f"启动传输进程失败: {e}"

        deadline = time.time() + Config.INSTALL_TIMEOUT
        try:
            while True:
                if time.time() > deadline:
                    self._kill_process(process)
                    return False, f"传输超时（超过 {Config.INSTALL_TIMEOUT} 秒）"

                output = process.stdout.readline()
                if output == '':
                    if process.poll() is not None:
                        break
                    # 管道已关闭但进程还没退出，短暂等待后继续
                    time.sleep(0.05)
                    continue

                stripped = output.strip()
                if not stripped:
                    continue
                push_lines.append(stripped)

                # adb push 进度格式: "[ 45%] /data/local/tmp/x.apk: 45%"
                match = _PUSH_PERCENT_RE.search(stripped)
                if match:
                    percent = int(match.group(1))
                    self._set_progress_value(min(95, percent))
                    size_match = _PUSH_SIZE_RE.search(stripped)
                    if size_match:
                        size_text = f"{size_match.group(1)} / {size_match.group(2)}"
                    self._update_install_status(
                        f"正在传输... {percent}%"
                        + (f"（{size_text}）" if size_text else "")
                    )
                elif "file pushed" in stripped:
                    self._set_progress_value(95)
            process.wait(timeout=30)
        except Exception as e:
            self._kill_process(process)
            return False, f"传输异常: {e}"

        push_out = "\n".join(push_lines)
        if process.returncode != 0 and "1 file pushed" not in push_out:
            detail = push_out[-300:] if push_out else "无输出"
            return False, f"传输失败: {detail}"

        # ⚠️ 可读性预检：部分定制 ROM（TCL 的 com.tcl.guard 等）会拦截 shell
        #    对 /data/local/tmp 的读取 —— push 显示"成功"但设备端 pm 打不开文件
        #    （"Error: Unable to open file" / "Permission denied"）。
        #    与其白跑一次 pm install 再失败，不如现在就识别出来直接走 adb install。
        readable, read_detail = self._check_remote_file_readable(remote_tmp, target_ip)
        if not readable:
            self._update_install_status(
                f"设备禁止 shell 读取 {remote_tmp}（{read_detail}），改用 adb install"
            )
            return False, f"设备端文件不可读: {read_detail}"

        # 传输完成 → 设备端安装（要解包 + dexopt，耗时较长且没有进度输出）
        self._set_progress_value(96)
        self._update_install_status(
            "传输完成，正在设备端安装（需要解包与优化，可能耗时 30~90 秒）..."
        )

        pm_out, pm_ok = self._run_pm_install(remote_tmp, target_ip)

        # 清理设备端临时文件（无论成败）
        try:
            self._run_adb_capture(
                build_adb_command_with_device(f"adb shell rm -f {remote_tmp}", target_ip),
                timeout=30
            )
        except Exception:
            pass

        if pm_ok and "Success" in pm_out:
            self._set_progress_value(100)
            return True, "安装成功（push + pm install）"
        detail = pm_out.strip() if pm_out else "无输出"
        return False, f"pm install 失败: {detail[-300:]}"

    def _run_pm_install(self, remote_tmp: str, target_ip: str = None) -> Tuple[str, bool]:
        """在设备端执行 pm install（合并 stdout/stderr，保留 Failure 原因）"""
        from utils import build_adb_command_with_device
        pm_cmd = build_adb_command_with_device(
            f"adb shell pm install -r -d {remote_tmp}", target_ip
        )
        try:
            result = subprocess.run(
                pm_cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                timeout=Config.INSTALL_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return "pm install 超时", False
        except Exception as e:
            return str(e), False

        output = result.stdout or ""
        return output, (result.returncode == 0 and "Success" in output)

    def _run_adb_capture(self, cmd: str, timeout: int = 30) -> str:
        """执行一条 adb 命令并返回合并后的输出"""
        result = subprocess.run(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
            timeout=timeout
        )
        return result.stdout or ""

    def _install_via_adb_install(self, apk_path: str, apk_size: int, target_ip: str = None) -> Tuple[bool, str]:
        """回退安装路径：直接 `adb install`（部分设备上比 push+pm 更可靠）。

        注意：adb install 不输出百分比，所以这里用固定间隔的心跳提示兜底，
        避免长时间"看起来卡住不动"。
        """
        from utils import build_adb_command_with_device

        install_cmd = build_adb_command_with_device(
            f'adb install -r -d "{apk_path}"', target_ip
        )
        self._update_install_status(f"[调试] 安装命令：{install_cmd}")
        self._update_install_status(
            "正在通过 adb install 安装（该方式无进度显示，请稍候）..."
        )
        self._set_progress_mode("determinate")
        self._set_progress_value(5)

        lines = []
        saw_device_success = False   # 设备端是否打印了 Success
        started_at = time.time()
        last_tick = started_at
        try:
            process = subprocess.Popen(
                install_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace'
            )
        except Exception as e:
            self._set_progress_mode("indeterminate")
            self._hide_progress()
            return False, f"启动安装进程失败: {e}"

        deadline = started_at + Config.INSTALL_TIMEOUT
        try:
            while True:
                if time.time() > deadline:
                    self._kill_process(process)
                    return False, f"安装超时（超过 {Config.INSTALL_TIMEOUT} 秒）"

                output = process.stdout.readline()
                if output == '':
                    if process.poll() is not None:
                        break
                    time.sleep(0.05)
                    continue

                stripped = output.strip()
                if not stripped:
                    continue
                lines.append(stripped)

                if "Performing Streamed Install" in stripped:
                    self._update_install_status("安装开始，正在传输数据...")
                elif stripped == "Success" or stripped.endswith(" Success"):
                    # ⚠️ 设备端明确打了 Success —— 这才是真实的成功信号。
                    #    某些定制 ROM（TCL com.tcl.guard 等）会让 adb 客户端
                    #    在安装成功后仍以退出码 1 结束（"Get install_switch_flag: 1"），
                    #    此时只看 returncode 会把成功误报成失败。
                    saw_device_success = True
                    self._update_install_status("设备端已确认安装成功")
                    self._set_progress_value(100)
                elif "Failure" in stripped:
                    self._update_install_status(f"安装失败: {stripped}")
                elif "install_switch_flag" in stripped:
                    self._update_install_status(
                        "设备的安全开关拦截了 ADB 安装（install_switch_flag）"
                    )
                else:
                    self._update_install_status(stripped)

                # 心跳：长时间没有新输出时提示还在跑，避免看起来像卡死
                now = time.time()
                if now - last_tick >= Config.INSTALL_HEARTBEAT:
                    last_tick = now
                    self._update_install_status(
                        f"仍在安装中... 已用 {int(now - started_at)} 秒"
                    )
            process.wait(timeout=30)
        except Exception as e:
            self._kill_process(process)
            return False, f"安装异常: {e}"

        self._set_progress_mode("indeterminate")
        self._hide_progress()

        if process.returncode == 0:
            self._set_progress_value(100)
            return True, "安装成功（adb install）"

        # ⚠️ 返回码非 0，但设备端打了 Success —— 定制 ROM 的已知行为：
        #    安装实际成功，只是 adb 客户端的退出码不可信。
        #    先按成功上报，最终由 _install_with_retry 用设备端版本号复核。
        if saw_device_success:
            detail = "\n".join(lines[-5:]) if lines else "无输出"
            self._set_progress_value(100)
            return True, (
                f"安装成功（adb install，设备端已确认）\n"
                f"注：adb 退出码为 {process.returncode}，属设备安全开关误报\n{detail}"
            )

        detail = "\n".join(lines[-5:]) if lines else "无输出"
        return False, f"安装失败 (code {process.returncode})\n{detail}"

    def _update_operation_status(self, operation: str, status: str, details: str = "", msg_type: str = "info"):
        """更新操作状态显示（统一格式 - 零阻塞优化）

        ⚠️ 线程安全：可能在后台线程被调用，非主线程时转投 UI 队列。

        Args:
            operation: 操作名称（如“日志捕获”、“屏幕录制”）
            status: 状态（如“开始”、“进行中”、“完成”、“失败”）
            details: 详细信息
            msg_type: 消息类型
        """
        # 非主线程 -> 转投 UI 队列
        if threading.current_thread() is not threading.main_thread():
            self._run_in_ui(
                lambda: self._update_operation_status(operation, status, details, msg_type))
            return
        timestamp = time.strftime("[%H:%M:%S] ", time.localtime())
            
        # 构造统一格式的消息
        if details:
            message = f"{timestamp}[{operation}] {status} - {details}"
        else:
            message = f"{timestamp}[{operation}] {status}"
            
        # 根据状态选择颜色
        if "失败" in status or "错误" in status:
            tag = "error"
        elif "警告" in status:
            tag = "warning"
        elif "完成" in status or "成功" in status:
            tag = "success"
        else:
            tag = msg_type
            
        self.status_text.insert(tk.END, f"\n{message}\n", tag)
        self.status_text.see(tk.END)
        # ✅ 移除 update_idletasks，避免阻塞
    
    def _update_install_status(self, message):
        """更新安装状态（线程安全：自动切回主线程执行）"""
        def _do():
            if "成功" in message:
                self.status_text.insert(tk.END, f"\n{message}\n", "success")
            elif "失败" in message or "错误" in message:
                self.status_text.insert(tk.END, f"\n{message}\n", "error")
            else:
                # 一般进度信息使用info标签
                self.status_text.insert(tk.END, f"\n{message}\n", "info")
            self.status_text.see(tk.END)

        # 安装在后台线程里跑，Tk 控件必须在主线程操作
        self._run_in_ui(_do)

    @require_device_connected
    def uninstall(self):
        """卸载应用(带确认对话框)"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        # 显示确认对话框
        result = messagebox.askyesno(
            "确认卸载",
            f"您确定要卸载应用吗？\n\n包名: {pkg_name}\n\n注意：卸载后应用数据将被永久删除。",
            icon="warning"
        )
        
        if result:
            def _work():
                output, success = self.run_adb_with_target(f"adb uninstall {pkg_name}")
                if success:
                    # 清除包信息缓存
                    cache_manager.package_cache.delete(f"package_{pkg_name}")
                    # 保存包名到历史记录（会操作 Tk，必须回主线程）
                    self._run_in_ui(lambda: self._save_pkg_to_history(pkg_name))
                self._update_status_safe(output, success)

            self.run_in_background(_work)
        else:
            self.update_status("已取消卸载操作", True)

    @require_device_connected
    def package_list(self):
        """获取已安装应用包名列表及其版本(优化版，使用动态线程池)"""
        # 目标设备必须在主线程取（读 Tk 控件），后台线程不能再碰
        target_ip = self.get_ip_address()

        def _work():
            try:
                # 获取所有已安装包名
                output, success = self.run_adb_with_target("adb shell pm list packages")
                if not success:
                    self._update_status_safe("获取应用列表失败", False)
                    return

                # 清理并获取包名列表
                packages = [line.replace("package:", "").strip()
                           for line in output.splitlines() if line.strip()]

                if not packages:
                    self._update_status_safe("未找到已安装的应用", False)
                    return

                self._update_status_safe(f"正在获取 {len(packages)} 个应用的版本信息...", True)

                # ⚠️ 一条 `dumpsys package packages` 拿全部版本号，
                #    取代逐包 `dumpsys package <pkg>`（每包 3 条 adb 命令，
                #    其中还包括一次完全多余的 `adb devices`）。
                #    300 个包：90 秒 → 0.5 秒。
                versions = get_all_package_versions(target_ip)

                if versions:
                    lines = []
                    for package in packages:
                        version_str = versions.get(package, "未知")
                        lines.append(f"{package} (版本: {version_str})")
                    # 一次性插入，避免几百次 Tk 重绘
                    self._run_in_ui(lambda: self.status_text.insert(
                        tk.END, "\n" + "\n".join(lines), "info"))
                    self._run_in_ui(lambda: self.status_text.see(tk.END))
                else:
                    # 兜底：全量命令失败时退回逐个查（慢但能用）
                    self._update_status_safe(
                        "批量获取版本失败，改用逐个查询（较慢）...", True, "info")
                    max_workers = calculate_optimal_workers(len(packages))
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_to_package = {
                            executor.submit(self.get_package_version, package, target_ip): package
                            for package in packages
                        }
                        for future in concurrent.futures.as_completed(future_to_package):
                            package = future_to_package[future]
                            try:
                                version = future.result()
                                version_str = version if version else "未知"
                                self._run_in_ui(lambda p=package, v=version_str: self.status_text.insert(
                                    tk.END, f"\n{p} (版本: {v})", "info"))
                            except Exception as e:
                                self._run_in_ui(lambda p=package, err=str(e): self.status_text.insert(
                                    tk.END, f"\n{p} (版本: 获取失败 - {err})", "error"))
                        self._run_in_ui(lambda: self.status_text.see(tk.END))

                self._update_status_safe(f"\n获取应用列表完成，共 {len(packages)} 个应用", True)

            except Exception as e:
                self._update_status_safe(f"获取应用列表时出错: {str(e)}", False)

        self.run_in_background(_work)

    def get_package_version(self, package_name: str, target_ip: Optional[str] = None) -> Optional[str]:
        """获取应用版本号(优化版，优先获取最新版本)

        ⚠️ target_ip 必须由调用方在主线程取好后传入：
        本方法会在线程池里跑，不能直接读 Tk 控件（get_ip_address）。
        """
        # 检查缓存
        cached_info = cache_manager.get_package_info(package_name)
        if cached_info and 'version' in cached_info:
            return cached_info['version']

        # 使用新的精确版本获取方法，传递目标设备
        version = get_accurate_package_version(package_name, target_device=target_ip)

        if version:
            # 更新缓存
            package_info = {'version': version, 'name': package_name}
            cache_manager.set_package_info(package_name, package_info)
            return version
        return None

    @require_device_connected
    def clear_cache(self):
        """清除应用缓存(带确认对话框)"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        # 显示确认对话框
        result = messagebox.askyesno(
            "确认清理缓存",
            f"您确定要清理应用缓存吗？\n\n包名: {pkg_name}\n\n注意：清理后应用需要重新加载数据。",
            icon="question"
        )
        
        if result:
            def _work():
                output, success = self.run_adb_with_target(f"adb shell pm clear {pkg_name}")
                if success:
                    # 清除包信息缓存
                    cache_manager.package_cache.delete(f"package_{pkg_name}")
                    # 保存包名到历史记录（会操作 Tk，必须回主线程）
                    self._run_in_ui(lambda: self._save_pkg_to_history(pkg_name))
                self._update_status_safe(output, success)

            self.run_in_background(_work)
        else:
            self.update_status("已取消清理缓存操作", True)

    @require_device_connected
    def root_device(self):
        """获取root权限"""
        # ⚠️ 获取 root 会重启 adbd、改变设备安全状态，属于不可逆操作，
        #    必须二次确认（之前是单击即执行）。
        if not messagebox.askyesno(
            "确认获取 Root 权限",
            "获取 Root 权限会重启设备的 adb 服务，可能导致：\n\n"
            "• 当前 ADB 连接断开，需要重新连接\n"
            "• 部分应用可能检测到 root 状态而拒绝运行\n\n"
            "确定要继续吗？",
            icon="warning"
        ):
            self.update_status("已取消获取 Root 权限", True)
            return

        def _work():
            output, success = self.run_adb_with_target("adb root")
            self._update_status_safe(output, success)

        self.run_in_background(_work)

    @require_device_connected
    def pull_anr_file(self):
        """拉取ANR文件"""
        def _work():
            # 获取用户自定义的日志存储路径（读的是线程安全快照）
            from utils import get_user_defined_log_path
            user_log_path = get_user_defined_log_path(self)
            # 在用户路径下创建anr_files子目录
            anr_dir = ensure_directory(os.path.join(user_log_path, "anr_files"))
            output, success = self.run_adb_with_target(f"adb pull /data/anr \"{anr_dir}\"")
            self._update_status_safe(f"ANR文件已保存至: {anr_dir}", success)

        self.run_in_background(_work)

    @require_device_connected
    def remount(self):
        """重新挂载分区"""
        # ⚠️ remount 会把 /system 挂成可写，属于会削弱系统安全性的操作，
        #    必须二次确认（之前是单击即执行）。
        if not messagebox.askyesno(
            "确认重新挂载分区",
            "重新挂载分区会把系统分区切换为可写状态，\n"
            "可能削弱设备的安全保护。\n\n"
            "确定要继续吗？",
            icon="warning"
        ):
            self.update_status("已取消重新挂载", True)
            return

        def _work():
            output, success = self.run_adb_with_target("adb remount")
            self._update_status_safe(output, success)

        self.run_in_background(_work)

    @require_device_connected
    def get_version(self):
        """获取应用版本"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        def _work():
            output, success = self.run_adb_with_target(f"adb shell pm dump {pkg_name}")
            if not success:
                # 清空版本显示
                self._run_in_ui(lambda: self.update_version_display())
                self._update_status_safe(output, False)
                return

            version = extract_version_info(output)
            if version:
                # 保存包名到历史记录（会操作 Tk，必须回主线程）
                self._run_in_ui(lambda: self._save_pkg_to_history(pkg_name))
                # 【新增】同步更新版本展示框
                self._run_in_ui(lambda: self.update_version_display(version))
                self._update_status_safe(f"当前应用{pkg_name}版本：{version}", True)
            else:
                # 清空版本显示
                self._run_in_ui(lambda: self.update_version_display())
                self._update_status_safe("版本信息解析失败", False)

        self.run_in_background(_work)

    @require_device_connected
    def reboot(self):
        """重启设备(带确认对话框)"""
        # 显示确认对话框
        result = messagebox.askyesno(
            "确认重启",
            "您确定要重启设备吗？\n\n注意：重启后将断开ADB连接，需要重新连接。",
            icon="warning"
        )

        if result:
            def _work():
                output, success = self.run_adb_with_target("adb reboot")
                if success:
                    # 清空设备缓存，因为重启后连接状态会发生变化
                    cache_manager.device_cache.clear()
                    self._update_status_safe("设备重启中...", True)
                else:
                    self._update_status_safe(output, False)

            self.run_in_background(_work)
        else:
            self.update_status("已取消重启操作", True)

    @require_device_connected
    def get_android_version(self):
        """获取Android版本(使用缓存)"""
        # 检查系统信息缓存
        cached_version = cache_manager.get_system_info("android_version")
        if cached_version:
            self.update_status(f"Android版本: {cached_version}", True)
            return

        def _work():
            output, success = self.run_adb_with_target("adb shell getprop ro.build.version.release")
            if success:
                version = output.strip()
                cache_manager.set_system_info("android_version", version)
                self._update_status_safe(f"Android 版本：{version}", True)
            else:
                self._update_status_safe(output, False)

        self.run_in_background(_work)

    @require_device_connected
    def send_text_input(self):
        """发送文本输入到设备

        ⚠️ `adb shell input text` **只支持 ASCII**（字母/数字/常用符号）。
        中文必须靠设备上安装的 ADBKeyBoard 之类第三方输入法（走广播通道），
        `input text` 根本不经过输入法，切换输入法也没用 —— 所以这里给出明确说明，
        不做无效尝试。
        """
        if not hasattr(self, 'text_input_entry'):
            self.update_status("文本输入组件未初始化", False)
            return

        text_to_send = self.text_input_entry.get().strip()
        if not text_to_send:
            self.update_status("请输入要发送的文本内容", False)
            return

        # 含非 ASCII（中文/全角符号等）-> 明确说明限制与可行方案
        if not text_to_send.isascii():
            self.update_status(
                "⚠ adb shell input text 不支持中文\n\n"
                f"检测到非 ASCII 字符：{text_to_send[:30]}\n\n"
                "可行方案：\n"
                "1) 在设备上安装 ADBKeyBoard 等支持 ADB 广播的输入法\n"
                "2) 然后用这条命令发送：\n"
                f'   adb shell am broadcast -a ADB_INPUT_TEXT --es msg "{text_to_send}"\n'
                "3) 或者直接输入英文/数字/符号（本工具可自动发送）",
                True
            )
            return

        self.update_status(f"正在输入：{text_to_send}...", True, "info")

        def _work():
            try:
                # ⚠️ 先看前台有没有焦点窗口 —— 没有焦点时 input text 会静默失败
                focus_out, focus_ok = self.run_adb_with_target(
                    "adb shell dumpsys activity activities")
                if focus_ok and focus_out:
                    focus_lines = filter_lines(
                        focus_out, 'mResumedActivity', 'mFocusedApp')
                    if not focus_lines:
                        self._update_status_safe(
                            "⚠ 没有检测到前台应用，请先打开应用并点击输入框再试", False)
                        return

                output, success = self.run_adb_with_target(
                    f'adb shell input text "{text_to_send}"')

                if success and not output.strip():
                    self._update_status_safe(f"✓ 输入成功：{text_to_send}", True)
                else:
                    self._update_status_safe(f"结果：{output}", False)
            except Exception as e:
                self._update_status_safe(f"出错：{str(e)}", False)

        self.run_in_background(_work)
    
    @require_device_connected
    def screencap(self):
        """屏幕截图(优化版 - 异步执行，不阻塞UI)"""
        try:
            # 🆕 优化：立即显示提示信息，不阻塞 UI
            self.update_status("⏳ 正在截图，请稍候...", True, "info")
            
            # 🆕 优化：使用后台线程执行截图，不阻塞界面
            import threading
            screenshot_thread = threading.Thread(
                target=self._do_screenshot_async,
                daemon=True
            )
            screenshot_thread.start()
            
        except Exception as e:
            self.update_status(f"截图过程出错: {str(e)}", False)
    
    def _do_screenshot_async(self):
        """异步执行截图（后台线程）"""
        try:
            # 先清理可能存在的旧截图
            self.run_adb_with_target("adb shell rm -f /sdcard/screenshot.png")
            
            # 获取用户自定义的日志存储路径
            from utils import get_user_defined_log_path
            user_log_path = get_user_defined_log_path(self)
            # 在用户路径下创建screenshots子目录
            save_dir = ensure_directory(os.path.join(user_log_path, "screenshots"))
            new_file = get_next_filename(os.path.join(save_dir, "截图"), ".png")
            
            # 最多尝试指定次数截图
            max_retries = Config.MAX_INSTALL_RETRIES
            success = False
            error_msg = ""
            
            for attempt in range(max_retries):
                # 截图到设备
                output1, success1 = self.run_adb_with_target("adb shell screencap -p /sdcard/screenshot.png")
                if not success1:
                    error_msg = output1
                    time.sleep(1)  # 等待1秒后重试
                    continue
                
                # 验证文件是否生成
                output2, success2 = self.run_adb_with_target("adb shell ls -l /sdcard/screenshot.png")
                if not success2 or "No such file" in output2:
                    error_msg = "截图文件未生成"
                    time.sleep(1)  # 等待1秒后重试
                    continue
                
                # 拉取文件到电脑
                output3, success3 = self.run_adb_with_target(f"adb pull /sdcard/screenshot.png {new_file}")
                if not success3:
                    error_msg = output3
                    time.sleep(1)  # 等待1秒后重试
                    continue
                
                # 验证本地文件
                if os.path.exists(new_file):
                    file_size = os.path.getsize(new_file)
                    if file_size > 0:
                        success = True
                        break
                    else:
                        error_msg = "生成的截图文件为空"
                else:
                    error_msg = "本地文件保存失败"
                time.sleep(1)  # 等待1秒后重试
            
            # 清理设备上的临时文件
            self.run_adb_with_target("adb shell rm -f /sdcard/screenshot.png")
            
            # 在主线程中更新 UI
            if success:
                file_size = format_file_size(os.path.getsize(new_file))
                self._run_in_ui(lambda: self.update_status(f"✅ 截图已保存至路径：{new_file}\n📊 文件大小：{file_size}", True))
            else:
                self._run_in_ui(lambda: self.update_status(f"❌ 截图失败: {error_msg}", False))
                
        except Exception as e:
            self._run_in_ui(lambda: self.update_status(f"❌ 截图过程出错: {str(e)}", False))

    @require_device_connected
    def get_serial_number(self):
        """获取设备序列号(优化版，多策略获取)"""
        from utils import get_device_serial_number
        
        # 检查系统信息缓存
        cached_serial = cache_manager.get_system_info("serial_number")
        if cached_serial:
            self.update_status(f"设备序列号: {cached_serial}  \n-注：已优化获取策略，自动适配连接方式。", True)
            return
            
        # 使用多策略获取设备标识
        serial = get_device_serial_number()
        if serial:
            cache_manager.set_system_info("serial_number", serial)
            
            # 根据结果类型提供不同的提示信息（优先硬件串号）
            if ':' in serial and serial.count('.') == 3:
                # IP地址格式，说明是网络连接标识（备用方案）
                info_msg = f"设备标识: {serial} (网络连接)\n-注：已优化获取策略，优先硬件串号。"
            elif len(serial) == 16 and all(c in '0123456789abcdefABCDEF' for c in serial):
                # 16位十六进制，可能是Android ID（备用方案）
                info_msg = f"设备标识: {serial} (Android ID)\n-注：已优化获取策略，优先硬件串号。"
            else:
                # 硬件序列号或其他格式（首选）
                info_msg = f"设备序列号: {serial}\n-注：已优化获取策略，优先硬件串号。"
            
            self.update_status(info_msg, True)
        else:
            self.update_status("无法获取设备序列号，请检查设备连接和权限。", False)

    # 屏幕录制相关方法
    @require_device_connected
    def start_recording(self):
        """开始屏幕录制（优化版 - 异步测试命令，不阻塞UI）"""
        if self.recording_active:
            self.update_status("屏幕录制已在进行中", False)
            return

        # 再次检查设备连接状态
        if not self.check_device_connected():
            self.update_status("设备未连接，无法开始录制", False)
            return
            
        # 🆕 优化：立即显示提示信息
        self.update_status("⏳ 正在启动屏幕录制...", True, "info")
        
        # 🆕 优化：使用后台线程执行测试和启动，不阻塞界面
        import threading
        recording_thread = threading.Thread(
            target=self._start_recording_async,
            daemon=True
        )
        recording_thread.start()
    
    def _start_recording_async(self):
        """异步启动屏幕录制（后台线程）"""
        try:
            # 测试screenrecord命令是否可用
            test_output, test_success = self.run_adb_with_target("adb shell screenrecord --help")
            if not test_success:
                self._run_in_ui(lambda: self.update_status(f"❌ ADB screenrecord命令不可用: {test_output}", False))
                return

            # 获取用户输入的日志路径（与日志使用相同路径）
            user_log_path = self.log_path_entry.get().strip()
            if not user_log_path:
                user_log_path = self.default_log_path
                self._run_in_ui(lambda: self.log_path_entry.delete(0, tk.END))
                self._run_in_ui(lambda path=user_log_path: self.log_path_entry.insert(0, path))

            # 确保路径存在并测试写入权限
            try:
                os.makedirs(user_log_path, exist_ok=True)
                test_file = os.path.join(user_log_path, "test_write.tmp")
                with open(test_file, 'w', encoding='utf-8') as tf:
                    tf.write("test")
                os.remove(test_file)
            except PermissionError:
                self._run_in_ui(lambda: self.update_status("无权限写入该目录，请以管理员身份运行程序或选择其他目录", False))
                return
            except Exception as e:
                self._run_in_ui(lambda err=str(e): self.update_status(f"创建录制目录失败: {err}", False))
                return

            # 设置录制文件路径（使用简单的临时名称，避免前缀问题）
            recording_file_name = f"temp_rec_{timestamp_time()}.mp4"
            self.recording_file_path = os.path.join(user_log_path, recording_file_name)
            
            # 设置状态
            self.recording_active = True
            
            # 显示启动信息
            self._run_in_ui(lambda: self.update_status(f"✅ 正在开始屏幕录制...\n📁 目标文件: {self.recording_file_path}", True))

            # 启动录制线程
            try:
                self.recording_thread = threading.Thread(
                    target=self._run_recording,
                    name="RecordingThread",
                    daemon=True
                )
                self.recording_thread.start()
                    
                # 使用 root.after 延迟检查，避免阻塞主线程
                self.root.after(1000, self._check_recording_thread_status)
                    
            except Exception as e:
                self._run_in_ui(lambda err=str(e): self.update_status(f"启动录制线程时出错：{err}", False))
                self.recording_active = False
        except Exception as e:
            self._run_in_ui(lambda err=str(e): self.update_status(f"启动录制失败：{err}", False))
        
    def _check_recording_thread_status(self):
        """检查录制线程状态（异步回调）"""
        try:
            if hasattr(self, 'recording_thread') and self.recording_thread.is_alive() and self.recording_active:
                self._update_operation_status("屏幕录制", "运行中", "点击'停止录制'结束录制", "success")
            else:
                self._update_operation_status("屏幕录制", "启动失败", "", "error")
                self.recording_active = False
        except Exception:
            pass

    @require_device_connected  
    def stop_recording(self):
        """停止屏幕录制（彻底优化版 - 完全异步）"""
        if not self.recording_active:
            self._run_in_ui(lambda: self.update_status("没有正在进行的录制", False))
            return
    
        # 显示停止提示
        self._run_in_ui(lambda: self.update_status("正在停止屏幕录制...", True, "info"))
        self.recording_active = False
    
        # 终止 screenrecord 进程
        if self.recording_subprocess and self.recording_subprocess.poll() is None:
            try:
                self.recording_subprocess.terminate()
            except Exception:
                pass
            
        # 将耗时的等待和文件处理移到后台线程
        cleanup_thread = threading.Thread(
            target=self._cleanup_recording_async,
            name="RecordingCleanupThread",
            daemon=True
        )
        cleanup_thread.start()
            
        # 关键优化：立即返回，不再执行任何同步代码！
        return
        
    def _cleanup_recording_async(self):
        """异步清理录屏文件（后台线程执行）"""
        try:
            # 等待录制线程结束（在后台进行，不阻塞 UI）
            if hasattr(self, 'recording_thread') and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=15)  # 给足够时间让录制完成
                
            # 重置状态
            self._run_in_ui(lambda: setattr(self, 'recording_active', False))
            self._run_in_ui(lambda: setattr(self, 'recording_subprocess', None))
                
            # 通知用户完成
            self._run_in_ui(lambda: self.update_status("录制停止操作完成", True, "success"))
                
        except Exception as e:
            self._run_in_ui(lambda: self.update_status(f"清理录制文件出错：{str(e)}", False))

    def open_storage_folder(self):
        """打开日志截屏录屏存储文件夹"""
        try:
            # 获取用户定义的日志路径
            from utils import get_user_defined_log_path
            user_log_path = get_user_defined_log_path(self)
            
            # 检查路径是否存在
            if not os.path.exists(user_log_path):
                self.update_status(f"存储文件夹不存在：{user_log_path}\n请先执行截图、日志或录屏操作以创建文件夹", False)
                return
            
            # 打开文件夹
            os.startfile(user_log_path)
            self.update_status(f"已打开存储文件夹：{user_log_path}", True)
        except Exception as e:
            self.update_status(f"打开文件夹失败：{str(e)}", False)

    def _run_recording(self):
        """实际执行屏幕录制（参考日志抓取的逻辑）"""
        try:
            # 再次验证设备连接状态
            if not self.check_device_connected():
                self.update_status("设备连接已断开，无法开始录制", False)
                self.recording_active = False
                return

            # 使用screenrecord命令录制屏幕到设备上的临时文件
            device_temp_file = "/sdcard/temp_recording.mp4"
            
            # 先清理可能存在的旧文件
            self.run_adb_with_target(f"adb shell rm -f {device_temp_file}")
            
            self.update_status("开始录制屏幕，保存中...", True)

            # Windows 系统添加 CREATE_NO_WINDOW 标志
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

            # 启动screenrecord进程（使用较低的分辨率和码率以保证兼容性）
            from utils import build_adb_command_with_device
            target_ip = self.get_ip_address()
            record_cmd = build_adb_command_with_device(f"adb shell screenrecord --bit-rate 4000000  {device_temp_file}", target_ip)
            
            # 分割命令为参数列表
            cmd_parts = record_cmd.split()
            
            self.recording_subprocess = subprocess.Popen(
                cmd_parts,
                stderr=subprocess.PIPE,
                creationflags=creation_flags,
                text=True, encoding='utf-8', errors='replace'
            )
            
            time.sleep(0.5)  # 等待一小段时间确保进程启动
            
            # 验证进程是否成功启动
            if self.recording_subprocess and self.recording_subprocess.poll() is not None:
                _, error_output = self.recording_subprocess.communicate()
                self.update_status(f"录制进程启动失败: {error_output}", False)
                self.recording_active = False
                return
            
            self.update_status("录制进程启动成功，正在录制...", True)
            
            # 等待直到用户停止或进程异常退出
            while self.recording_active and self.recording_subprocess and self.recording_subprocess.poll() is None:
                time.sleep(1)
                
                # 定期检查设备连接状态（每30秒）
                if not self.check_device_connected():
                    self.update_status("设备连接断开，停止录制", False)
                    self.recording_active = False
                    break
            
            # 终止进程（如果还在运行）
            if self.recording_subprocess and self.recording_subprocess.poll() is None:
                self.recording_subprocess.terminate()
                self.recording_subprocess.wait(timeout=5)
            
            # 等待一段时间确保设备文件写入完成
            time.sleep(1)
            
            self.update_status("录制进程已停止，正在从设备下载文件...", True)
            
            # 检查设备文件是否存在
            check_output, check_success = self.run_adb_with_target(f"adb shell ls -la {device_temp_file}")
            if not check_success or "No such file" in check_output:
                self.update_status(f"设备上的录制文件不存在: {device_temp_file}", False)
                return
            
            # 从设备上下载录制文件
            pull_output, pull_success = self.run_adb_with_target(f'adb pull "{device_temp_file}" "{self.recording_file_path}"')
            
            if pull_success:
                # 清理设备上的临时文件
                self.run_adb_with_target(f"adb shell rm -f {device_temp_file}")
                
                # 验证文件确实下载成功
                if os.path.exists(self.recording_file_path):
                    self.update_status("录制文件下载成功，正在重命名...", True)
                    
                    # 立即重命名文件（使用停止时的时间戳）
                    original_path = os.path.dirname(self.recording_file_path)
                    stop_timestamp = timestamp_time()  # 获取停止时的时间戳
                    
                    # 检查文件大小决定命名
                    file_size = os.path.getsize(self.recording_file_path)
                    if file_size == 0:
                        new_name = os.path.join(original_path, f"{stop_timestamp}_empty_video.mp4")
                    else:
                        new_name = os.path.join(original_path, f"{stop_timestamp}_video.mp4")
                    
                    # 重试重命名机制
                    max_retries = 3
                    success_rename = False
                    
                    for attempt in range(max_retries):
                        try:
                            os.rename(self.recording_file_path, new_name)
                            success_rename = True
                            
                            # 更新成功信息
                            save_path = os.path.abspath(new_name)
                            file_size_str = format_file_size(file_size) if file_size > 0 else "空文件"
                            if file_size == 0:
                                self.update_status(f"录制已完成\n空录制文件已保存到: {save_path}\n文件大小: {file_size_str}", False)
                            else:
                                self.update_status(f"录制已完成\n录制文件已保存到: {save_path}\n文件大小: {file_size_str}", True)
                            
                            # 移除自动打开文件夹功能，改为手动点击按钮
                            break
                            
                        except Exception as e:
                            if attempt < max_retries - 1:
                                time.sleep(1)  # 等待1秒后重试
                                continue
                            else:
                                # 重命名失败，但文件已下载
                                file_size_str = format_file_size(file_size) if file_size > 0 else "空文件"
                                self.update_status(f"录制文件下载成功但重命名失败\n原文件位置: {self.recording_file_path}\n文件大小: {file_size_str}\n错误: {str(e)}", False)
                    
                    if not success_rename:
                        # 如果重命名失败，至少文件已经下载了
                        self.update_status(f"文件已下载到: {self.recording_file_path}\n请手动重命名为: {os.path.basename(new_name)}", False)
                        
                else:
                    self.update_status(f"下载失败：本地文件不存在 {self.recording_file_path}", False)
            else:
                self.update_status(f"下载录制文件失败: {pull_output}", False)
                
        except Exception as e:
            self.update_status(f"录制过程出错: {str(e)}", False)
        finally:
            # 确保进程正确终止
            if self.recording_subprocess and self.recording_subprocess.poll() is None:
                try:
                    self.recording_subprocess.terminate()
                    self.recording_subprocess.wait(timeout=3)
                except Exception:
                    pass

    # 日志相关方法
    @require_device_connected
    def start_logcat(self):
        """启动日志捕获（优化版 - 异步测试命令，不阻塞UI）"""
        if self.logging_active:
            self.update_status("日志捕获已在运行", False)
            return

        # 再次检查设备连接状态
        if not self.check_device_connected():
            self.update_status("设备未连接，无法启动日志捕获", False)
            return
            
        # 🆕 优化：立即显示提示信息
        self.update_status("⏳ 正在启动日志捕获...", True, "info")
        
        # 🆕 优化：使用后台线程执行测试和启动，不阻塞界面
        import threading
        logcat_thread = threading.Thread(
            target=self._start_logcat_async,
            daemon=True
        )
        logcat_thread.start()
    
    def _start_logcat_async(self):
        """异步启动日志捕获（后台线程）"""
        try:
            # 测试ADB logcat命令是否可用
            test_output, test_success = self.run_adb_with_target("adb logcat -d -t 1")
            if not test_success:
                self._run_in_ui(lambda: self.update_status(f"❌ ADB logcat命令不可用: {test_output}", False))
                return

            # 获取用户输入的日志路径
            user_log_path = self.log_path_entry.get().strip()
            if not user_log_path:
                # 使用默认路径
                user_log_path = self.default_log_path
                self._run_in_ui(lambda: self.log_path_entry.delete(0, tk.END))
                self._run_in_ui(lambda path=user_log_path: self.log_path_entry.insert(0, path))

            # 确保路径存在并测试写入权限
            try:
                os.makedirs(user_log_path, exist_ok=True)
                # 测试写入权限
                test_file = os.path.join(user_log_path, "test_write.tmp")
                with open(test_file, 'w', encoding='utf-8') as tf:
                    tf.write("test")
                os.remove(test_file)
            except PermissionError:
                self._run_in_ui(lambda: self.update_status("无权限写入该目录，请以管理员身份运行程序或选择其他目录", False))
                return
            except Exception as e:
                self._run_in_ui(lambda err=str(e): self.update_status(f"创建日志目录失败: {err}", False))
                return

            # 设置日志文件路径
            log_file_name = f"{timestamp_time()}.log"
            self.log_file_path = os.path.join(user_log_path, log_file_name)
            
            # 检查文件是否已存在（避免覆盖）
            counter = 1
            original_path = self.log_file_path
            while os.path.exists(self.log_file_path):
                base_name = os.path.splitext(original_path)[0]
                self.log_file_path = f"{base_name}_{counter}.log"
                counter += 1
                if counter > 100:  # 防止无限循环
                    self._run_in_ui(lambda: self.update_status("无法创建唯一文件名", False))
                    return
            
            # 设置状态和事件
            self.logging_active = True
            self.stop_event.clear()
            
            # 显示启动信息
            self._run_in_ui(lambda: self._update_operation_status("日志捕获", "开始", f"目标文件: {self.log_file_path}"))

            # 启动日志捕获线程
            try:
                self.logcat_thread = threading.Thread(
                    target=self._run_logcat,
                    name="LogcatThread",
                    daemon=True
                )
                self.logcat_thread.start()
                    
                # 使用 root.after 延迟检查，避免阻塞主线程
                self.root.after(1000, self._check_logcat_thread_status)
                    
            except Exception as e:
                self._run_in_ui(lambda err=str(e): self.update_status(f"启动日志捕获线程失败：{err}", False))
                self.logging_active = False
        except Exception as e:
            self._run_in_ui(lambda err=str(e): self.update_status(f"启动日志捕获失败：{err}", False))
        
    def _check_logcat_thread_status(self):
        """检查日志捕获线程状态（异步回调）"""
        try:
            if hasattr(self, 'logcat_thread') and self.logcat_thread.is_alive() and self.logging_active:
                self._update_operation_status("日志捕获", "运行中", "点击'停止日志捕获'结束捕获", "success")
            else:
                self._update_operation_status("日志捕获", "启动失败", "", "error")
                self.logging_active = False
        except Exception:
            pass

    @require_device_connected
    def stop_logcat(self):
        """停止日志捕获（极致优化版 - 异步处理）"""
        if not self.logging_active:
            self.update_status("没有正在运行的日志捕获", False)
            return
    
        # 设置停止信号
        self.stop_event.set()
        self._update_operation_status("日志捕获", "正在停止", "")
            
        # 确保进程终止
        self._terminate_logcat()
            
        # 将耗时的文件处理移到后台线程
        cleanup_thread = threading.Thread(
            target=self._cleanup_logcat_async,
            name="LogcatCleanupThread",
            daemon=True
        )
        cleanup_thread.start()
        # 关键优化：立即返回，不再执行任何同步代码！
        return
        
        # ========== 以下代码已移至_cleanup_logcat_async，永远不会执行 ==========
        # 检查文件大小（已废弃）
            
        # 检查文件大小
        file_size = os.path.getsize(self.log_file_path)
        if file_size == 0:
            self.update_status("警告：日志文件为空，可能原因：\n1. 设备无日志输出\n2. ADB连接不稳定\n3. 权限不足\n4. 捕获时间过短", False)
        else:
            file_size_str = format_file_size(file_size)
            self.update_status(f"日志捕获成功，文件大小: {file_size_str}", True)

        # 生成新的文件名（使用停止时的时间戳）
        original_path = os.path.dirname(self.log_file_path)
        stop_timestamp = timestamp_time()  # 获取停止时的时间戳
        if file_size == 0:
            # 为空文件添加特殊标记
            new_name = os.path.join(original_path, f"{stop_timestamp}_empty.log")
        else:
            new_name = os.path.join(original_path, f"{stop_timestamp}.log")

        # 重试机制（最多5次，增加重试次数）
        max_retries = 5
        success_save = False
        last_error = ""
        
        for attempt in range(max_retries):
            try:
                # 在重命名前再次检查文件是否被其他进程占用
                # 尝试以独占模式打开文件测试是否被占用
                try:
                    with open(self.log_file_path, 'r+b') as test_file:
                        pass  # 如果能打开说明没有被占用
                except IOError:
                    # 文件被占用，等待更长时间
                    self.update_status(f"文件仍被占用，等待释放... (尝试 {attempt + 1}/{max_retries})", True)
                    time.sleep(2)
                    continue
                
                # 尝试重命名文件
                os.rename(self.log_file_path, new_name)
                success_save = True
                
                # 构建提示信息
                save_path = os.path.abspath(new_name)
                if file_size == 0:
                    self.update_status(f"日志捕获已停止\n空日志文件已保存到：{save_path}\n建议检查设备连接和权限设置", False)
                else:
                    self.update_status(f"日志捕获已停止\n日志文件已保存到：{save_path}", True)
                break
                
            except PermissionError as e:
                last_error = f"权限错误: {str(e)}"
                if attempt < max_retries - 1:
                    self.update_status(f"文件被占用，等待释放... (尝试 {attempt + 1}/{max_retries})", True)
                    time.sleep(2)  # 增加等待时间
                    continue
            except Exception as e:
                last_error = f"重命名失败: {str(e)}"
                self.update_status(f"保存日志文件失败: {str(e)}", False)
                break

        # 清理进程引用
        self.logcat_subprocess = None
        
    def _read_log_tail(self, chars: int = 400) -> str:
        """读取日志文件末尾若干字符（用于展示 logcat 启动失败的原因）"""
        try:
            if self.log_file_path and os.path.exists(self.log_file_path):
                with open(self.log_file_path, 'rb') as fh:
                    try:
                        fh.seek(-chars, os.SEEK_END)
                    except OSError:
                        fh.seek(0)
                    return fh.read().decode('utf-8', errors='replace').strip()
        except Exception:
            pass
        return "未知错误"

    def _cleanup_logcat_async(self):
        """异步清理日志文件（后台线程执行）"""
        try:
            # 等待线程结束（在后台进行，不阻塞 UI）
            if hasattr(self, 'logcat_thread') and self.logcat_thread.is_alive():
                self.logcat_thread.join(timeout=3)
                
            # 短暂等待确保文件句柄释放
            time.sleep(0.5)
                
            # 检查文件是否存在和大小
            if not os.path.exists(self.log_file_path):
                self._run_in_ui(lambda: self.update_status("日志文件不存在，可能捕获过程中出现错误", False))
                self.logging_active = False
                return
                    
            # 检查文件大小
            file_size = os.path.getsize(self.log_file_path)
            if file_size == 0:
                self._run_in_ui(lambda: self.update_status("警告：日志文件为空，可能原因：\n1. 设备无日志输出\n2. ADB 连接不稳定\n3. 权限不足\n4. 捕获时间过短", False))
            else:
                file_size_str = format_file_size(file_size)
                self._run_in_ui(lambda: self.update_status(f"日志捕获成功，文件大小：{file_size_str}", True))
    
            # 生成新的文件名（使用停止时的时间戳）
            original_path = os.path.dirname(self.log_file_path)
            stop_timestamp = timestamp_time()  # 获取停止时的时间戳
            if file_size == 0:
                # 为空文件添加特殊标记
                new_name = os.path.join(original_path, f"{stop_timestamp}_empty.log")
            else:
                new_name = os.path.join(original_path, f"{stop_timestamp}.log")
    
            # 重试机制（减少到 3 次，缩短等待时间）
            max_retries = 3
            success_save = False
            last_error = ""
                
            for attempt in range(max_retries):
                try:
                    # 尝试重命名文件
                    os.rename(self.log_file_path, new_name)
                    success_save = True
                        
                    # 构建提示信息
                    save_path = os.path.abspath(new_name)
                    if file_size == 0:
                        self._run_in_ui(lambda: self.update_status(f"日志捕获已停止\n空日志文件已保存到：{save_path}\n建议检查设备连接和权限设置", False))
                    else:
                        self._run_in_ui(lambda: self.update_status(f"日志捕获已停止\n日志文件已保存到：{save_path}", True))
                    break
                        
                except PermissionError as e:
                    last_error = f"权限错误：{str(e)}"
                    if attempt < max_retries - 1:
                        # 缩短等待时间
                        time.sleep(0.5)
                        continue
                except Exception as e:
                    last_error = f"重命名失败：{str(e)}"
                    self._run_in_ui(lambda: self.update_status(f"保存日志文件失败：{str(e)}", False))
                    break
    
            # 重置状态
            self.logging_active = False
                
            if not success_save:
                # 如果重命名失败，至少告诉用户原文件位置
                file_size_str = format_file_size(file_size) if file_size > 0 else "空文件"
                self._run_in_ui(lambda: self.update_status(f"日志捕获已停止，但文件保存失败。\n原因：{last_error}\n原文件位置：{self.log_file_path}\n文件大小：{file_size_str}", False))
                
            # 清理进程引用
            self.logcat_subprocess = None
                
        except Exception as e:
            self._run_in_ui(lambda: self.update_status(f"清理日志文件出错：{str(e)}", False))
            self.logging_active = False

    def _run_logcat(self):
        """实际执行日志捕获（修复版，解决文件句柄释放问题）"""
        f = None
        try:
            # 再次验证设备连接状态
            if not self.check_device_connected():
                self.update_status("设备连接已断开，无法启动日志捕获", False)
                self.logging_active = False
                return
                
            # 验证路径可写性
            log_dir = os.path.dirname(self.log_file_path)
            if not os.access(log_dir, os.W_OK):
                self.update_status(f"日志文件目录不可写: {log_dir}", False)
                self.logging_active = False
                return

            # 先测试创建文件
            try:
                f = open(self.log_file_path, "w", encoding='utf-8', buffering=1)
                # 写入启动标记
                f.write(f"# ADB Tool 日志捕获开始 - {timestamp_time()}\n")
                f.flush()
                self.update_status(f"日志文件创建成功: {self.log_file_path}", True)
            except Exception as file_error:
                self.update_status(f"无法创建日志文件: {str(file_error)}", False)
                self.logging_active = False
                return

            # Windows 系统添加 CREATE_NO_WINDOW 标志
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

            # 启动logcat进程
            try:
                # 获取目标设备IP并构建支持多设备的命令
                from utils import build_adb_command_with_device
                target_ip = self.get_ip_address()
                logcat_cmd = build_adb_command_with_device("adb logcat -v time *:V", target_ip)
                
                # 分割命令为参数列表
                cmd_parts = logcat_cmd.split()
                
                self.logcat_subprocess = subprocess.Popen(
                    cmd_parts,
                    stdout=f,
                    # ⚠️ stderr 必须并入 stdout（写文件）或丢弃：
                    #    用 PIPE 却不读，管道缓冲区(64KB)一满 logcat 进程就会被挂住。
                    stderr=subprocess.STDOUT,
                    creationflags=creation_flags,
                    text=True, encoding='utf-8', errors='replace',
                    bufsize=1
                )
                
                # 等待一小段时间确保进程启动
                time.sleep(0.5)
                
                # 验证进程是否成功启动
                if self.logcat_subprocess.poll() is not None:
                    # 进程已经退出，获取错误信息
                    # stderr 已并入 stdout（写日志文件），这里从文件尾部取错误信息
                    stderr_output = self._read_log_tail(400)
                    self.update_status(f"logcat进程启动失败: {stderr_output}", False)
                    self.logging_active = False
                    return
                    
                self.update_status("logcat进程已成功启动，开始捕获日志...", True)
                
            except Exception as proc_error:
                self.update_status(f"启动logcat进程失败: {str(proc_error)}", False)
                self.logging_active = False
                return

            # 监控进程状态并定期刷新文件
            last_flush_time = time.time()
            flush_interval = 5  # 每5秒刷新一次
            device_check_counter = 0  # 设备检查计数器
            
            while self.logcat_subprocess.poll() is None:
                # 检查停止信号
                if self.stop_event.wait(0.5):
                    break  # 正常停止，不调用_terminate_logcat
                    
                # 定期刷新文件缓冲区
                current_time = time.time()
                if current_time - last_flush_time >= flush_interval:
                    try:
                        f.flush()
                        # ⚠️ 不做 os.fsync()：那是同步磁盘操作，慢盘/杀软下可能阻塞
                        #    几十~几百毫秒，而这里每 5 秒一次。flush() 已经把数据交给
                        #    操作系统，进程异常退出时最多丢最后 5 秒的缓冲。
                        last_flush_time = current_time
                    except Exception:
                        pass  # 忽略刷新错误
                        
                # 检查设备连接状态（每60秒检查一次，减少频率）
                device_check_counter += 1
                if device_check_counter >= 120:  # 0.5秒 * 120 = 60秒
                    device_check_counter = 0
                    if not self.check_device_connected():
                        self.update_status("设备连接断开，停止日志捕获", False)
                        break
                        
            # 进程结束，检查退出状态
            return_code = self.logcat_subprocess.poll()
            if return_code is not None and return_code != 0 and not self.stop_event.is_set():
                # 只有在非正常停止时才报告错误
                stderr_output = self._read_log_tail(400)
                self.update_status(f"logcat进程异常退出 (代码: {return_code}): {stderr_output}", False)
                
        except Exception as e:
            self.update_status(f"日志捕获过程出错: {str(e)}", False)
        finally:
            # 确保文件正确关闭和进程终止
            if self.logcat_subprocess and self.logcat_subprocess.poll() is None:
                try:
                    self.logcat_subprocess.terminate()
                    self.logcat_subprocess.wait(timeout=3)
                except Exception:
                    pass
            
            if f:
                try:
                    # 写入结束标记
                    f.write(f"\n# ADB Tool 日志捕获结束 - {timestamp_time()}\n")
                    f.flush()
                    os.fsync(f.fileno())  # 强制写入磁盘
                except Exception:
                    pass
                finally:
                    try:
                        f.close()  # 确保文件关闭
                    except Exception:
                        pass
            
            # 验证文件大小
            if os.path.exists(self.log_file_path):
                file_size = os.path.getsize(self.log_file_path)
                if file_size == 0:
                    self.update_status("警告：日志文件为空，可能存在以下问题：\n1. 设备无日志输出\n2. ADB连接不稳定\n3. 权限不足", False)
                else:
                    file_size_str = format_file_size(file_size)
                    self.update_status(f"日志捕获进程已结束，文件大小: {file_size_str}", True)

    def _terminate_logcat(self):
        '''终止日志捕获进程（修复版，避免反复终止）'''
        if self.logcat_subprocess and self.logcat_subprocess.poll() is None:
            try:
                # 先尝试正常终止
                self.logcat_subprocess.terminate()
                self.logcat_subprocess.wait(timeout=5)  # 增加等待时间
            except (subprocess.TimeoutExpired, psutil.NoSuchProcess):
                # 如果正常终止失败，强制终止进程树
                try:
                    parent = psutil.Process(self.logcat_subprocess.pid)
                    for child in parent.children(recursive=True):
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    try:
                        parent.kill()
                    except psutil.NoSuchProcess:
                        pass
                except psutil.NoSuchProcess:
                    pass  # 进程已经不存在
            except Exception:
                pass  # 忽略终止时的其他错误

    @require_device_connected
    def log_clear(self):
        """清除日志(带确认对话框)"""
        # 显示确认对话框
        result = messagebox.askyesno(
            "确认清理日志",
            "您确定要清理设备日志缓冲区吗？\n\n注意：清理后所有历史日志将被删除。",
            icon="warning"
        )
        
        if result:
            def _work():
                output, success = self.run_adb_with_target("adb logcat -c")
                if success:
                    self._update_status_safe("日志清除成功", True)
                else:
                    self._update_status_safe(output, False)

            self.run_in_background(_work)
        else:
            self.update_status("已取消清理日志操作", True)

    @require_device_connected
    def get_package_name(self):
        """获取当前打开应用包名"""
        def _work():
            try:
                # ⚠️ 过滤放在 Python 侧做，不能用 `| findstr`：
                #    管道由本机 cmd 解析；且 dumpsys window 输出极大（全量传回本机很慢）。
                #    dumpsys activity activities 体积小得多，同样能拿到前台包名。
                output, success = self.run_adb_with_target(
                    "adb shell dumpsys activity activities")
                if not success or not output:
                    # 备用命令
                    output, success = self.run_adb_with_target(
                        "adb shell dumpsys window windows")
                if not success or not output:
                    self._update_status_safe("获取当前应用包名失败", False)
                    return

                # 只保留与前台窗口相关的行
                output = "\n".join(filter_lines(
                    output, 'mResumedActivity', 'mFocusedApp', 'mCurrentFocus'))

                # 调试输出
                self._update_status_safe(f"原始输出: {output}", True)

                package_name = None
                # 尝试多种格式匹配
                if "u0" in output:
                    # 格式1: mCurrentFocus=Window{...u0 包名/活动名}
                    try:
                        package_name = output.split("u0 ")[1].split("/")[0].strip()
                    except Exception:
                        pass

                if not package_name and "Window{" in output:
                    # 格式2: mCurrentFocus=Window{...包名/活动名}
                    try:
                        package_name = output.split("Window{")[1].split("/")[0].split()[-1].strip()
                    except Exception:
                        pass

                if not package_name and "ResumedActivity" in output:
                    # 格式3: ResumedActivity: ActivityRecord{...包名/活动名}
                    try:
                        package_name = output.split("ResumedActivity")[1].split("/")[0].split()[-1].strip()
                    except Exception:
                        pass

                if not package_name:
                    # 格式4: 尝试直接从/分隔的内容中提取
                    try:
                        parts = output.split("/")
                        if len(parts) > 1:
                            package_name = parts[0].split()[-1].strip()
                    except Exception:
                        pass

                if package_name:
                    # 验证包名格式
                    if "." in package_name and not package_name.startswith(".") and not package_name.endswith("."):
                        self._update_status_safe(f"当前应用包名: {package_name}", True)
                        # 保存包名到历史记录 + 自动填充包名到输入框（都要回主线程）
                        def _fill():
                            self._save_pkg_to_history(package_name)
                            if hasattr(self, 'pkg_combobox'):
                                self.pkg_combobox.delete(0, tk.END)
                                self.pkg_combobox.insert(0, package_name)
                            else:
                                self.pkg_entry.delete(0, tk.END)
                                self.pkg_entry.insert(0, package_name)
                        self._run_in_ui(_fill)
                    else:
                        self._update_status_safe("解析出的包名格式不正确", False)
                else:
                    self._update_status_safe("无法解析应用包名", False)

            except Exception as e:
                self._update_status_safe(f"获取应用包名时出错: {str(e)}", False)

        self.run_in_background(_work)

    @require_device_connected
    def get_package_path(self):
        """获取当前包名应用安装路径"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        def _work():
            try:
                output, success = self.run_adb_with_target(f"adb shell pm path {pkg_name}")
                if success and output:
                    # 保存包名到历史记录（会操作 Tk，必须回主线程）
                    self._run_in_ui(lambda: self._save_pkg_to_history(pkg_name))
                    # 移除"package:"前缀并清理输出
                    path = output.replace("package:", "").strip()
                    self._run_in_ui(lambda: self.status_text.insert(
                        tk.END, f"\n应用安装路径：{path}\n", "info"))
                    self._run_in_ui(lambda: self.status_text.see(tk.END))
                else:
                    self._update_status_safe(f"未找到包名 {pkg_name} 的安装路径", False)
            except Exception as e:
                self._update_status_safe(f"获取安装路径失败：{str(e)}", False)

        self.run_in_background(_work)
        
    @require_device_connected
    def get_app_resource_usage(self):
        """获取当前包名应用的内存和 CPU 占用情况"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return
            
        try:
            # 显示正在获取的提示
            self.update_status(f"⏳ 正在获取应用 {pkg_name} 的资源占用情况...", True, "info")
                
            # 使用后台线程异步获取（不阻塞界面）
            import threading
            thread = threading.Thread(target=lambda: self._get_app_resource_usage_async(pkg_name), daemon=True)
            thread.start()
        except Exception as e:
            self.update_status(f"获取资源占用失败：{str(e)}", False)
        
    def _get_app_resource_usage_async(self, pkg_name: str):
        """异步获取应用资源占用（后台线程执行）"""
        try:
            import re
            info_lines = []
            info_lines.append("\n" + "="*60)
            info_lines.append(f"📊 应用资源占用监控：{pkg_name}")
            info_lines.append("="*60)
                
            # 1. 获取 CPU 和内存占用（使用更可靠的命令）
            try:
                # 方式 1：使用 top -n 1 获取单行输出
                # ⚠️ 不能写 `| grep {pkg}`：管道由本机 cmd 解析，用户环境没有 grep 会整条失败
                output, _ = self.run_adb_with_target("adb shell top -n 1")

                if not output or not output.strip():
                    # 方式 2：使用 top -m 1 获取单行
                    output, _ = self.run_adb_with_target("adb shell top -m 1")

                # 过滤目标应用的行（Python 侧过滤，不依赖本机/设备端 grep）
                output = "\n".join(filter_lines(output, pkg_name))

                if output and output.strip():
                    # 解析 top 输出
                    for line in output.strip().split('\n'):
                        if line.strip():
                            parts = line.split()
                            # 尝试多种格式解析
                            cpu = None
                            mem = None
                            
                            # Android 8.0+ 格式：USER PID %CPU %MEM VSZ RSS ...
                            if len(parts) >= 10:
                                # 查找包含 % 的值作为 CPU
                                for i, part in enumerate(parts):
                                    if '%' in part and part.replace('%', '').replace('.', '').isdigit():
                                        cpu = part.replace('%', '')
                                        # 下一个数字可能是内存
                                        if i+1 < len(parts) and parts[i+1].replace('.', '').isdigit():
                                            mem = parts[i+1]
                                        break
                            
                            # 旧版 Android 格式
                            if not cpu and len(parts) >= 9:
                                cpu = parts[2] if len(parts) > 2 else None
                                mem = parts[4] if len(parts) > 4 else None
                            
                            if cpu:
                                info_lines.append(f"\n【CPU 占用】")
                                info_lines.append(f"  CPU: {cpu}%")
                                if mem:
                                    info_lines.append(f"\n【内存占用】")
                                    info_lines.append(f"  内存：{mem}")
                            break
                    else:
                        info_lines.append("\n⚠️ 未找到该应用的进程信息（可能未运行）")
                else:
                    info_lines.append("\n⚠️ 未找到该应用的进程信息（可能未运行）")
            except Exception as e:
                info_lines.append(f"\n⚠️ 无法获取 CPU/内存信息：{str(e)}")
                
            # 2. 获取详细内存信息（dumpsys meminfo）
            try:
                output, _ = self.run_adb_with_target(f"adb shell dumpsys meminfo {pkg_name}")
                if output:
                    info_lines.append("\n【详细内存信息】")
                        
                    # 解析 PSS 内存
                    pss_match = re.search(r'TOTAL.*?(\d+)', output)
                    if pss_match:
                        pss_total = int(pss_match.group(1))
                        info_lines.append(f"  PSS 总内存：{self._format_memory_size(pss_total)}")
                        
                    # 解析 Native Heap
                    native_match = re.search(r'Native Heap.*?(\d+)', output)
                    if native_match:
                        native_heap = int(native_match.group(1))
                        info_lines.append(f"  Native Heap: {self._format_memory_size(native_heap)}")
                        
                    # 解析 Dalvik Heap
                    dalvik_match = re.search(r'Dalvik Heap.*?(\d+)', output)
                    if dalvik_match:
                        dalvik_heap = int(dalvik_match.group(1))
                        info_lines.append(f"  Dalvik Heap: {self._format_memory_size(dalvik_heap)}")
            except Exception:
                info_lines.append("\n⚠️ 无法获取详细内存信息")
                
            # 3. 获取进程信息
            try:
                # ⚠️ 不能写 `| grep {pkg}`：管道由本机 cmd 解析，用户环境没有 grep 会整条失败
                output, _ = self.run_adb_with_target("adb shell ps -A")
                output = "\n".join(filter_lines(output, pkg_name))
                if output:
                    lines = output.strip().split('\n')
                    info_lines.append(f"\n【进程信息】")
                    info_lines.append(f"  进程数：{len(lines)}")
                    for i, line in enumerate(lines[:3], 1):  # 只显示前 3 个进程
                        parts = line.split()
                        if len(parts) >= 2:
                            pid = parts[0]
                            info_lines.append(f"  进程{i} PID: {pid}")
            except Exception:
                info_lines.append("\n⚠️ 无法获取进程信息")
                
            # 4. 获取电池消耗（可选）
            try:
                output, _ = self.run_adb_with_target("adb shell dumpsys batterystats --checkin")
                if output and pkg_name in output:
                    info_lines.append("\n【电池消耗】")
                    # 简化显示
                    info_lines.append(f"  有电池消耗记录")
            except Exception:
                pass
                
            info_lines.append("\n" + "="*60)
                
            # 在 UI 线程中显示
            result_text = "\n".join(info_lines)
            self._run_in_ui(lambda: self.update_status(result_text, True, "info"))
                
        except Exception as e:
            self._run_in_ui(lambda: self.update_status(f"获取资源占用失败：{str(e)}", False))
        
    def _format_memory_size(self, size_kb: int) -> str:
        """格式化内存大小（KB 转换为易读单位）"""
        if size_kb >= 1024 * 1024:
            return f"{size_kb / (1024 * 1024):.1f} MB"
        elif size_kb >= 1024:
            return f"{size_kb / 1024:.1f} MB"
        else:
            return f"{size_kb} KB"

    # 帮助文档


    def show_all_adb_commands(self):
        """输出所有功能按钮及其对应的adb命令（优化版 - 清晰分组展示）"""
        # 按功能分组的命令映射
        command_groups = [
            {
                "title": "📱 设备连接",
                "commands": [
                    ("连接 ADB", "adb connect <IP地址>"),
                    ("断开所有ADB连接", "adb disconnect"),
                ]
            },
            {
                "title": "📦 应用管理",
                "commands": [
                    ("强制安装apk", "adb install -r -d <APK路径>"),
                    ("卸载当前包名应用", "adb uninstall <包名>"),
                    ("获取已安装应用包名列表", "adb shell pm list packages"),
                    ("清除应用缓存", "adb shell pm clear <包名>"),
                    ("终止当前包名所有进程", "adb shell am force-stop <包名>"),
                    ("获取当前包名应用安装路径", "adb shell pm path <包名>"),
                ]
            },
            {
                "title": "🔧 系统操作",
                "commands": [
                    ("获取Root权限", "adb root"),
                    ("重新挂载分区", "adb remount"),
                    ("重启设备", "adb reboot"),
                ]
            },
            {
                "title": "ℹ️ 系统信息",
                "commands": [
                    ("获取Android版本号", "adb shell getprop ro.build.version.release"),
                    ("获取设备串号", "adb shell getprop ro.serialno"),
                    ("获取当前包名版本号", "adb shell pm dump <包名> | 查找versionName"),
                ]
            },
            {
                "title": "📺 屏幕操作",
                "commands": [
                    ("截取当前屏幕", "adb shell screencap -p /sdcard/screenshot.png && adb pull /sdcard/screenshot.png <本地路径>"),
                    ("开始屏幕录制", "adb shell screenrecord /sdcard/temp_recording.mp4 && adb pull /sdcard/temp_recording.mp4 <本地路径>"),
                    ("停止屏幕录制", "终止screenrecord进程并下载视频文件"),
                ]
            },
            {
                "title": "📝 日志操作",
                "commands": [
                    ("启动日志捕获", "adb logcat -v time *:V > <本地路径>"),
                    ("停止日志捕获", "结束logcat进程"),
                    ("清除日志缓存", "adb logcat -c"),
                    ("导出ANR文件", "adb pull /data/anr <本地目录>"),
                ]
            },
            {
                "title": "🎯 应用状态",
                "commands": [
                    ("获取当前打开应用包名", "adb shell dumpsys window windows | findstr mCurrentFocus"),
                    ("获取当前打开应用包名(备用)", "adb shell dumpsys activity activities | findstr mResumedActivity"),
                ]
            },
        ]
        
        # 输出标题
        self.status_text.insert(tk.END, "\n" + "="*70 + "\n", "info")
        self.status_text.insert(tk.END, "📝 功能按钮与对应 ADB 命令速查\n", "info")
        self.status_text.insert(tk.END, "="*70 + "\n\n", "info")
        
        # 按组输出命令
        cmd_index = 1
        for group in command_groups:
            # 输出分组标题
            self.status_text.insert(tk.END, f"{group['title']}\n", "info")
            self.status_text.insert(tk.END, "-" * 70 + "\n", "info")
            
            # 输出该组的命令
            for name, cmd in group['commands']:
                # 使用更清晰的对齐格式
                self.status_text.insert(tk.END, f"  {cmd_index:2d}. {name:<25} → {cmd}\n", "info")
                cmd_index += 1
            
            # 组间空行
            self.status_text.insert(tk.END, "\n", "info")
        
        # 输出结尾
        self.status_text.insert(tk.END, "="*70 + "\n", "info")
        self.status_text.insert(tk.END, "💡 提示：将 <xxx> 替换为实际参数值\n", "info")
        self.status_text.insert(tk.END, "="*70 + "\n", "info")
        self.status_text.see(tk.END)
        
    def show_common_adb_commands(self):
        """输出 30 条常用的 ADB 命令（优化版 - 清晰分组）"""
        # 按功能分组的 ADB 命令
        command_groups = [
            {
                "title": "📱 设备连接",
                "commands": [
                    ("查看已连接设备", "adb devices"),
                    ("连接无线设备", "adb connect <IP 地址>:5555"),
                    ("断开无线连接", "adb disconnect <IP 地址>:5555"),
                    ("断开所有连接", "adb disconnect"),
                ]
            },
            {
                "title": "🔄 重启与模式",
                "commands": [
                    ("重启设备", "adb reboot"),
                    ("重启到 Recovery", "adb reboot recovery"),
                    ("重启到 Bootloader", "adb reboot bootloader"),
                    ("进入 Fastboot", "adb reboot bootloader"),
                ]
            },
            {
                "title": "🔧 系统操作",
                "commands": [
                    ("获取 Root 权限", "adb root"),
                    ("重新挂载分区", "adb remount"),
                ]
            },
            {
                "title": "ℹ️ 系统信息",
                "commands": [
                    ("查看系统属性", "adb shell getprop"),
                    ("查看 Android 版本", "adb shell getprop ro.build.version.release"),
                    ("查看 SDK 版本", "adb shell getprop ro.build.version.sdk"),
                    ("查看设备型号", "adb shell getprop ro.product.model"),
                    ("查看设备品牌", "adb shell getprop ro.product.brand"),
                    ("查看设备串号", "adb shell getprop ro.serialno"),
                ]
            },
            {
                "title": "📺 屏幕信息",
                "commands": [
                    ("查看屏幕分辨率", "adb shell wm size"),
                    ("查看屏幕密度", "adb shell wm density"),
                ]
            },
            {
                "title": "📦 应用管理",
                "commands": [
                    ("查看已安装应用", "adb shell pm list packages"),
                    ("查看第三方应用", "adb shell pm list packages -3"),
                    ("查看系统应用", "adb shell pm list packages -s"),
                    ("安装 APK", "adb install <APK 路径>"),
                    ("覆盖安装", "adb install -r <APK 路径>"),
                    ("降级安装", "adb install -d <APK 路径>"),
                    ("卸载应用", "adb uninstall <包名>"),
                    ("清除应用数据", "adb shell pm clear <包名>"),
                    ("强制停止应用", "adb shell am force-stop <包名>"),
                    ("查看应用安装路径", "adb shell pm path <包名>"),
                ]
            },
            {
                "title": "📝 日志操作",
                "commands": [
                    ("查看日志", "adb logcat"),
                    ("清除日志", "adb logcat -c"),
                ]
            },
            {
                "title": "📸 截屏录屏",
                "commands": [
                    ("截图", "adb shell screencap -p /sdcard/screen.png"),
                    ("下载截图", "adb pull /sdcard/screen.png <本地路径>"),
                    ("屏幕录制", "adb shell screenrecord /sdcard/test.mp4"),
                    ("下载录屏", "adb pull /sdcard/test.mp4 <本地路径>"),
                ]
            },
            {
                "title": "💻 硬件信息",
                "commands": [
                    ("查看 CPU 信息", "adb shell cat /proc/cpuinfo"),
                    ("查看内存信息", "adb shell cat /proc/meminfo"),
                    ("查看存储信息", "adb shell df"),
                ]
            },
            {
                "title": "⚙️ 系统进程",
                "commands": [
                    ("查看进程", "adb shell ps"),
                    ("查看顶层活动", "adb shell dumpsys window windows"),
                    ("查看电池信息", "adb shell dumpsys battery"),
                ]
            },
        ]
            
        # 输出标题
        self.status_text.insert(tk.END, "\n" + "="*70 + "\n", "info")
        self.status_text.insert(tk.END, "📝 常用 ADB 命令速查手册\n", "info")
        self.status_text.insert(tk.END, "="*70 + "\n\n", "info")
            
        # 按组输出命令
        cmd_index = 1
        for group in command_groups:
            # 输出分组标题
            self.status_text.insert(tk.END, f"{group['title']}\n", "info")
            self.status_text.insert(tk.END, "-" * 70 + "\n", "info")
                
            # 输出该组的命令
            for name, cmd in group['commands']:
                self.status_text.insert(tk.END, f"  {cmd_index:2d}. {name:<30} → {cmd}\n", "info")
                cmd_index += 1
                
            # 组间空行
            self.status_text.insert(tk.END, "\n", "info")
            
        # 输出结尾
        self.status_text.insert(tk.END, "="*70 + "\n", "info")
        self.status_text.insert(tk.END, "💡 提示：将 <xxx> 替换为实际参数值\n", "info")
        self.status_text.insert(tk.END, "="*70 + "\n", "info")
        self.status_text.see(tk.END)

    def _set_drop_highlight(self, entry, active: bool) -> None:
        """拖拽悬停时的高亮反馈

        ⚠️ 不能写死 white / lightblue / lightgreen ——
        深色主题下这些浅色块会非常刺眼。统一改用主题的高亮底色。

        Args:
            entry: 目标输入框
            active: True 表示进入拖拽悬停态
        """
        if entry is None:
            return
        theme = getattr(self, '_ui_theme', None)
        if theme is None:
            return
        try:
            entry.config(background=theme.color('bg_active' if active else 'bg_elev'))
        except Exception:
            pass

    def _setup_drag_drop(self):
        """设置拖拽APK文件和脚本文件功能"""
        # 幂等：app Tab 是懒加载的，重复触发时不要重复绑定
        if getattr(self, '_drag_drop_ready', False):
            return
        if not hasattr(self, 'apk_entry'):
            return
        self._drag_drop_ready = True

        # 先设置占位符文本
        def setup_placeholder():
            if not self.apk_entry.get():
                self.apk_entry.insert(0, "可直接拖拽APK文件到此处...")
                
        def on_focus_in(event):
            if self.apk_entry.get() == "可直接拖拽APK文件到此处...":
                self.apk_entry.delete(0, tk.END)
                
        def on_focus_out(event):
            if not self.apk_entry.get():
                setup_placeholder()
        
        # 绑定焦点事件
        self.apk_entry.bind('<FocusIn>', on_focus_in)
        self.apk_entry.bind('<FocusOut>', on_focus_out)
        setup_placeholder()
        
        # 尝试安装和使用 tkinterdnd2
        try:
            from tkinterdnd2 import DND_FILES
            
            def on_drop_apk(event):
                """处理APK文件拖拽（优化版 - 异步提取包名，不阻塞UI）"""
                self._set_drop_highlight(self.apk_entry, False)
                
                # 获取拖拽的文件路径
                files = event.data.split()
                if files:
                    file_path = files[0].strip('{}"')  # 移除可能的引号和大括号
                    
                    # 检查文件是否存在且为APK文件
                    if os.path.exists(file_path) and file_path.lower().endswith('.apk'):
                        # 清除占位符
                        self.apk_entry.delete(0, tk.END)
                        self.apk_entry.insert(0, file_path)
                        
                        # 显示文件信息（立即显示，不等待提取）
                        try:
                            file_size = format_file_size(os.path.getsize(file_path))
                            file_name = os.path.basename(file_path)
                            self.update_status(f"📦 已选择APK文件: {file_name}\n📊 文件大小: {file_size}\n⏳ 正在提取包名信息...", True)
                        except Exception:
                            self.update_status(f"📦 已选择 APK 文件：{os.path.basename(file_path)}\n⏳ 正在提取包名信息...", True)
                                                
                        # 🆕 优化：使用后台线程异步提取包名，不阻塞界面
                        import threading
                        extract_thread = threading.Thread(
                            target=lambda: self._extract_and_update_package_name_async(file_path),
                            daemon=True
                        )
                        extract_thread.start()
                            
                        # 提示用户可以安装
                        self.update_status("🚀 请点击'强制安装apk'按钮进行安装", True)
                    else:
                        self.update_status("⚠️ 请拖拽有效的.apk文件", False)
            
            def on_drag_enter_apk(event):
                """鼠标进入拖拽区域时的视觉反馈"""
                self._set_drop_highlight(self.apk_entry, True)
            
            def on_drag_leave_apk(event):
                """鼠标离开拖拽区域时恢复原样"""
                self._set_drop_highlight(self.apk_entry, False)
            
            # 注册APK拖拽事件
            self.apk_entry.drop_target_register(DND_FILES)
            self.apk_entry.dnd_bind('<<Drop>>', on_drop_apk)
            self.apk_entry.dnd_bind('<<DragEnter>>', on_drag_enter_apk)
            self.apk_entry.dnd_bind('<<DragLeave>>', on_drag_leave_apk)
            
            # === 为脚本输入框添加拖拽支持 ===
            if hasattr(self, 'script_entry'):
                def setup_script_placeholder():
                    if not self.script_entry.get():
                        self.script_entry.insert(0, "可直接拖拽.sh脚本文件到此处...")
                    
                def on_script_focus_in(event):
                    if self.script_entry.get() == "可直接拖拽.sh脚本文件到此处...":
                        self.script_entry.delete(0, tk.END)
                        
                def on_script_focus_out(event):
                    if not self.script_entry.get():
                        setup_script_placeholder()
                
                # 绑定焦点事件
                self.script_entry.bind('<FocusIn>', on_script_focus_in)
                self.script_entry.bind('<FocusOut>', on_script_focus_out)
                setup_script_placeholder()
                
                def on_drop_script(event):
                    """处理脚本文件拖拽"""
                    self._set_drop_highlight(self.script_entry, False)
                    
                    # 获取拖拽的文件路径
                    files = event.data.split()
                    if files:
                        file_path = files[0].strip('{}"')
                        
                        # 检查文件是否存在且为.sh文件
                        if os.path.exists(file_path) and file_path.lower().endswith('.sh'):
                            # 清除占位符
                            self.script_entry.delete(0, tk.END)
                            self.script_entry.insert(0, file_path)
                            
                            file_name = os.path.basename(file_path)
                            self.update_status(f"✅ 已选择脚本文件: {file_name}", True)
                            self.update_status(f"💡 点击'推送脚本'按钮上传到设备", True)
                        else:
                            self.update_status("⚠️ 请拖拽有效的.sh脚本文件", False)
                
                def on_drag_enter_script(event):
                    """鼠标进入拖拽区域时的视觉反馈"""
                    self._set_drop_highlight(self.script_entry, True)
                
                def on_drag_leave_script(event):
                    """鼠标离开拖拽区域时恢复原样"""
                    self._set_drop_highlight(self.script_entry, False)
                
                # 注册脚本拖拽事件
                self.script_entry.drop_target_register(DND_FILES)
                self.script_entry.dnd_bind('<<Drop>>', on_drop_script)
                self.script_entry.dnd_bind('<<DragEnter>>', on_drag_enter_script)
                self.script_entry.dnd_bind('<<DragLeave>>', on_drag_leave_script)
            
        except ImportError:
            # 如果没有安装tkinterdnd2，提供基本的文件选择功能
            def browse_apk_file():
                file_path = filedialog.askopenfilename(
                    title="选择APK文件",
                    filetypes=[("APK文件", "*.apk"), ("所有文件", "*.*")]
                )
                if file_path:
                    self.apk_entry.delete(0, tk.END)
                    self.apk_entry.insert(0, file_path)
                    self.update_status(f"已选择 APK 文件：{os.path.basename(file_path)}", True)
                    # 🆕 新增：自动提取包名并更新到输入框
                    self._run_in_ui(lambda: self._extract_and_update_package_name(file_path))
            
            # 为apk_entry添加右键菜单
            def show_context_menu(event):
                context_menu = tk.Menu(self.root, tearoff=0)
                context_menu.add_command(label="浏览文件", command=browse_apk_file)
                context_menu.add_separator()
                context_menu.add_command(label="清空", command=lambda: self.apk_entry.delete(0, tk.END))
                context_menu.post(event.x_root, event.y_root)
            
            self.apk_entry.bind("<Button-3>", show_context_menu)
    
    @require_device_connected
    def open_factory_menu(self):
        """打开工厂菜单"""
        def _work():
            try:
                # 尝试不同的启动方式
                # 方式1: 使用完整的组件名称格式
                output, success = self.run_adb_with_target("adb shell am start -n com.konka.kkfactory/.FactoryHome")

                if not success:
                    # 方式2: 如果上面失败，尝试其他可能的格式
                    output, success = self.run_adb_with_target("adb shell am start -n com.konka.kkfactory.FactoryHome/.FactoryHome")

                if not success:
                    # 方式3: 尝试直接启动包
                    output, success = self.run_adb_with_target("adb shell am start -n com.konka.kkfactory")

                if success:
                    self._update_status_safe("工厂菜单已打开", True)
                else:
                    self._update_status_safe(f"打开工厂菜单失败：{output}", False)
            except Exception as e:
                self._update_status_safe(f"打开工厂菜单时出错：{str(e)}", False)

        self.run_in_background(_work)
        
    def open_cmd_window(self):
        """打开 CMD 窗口（在日志路径下）"""
        try:
            # 获取目标设备 IP
            target_ip = self.get_ip_address()
                
            # 构建 ADB 命令提示符窗口标题和初始命令
            if target_ip and target_ip != "192.168.":
                # 如果有指定设备，在标题中显示
                cmd_title = f"ADB Command Prompt - {target_ip}"
                initial_commands = [
                    f"title {cmd_title}",
                    f"echo ADB Device: {target_ip}",
                    "echo."
                ]
            else:
                cmd_title = "ADB Command Prompt"
                initial_commands = [
                    f"title {cmd_title}",
                    "echo ADB Command Line Tool",
                    "echo."
                ]
                
            # 设置工作目录为用户设置的日志路径或默认路径
            user_log_path = self.log_path_entry.get().strip()
            if not user_log_path:
                user_log_path = self.default_log_path
            
            # 确保路径存在
            os.makedirs(user_log_path, exist_ok=True)
            work_dir = os.path.normpath(user_log_path)
                
            # 创建批处理脚本来启动带初始命令的 CMD
            import tempfile
            temp_dir = tempfile.gettempdir()
            bat_file = os.path.join(temp_dir, "adb_cmd_temp.bat")
                
            # 写入批处理内容
            with open(bat_file, 'w', encoding='utf-8') as f:
                # 先执行初始命令（设置标题等）
                for cmd in initial_commands:
                    f.write(f"{cmd}\n")
                    
                # 添加常用提示和 adb 路径设置（如果需要）
                f.write("echo You can use ADB commands here.\n")
                f.write("echo Type 'adb help' for available commands.\n")
                f.write("echo.\n")
                    
                # 保持窗口打开（进入交互模式）
                f.write("cmd /k\n")
                
            # 使用新进程启动 CMD 窗口，不阻塞主程序
            subprocess.Popen(
                [bat_file],
                cwd=work_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
                
            # 延迟一小段时间后删除临时文件（让 CMD 有时间读取）
            def cleanup_bat():
                try:
                    import time
                    time.sleep(2)  # 等待 2 秒确保文件被读取
                    if os.path.exists(bat_file):
                        os.remove(bat_file)
                except Exception:
                    pass
                
            cleanup_thread = threading.Thread(target=cleanup_bat, daemon=True)
            cleanup_thread.start()
                
            # 显示成功信息
            self.update_status(f"🖥️ CMD 窗口已打开 (路径: {work_dir})", True)
                
        except Exception as e:
            self.update_status(f"打开 CMD 窗口失败：{str(e)}", False)
    
    def get_scrcpy_options(self) -> dict:
        """获取用户在「投屏」Tab 里选择的投屏参数

        Returns:
            dict: {'bitrate': '8M', 'max_size': '1920', 'max_fps': '30'}
        """
        def pick(attr, default):
            var = getattr(self, attr, None)
            if var is None:
                return default
            try:
                v = (var.get() or '').strip()
            except Exception:
                v = ''
            return v if v else default

        return {
            'bitrate': pick('scrcpy_bitrate_var', Config.SCRCPY_BITRATE),
            'max_size': pick('scrcpy_max_size_var', Config.SCRCPY_MAX_SIZE),
            'max_fps': pick('scrcpy_max_fps_var', Config.SCRCPY_MAX_FPS),
        }

    def start_screen_mirror(self):
        """启动投屏（使用 scrcpy）"""
        try:
            # 获取设备 IP
            device_ip = self.get_ip_address()

            # 初始化投屏管理器（如果尚未初始化）
            if not hasattr(self, 'screen_mirror_manager'):
                from modules.screen_mirror import ScreenMirrorManager
                self.screen_mirror_manager = ScreenMirrorManager(self)

            # 启动投屏（带上用户选择的参数）
            options = self.get_scrcpy_options()
            self.screen_mirror_manager.start_mirroring(device_ip, options)

        except Exception as e:
            error_msg = f"启动投屏失败: {str(e)}"
            logging.error(f"[投屏] {error_msg}", exc_info=True)
            self.update_status(f"✗ {error_msg}", False)
    
    def stop_screen_mirror(self):
        """停止投屏"""
        try:
            if hasattr(self, 'screen_mirror_manager'):
                self.screen_mirror_manager.stop_mirroring()
            else:
                self.update_status("⚠ 投屏未在运行", False)
        except Exception as e:
            error_msg = f"停止投屏失败: {str(e)}"
            logging.error(f"[投屏] {error_msg}", exc_info=True)
            self.update_status(f"✗ {error_msg}", False)
    
    # ========== 投屏按键模拟功能 ==========
    
    def key_up(self):
        """模拟上方向键"""
        self._send_key_event(19, "方向键-上 (DPAD_UP)")
    
    def key_down(self):
        """模拟下方向键"""
        self._send_key_event(20, "方向键-下 (DPAD_DOWN)")
    
    def key_left(self):
        """模拟左方向键"""
        self._send_key_event(21, "方向键-左 (DPAD_LEFT)")
    
    def key_right(self):
        """模拟右方向键"""
        self._send_key_event(22, "方向键-右 (DPAD_RIGHT)")
    
    def key_enter(self):
        """模拟确认键（Enter）"""
        self._send_key_event(66, "确认键 (ENTER/DPAD_CENTER)")
    
    def key_back(self):
        """模拟返回键"""
        self._send_key_event(4, "返回键 (BACK)")
    
    def key_home(self):
        """模拟主页键"""
        self._send_key_event(3, "主页键 (HOME)")
    
    def key_menu(self):
        """模拟菜单键"""
        self._send_key_event(82, "菜单键 (MENU)")
    
    def key_volume_up(self):
        """模拟音量+"""
        self._send_key_event(24, "音量增加键 (VOLUME_UP)")
    
    def key_volume_down(self):
        """模拟音量-"""
        self._send_key_event(25, "音量减少键 (VOLUME_DOWN)")
    
    def key_mute(self):
        """模拟静音键"""
        self._send_key_event(164, "静音键 (MUTE)")
    
    def key_power(self):
        """模拟电源键"""
        self._send_key_event(26, "电源键 (POWER)")
    
    def key_lock(self):
        """模拟锁屏键"""
        self._send_key_event(276, "锁屏键 (LOCK)")
    
    def _send_key_event(self, keycode: int, key_name: str):
        """
        发送按键事件
        
        Args:
            keycode: Android 按键码
            key_name: 按键名称（用于日志显示）
        """
        try:
            command = f"adb shell input keyevent {keycode}"
            output, success = self.run_adb_with_target(command)
            
            if success:
                self.update_status(f"✅ 已模拟按键: {key_name}", True)
            else:
                self.update_status(f"❌ 按键模拟失败: {output}", False)
        except Exception as e:
            error_msg = f"模拟按键 {key_name} 失败: {str(e)}"
            logging.error(f"[按键模拟] {error_msg}", exc_info=True)
            self.update_status(f"✗ {error_msg}", False)
    
    # ==================== 性能监控相关方法 ====================
    
    def refresh_perf_package_list(self):
        """刷新性能监控的包名列表"""
        try:
            self.update_status("⏳ 正在获取应用列表...", True, "info")
            
            # 获取已安装的包名列表
            output, success = self.run_adb_with_target("adb shell pm list packages")
            
            if success:
                # 解析包名
                packages = [line.replace("package:", "").strip() 
                           for line in output.splitlines() if line.strip()]
                
                # 保存完整列表（用于搜索）
                self._perf_all_packages = sorted(packages)
                
                # 隐藏下拉列表
                self._hide_perf_dropdown()
                
                self.update_status(f"✓ 已加载 {len(packages)} 个应用", True)
                logging.info(f"[性能监控] 已加载 {len(packages)} 个应用")
            else:
                self.update_status(f"✗ 获取应用列表失败: {output}", False)
        
        except Exception as e:
            logging.error(f"[性能监控] 刷新包名列表失败: {str(e)}", exc_info=True)
            self.update_status(f"✗ 刷新失败: {str(e)}", False)
    
    def _on_perf_package_search(self, event=None):
        """性能监控包名搜索过滤（Entry + 浮动Listbox）"""
        try:
            if not hasattr(self, '_perf_all_packages') or not self._perf_all_packages:
                return
            
            # 获取输入内容
            search_text = self.perf_package_entry.get().strip().lower()
            
            if not search_text:
                # 如果输入为空，隐藏下拉列表
                self._hide_perf_dropdown()
                return
            
            # 模糊匹配：包含关键字的包名
            matched = [
                pkg for pkg in self._perf_all_packages
                if search_text in pkg.lower()
            ]
            
            if not matched:
                # 没有匹配项，隐藏下拉列表
                self._hide_perf_dropdown()
                return
            
            # 显示或更新浮动下拉列表
            self._show_perf_dropdown(matched)
            
        except Exception as e:
            logging.debug(f"[性能监控搜索] 过滤失败: {e}")
    
    def _show_perf_dropdown(self, packages):
        """显示浮动下拉列表"""
        try:
            # 如果下拉列表不存在，创建它
            if self.perf_dropdown_toplevel is None or not self.perf_dropdown_toplevel.winfo_exists():
                self._create_perf_dropdown()
            
            # 更新列表内容
            self.perf_dropdown_listbox.delete(0, tk.END)
            for pkg in packages:
                self.perf_dropdown_listbox.insert(tk.END, pkg)
            
            # 显示下拉列表
            self.perf_dropdown_toplevel.deiconify()
            
            # 计算位置和宽度
            entry_x = self.perf_package_entry.winfo_rootx()
            entry_y = self.perf_package_entry.winfo_rooty()
            entry_height = self.perf_package_entry.winfo_height()
            entry_width = self.perf_package_entry.winfo_width()
            
            # 设置下拉列表的宽度和位置
            self.perf_dropdown_toplevel.geometry(f"{entry_width}x150+{entry_x}+{entry_y + entry_height}")
            
        except Exception as e:
            logging.debug(f"[性能监控搜索] 显示下拉列表失败: {e}")
    
    def _create_perf_dropdown(self):
        """创建浮动下拉列表"""
        try:
            # 创建 Toplevel 窗口
            self.perf_dropdown_toplevel = tk.Toplevel(self.root)
            self.perf_dropdown_toplevel.withdraw()  # 初始隐藏
            self.perf_dropdown_toplevel.overrideredirect(True)  # 无边框
            self.perf_dropdown_toplevel.attributes('-topmost', True)  # 置顶
            
            # 创建 Listbox
            # ⚠️ 选色走主题：深色模式下的纯白选中块会非常刺眼
            theme = getattr(self, '_ui_theme', None)
            sel_bg = theme.color('accent') if theme else '#0078D4'
            sel_fg = theme.color('accent_fg') if theme else 'white'
            self.perf_dropdown_listbox = tk.Listbox(
                self.perf_dropdown_toplevel,
                font=('Microsoft YaHei UI', 9),
                selectbackground=sel_bg,
                selectforeground=sel_fg,
                bd=1,
                relief='solid',
                highlightthickness=0
            )
            self.perf_dropdown_listbox.pack(fill=tk.BOTH, expand=True)
            if theme is not None:
                theme.register(self.perf_dropdown_listbox, 'listbox')
            
            # 绑定点击事件
            self.perf_dropdown_listbox.bind('<ButtonRelease-1>', self._on_perf_package_select)
            
            # 绑定键盘事件（上下键选择，回车确认）
            self.perf_dropdown_listbox.bind('<Return>', self._on_perf_package_select)
            self.perf_dropdown_listbox.bind('<Escape>', lambda e: self._hide_perf_dropdown())
            
            # 绑定鼠标滚轮
            self.perf_dropdown_listbox.bind('<MouseWheel>', self._on_perf_dropdown_mousewheel)
            
        except Exception as e:
            logging.error(f"[性能监控] 创建下拉列表失败: {e}")
    
    def _hide_perf_dropdown(self):
        """隐藏下拉列表"""
        try:
            if self.perf_dropdown_toplevel and self.perf_dropdown_toplevel.winfo_exists():
                self.perf_dropdown_toplevel.withdraw()
        except Exception as e:
            logging.debug(f"[性能监控搜索] 隐藏下拉列表失败: {e}")
    
    def _on_perf_package_select(self, event=None):
        """选择包名"""
        try:
            selection = self.perf_dropdown_listbox.curselection()
            if selection:
                package_name = self.perf_dropdown_listbox.get(selection[0])
                # 设置到输入框
                self.perf_package_entry.delete(0, tk.END)
                self.perf_package_entry.insert(0, package_name)
                # 隐藏下拉列表
                self._hide_perf_dropdown()
                logging.info(f"[性能监控] 选择包名: {package_name}")
        except Exception as e:
            logging.debug(f"[性能监控搜索] 选择包名失败: {e}")
    
    def _on_perf_dropdown_mousewheel(self, event):
        """鼠标滚轮滚动"""
        try:
            self.perf_dropdown_listbox.yview_scroll(int(-1*(event.delta/120)), "units")
        except Exception:
            pass
    
    def get_current_package_for_perf(self):
        """获取当前正在运行的应用包名并设置到性能监控"""
        def _work():
            try:
                # ⚠️ 过滤放在 Python 侧做，不能用 `| findstr`：
                #    dumpsys window 输出极大（全量传回本机，网络设备上更慢），
                #    dumpsys activity activities 体积小得多，同样能拿到前台包名。
                output, success = self.run_adb_with_target(
                    "adb shell dumpsys activity activities")
                if not success or not output:
                    # 备用命令
                    output, success = self.run_adb_with_target(
                        "adb shell dumpsys window windows")
                if not success or not output:
                    self._update_status_safe("获取当前应用包名失败", False)
                    return

                # 只保留与前台窗口相关的行
                output = "\n".join(filter_lines(
                    output, 'mResumedActivity', 'mFocusedApp', 'mCurrentFocus'))

                package_name = None
                # 尝试多种格式匹配
                if "u0" in output:
                    # 格式1: mCurrentFocus=Window{...u0 包名/活动名}
                    try:
                        package_name = output.split("u0 ")[1].split("/")[0].strip()
                    except Exception:
                        pass

                if not package_name and "Window{" in output:
                    # 格式2: mCurrentFocus=Window{...包名/活动名}
                    try:
                        package_name = output.split("Window{")[1].split("/")[0].split()[-1].strip()
                    except Exception:
                        pass

                if not package_name and "ResumedActivity" in output:
                    # 格式3: ResumedActivity: ActivityRecord{...包名/活动名}
                    try:
                        package_name = output.split("ResumedActivity")[1].split("/")[0].split()[-1].strip()
                    except Exception:
                        pass

                if not package_name:
                    # 格式4: 尝试直接从/分隔的内容中提取
                    try:
                        parts = output.split("/")
                        if len(parts) > 1:
                            package_name = parts[0].split()[-1].strip()
                    except Exception:
                        pass

                if package_name:
                    # 验证包名格式
                    if "." in package_name and not package_name.startswith(".") and not package_name.endswith("."):
                        def _fill():
                            # 设置到输入框（Tk 操作，必须回主线程）
                            if hasattr(self, 'perf_package_entry'):
                                self.perf_package_entry.delete(0, tk.END)
                                self.perf_package_entry.insert(0, package_name)
                                self.update_status(f"✓ 已设置监控目标: {package_name}", True)
                                logging.info(f"[性能监控] 设置监控目标: {package_name}")
                            else:
                                self.update_status("✗ 性能监控组件未初始化", False)

                        self._run_in_ui(_fill)
                    else:
                        self._update_status_safe("解析出的包名格式不正确", False)
                else:
                    self._update_status_safe("无法解析应用包名", False)

            except Exception as e:
                self._update_status_safe(f"获取当前应用包名时出错: {str(e)}", False)

        self.run_in_background(_work)

    def start_performance_monitor(self):
        """开始性能监控"""
        try:
            # 包名留空表示监控系统整体
            package_name = None
            if hasattr(self, 'perf_package_entry'):
                pkg_input = self.perf_package_entry.get().strip()
                if pkg_input:
                    package_name = pkg_input

            interval = 2
            if hasattr(self, 'perf_interval_var'):
                try:
                    interval = float(self.perf_interval_var.get())
                except (TypeError, ValueError):
                    interval = 2

            self._hide_perf_dropdown()
            self.performance_monitor.update_callback = self._update_performance_ui
            self.performance_monitor.start(package_name, interval)
            self._set_perf_status(True)

        except Exception as e:
            logging.error(f"[性能监控] 启动失败: {str(e)}", exc_info=True)
            self.update_status(f"✗ 启动性能监控失败: {str(e)}", False)

    def stop_performance_monitor(self):
        """停止性能监控（停止后自动落盘一份 CSV，避免忘记导出丢失数据）"""
        try:
            success = self.performance_monitor.stop()
            self._set_perf_status(False)

            if self.performance_monitor.history:
                pkg = self.performance_monitor.package_name or "system"
                try:
                    file_path = os.path.join(
                        self._get_perf_report_dir(), f"perf_{pkg}_{timestamp_time()}.csv")
                    self.performance_monitor.export_csv(file_path)
                    self.update_status(f"💾 本次采样已自动保存: {file_path}", True, "info")
                except Exception as e:
                    logging.error(f"[性能监控] 自动保存失败: {str(e)}", exc_info=True)

            return success
        except Exception as e:
            logging.error(f"[性能监控] 停止失败: {str(e)}", exc_info=True)
            self.update_status(f"✗ 停止性能监控失败: {str(e)}", False)
            return False

    def clear_performance_data(self):
        """清空性能统计数据"""
        try:
            self.performance_monitor.clear()
            self._perf_thread_items = {}
            if hasattr(self, 'perf_thread_tree'):
                self.perf_thread_tree.delete(*self.perf_thread_tree.get_children())
            if hasattr(self, 'perf_samples_tree'):
                self.perf_samples_tree.delete(*self.perf_samples_tree.get_children())
            self._set_perf_status(self.performance_monitor.monitoring)
        except Exception as e:
            logging.error(f"[性能监控] 清空失败: {str(e)}", exc_info=True)

    def _set_perf_status(self, running: bool):
        """更新性能页右上角的运行状态指示"""
        if not hasattr(self, 'perf_status_label'):
            return
        try:
            if running:
                self.perf_status_label.config(text="● 采集中",
                                              foreground=self._perf_color('success'))
            else:
                self.perf_status_label.config(text="● 未开始",
                                              foreground=self._perf_color('fg_dim'))
        except Exception:
            pass

    def _perf_color(self, token: str) -> str:
        """取当前主题下的颜色

        性能页的阈值色（绿/黄/红）必须跟着主题走，
        否则深色模式下会看到刺眼的旧配色。

        Args:
            token: 主题令牌名（success / warning / error / fg_dim ...）
        """
        theme = getattr(self, '_ui_theme', None)
        if theme is not None:
            try:
                return theme.color(token)
            except Exception:
                pass
        # 兜底：无主题管理器时用经典配色
        return {
            'success': '#107C10', 'warning': '#BA7517', 'error': '#A32D2D',
            'accent': '#0078D4', 'fg_dim': '#888780',
        }.get(token, '#107C10')

    def _on_perf_thread_sort(self, col: str):
        """线程表格点击表头排序"""
        try:
            if getattr(self, '_perf_thread_sort_col', None) == col:
                self._perf_thread_sort_rev = not getattr(self, '_perf_thread_sort_rev', False)
            else:
                self._perf_thread_sort_col = col
                self._perf_thread_sort_rev = (col != 'name')
            threads = list(self.performance_monitor.stats.get('threads', []))
            self._fill_thread_table(threads)
        except Exception as e:
            logging.debug(f"[性能监控] 排序失败: {e}")
    
    def get_performance_snapshot(self):
        """单次性能快照（后台线程执行，避免阻塞 UI）"""
        try:
            package_name = None
            if hasattr(self, 'perf_package_entry'):
                pkg_input = self.perf_package_entry.get().strip()
                if pkg_input:
                    package_name = pkg_input

            self.update_status("📸 正在采集性能快照（约 1 秒）...", True, "info")
            self.performance_monitor.update_callback = self._update_performance_ui

            def _task():
                try:
                    self.performance_monitor.snapshot_once(package_name)
                    # snapshot_once 内部回调会刷新指标卡与趋势图
                    self._run_in_ui(lambda: self.update_status(
                        self.performance_monitor.get_summary(), True, "info"))
                except Exception as e:
                    logging.error(f"[性能监控] 快照失败: {e}", exc_info=True)
                    self._run_in_ui(lambda: self.update_status(
                        f"✗ 获取性能快照失败: {e}", False))

            threading.Thread(target=_task, daemon=True).start()

        except Exception as e:
            logging.error(f"[性能监控] 快照启动失败: {str(e)}", exc_info=True)
            self.update_status(f"✗ 获取性能快照失败: {str(e)}", False)
    
    def _get_perf_report_dir(self) -> str:
        """性能报告输出目录：<数据存储路径>/perf_reports"""
        user_log_path = ''
        if hasattr(self, 'log_path_entry'):
            user_log_path = self.log_path_entry.get().strip()
        if not user_log_path:
            user_log_path = getattr(self, 'default_log_path', os.getcwd())
        return ensure_directory(os.path.join(user_log_path, "perf_reports"))

    def export_performance_csv(self):
        """导出逐次采样明细为 CSV"""
        try:
            if not self.performance_monitor.history:
                self.update_status("⚠ 暂无历史数据，请先开始监控采集", False)
                return

            pkg = self.performance_monitor.package_name or "system"
            file_path = os.path.join(
                self._get_perf_report_dir(), f"perf_{pkg}_{timestamp_time()}.csv")

            self.performance_monitor.export_csv(file_path)
            self.update_status(f"✓ 采样明细已导出 CSV: {file_path}", True)

        except Exception as e:
            logging.error(f"[性能监控] 导出失败: {str(e)}", exc_info=True)
            self.update_status(f"✗ 导出性能数据失败: {str(e)}", False)

    def export_performance_report(self):
        """生成统计报告并写入文件（同时在终端提示路径）"""
        try:
            if not self.performance_monitor.history:
                self.update_status("⚠ 暂无历史数据，请先开始监控采集", False)
                return

            pkg = self.performance_monitor.package_name or "system"
            report_dir = self._get_perf_report_dir()
            file_path = os.path.join(report_dir, f"report_{pkg}_{timestamp_time()}.txt")

            self.performance_monitor.export_report(file_path)
            summary = self.performance_monitor.get_summary()
            self.update_status(
                f"✓ 统计报告已生成: {file_path}\n\n{summary}", True, "info")

        except Exception as e:
            logging.error(f"[性能监控] 生成报告失败: {str(e)}", exc_info=True)
            self.update_status(f"✗ 生成性能报告失败: {str(e)}", False)

    def _update_performance_ui(self, stats: dict, status_msg: str = None):
        """
        性能数据回调（引擎已调度到主线程）

        Args:
            stats: PerformanceMonitor.stats 快照（指标聚合 + 线程列表 + 历史计数）
            status_msg: 非 None 表示状态消息（启动/停止/异常提示）
        """
        try:
            if status_msg is not None:
                self.update_status(status_msg, not status_msg.startswith("✗"), "info")
                self._set_perf_status(self.performance_monitor.monitoring)

            # 顶部 PID / 模式 / 采样数指示
            if hasattr(self, 'perf_pid_label'):
                mode_text = {'proc': '精确差分', 'cpuinfo': '降级模式',
                             'system': '系统整体'}.get(
                    stats.get('mode'), stats.get('mode') or '--')
                duration = PerformanceMonitor._fmt_duration(stats.get('elapsed', 0))
                self.perf_pid_label.config(
                    text=(f"PID: {stats.get('pid') or '--'}   模式: {mode_text}   "
                          f"采样: {stats.get('sample_count', 0)} 次   时长 {duration}"))

            # 指标卡（当前大字 + 均值/峰值小字）
            metric_units = {
                'cpu': '%', 'pss': ' MB', 'rss': ' MB', 'java': ' MB',
                'native': ' MB', 'fps': '',
            }
            # 记一份快照：切换主题时布局层要靠它还原指标卡的阈值色
            snapshot = {}
            for key, (cur_label, sub_label) in getattr(
                    self, 'perf_metric_labels', {}).items():
                m = stats.get(key, {})
                unit = metric_units.get(key, '')
                cur, avg, peak = m.get('cur'), m.get('avg'), m.get('peak')
                if cur is None:
                    cur_label.config(text="--")
                    sub_label.config(text="均值 --   P95 --   峰值 --")
                    continue
                snapshot[key] = cur
                cur_label.config(text=f"{cur:.1f}{unit}")
                sub_label.config(text=f"均 {avg:.1f}  P95 {m.get('p95'):.1f}  峰 {peak:.1f}")

                # 阈值变色
                # ⚠️ 颜色走主题系统（深/浅两套），不能写死十六进制
                if key == 'cpu':
                    color = self._perf_color('error' if cur > 80 else
                                             'warning' if cur > 50 else 'success')
                    cur_label.config(foreground=color)
                elif key == 'fps':
                    color = self._perf_color('error' if cur < 30 else
                                             'warning' if cur < 50 else 'success')
                    cur_label.config(foreground=color)

            # 把快照交给布局层（换肤时用它还原阈值色）
            layout = getattr(self, 'layout_instance', None)
            if layout is not None:
                try:
                    layout._metric_snapshot = snapshot
                except Exception:
                    pass

            # 卡顿率单独显示在状态栏式标签上（与 FPS 语义相近，不额外占卡片）
            jank = stats.get('jank', {}).get('cur')
            if hasattr(self, 'perf_jank_label'):
                self.perf_jank_label.config(
                    text=f"卡顿率 {jank:.1f}%" if jank is not None else "卡顿率 --")
                if jank is not None:
                    self.perf_jank_label.config(
                        foreground=self._perf_color('error' if jank > 5 else
                                                    'warning' if jank > 2 else 'success'))

            # 告警状态指示
            if hasattr(self, 'perf_status_label') and self.performance_monitor.monitoring:
                if stats.get('alert'):
                    self.perf_status_label.config(text="● 采集中 · 超阈值",
                                                  foreground=self._perf_color('error'))
                else:
                    self.perf_status_label.config(text="● 采集中",
                                                  foreground=self._perf_color('success'))

            # 采样明细表 + 线程表格
            if hasattr(self, 'perf_samples_tree'):
                self._fill_perf_samples()
            if hasattr(self, 'perf_thread_tree'):
                self._fill_thread_table(stats.get('threads', []))

        except Exception as e:
            logging.error(f"[性能监控] UI更新失败: {str(e)}")

    def _fill_perf_samples(self):
        """采样明细增量刷新：新点插到顶部，最新行高亮，最多保留 60 行"""
        try:
            tree = self.perf_samples_tree
            history = self.performance_monitor.history
            if not history:
                return

            # 旧行取消高亮
            children = tree.get_children()
            if children:
                old = tree.item(children[0], 'tags')
                tree.item(children[0], tags=tuple(t for t in old if t != 'last'))

            ts, cpu, pss, rss, java, native, fps, jank = history[-1]
            tags = ('last',)
            if self.performance_monitor.stats.get('alert'):
                tags = ('last', 'alert')
            tree.insert('', 0, tags=tags, values=(
                ts,
                '--' if cpu is None else f"{cpu:.2f}",
                '--' if pss is None else f"{pss:.1f}",
                '--' if rss is None else f"{rss:.1f}",
                '--' if java is None else f"{java:.1f}",
                '--' if native is None else f"{native:.1f}",
                '--' if fps is None else f"{fps:.2f}",
                '--' if jank is None else f"{jank:.2f}"))

            # 截断到 60 行
            children = tree.get_children()
            if len(children) > 60:
                tree.delete(*children[60:])
        except Exception as e:
            logging.debug(f"[性能监控] 采样表刷新失败: {e}")

    def _fill_thread_table(self, threads: list):
        """线程表增量刷新：按 tid 复用行，避免每次采样全量重建"""
        try:
            tree = self.perf_thread_tree
            col = getattr(self, '_perf_thread_sort_col', 'cur')
            rev = getattr(self, '_perf_thread_sort_rev', True)

            def sort_key(t):
                v = t.get(col)
                if isinstance(v, str):
                    return v.lower()
                return v if v is not None else -1

            ordered = sorted(threads, key=sort_key, reverse=rev)

            if not hasattr(self, '_perf_thread_items'):
                self._perf_thread_items = {}
            items = self._perf_thread_items

            # 移除已消失的线程行
            alive = {t['tid'] for t in ordered}
            for tid, item in list(items.items()):
                if tid not in alive:
                    if tree.exists(item):
                        tree.delete(item)
                    items.pop(tid, None)

            # 新增或更新
            for i, t in enumerate(ordered):
                values = (t['tid'], t['name'],
                          f"{t['cur']:.2f}", f"{t['avg']:.2f}", f"{t['peak']:.2f}")
                item = items.get(t['tid'])
                if item and tree.exists(item):
                    tree.item(item, values=values)
                else:
                    items[t['tid']] = tree.insert('', tk.END, values=values)

            # 按当前排序重排（仅移动行，不重建）
            for i, t in enumerate(ordered):
                tree.move(items[t['tid']], '', i)

        except Exception as e:
            logging.debug(f"[性能监控] 线程表刷新失败: {e}")

    
    # ==================== 脚本运行相关方法 ====================
    
    def browse_script(self):
        """选择脚本文件"""
        from tkinter import filedialog
        script_path = filedialog.askopenfilename(
            title="选择Shell脚本文件",
            filetypes=[("Shell脚本", "*.sh"), ("所有文件", "*.*")]
        )
        if script_path:
            self.script_entry.delete(0, tk.END)
            self.script_entry.insert(0, script_path)
            self.update_status(f"✅ 已选择脚本: {os.path.basename(script_path)}", True)
    
    def push_script_to_device(self):
        """推送脚本到设备（智能检测版本）"""
        try:
            # 获取脚本路径
            script_path = self.script_entry.get().strip()
            if not script_path:
                self.update_status("❌ 请先选择脚本文件", False)
                return
                
            if not os.path.exists(script_path):
                self.update_status(f"❌ 脚本文件不存在: {script_path}", False)
                return
                
            # 获取文件名
            script_name = os.path.basename(script_path)
            device_path = f"/data/local/tmp/{script_name}"
                
            # 🆕 先检查设备上是否已存在相同版本的脚本
            need_push = self._check_and_push_script_if_needed(script_path, device_path)
                
            if not need_push:
                # 脚本已存在且无需更新，询问用户是否强制推送
                from tkinter import messagebox
                result = messagebox.askyesno(
                    "脚本已存在",
                    f"设备上已存在相同版本的脚本:\n{script_name}\n\n是否仍要重新推送？",
                    icon="question"
                )
                if not result:
                    self.update_status("❌ 已取消推送", False)
                    return
                
            # 推送脚本
            self.update_status(f"📤 正在推送脚本: {script_name}...", True)
            output, success = self.run_adb_with_target(f'adb push "{script_path}" {device_path}')
                
            if success:
                self.update_status(f"✅ 脚本推送成功: {device_path}", True)
                    
                # 自动赋予执行权限
                self.update_status(f"🔧 正在赋予执行权限...", True)
                chmod_output, chmod_success = self.run_adb_with_target(f"adb shell chmod +x {device_path}")
                    
                if chmod_success:
                    self.update_status(f"✅ 执行权限已赋予", True)
                    self.update_status(f"💡 点击'启动脚本'按钮运行此脚本", True)
                else:
                    self.update_status(f"⚠️ 权限赋予可能失败: {chmod_output}", False)
            else:
                self.update_status(f"❌ 脚本推送失败: {output}", False)
            
        except Exception as e:
            self.update_status(f"❌ 推送脚本出错: {str(e)}", False)
    
    def start_script_on_device(self):
        """在设备上启动脚本（异步执行）"""
        import threading
        
        # 获取脚本路径
        script_path = self.script_entry.get().strip()
        if not script_path:
            self.update_status("❌ 请先选择脚本文件", False)
            return
        
        # 在后台线程中执行启动操作
        thread = threading.Thread(target=self._start_script_async, args=(script_path,), daemon=True)
        thread.start()
        self.update_status("⏳ 正在后台启动脚本...", True)
    
    def _check_and_push_script_if_needed(self, script_path, device_path):
        """检查并推送脚本（如果需要）
        
        Args:
            script_path: 本地脚本路径
            device_path: 设备上的脚本路径
            
        Returns:
            bool: 是否需要推送
        """
        try:
            import logging
            import os
            
            # 检查本地文件是否存在
            if not os.path.exists(script_path):
                self.update_status(f"❌ 本地脚本文件不存在: {script_path}", False)
                return False
            
            # 检查设备上是否存在脚本
            check_output, check_success = self.run_adb_with_target(f"adb shell ls -l {device_path}")
            
            if not check_success or "No such file" in check_output:
                # 设备上不存在脚本，需要推送
                logging.info(f"[脚本检查] 设备上未找到脚本，需要推送")
                return True
            
            # 解析设备上的文件信息
            device_file_info = check_output.strip()
            logging.info(f"[脚本检查] 设备上的文件信息: {device_file_info}")
            
            # 获取本地文件信息
            local_file_size = os.path.getsize(script_path)
            local_mod_time = os.path.getmtime(script_path)
            
            # 尝试从设备输出中提取文件大小（不同Android版本格式可能不同）
            # 格式示例: "-rwxr-xr-x 1 root root 1234 2024-01-01 12:00 script.sh"
            parts = device_file_info.split()
            device_file_size = None
            
            for i, part in enumerate(parts):
                if part.isdigit() and i > 2:  # 文件大小通常是数字
                    try:
                        device_file_size = int(part)
                        break
                    except ValueError:
                        continue
            
            # 如果文件大小不同，需要重新推送
            if device_file_size is not None and device_file_size != local_file_size:
                logging.info(f"[脚本检查] 文件大小不同 (本地: {local_file_size}, 设备: {device_file_size})，需要推送")
                self.update_status(f"📝 检测到脚本已更新，正在重新推送...", True)
                return True
            
            # 文件大小相同，认为脚本已存在且无需更新
            logging.info(f"[脚本检查] ✅ 脚本已存在且无需更新")
            self.update_status(f"✅ 脚本已存在于设备上（无需重新推送）", True)
            return False
            
        except Exception as e:
            import logging
            import traceback
            logging.error(f"[脚本检查] 检查出错: {str(e)}\n{traceback.format_exc()}")
            # 出错时保守处理，建议推送
            return True
    
    def _start_script_async(self, script_path):
        """异步启动脚本（在后台线程中执行）"""
        try:
            import logging
            
            logging.info(f"[脚本启动] 开始启动脚本: {script_path}")
            
            # 获取文件名
            script_name = os.path.basename(script_path)
            device_path = f"/data/local/tmp/{script_name}"
            log_path = f"/data/local/tmp/{script_name}.log"
            
            logging.info(f"[脚本启动] 脚本名称: {script_name}")
            logging.info(f"[脚本启动] 设备路径: {device_path}")
            logging.info(f"[脚本启动] 日志路径: {log_path}")
            
            # 🆕 智能检查并推送脚本（如果需要）
            need_push = self._check_and_push_script_if_needed(script_path, device_path)
            
            if need_push:
                # 需要推送脚本
                self.update_status(f"📤 正在推送脚本到设备...", True)
                push_output, push_success = self.run_adb_with_target(f'adb push "{script_path}" {device_path}')
                
                if not push_success:
                    self.update_status(f"❌ 脚本推送失败: {push_output}", False)
                    logging.error(f"[脚本启动] ❌ 脚本推送失败: {push_output}")
                    return
                
                self.update_status(f"✅ 脚本推送成功", True)
                
                # 赋予执行权限
                self.update_status(f"🔧 正在赋予执行权限...", True)
                chmod_output, chmod_success = self.run_adb_with_target(f"adb shell chmod +x {device_path}")
                
                if chmod_success:
                    self.update_status(f"✅ 执行权限已赋予", True)
                else:
                    self.update_status(f"⚠️ 权限赋予可能失败: {chmod_output}", False)
            else:
                # 脚本已存在，提示用户
                self.update_status(f"💡 使用设备上已有的脚本", True)
            
            # 检查脚本是否有执行权限
            self.update_status(f"🔍 正在检查执行权限...", True)
            perm_output, perm_success = self.run_adb_with_target(f"adb shell ls -l {device_path}")
            
            logging.info(f"[脚本启动] 权限检查: {perm_output[:200]}")
            
            if perm_success and 'x' in perm_output:
                self.update_status(f"✅ 脚本已有执行权限", True)
                logging.info(f"[脚本启动] ✅ 脚本已有执行权限")
            else:
                self.update_status(f"⚠️ 脚本可能没有执行权限，尝试赋予权限...", True)
                chmod_output, chmod_success = self.run_adb_with_target(f"adb shell chmod +x {device_path}")
                if chmod_success:
                    self.update_status(f"✅ 已赋予执行权限", True)
                    logging.info(f"[脚本启动] ✅ 已赋予执行权限")
                else:
                    self.update_status(f"⚠️ 权限赋予可能失败: {chmod_output}", False)
                    logging.warning(f"[脚本启动] 权限赋予失败: {chmod_output}")
            
            # 启动脚本（后台运行）- 使用更可靠的方式
            self.update_status(f"▶️ 正在启动脚本: {script_name}...", True)
            logging.info(f"[脚本启动] 准备执行启动命令...")
            
            # 方式1: 使用 nohup 后台执行（最可靠的方式）
            start_cmd = f'adb shell "cd /data/local/tmp && nohup ./{script_name} > {log_path} 2>&1 &"'
            logging.info(f"[脚本启动] 执行命令: {start_cmd}")
            
            output, success = self.run_adb_with_target(start_cmd)
            
            logging.info(f"[脚本启动] 启动结果: success={success}, output={output[:200] if output else 'None'}")
            
            if success:
                self.update_status(f"✅ 脚本已在后台启动", True)
                self.update_status(f"📝 日志文件: {log_path}", True)
                self.update_status(f"💡 可使用'导出Monkey日志'按钮查看日志", True)
                logging.info(f"[脚本启动] ✅ 脚本启动成功")
                
                # 等待1秒后检查日志文件是否生成
                import time
                self.update_status(f"⏳ 等待1秒后检查日志文件...", True)
                time.sleep(1)
                
                logging.info(f"[脚本启动] 开始检查日志文件是否存在...")
                check_log_output, check_log_success = self.run_adb_with_target(f"adb shell ls -l {log_path}")
                
                logging.info(f"[脚本启动] 日志文件检查: success={check_log_success}, output={check_log_output[:200] if check_log_output else 'None'}")
                
                if check_log_success and "No such file" not in check_log_output:
                    self.update_status(f"✅ 日志文件已生成，脚本正在运行", True)
                    logging.info(f"[脚本启动] ✅ 日志文件已生成，脚本正在运行")
                    
                    # 显示日志文件大小
                    if check_log_output.strip():
                        self.update_status(f"📊 日志文件信息: {check_log_output.strip()}", True)
                else:
                    self.update_status(f"⚠️ 日志文件尚未生成，请检查脚本是否正确", False)
                    logging.warning(f"[脚本启动] ⚠️ 日志文件未生成")
                    
                    # 尝试查看目录内容
                    dir_output, dir_success = self.run_adb_with_target("adb shell ls -la /data/local/tmp/")
                    if dir_success:
                        logging.info(f"[脚本启动] /data/local/tmp 目录内容:\n{dir_output[:500]}")
                        self.update_status(f"📁 /data/local/tmp 目录内容:\n{dir_output[:300]}", True)
            else:
                self.update_status(f"❌ 脚本启动失败: {output}", False)
                logging.error(f"[脚本启动] ❌ 脚本启动失败: {output}")
                
                # 尝试方式2: 使用备用方式
                self.update_status(f"🔄 尝试使用备用启动方式...", True)
                logging.info(f"[脚本启动] 尝试备用启动方式...")
                
                start_cmd2 = f"adb shell nohup sh {device_path} > {log_path} 2>&1 &"
                logging.info(f"[脚本启动] 备用命令: {start_cmd2}")
                
                output2, success2 = self.run_adb_with_target(start_cmd2)
                
                logging.info(f"[脚本启动] 备用启动结果: success={success2}, output={output2[:200] if output2 else 'None'}")
                
                if success2:
                    self.update_status(f"✅ 脚本已通过备用方式启动", True)
                    self.update_status(f"📝 日志文件: {log_path}", True)
                    logging.info(f"[脚本启动] ✅ 备用方式启动成功")
                else:
                    self.update_status(f"❌ 备用启动方式也失败: {output2}", False)
                    logging.error(f"[脚本启动] ❌ 备用方式也失败: {output2}")
        
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            logging.error(f"[脚本启动] ❌ 异常: {str(e)}\n{error_traceback}")
            self.update_status(f"❌ 启动脚本出错: {str(e)}", False)
    
    def stop_script_on_device(self):
        """停止设备上运行的脚本"""
        try:
            # 获取脚本路径
            script_path = self.script_entry.get().strip()
            if not script_path:
                self.update_status("❌ 请先选择脚本文件", False)
                return
            
            # 获取文件名
            script_name = os.path.basename(script_path)
            
            # 查找并杀死进程
            self.update_status(f"⏹️ 正在停止脚本: {script_name}...", True)
            
            # 先查找进程
            # ⚠️ 不能写 `| grep {script_name}`：管道由本机 cmd 解析，用户环境没有 grep 会整条失败
            ps_output, ps_success = self.run_adb_with_target("adb shell ps")
            ps_output = "\n".join(filter_lines(ps_output, script_name))

            if ps_success and ps_output.strip():
                # 提取PID并杀死
                lines = ps_output.strip().split('\n')
                for line in lines:
                    parts = line.split()
                    if len(parts) >= 2:
                        pid = parts[1]
                        if pid.isdigit():
                            kill_output, kill_success = self.run_adb_with_target(f"adb shell kill {pid}")
                            if kill_success:
                                self.update_status(f"✅ 已停止进程 PID: {pid}", True)
                            else:
                                self.update_status(f"⚠️ 停止进程 {pid} 失败", False)
            else:
                self.update_status(f"⚠️ 未找到运行中的脚本进程", False)
        
        except Exception as e:
            self.update_status(f"❌ 停止脚本出错: {str(e)}", False)
    
    def clear_tmp_directory(self):
        """清空 /data/local/tmp 目录下的所有文件"""
        try:
            from tkinter import messagebox
            
            # 确认对话框
            result = messagebox.askyesno(
                "确认清空",
                "确定要清空 /data/local/tmp 目录下的所有文件吗？\n\n此操作不可恢复！",
                icon="warning"
            )
            
            if not result:
                self.update_status("❌ 已取消清空操作", False)
                return
            
            self.update_status("🗑️ 正在清空 /data/local/tmp 目录...", True)
            
            # 执行清空命令
            clear_output, clear_success = self.run_adb_with_target("adb shell rm -rf /data/local/tmp/*")
            
            if clear_success:
                self.update_status("✅ /data/local/tmp 目录已清空", True)
                
                # 验证清空结果
                verify_output, verify_success = self.run_adb_with_target("adb shell ls /data/local/tmp/")
                if verify_success and (not verify_output.strip() or "No such file" in verify_output):
                    self.update_status("✅ 验证成功：目录已完全清空", True)
                else:
                    self.update_status(f"⚠️ 目录下可能还有文件:\n{verify_output}", False)
            else:
                self.update_status(f"❌ 清空失败: {clear_output}", False)
        
        except Exception as e:
            self.update_status(f"❌ 清空目录出错: {str(e)}", False)
    
    def export_monkey_logs(self):
        """导出Monkey日志"""
        try:
            # 获取用户设置的日志路径
            user_log_path = self.log_path_entry.get().strip()
            if not user_log_path:
                user_log_path = self.default_log_path
            
            # 确保路径存在
            os.makedirs(user_log_path, exist_ok=True)
            
            # 列出设备上的日志文件
            self.update_status(f"🔍 正在查找 /data/local/tmp 下的日志文件...", True)
            ls_output, ls_success = self.run_adb_with_target("adb shell ls -l /data/local/tmp/*.log")
            
            if not ls_success or "No such file" in ls_output:
                self.update_status(f"⚠️ 未找到日志文件 (*.log)", False)
                return
            
            # 解析日志文件列表
            log_files = []
            for line in ls_output.strip().split('\n'):
                if line.strip() and '.log' in line:
                    # 提取文件名
                    parts = line.split()
                    if parts:
                        filename = parts[-1].split('/')[-1]
                        if filename.endswith('.log'):
                            log_files.append(filename)
            
            if not log_files:
                self.update_status(f"⚠️ 未找到有效的日志文件", False)
                return
            
            # 导出每个日志文件
            exported_count = 0
            for log_file in log_files:
                device_path = f"/data/local/tmp/{log_file}"
                local_path = os.path.join(user_log_path, log_file)
                
                self.update_status(f"📥 正在导出: {log_file}...", True)
                pull_output, pull_success = self.run_adb_with_target(f"adb pull {device_path} \"{local_path}\"")
                
                if pull_success:
                    exported_count += 1
                    self.update_status(f"✅ 已导出: {log_file} -> {local_path}", True)
                else:
                    self.update_status(f"❌ 导出失败: {log_file} - {pull_output}", False)
            
            if exported_count > 0:
                self.update_status(f"\n🎉 成功导出 {exported_count} 个日志文件到:\n{user_log_path}", True)
            else:
                self.update_status(f"❌ 没有成功导出任何日志文件", False)
        
        except Exception as e:
            self.update_status(f"❌ 导出日志出错: {str(e)}", False)

