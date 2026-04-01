import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import psutil
import subprocess
import os
import glob
import logging
from typing import Optional, Tuple, Dict, Any
from decorators import require_device_connected
from utils import (
    run_adb_command, timestamp_time,
    extract_version_info, ensure_directory,
    get_next_filename, load_ip_history, save_ip_history,
    load_pkg_history, save_pkg_history, is_valid_package_name,
    get_accurate_package_version, calculate_optimal_workers, format_file_size,
    get_connected_devices, get_connected_devices_simple,
    extract_package_name_from_apk, get_connected_devices_parallel
)
from config import Config
from cache_manager import cache_manager
import concurrent.futures
from device_monitor import DeviceStatusManager

# 配置日志输出
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # 输出到控制台
        logging.FileHandler('adb_tool_debug.log', encoding='utf-8')  # 输出到文件
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
                
        # 线程池管理：用于并发执行功能操作
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=10,  # 增加到 10 个并发线程，提升并发能力
            thread_name_prefix="ADBTask"
        )
        self._running_tasks = {}  # 跟踪正在运行的任务 {future: task_name}
        
        # 长时间运行任务的独立线程管理（不占用线程池）
        self._long_running_threads = []  # 跟踪日志、录屏等长时间运行的线程
        self._cleanup_interval = 300  # 清理已完成线程的间隔（秒）
        self._last_cleanup_time = time.time()
        
        # 设备监控管理器
        self.device_monitor_manager = None
                
        self._init_variables()
        self._setup_gui()
        # 注意：_delayed_initialization 已经在_setup_gui 中调用，不需要在此重复调用

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
            self.root.after(0, lambda: self._handle_detected_devices(connected_devices))
        except Exception as error:
            error_msg = str(error)
            self.root.after(0, lambda msg=error_msg: self.update_status(f"启动时设备检测失败：{msg}", False))
    
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
        
    def _async_device_detection_full(self):
        """完整的异步设备检测（包含 IP 历史记录更新）"""
        try:
            # 在主线程中执行完整的设备检测逻辑
            self.root.after(0, self._detect_connected_devices_on_startup)
        except Exception as error:
            error_msg = str(error)
            self.root.after(0, lambda msg=error_msg: self.update_status(f"启动时设备检测失败：{msg}", False))

    def _async_device_detection(self):
        """异步设备检测（简化版本）"""
        try:
            connected_devices = get_connected_devices()
            # 在主线程中更新 UI
            self.root.after(0, lambda: self._handle_detected_devices(connected_devices))
        except Exception as error:
            error_msg = str(error)
            self.root.after(0, lambda msg=error_msg: self.update_status(f"启动时设备检测失败：{msg}", False))

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

    def _load_all_history_async(self):
        """异步加载所有历史记录（合并 IP 和 pkg 历史）"""
        # 在后台线程中同时加载两种历史记录
        def load_history():
            try:
                # 加载 IP 历史
                file_history = load_ip_history()
                merged_history = []
                for device in self.ip_history:
                    if device not in merged_history:
                        merged_history.append(device)
                for item in file_history:
                    if item not in merged_history:
                        merged_history.append(item)
                merged_history = merged_history[:Config.MAX_IP_HISTORY]
                
                # 加载 pkg 历史
                pkg_history = load_pkg_history()
                
                # 在主线程中更新 UI
                self.root.after(0, lambda: self._update_history_ui(merged_history, pkg_history))
            except Exception as error:
                error_msg = str(error)
                self.root.after(0, lambda msg=error_msg: self.update_status(f"加载历史记录失败：{msg}", False))
        
        # 启动后台线程
        thread = threading.Thread(target=load_history, daemon=True)
        thread.start()
    
    def _update_history_ui(self, ip_history, pkg_history):
        """更新历史记录 UI"""
        self.ip_history = ip_history
        self.pkg_history = pkg_history
        
        if hasattr(self, 'ip_combobox'):
            self.ip_combobox['values'] = self.ip_history
        if hasattr(self, 'pkg_combobox'):
            self.pkg_combobox['values'] = self.pkg_history
    
    def _ensure_directories_async(self):
        """异步创建必要目录"""
        try:
            Config.ensure_directories()
        except Exception as e:
            self.update_status(f"创建目录失败：{str(e)}", False)
    
    def _detect_connected_devices_on_startup(self):
        """启动时检测已连接的设备并更新IP历史记录"""
        try:
            # 获取当前连接的设备
            connected_devices = get_connected_devices()
            
            if connected_devices:
                # 提取所有设备（包括 USB 设备和网络 IP）
                detected_devices = []
                for device in connected_devices:
                    if device not in detected_devices:
                        detected_devices.append(device)
                            
                # 将所有设备添加到历史记录中（保持原有顺序，新设备放在前面）
                for device in detected_devices:
                    if device not in self.ip_history:
                        self.ip_history.insert(0, device)
                                
                # 限制历史记录数量
                self.ip_history = self.ip_history[:Config.MAX_IP_HISTORY]
                            
                # 保存到文件
                save_ip_history(self.ip_history)
                            
                # 更新下拉框
                if hasattr(self, 'ip_combobox'):
                    self.ip_combobox['values'] = self.ip_history
                    # 如果输入框为空或只有默认值，设置第一个检测到的设备
                    current_value = self.ip_combobox.get().strip()
                    if not current_value or current_value == "192.168." and self.ip_history:
                        self.ip_combobox.delete(0, tk.END)
                        self.ip_combobox.insert(0, self.ip_history[0])
                        # 触发 IP 变更事件以更新连接状态
                        self.on_ip_changed()
                            
                # 显示检测结果（显示所有设备）
                self.update_status(f"启动时检测到 {len(detected_devices)} 台设备：{', '.join(detected_devices)}", True)
            else:
                # 没有检测到设备时的提示
                self.update_status("启动时未检测到已连接的设备", True)
                
        except Exception as e:
            self.update_status(f"启动时设备检测失败: {str(e)}", False)
    
    def _handle_detected_devices(self, devices):
        """处理检测到的设备"""
        if devices:
            self.update_status(f"启动时检测到 {len(devices)} 台已连接设备", True)
        else:
            self.update_status("启动时未检测到已连接的设备", True)

    def _save_pkg_to_history(self, pkg_name: str) -> None:
        """保存包名到历史记录
        
        Args:
            pkg_name: 要保存的包名
        """
        if pkg_name and pkg_name.strip() and is_valid_package_name(pkg_name.strip()):
            pkg_name = pkg_name.strip()
            if pkg_name not in self.pkg_history:
                self.pkg_history.insert(0, pkg_name)
                save_pkg_history(self.pkg_history)
                if hasattr(self, 'pkg_combobox'):
                    self.pkg_combobox['values'] = self.pkg_history
    
    def _save_apk_to_history(self, apk_path: str) -> None:
        """保存 APK 路径到历史记录（增强版 - 同时更新下拉框）"""
        try:
            # 获取当前历史记录
            if hasattr(self, 'apk_combobox'):
                current_values = list(self.apk_combobox['values'])
                
                # 如果路径已存在，先移除
                if apk_path in current_values:
                    current_values.remove(apk_path)
                
                # 添加到最前面
                current_values.insert(0, apk_path)
                
                # 限制历史记录数量（最多 20 条）
                if len(current_values) > 20:
                    current_values = current_values[:20]
                
                # 更新下拉框
                self.apk_combobox['values'] = tuple(current_values)
        except:
            pass  # 失败不提示
                    
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
        """当 IP 地址改变时触发，显示当前设备状态（极致优化版）"""
        # 立即更新连接状态（不使用防抖）
        self.update_connection_status()
            
        # 获取当前 IP 地址
        current_ip = self.get_ip_address()
        if current_ip and current_ip != "192.168.":
            # 只在下拉框选择时才刷新设备状态
            if event and event.type == 'VirtualEvent' and event.name == 'ComboboxSelected':
                self.show_current_device_status(force_display=True)

    def update_connection_status(self, ip_address: Optional[str] = None):
        """更新连接状态标签（支持 USB 设备）"""
        if not hasattr(self, 'connection_status_label'):
            return
            
        if not ip_address:
            ip_address = self.get_ip_address()
            
        # 获取所有已连接设备
        devices = get_connected_devices()
            
        if not devices:
            self.connection_status_label.config(text="未连接", foreground="gray")
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
                self.connection_status_label.config(text=f"✓ USB 设备", foreground="green")
            else:
                self.connection_status_label.config(text="未连接", foreground="gray")
            return
            
        # 有 IP 地址时，检查是否匹配任何已连接设备
        is_connected = False
        for device in devices:
            if device == ip_address or device.startswith(ip_address + ':'):
                is_connected = True
                break
            
        if is_connected:
            self.connection_status_label.config(text="✓ 已连接", foreground="green")
        else:
            self.connection_status_label.config(text="✗ 未连接", foreground="red")

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
                    self.root.after(0, lambda: self._sync_device_to_ip_input(first_device))
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
            self.root.after(0, self.update_connection_status)
            
            # 【优化】移除详细设备信息获取（这个太耗时，用户需要时可以单独点击"获取设备信息"）
            # self.root.after(100, lambda: self._get_detailed_device_info())
            logging.info("[后台线程] 执行完成（不获取详细信息）")
        except Exception as e:
            logging.error(f"[后台线程] 异常：{str(e)}")
            self.update_status(f"获取设备信息失败：{str(e)}", False)
    
    def _sync_device_to_ip_input(self, device: str):
        """同步设备到 IP 输入框"""
        import logging
        logging.info(f"[同步操作] 开始同步设备到 IP 输入框：{device}")
        
        if hasattr(self, 'ip_combobox'):
            # 将设备添加到下拉框历史记录
            if device not in self.ip_history:
                self.ip_history.insert(0, device)
                self.ip_history = self.ip_history[:Config.MAX_IP_HISTORY]
                from utils import save_ip_history
                save_ip_history(self.ip_history)
                self.ip_combobox['values'] = self.ip_history
                logging.info(f"[同步操作] 已更新下拉框历史记录：{self.ip_history}")
            
            # 设置当前选中的设备
            self.ip_combobox.delete(0, tk.END)
            self.ip_combobox.insert(0, device)
            logging.info(f"[同步操作] 已设置 IP 输入框值为：{device}")
            
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
            self.root.after(0, lambda: self.update_status("⏳ 正在获取设备信息...", True, "info"))
            
            # 使用线程池并行获取（最大速度）
            import concurrent.futures
            import re
            
            def get_prop_quick(prop_name):
                """超快速获取单个属性（1.5 秒超时）"""
                try:
                    output, _ = self.run_adb_with_target(f"adb shell getprop {prop_name}")
                    return output.strip() if output else None
                except:
                    return None
            
            # 核心信息（6 个，必获取）
            core_props = {
                "Android 版本": "ro.build.version.release",
                "SDK 版本": "ro.build.version.sdk",
                "设备型号": "ro.product.model",
                "品牌": "ro.product.brand",
                "安全补丁": "ro.build.version.security_patch",
                "CPU ABI": "ro.product.cpu.abi",
            }
            
            # 并行获取核心属性（4 线程并发）
            core_results = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_to_name = {
                    executor.submit(get_prop_quick, prop): name 
                    for name, prop in core_props.items()
                }
                for future in concurrent.futures.as_completed(future_to_name):
                    name = future_to_name[future]
                    try:
                        value = future.result(timeout=1.5)
                        if value:
                            core_results[name] = value
                    except:
                        pass  # 超时或失败就跳过
            
            # 额外信息（串行获取，更详细的设备信息）
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
                    output, _ = self.run_adb_with_target("adb shell getprop ro.serialno")
                    if output and output.strip():
                        extra_info["设备序列号"] = output.strip()
            except:
                # 失败时尝试获取序列号
                try:
                    output, _ = self.run_adb_with_target("adb shell getprop ro.serialno")
                    if output and output.strip():
                        extra_info["设备序列号"] = output.strip()
                except:
                    pass
            
            # 2. 软件版本号
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.build.display.id")
                if output and output.strip():
                    extra_info["软件版本"] = output.strip()
            except:
                pass
            
            # 3. 硬件平台
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.hardware")
                if output and output.strip():
                    extra_info["硬件平台"] = output.strip()
            except:
                pass
            
            # 4. 构建 ID
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.build.id")
                if output and output.strip():
                    extra_info["构建 ID"] = output.strip()
            except:
                pass
            
            # 5. 基带版本
            try:
                output, _ = self.run_adb_with_target("adb shell getprop gsm.version.baseband")
                if output and output.strip():
                    extra_info["基带版本"] = output.strip()
            except:
                pass
            
            # 6. 内核版本（精简）
            try:
                output, _ = self.run_adb_with_target("adb shell uname -r")
                if output and output.strip():
                    extra_info["内核版本"] = output.strip()
            except:
                pass
            
            # 7. 屏幕密度
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.sf.lcd_density")
                if output and output.strip():
                    extra_info["屏幕密度"] = output.strip() + " dpi"
            except:
                pass
            
            # 8. 电池电量
            try:
                output, _ = self.run_adb_with_target("adb shell dumpsys battery | grep level")
                if output and "level" in output:
                    match = re.search(r'level:\s*(\d+)', output)
                    if match:
                        extra_info["电池电量"] = match.group(1) + "%"
            except:
                pass
            
            # 9. 设备制造商
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.product.manufacturer")
                if output and output.strip():
                    extra_info["制造商"] = output.strip()
            except:
                pass
            
            # 10. 产品名称
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.product.name")
                if output and output.strip():
                    extra_info["产品名称"] = output.strip()
            except:
                pass
            
            # 11. 设备代号
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.product.device")
                if output and output.strip():
                    extra_info["设备代号"] = output.strip()
            except:
                pass
            
            # 12. 构建时间
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.build.date.utc")
                if output and output.strip():
                    import datetime
                    timestamp = int(output.strip())
                    build_date = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    extra_info["构建时间"] = build_date
            except:
                pass
            
            # 13. 系统版本
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.build.version.incremental")
                if output and output.strip():
                    extra_info["系统版本号"] = output.strip()
            except:
                pass
            
            # 14. 用户版本
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.build.user")
                if output and output.strip():
                    extra_info["构建用户"] = output.strip()
            except:
                pass
            
            # 15. 主机信息
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.build.host")
                if output and output.strip():
                    extra_info["构建主机"] = output.strip()
            except:
                pass
            
            # 16. 主板信息
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.board.platform")
                if output and output.strip():
                    extra_info["主板平台"] = output.strip()
            except:
                pass
            
            # 17. Bootloader 版本
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.bootloader")
                if output and output.strip():
                    extra_info["Bootloader"] = output.strip()
            except:
                pass
            
            # 18. 蓝牙版本
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.bluetooth.version")
                if output and output.strip():
                    extra_info["蓝牙版本"] = output.strip()
            except:
                pass
            
            # 19. WiFi 芯片版本
            try:
                output, _ = self.run_adb_with_target("adb shell getprop ro.wifi.version")
                if output and output.strip():
                    extra_info["WiFi 版本"] = output.strip()
            except:
                pass
            
            # 20. 屏幕分辨率（如果支持）
            try:
                output, _ = self.run_adb_with_target("adb shell wm size")
                if output and "Physical size" in output:
                    match = re.search(r'Physical size: (\d+x\d+)', output)
                    if match:
                        extra_info["屏幕分辨率"] = match.group(1)
            except:
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
            self.root.after(0, lambda: self.update_status(detailed_info, True, "info"))
            
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"获取设备信息失败：{str(e)}", False))
    
    def _get_detailed_device_info(self):
        """异步获取详细的设备信息（优化版 - 并行获取 + 精简数据）"""
        try:
            current_ip = self.get_ip_address()
            if not current_ip:
                return
            
            # 显示正在获取的提示
            self.root.after(0, lambda: self.update_status("⏳ 正在快速获取设备信息...", True, "info"))
            
            # 使用线程池并行获取（提升速度）
            import concurrent.futures
            
            def get_prop(prop_name):
                """快速获取单个属性（带超时）"""
                try:
                    output, _ = self.run_adb_with_target(f"adb shell getprop {prop_name}")
                    return output.strip() if output else "未知"
                except:
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
                    except:
                        results[name] = "超时"
            
            # 立即显示关键信息（快速响应）
            quick_lines = []
            quick_lines.append("\n" + "="*50)
            quick_lines.append("📱 设备关键信息 (快速获取)")
            quick_lines.append("="*50)
            for name, value in results.items():
                quick_lines.append(f"  {name}: {value}")
            
            quick_info_text = "\n".join(quick_lines)
            self.root.after(0, lambda: self.update_status(quick_info_text, True, "info"))
            
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
                except:
                    pass
                
                # 电池信息（可选）
                try:
                    output, _ = self.run_adb_with_target("adb shell dumpsys battery | grep level")
                    if output and "level" in output:
                        import re
                        match = re.search(r'level:\s*(\d+)', output)
                        if match:
                            info_lines.append(f"  电池电量：{match.group(1)}%")
                except:
                    pass
                
                info_lines.append("="*50)
                detailed_info = "\n".join(info_lines)
                
                # 追加显示
                if info_lines:
                    self.root.after(0, lambda info=detailed_info: self.update_status(f"\n📋 更多设备信息:\n{info}", True, "info"))
            
            # 异步获取完整信息（不阻塞）
            detail_thread = threading.Thread(target=get_full_info, daemon=True)
            detail_thread.start()
            
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"获取设备信息失败：{str(e)}", False))
    
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
        except:
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
        all_devices = get_connected_devices()
        
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
            
        # 配置状态文本框的标签样式
        self.status_text.tag_configure("success", foreground="green")
        self.status_text.tag_configure("error", foreground="red")
        self.status_text.tag_configure("info", foreground="blue")
        self.status_text.tag_configure("warning", foreground="orange")  # 添加警告颜色
            
        # 立即设置默认值和拖拽功能（不延迟）
        self._setup_post_components()
            
        # 延迟加载非关键组件以提高启动速度（从 100ms 减少到 50ms）
        self.root.after(50, self._delayed_initialization)
    
    def _setup_post_components(self):
        """设置 GUI 组件创建完成后的操作"""
        # 设置默认值
        try:
            if hasattr(self, 'log_path_entry') and self.log_path_entry.winfo_exists():
                self.log_path_entry.delete(0, tk.END)
                self.log_path_entry.insert(0, self.default_log_path)
        except Exception:
            pass
            
        # 设置拖拽功能
        self._setup_drag_drop()
    
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
        
    def execute_task_async(self, task_name: str, method_name: str):
        """异步执行任务（底层优化版 - 零阻塞）"""
        if not hasattr(self, method_name):
            self.root.after(0, lambda: self.update_status(f"方法不存在：{method_name}", False))
            return
            
        method = getattr(self, method_name)
            
        # 长时间运行任务使用独立线程（不占用线程池）
        long_running_tasks = ['start_logcat', 'stop_logcat', 'start_recording', 'stop_recording']
            
        if method_name in long_running_tasks:
            # 直接创建线程，零开销
            thread = threading.Thread(
                target=self._execute_method_async,
                args=(task_name, method),
                name=f"AsyncTask-{task_name}-{time.time()}",
                daemon=True
            )
            thread.start()
        else:
            # 使用线程池，但通过 after 避免阻塞
            self.root.after(0, lambda: self._submit_to_pool(task_name, method))
        
    def _submit_to_pool(self, task_name: str, method):
        """提交到线程池（在 UI 线程之外）"""
        try:
            future = self._executor.submit(self._execute_method_async, task_name, method)
            self._running_tasks[future] = task_name
            future.add_done_callback(lambda f: self._on_task_complete(f, task_name))
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"{task_name}提交失败：{str(e)}", False))
        
    def _execute_method_async(self, task_name: str, method):
        """执行方法（精简版）"""
        try:
            result = method()
            return result
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"{task_name}执行出错：{str(e)}", False, "error"))
            return None
        
    def _cleanup_long_running_threads(self):
        """清理已完成的长时间运行线程"""
        current_time = time.time()
        if current_time - self._last_cleanup_time < self._cleanup_interval:
            return
            
        # 移除已结束的线程
        self._long_running_threads = [
            t for t in self._long_running_threads if t.is_alive()
        ]
        self._last_cleanup_time = current_time
        
    def _task_wrapper(self, task_name: str, method):
        """任务包装器（极致精简版）"""
        try:
            # 执行实际方法（装饰器会处理设备连接验证）
            result = method()
            return result
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"{task_name}执行出错：{str(e)}", False, "error"))
            return None
        
    def _on_task_complete(self, future, task_name: str):
        """任务完成回调"""
        if future in self._running_tasks:
            del self._running_tasks[future]
        try:
            result = future.result(timeout=0.1)
            if result is not None:
                self.update_status(f"{task_name}完成", True, "success")
        except Exception:
            pass

    # 状态更新方法
    def update_status(self, message: str, success: bool, msg_type: str = "normal") -> None:
        """
        更新状态文本框（极致优化版 - 零阻塞）
            
        Args:
            message: 要显示的消息
            success: 是否为成功状态
            msg_type: 消息类型 (normal/success/error/warning/info/system)
        """
        # 【日志】记录 UI 更新
        import logging
        logging.info(f"[UI 更新] 类型:{msg_type}, 成功:{success}, 消息:{message[:50]}...")
        
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
        选择 APK 文件（增强版 - 自动提取包名和版本号）
            
        打开文件对话框让用户选择 APK 文件，并将文件路径
        填入到 APK 输入框中，同时提取包名和版本号。
        """
        import logging
        file_path = filedialog.askopenfilename(filetypes=[("APK files", "*.apk")])
        if file_path:
            logging.info(f"[browse_apk] 选择了文件：{file_path}")
            self.apk_entry.delete(0, tk.END)
            self.apk_entry.insert(0, file_path)
                
            # 【新增】自动提取 APK 的包名和版本号
            try:
                from utils import extract_package_name_from_apk
                logging.info(f"[browse_apk] 开始提取 APK 信息")
                package_name = extract_package_name_from_apk(file_path)
                logging.info(f"[browse_apk] 提取结果：{package_name}")
                    
                if package_name:
                    pkg_name = package_name
                    version = ""  # aapt2/aapt 不直接返回版本号
                    logging.info(f"[browse_apk] 提取成功 - 包名：{pkg_name}")
                        
                    # 更新包名输入框
                    if hasattr(self, 'pkg_combobox') and pkg_name:
                        self.pkg_combobox.set(pkg_name)
                        self._save_pkg_to_history(pkg_name)
                        
                    # 【新增】更新版本展示框
                    if version:
                        self.update_version_display(version)
                        self.update_status(f"已识别 APK: {pkg_name} (版本：{version})", True)
                    else:
                        self.update_version_display()
                        self.update_status(f"已识别 APK 包名：{pkg_name}\n💡 点击'获取包名版本号'查看版本", True)
                else:
                    logging.warning(f"[browse_apk] 提取失败，package_name: {package_name}")
                    # 清空版本显示
                    self.update_version_display()
                    self.update_status("无法从 APK 提取包名信息", False)
            except Exception as e:
                logging.error(f"[browse_apk] 提取异常：{str(e)}")
                self.update_version_display()
                self.update_status(f"提取 APK 信息失败：{str(e)}", False)
            
            # 🆕 新增：保存 APK 路径到历史记录
            self._save_apk_to_history(file_path)

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

    @require_device_connected
    def kill_app_process(self):
        """强制停止应用进程"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入需要终止进程的应用包名", False)
            return

        try:
            output, success = self.run_adb_with_target(f"adb shell am force-stop {pkg_name}")
            if success:
                # 保存包名到历史记录
                self._save_pkg_to_history(pkg_name)
                self.update_status(f"成功终止{pkg_name}应用所处进程", True)
            else:
                self.update_status(f"终止{pkg_name}进程失败", False)
        except:
            self.update_status(f"未找到{pkg_name}所属进程:", False)
    
    @require_device_connected
    def start_app(self):
        """启动当前包名应用"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入要启动的应用包名", False)
            return

        try:
            output, success = self.run_adb_with_target(f"adb shell monkey -p {pkg_name} -c android.intent.category.LAUNCHER 1")
            if success:
                # 保存包名到历史记录
                self._save_pkg_to_history(pkg_name)
                self.update_status(f"成功启动{pkg_name}应用", True)
            else:
                self.update_status(f"启动{pkg_name}应用失败", False)
        except Exception as e:
            self.update_status(f"启动应用失败：{str(e)}", False)


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
                # 保存新的 IP 到历史记录
                if ip_address not in self.ip_history:
                    self.ip_history.insert(0, ip_address)
                    save_ip_history(self.ip_history)
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
            self.root.after(0, lambda: self.update_status("⏳ 正在停止 ADB 服务...", True, "info"))
            
            kill_output, kill_success = run_adb_command("adb kill-server")
            logging.info(f"[后台线程] adb kill-server 完成，成功:{kill_success}")
            
            if not kill_success:
                # kill-server 失败也继续执行 start-server
                logging.warning(f"[后台线程] adb kill-server 失败，继续执行 start-server: {kill_output}")
            
            # 等待一小段时间确保服务完全停止
            time.sleep(0.5)
            
            # 步骤 2: 启动 ADB 服务
            logging.info("[后台线程] 开始启动 ADB 服务...")
            self.root.after(0, lambda: self.update_status("⏳ 正在启动 ADB 服务...", True, "info"))
            
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
                
                self.root.after(0, lambda: self.update_status(final_message, True))
                self.root.after(0, self.update_connection_status)
                
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
                
                self.root.after(0, lambda msg=error_message: self.update_status(msg, False))
                
        except Exception as e:
            logging.error(f"[后台线程] 异常：{str(e)}")
            error_msg = f"重启 ADB 服务过程出错：{str(e)}\n\n请尝试：\n1. 关闭其他 ADB 相关程序\n2. 以管理员身份运行本程序"
            self.root.after(0, lambda msg=error_msg: self.update_status(msg, False))

    def check_device_connected(self, ip_address: Optional[str] = None) -> bool:
        """检查设备连接状态(强化版，确保获取最新状态)"""
        if not ip_address:
            ip_address = self.get_ip_address()
            
        if not ip_address:
            return False
            
        # 强制刷新设备列表，不使用缓存
        output, success = run_adb_command("adb devices")
        if success:
            devices = [line.split("\t")[0] for line in output.splitlines()[1:] if "device" in line]
            ip_with_port = f"{ip_address}:5555" if ip_address else None
            
            # 精确匹配设备
            is_connected = False
            for device in devices:
                if device == ip_address or device == ip_with_port or device.startswith(ip_address + ':'):
                    is_connected = True
                    break
            
            # 更新缓存
            cache_manager.set_device_status(ip_address, is_connected)
            return is_connected
        return False

    def ensure_device_connected(self) -> bool:
        """设备连接验证"""
        ip_address = self.get_ip_address()
        if not ip_address:
            self.update_status("请输入IP地址", False)
            return False
        if not self.check_device_connected(ip_address):
            self.update_status(f"设备未连接: {ip_address}", False)
            return False
        return True

    def _show_progress(self):
        """显示进度条动画"""
        self.progress.pack(fill=tk.X, pady=5)
        self.progress.start()

    def _hide_progress(self):
        """隐藏进度条"""
        self.progress.stop()
        self.progress.pack_forget()


    @require_device_connected
    def force_install(self):
        """带进度显示的强制安装"""
        apk_path = self.apk_entry.get()
        if not apk_path:
            self.update_status("请选择APK文件", False)
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
        """实际执行安装并捕获输出"""
        try:
            # 获取目标设备 IP
            target_ip = self.get_ip_address()
                
            # 调试日志
            self._update_install_status(f"[调试] 开始安装，APK 路径：{apk_path}, 目标设备：{target_ip}")
                
            # 获取所有已连接设备并构建支持多设备的安装命令
            from utils import build_adb_command_with_device
                
            # 获取 APK 大小用于计算进度
            apk_size = os.path.getsize(apk_path)
            current_size = 0
                
            # 构建支持多设备的安装命令
            install_cmd = f"adb install -r -d \"{apk_path}\""
            install_cmd = build_adb_command_with_device(install_cmd, target_ip)
                
            # 显示调试信息
            self._update_install_status(f"[调试] 安装命令：{install_cmd}")
            
            # 显示当前操作的设备信息
            if target_ip:
                self._update_install_status(f"正在向设备 {target_ip} 安装应用...")
            else:
                self._update_install_status("正在安装应用...")
            
            process = subprocess.Popen(
                install_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            # 定义需要过滤的关键词
            filter_keywords = ["Performing Streamed Install"]
            installing_started = False

            # 实时捕获输出
            full_output = []  # 保存所有输出用于调试
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    full_output.append(output)  # 保存输出
                    stripped_output = output.strip()
                    
                    # 检测安装开始
                    if "Performing Streamed Install" in stripped_output:
                        installing_started = True
                        self.progress["mode"] = "determinate"
                        self.progress["maximum"] = 100
                        self.progress["value"] = 0
                        current_size = 0
                        self._update_install_status("安装开始，正在传输数据...")
                        continue

                    # 更新进度
                    if installing_started:
                        # 估算进度
                        current_size += len(output)  # 增加已处理的数据大小
                        progress = min(95, int((current_size / apk_size) * 100))
                        self.progress["value"] = progress
                        
                        # 显示传输进度和流量信息
                        transferred = format_file_size(current_size)
                        total = format_file_size(apk_size)
                        self._update_install_status(f"正在传输... {progress}% ({transferred} / {total})")
                        
                        if "Success" in stripped_output:
                            self.progress["value"] = 100
                            self._update_install_status("安装成功")
                        elif "Failure" in stripped_output:
                            self._update_install_status(f"安装失败: {stripped_output}")
                        elif not any(keyword in stripped_output for keyword in filter_keywords):
                            # 只有在不是过滤关键词时才显示详细输出
                            if stripped_output:
                                self._update_install_status(stripped_output)

            # 获取最终结果
            return_code = process.poll()
            success = return_code == 0
            
            # 重置进度条模式
            self.progress["mode"] = "indeterminate"
            self._hide_progress()
            
            # 构建详细的错误信息
            if not success:
                error_detail = "\\n".join(full_output[-5:]) if full_output else "无输出"  # 显示最后5行
                final_output = f"安装失败 (code {return_code})\\n详细信息:\\n{error_detail}"
            else:
                final_output = "安装成功"
            
            self._update_install_status(final_output)
            
            # 如果安装成功，显示APK信息
            if success:
                file_size = format_file_size(os.path.getsize(apk_path))
                apk_name = os.path.basename(apk_path)
                self.update_status(f"安装完成\\n文件: {apk_name}\\n大小: {file_size}\\n目标设备: {target_ip if target_ip else '未知'}", True)
            
        except Exception as e:
            self._update_install_status(f"安装过程出错: {str(e)}")
            self._hide_progress()

    def _update_operation_status(self, operation: str, status: str, details: str = "", msg_type: str = "info"):
        """更新操作状态显示（统一格式 - 零阻塞优化）
            
        Args:
            operation: 操作名称（如“日志捕获”、“屏幕录制”）
            status: 状态（如“开始”、“进行中”、“完成”、“失败”）
            details: 详细信息
            msg_type: 消息类型
        """
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
        """更新安装状态（优化版）"""
        if "成功" in message:
            self.status_text.insert(tk.END, f"\n{message}\n", "success")
        elif "失败" in message or "错误" in message:
            self.status_text.insert(tk.END, f"\n{message}\n", "error")
        else:
            # 一般进度信息使用info标签
            self.status_text.insert(tk.END, f"\n{message}\n", "info")
        self.status_text.see(tk.END)

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
            output, success = self.run_adb_with_target(f"adb uninstall {pkg_name}")
            if success:
                # 保存包名到历史记录
                self._save_pkg_to_history(pkg_name)
                # 清除包信息缓存
                cache_manager.package_cache.delete(f"package_{pkg_name}")
            self.update_status(output, success)
        else:
            self.update_status("已取消卸载操作", True)

    @require_device_connected
    def package_list(self):
        """获取已安装应用包名列表及其版本(优化版，使用动态线程池)"""
        try:
            # 获取所有已安装包名
            output, success = self.run_adb_with_target("adb shell pm list packages")
            if not success:
                self.update_status("获取应用列表失败", False)
                return

            # 清理并获取包名列表
            packages = [line.replace("package:", "").strip() 
                       for line in output.splitlines() if line.strip()]
            
            if not packages:
                self.update_status("未找到已安装的应用", False)
                return
            
            self.update_status(f"正在获取 {len(packages)} 个应用的版本信息...", True)
            
            # 使用动态线程池并行获取版本信息
            max_workers = calculate_optimal_workers(len(packages))
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_package = {
                    executor.submit(self.get_package_version, package): package 
                    for package in packages
                }
                
                processed_count = 0
                for future in concurrent.futures.as_completed(future_to_package):
                    package = future_to_package[future]
                    try:
                        version = future.result()
                        version_str = version if version else "未知"
                        self.status_text.insert(
                            tk.END, 
                            f"\n{package} (版本: {version_str})", 
                            "info"
                        )
                    except Exception as e:
                        self.status_text.insert(
                            tk.END,
                            f"\n{package} (版本: 获取失败 - {str(e)})",
                            "error"
                        )
                    
                    processed_count += 1
                    # 每处理10个显示一次进度
                    if processed_count % 10 == 0:
                        self.status_text.insert(
                            tk.END,
                            f"\n已处理 {processed_count}/{len(packages)} 个应用",
                            "info"
                        )
                    
                    self.status_text.see(tk.END)
                    
            self.update_status(f"\n获取应用列表完成，共 {len(packages)} 个应用", True)
            
        except Exception as e:
            self.update_status(f"获取应用列表时出错: {str(e)}", False)

    def get_package_version(self, package_name: str) -> Optional[str]:
        """获取应用版本号(优化版，优先获取最新版本)"""
        # 检查缓存
        cached_info = cache_manager.get_package_info(package_name)
        if cached_info and 'version' in cached_info:
            return cached_info['version']
            
        # 使用新的精确版本获取方法
        version = get_accurate_package_version(package_name)
        
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
            output, success = self.run_adb_with_target(f"adb shell pm clear {pkg_name}")
            if success:
                # 保存包名到历史记录
                self._save_pkg_to_history(pkg_name)
                # 清除包信息缓存
                cache_manager.package_cache.delete(f"package_{pkg_name}")
            self.update_status(output, success)
        else:
            self.update_status("已取消清理缓存操作", True)

    @require_device_connected
    def root_device(self):
        """获取root权限"""
        output, success = self.run_adb_with_target("adb root")
        self.update_status(output, success)

    @require_device_connected
    def pull_anr_file(self):
        """拉取ANR文件"""
        # 获取用户自定义的日志存储路径
        from utils import get_user_defined_log_path
        user_log_path = get_user_defined_log_path(self)
        # 在用户路径下创建anr_files子目录
        anr_dir = ensure_directory(os.path.join(user_log_path, "anr_files"))
        output, success = self.run_adb_with_target(f"adb pull /data/anr \"{anr_dir}\"")
        self.update_status(f"ANR文件已保存至: {anr_dir}", success)

    @require_device_connected
    def remount(self):
        """重新挂载分区"""
        output, success = self.run_adb_with_target("adb remount")
        self.update_status(output, success)

    @require_device_connected
    def get_version(self):
        """获取应用版本"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return
    
        output, success = self.run_adb_with_target(f"adb shell pm dump {pkg_name}")
        if success:
            version = extract_version_info(output)
            if version:
                # 保存包名到历史记录
                self._save_pkg_to_history(pkg_name)
                # 【新增】同步更新版本展示框
                self.update_version_display(version)
                self.update_status(f"当前应用{pkg_name}版本：{version}", True)
            else:
                # 清空版本显示
                self.update_version_display()
                self.update_status("版本信息解析失败", False)
        else:
            # 清空版本显示
            self.update_version_display()
            self.update_status(output, False)

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
            output, success = self.run_adb_with_target("adb reboot")
            if success:
                self.update_status("设备重启中...", True)
                # 清空设备缓存，因为重启后连接状态会发生变化
                cache_manager.device_cache.clear()
            else:
                self.update_status(output, False)
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
            
        output, success = self.run_adb_with_target("adb shell getprop ro.build.version.release")
        if success:
            version = output.strip()
            cache_manager.set_system_info("android_version", version)
            self.update_status(f"Android 版本：{version}", True)
        else:
            self.update_status(output, False)
    
    @require_device_connected
    def send_text_input(self):
        """发送文本输入到设备（只支持数字）"""
        # 获取输入框内容
        if not hasattr(self, 'text_input_entry'):
            self.update_status("文本输入组件未初始化", False)
            return
                
        text_to_send = self.text_input_entry.get().strip()
        if not text_to_send:
            self.update_status("请输入要发送的文本内容", False)
            return
            
        # 检查是否只包含数字
        if not text_to_send.isdigit():
            self.update_status(
                f"⚠ 只支持数字输入\n\n"
                f"请手动输入：{text_to_send}",
                True
            )
            return
            
        # 直接执行 ADB 命令
        self.update_status(f"正在输入：{text_to_send}...", True, "info")
        
        try:
            output, success = self.run_adb_with_target(f'adb shell input text "{text_to_send}"')
            
            if success and not output.strip():
                self.update_status(f"✓ 输入成功：{text_to_send}", True)
            else:
                self.update_status(f"结果：{output}", False)
        except Exception as e:
            self.update_status(f"出错：{str(e)}", False)
    
    def _send_text_simple(self, text: str):
        """发送数字和字母文本（简单直接）"""
        import logging
            
        try:
            # 显示正在发送
            self.update_status(f"正在发送：{text}...", True, "info")
                
            # 使用 input text 命令
            output, success = self.run_adb_with_target(f'adb shell input text "{text}"')
                
            if success and not output.strip():
                # 成功且无错误输出
                self.update_status(f"✓ 已发送：{text}", True)
            elif "NullPointerException" in output or "Exception" in output:
                # 系统限制了 input 命令
                self.update_status(
                    f"✗ 发送失败\n\n"
                    f"原因：设备系统限制了 ADB input 命令\n\n"
                    f"建议：\n"
                    f"1. 重新点击输入框，确保光标闪烁\n"
                    f"2. 切换到系统默认输入法\n"
                    f"3. 或者重启设备后重试\n\n"
                    f"错误信息：{output}",
                    False
                )
            else:
                # 其他错误
                self.update_status(f"发送失败：{output}", False)
                    
        except Exception as e:
            logging.error(f"文本输入失败：{str(e)}")
            self.update_status(f"发送过程出错：{str(e)}", False)
        
    def _send_numeric_text(self, text: str):
        """发送数字和符号文本（简单可靠）"""
        import logging
            
        try:
            # 显示正在发送
            self.update_status(f"正在发送：{text}...", True, "info")
                
            # 使用 input text 命令
            output, success = self.run_adb_with_target(f'adb shell input text "{text}"')
                
            if success and not output.strip():
                # 成功且无错误输出
                self.update_status(f"✓ 已发送：{text}", True)
            elif "NullPointerException" in output or "Exception" in output:
                # 系统限制了 input 命令
                self.update_status(
                    f"✗ 发送失败\n\n"
                    f"原因：设备系统限制了 ADB input 命令\n\n"
                    f"建议：\n"
                    f"1. 重新点击输入框，确保光标闪烁\n"
                    f"2. 切换到系统默认输入法\n"
                    f"3. 或者重启设备后重试\n\n"
                    f"错误信息：{output}",
                    False
                )
            else:
                # 其他错误
                self.update_status(f"发送失败：{output}", False)
                    
        except Exception as e:
            logging.error(f"数字输入失败：{str(e)}")
            self.update_status(f"发送过程出错：{str(e)}", False)
        
    def _send_char_by_char(self, text: str):
        """逐字符发送文本（不破坏输入法状态）"""
        import logging
        import time
            
        try:
            # 先测试 input text 命令是否可用
            test_output, test_success = self.run_adb_with_target('adb shell input text "a"')
            if not test_success or "NullPointerException" in test_output or "Exception" in test_output:
                # input text 命令不可用，使用备用方案
                self._send_via_ime(text)
                return
                
            # 如果测试成功，继续逐字符发送
            # 不切换输入法，保持用户当前输入法状态
            # 直接逐字符发送，让输入法自己处理
                
            success_count = 0
            fail_count = 0
                
            for i, char in enumerate(text):
                try:
                    # 每个字符之间添加短暂延迟，让输入法有时间处理
                    output, success = self.run_adb_with_target(
                        f'adb shell input text "{char}"'
                    )
                        
                    if success and "Exception" not in output and "NullPointerException" not in output:
                        success_count += 1
                    else:
                        fail_count += 1
                        logging.warning(f"字符 '{char}' 输入失败：{output}")
                        
                    # 每发送 1 个字符停顿一下，避免输入过快
                    time.sleep(0.08)
                            
                except Exception as char_error:
                    fail_count += 1
                    logging.error(f"字符 '{char}' 输入异常：{str(char_error)}")
                
            # 显示结果
            if fail_count == 0:
                self.update_status(
                    f"✓ 文本已发送到设备：{text}\n"
                    f"共发送 {success_count} 个字符",
                    True
                )
            elif fail_count < len(text):
                self.update_status(
                    f"⚠ 部分文本发送成功：{text}\n"
                    f"成功：{success_count}/{len(text)} 个字符\n"
                    f"提示：某些字符可能不被当前输入法支持",
                    True
                )
            else:
                self.update_status(
                    f"✗ 文本发送失败\n"
                    f"成功：{success_count}/{len(text)} 个字符\n\n"
                    f"可能原因：\n"
                    f"1. 输入框未获得焦点\n"
                    f"2. 当前输入法不支持 ADB 输入\n"
                    f"3. 设备响应延迟",
                    False
                )
                    
        except Exception as e:
            import logging
            logging.error(f"逐字符输入失败：{str(e)}")
            self.update_status(
                f"逐字符输入失败：{str(e)}\n"
                f"操作建议：\n"
                f"1. 确保输入框已选中（光标闪烁）\n"
                f"2. 尝试切换到系统默认输入法\n"
                f"3. 重新点击输入框后再试",
                False
            )
        
    def _send_via_ime(self, text: str):
        """通过 Unicode 编码方式发送文本（真正支持中文的方法）"""
        import logging
        import time
            
        try:
            logging.info(f"使用 Unicode 编码方式发送：{text}")
                
            # 方法：将每个中文字符转换为 Unicode 编码，然后通过 keyevent 输入
            # 这是最底层、最可靠的方法，因为直接模拟按键事件
                
            success_count = 0
            fail_count = 0
                
            for char in text:
                try:
                    # 获取字符的 Unicode 编码
                    unicode_val = ord(char)
                        
                    # 对于 ASCII 字符（0-127），直接输入
                    if unicode_val < 128:
                        output, success = self.run_adb_with_target(
                            f'adb shell input text "{char}"'
                        )
                        if success:
                            success_count += 1
                        else:
                            fail_count += 1
                    else:
                        # 对于非 ASCII 字符（中文等），使用 Unicode 输入
                        # 通过 input keyevent 模拟按键
                        # 格式：KEYCODE_CHAR + Unicode 值
                            
                        # 方法 1: 使用文本编辑器的方式 - 直接粘贴
                        # 先将字符保存到临时文件
                        temp_file = "/sdcard/input_text.tmp"
                            
                        # 使用 echo 写入文件（支持中文）
                        echo_cmd = f'echo -n "{char}" > {temp_file}'
                        self.run_adb_with_target(f"adb shell {echo_cmd}")
                            
                        # 然后使用 input tap 模拟点击输入框
                        # 但这需要知道输入框坐标，不可行
                            
                        # 方法 2: 使用 am broadcast 直接发送文本
                        # 这是 Android 系统级的文本输入接口
                        broadcast_cmd = f'am broadcast -a ADB_INPUT_TEXT --es text "{char}"'
                        output, success = self.run_adb_with_target(f"adb shell {broadcast_cmd}")
                            
                        if success or "result=0" in output.lower():
                            success_count += 1
                        else:
                            # 如果 broadcast 失败，尝试最后的方法
                            # 使用 settings 命令设置剪贴板
                            clip_cmd = f'pm grant com.android.shell android.permission.WRITE_SECURE_SETTINGS'
                            self.run_adb_with_target(f"adb shell {clip_cmd}")
                                
                            # 然后设置剪贴板
                            clip_set = f'content insert --uri content://clipboard --bind text:s:"{char}"'
                            self.run_adb_with_target(f"adb shell {clip_set}")
                                
                            # 模拟粘贴
                            self.run_adb_with_target("adb shell input keyevent KEYCODE_PASTE")
                            success_count += 1
                            fail_count -= 1  # 不算失败
                        
                    # 每个字符之间停顿
                    time.sleep(0.1)
                            
                except Exception as char_error:
                    fail_count += 1
                    logging.error(f"字符 '{char}' 输入异常：{str(char_error)}")
                
            # 显示结果
            if fail_count == 0:
                self.update_status(
                    f"✓ 文本已发送到设备：{text}\n"
                    f"共发送 {success_count} 个字符",
                    True
                )
            elif fail_count < len(text):
                self.update_status(
                    f"⚠ 部分文本发送成功：{text}\n"
                    f"成功：{success_count}/{len(text)} 个字符",
                    True
                )
            else:
                # 全部失败，提供最实用的建议
                self.update_status(
                    f"✗ 自动输入失败\n\n"
                    f"原因：\n"
                    f"您的设备系统版本限制了所有 ADB 自动输入方式\n\n"
                    f"这是 Android 系统安全策略，不是工具问题\n\n"
                    f"可行的解决方案：\n"
                    f"1. 【推荐】手动输入 - 最快速度\n"
                    f"2. Root 设备后使用自动化工具（如 Auto.js）\n"
                    f"3. 使用 Android 无障碍服务（需要开发辅助应用）",
                    False
                )
                    
        except Exception as e:
            import logging
            logging.error(f"Unicode 输入失败：{str(e)}")
            self.update_status(
                f"Unicode 输入失败：{str(e)}\n\n"
                f"结论：\n"
                f"您的设备不支持 ADB 自动文本输入\n\n"
                f"建议：\n"
                f"1. 手动在设备上输入文本\n"
                f"2. 或者考虑使用其他自动化方案",
                False
            )
        
    def _send_chinese_text(self, text: str):
        """发送中文文本（使用输入法兼容方式）"""
        import logging
        import time
            
        try:
            # 步骤 0: 先检查是否有设备连接
            devices_output, devices_success = self.run_adb_with_target("adb devices")
            if not devices_success:
                self.update_status("设备连接异常，请重新连接设备", False)
                return
            
            # 步骤 1: 检查当前输入法状态
            ime_output, ime_success = self.run_adb_with_target(
                "adb shell ime list -s"
            )
            
            if ime_success and ime_output:
                logging.info(f"可用输入法：{ime_output}")
                
                # 获取当前启用的输入法
                current_ime_output, _ = self.run_adb_with_target("adb shell ime get")
                if current_ime_output:
                    logging.info(f"当前输入法：{current_ime_output.strip()}")
                    
                # 尝试找到并切换到支持中文的输入法
                chinese_imes = [
                    "com.android.inputmethod.pinyin/.PinyinIME",
                    "com.google.android.inputmethod.pinyin/.AndroidLatinIME",
                    "com.sohu.inputmethod.sogou/.SogouIME",
                    "com.baidu.input/.ImeService",
                    "com.iflytek.inputmethod/.FlyIME",
                    "com.qq.pinyin/.QQPinyinIME",
                    "com.google.android.inputmethod.latin/.LatinIME"  # GBoard
                ]
                    
                current_ime = None
                for ime in chinese_imes:
                    if ime in ime_output:
                        current_ime = ime
                        break
                    
                if current_ime:
                    # 切换到中文输入法
                    set_ime_output, set_ime_success = self.run_adb_with_target(
                        f"adb shell ime set {current_ime}"
                    )
                    if set_ime_success:
                        logging.info(f"已切换到输入法：{current_ime}")
                        time.sleep(0.5)  # 等待输入法切换完成
                    else:
                        logging.warning(f"切换输入法失败：{set_ime_output}")
                else:
                    logging.warning("未找到支持的中文输入法，将尝试使用默认输入法")
            else:
                logging.warning(f"获取输入法列表失败：{ime_output}")
            
            # 步骤 2: 检查是否有焦点（通过检查当前聚焦的窗口）
            focus_output, focus_success = self.run_adb_with_target(
                "adb shell dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"
            )
            if focus_success and focus_output:
                logging.info(f"当前焦点窗口：{focus_output}")
            
            # 步骤 3: 逐字符发送文本（使用增强的转义处理）
            success_count = 0
            fail_count = 0
            
            # 对特殊字符进行转义
            special_chars = ['"', "'", "\\", "$", "`", "(", ")", "[", "]", "{", "}", "<", ">", "|", "&", ";"]
            
            for i, char in enumerate(text):
                try:
                    # 对特殊字符进行转义
                    if char in special_chars:
                        # 使用 Unicode 编码输入特殊字符
                        unicode_val = ord(char)
                        # 使用 input keyevent 模拟输入（对于特殊字符）
                        char_output, char_success = self.run_adb_with_target(
                            f'adb shell input text "{char}"'
                        )
                    else:
                        # 普通字符直接输入
                        char_output, char_success = self.run_adb_with_target(
                            f'adb shell input text "{char}"'
                        )
                    
                    if char_success:
                        success_count += 1
                    else:
                        fail_count += 1
                        logging.warning(f"字符 '{char}' 输入失败：{char_output}")
                    
                    # 每发送 3 个字符稍作停顿，避免输入过快
                    if (i + 1) % 3 == 0:
                        time.sleep(0.15)
                        
                except Exception as char_error:
                    fail_count += 1
                    logging.error(f"字符 '{char}' 输入异常：{str(char_error)}")
            
            # 步骤 4: 显示结果
            if fail_count == 0:
                self.update_status(
                    f"✓ 文本已发送到设备：{text}\n"
                    f"共发送 {success_count} 个字符\n"
                    f"提示：如果输入框未显示，请点击输入框后重试",
                    True
                )
            elif fail_count < len(text):
                self.update_status(
                    f"⚠ 部分文本发送成功：{text}\n"
                    f"成功：{success_count}/{len(text)} 个字符\n"
                    f"可能原因：\n"
                    f"1. 输入框未获得焦点（需光标闪烁）\n"
                    f"2. 某些字符不被当前输入法支持\n"
                    f"3. 设备响应延迟，请稍后重试",
                    True
                )
            else:
                # 全部失败，提供详细诊断
                self.update_status(
                    f"✗ 文本发送失败\n"
                    f"成功：{success_count}/{len(text)} 个字符\n\n"
                    f"诊断步骤：\n"
                    f"1. 确认设备已连接：adb devices\n"
                    f"2. 打开应用并点击输入框\n"
                    f"3. 确保光标在输入框中闪烁\n"
                    f"4. 检查输入法是否为中文\n\n"
                    f"快速解决：\n"
                    f"在设备上手动输入一个字测试，\n"
                    f"如果手动输入正常，请重新点击输入框后再试",
                    False
                )
                
        except Exception as e:
            import logging
            logging.error(f"中文输入失败：{str(e)}")
            self.update_status(
                f"中文输入失败：{str(e)}\n"
                f"操作建议：\n"
                f"1. 在设备上打开目标应用\n"
                f"2. 点击输入框使其获得焦点（光标闪烁）\n"
                f"3. 确保已安装中文输入法（如搜狗、百度等）\n"
                f"4. 重新尝试发送",
                False
            )
    
    @require_device_connected
    def screencap(self):
        """屏幕截图(优化版)"""
        try:
            # 先显示提示信息
            self.update_status("正在截图，请稍候...", True)
            # 强制更新界面
            self.root.update()
            # 短暂延迟，确保提示信息显示
            time.sleep(0.5)
            
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
            
            if success:
                file_size = format_file_size(os.path.getsize(new_file))
                self.update_status(f"截图已保存至路径：{new_file}\n文件大小：{file_size}", True)
            else:
                self.update_status(f"截图失败: {error_msg}", False)
                
        except Exception as e:
            self.update_status(f"截图过程出错: {str(e)}", False)

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
        """开始屏幕录制"""
        if self.recording_active:
            self.update_status("屏幕录制已在进行中", False)
            return

        # 再次检查设备连接状态
        if not self.check_device_connected():
            self.update_status("设备未连接，无法开始录制", False)
            return
            
        # 测试screenrecord命令是否可用
        test_output, test_success = self.run_adb_with_target("adb shell screenrecord --help")
        if not test_success:
            self.update_status(f"ADB screenrecord命令不可用: {test_output}", False)
            return

        # 获取用户输入的日志路径（与日志使用相同路径）
        user_log_path = self.log_path_entry.get().strip()
        if not user_log_path:
            user_log_path = self.default_log_path
            self.log_path_entry.delete(0, tk.END)
            self.log_path_entry.insert(0, user_log_path)

        # 确保路径存在并测试写入权限
        try:
            os.makedirs(user_log_path, exist_ok=True)
            test_file = os.path.join(user_log_path, "test_write.tmp")
            with open(test_file, 'w', encoding='utf-8') as tf:
                tf.write("test")
            os.remove(test_file)
        except PermissionError:
            self.update_status("无权限写入该目录，请以管理员身份运行程序或选择其他目录", False)
            return
        except Exception as e:
            self.update_status(f"创建录制目录失败: {str(e)}", False)
            return

        # 设置录制文件路径（使用简单的临时名称，避免前缀问题）
        recording_file_name = f"temp_rec_{timestamp_time()}.mp4"
        self.recording_file_path = os.path.join(user_log_path, recording_file_name)
        
        # 设置状态
        self.recording_active = True
        
        # 显示启动信息
        self.update_status(f"正在开始屏幕录制...\n目标文件: {self.recording_file_path}", True)

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
            self.update_status(f"启动录制线程时出错：{str(e)}", False)
            self.recording_active = False
        
    def _check_recording_thread_status(self):
        """检查录制线程状态（异步回调）"""
        try:
            if hasattr(self, 'recording_thread') and self.recording_thread.is_alive() and self.recording_active:
                self._update_operation_status("屏幕录制", "运行中", "点击'停止录制'结束录制", "success")
            else:
                self._update_operation_status("屏幕录制", "启动失败", "", "error")
                self.recording_active = False
        except:
            pass

    @require_device_connected  
    def stop_recording(self):
        """停止屏幕录制（彻底优化版 - 完全异步）"""
        if not self.recording_active:
            self.root.after(0, lambda: self.update_status("没有正在进行的录制", False))
            return
    
        # 显示停止提示
        self.root.after(0, lambda: self.update_status("正在停止屏幕录制...", True, "info"))
        self.recording_active = False
    
        # 终止 screenrecord 进程
        if self.recording_subprocess and self.recording_subprocess.poll() is None:
            try:
                self.recording_subprocess.terminate()
            except:
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
            self.root.after(0, lambda: setattr(self, 'recording_active', False))
            self.root.after(0, lambda: setattr(self, 'recording_subprocess', None))
                
            # 通知用户完成
            self.root.after(0, lambda: self.update_status("录制停止操作完成", True, "success"))
                
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"清理录制文件出错：{str(e)}", False))

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
                text=True
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
                except:
                    pass

    # 日志相关方法
    @require_device_connected
    def start_logcat(self):
        """启动日志捕获（优化版，增强预检查和错误处理）"""
        if self.logging_active:
            self.update_status("日志捕获已在运行", False)
            return

        # 再次检查设备连接状态
        if not self.check_device_connected():
            self.update_status("设备未连接，无法启动日志捕获", False)
            return
            
        # 测试ADB logcat命令是否可用
        test_output, test_success = self.run_adb_with_target("adb logcat -d -t 1")
        if not test_success:
            self.update_status(f"ADB logcat命令不可用: {test_output}", False)
            return

        # 获取用户输入的日志路径
        user_log_path = self.log_path_entry.get().strip()
        if not user_log_path:
            # 使用默认路径
            user_log_path = self.default_log_path
            self.log_path_entry.delete(0, tk.END)
            self.log_path_entry.insert(0, user_log_path)

        # 确保路径存在并测试写入权限
        try:
            os.makedirs(user_log_path, exist_ok=True)
            # 测试写入权限
            test_file = os.path.join(user_log_path, "test_write.tmp")
            with open(test_file, 'w', encoding='utf-8') as tf:
                tf.write("test")
            os.remove(test_file)
        except PermissionError:
            self.update_status("无权限写入该目录，请以管理员身份运行程序或选择其他目录", False)
            return
        except Exception as e:
            self.update_status(f"创建日志目录失败: {str(e)}", False)
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
                self.update_status("无法创建唯一文件名", False)
                return
        
        # 设置状态和事件
        self.logging_active = True
        self.stop_event.clear()
        
        # 显示启动信息
        self._update_operation_status("日志捕获", "开始", f"目标文件: {self.log_file_path}")

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
            self.update_status(f"启动日志捕获线程失败：{str(e)}", False)
            self.logging_active = False
        
    def _check_logcat_thread_status(self):
        """检查日志捕获线程状态（异步回调）"""
        try:
            if hasattr(self, 'logcat_thread') and self.logcat_thread.is_alive() and self.logging_active:
                self._update_operation_status("日志捕获", "运行中", "点击'停止日志捕获'结束捕获", "success")
            else:
                self._update_operation_status("日志捕获", "启动失败", "", "error")
                self.logging_active = False
        except:
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
                self.root.after(0, lambda: self.update_status("日志文件不存在，可能捕获过程中出现错误", False))
                self.logging_active = False
                return
                    
            # 检查文件大小
            file_size = os.path.getsize(self.log_file_path)
            if file_size == 0:
                self.root.after(0, lambda: self.update_status("警告：日志文件为空，可能原因：\n1. 设备无日志输出\n2. ADB 连接不稳定\n3. 权限不足\n4. 捕获时间过短", False))
            else:
                file_size_str = format_file_size(file_size)
                self.root.after(0, lambda: self.update_status(f"日志捕获成功，文件大小：{file_size_str}", True))
    
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
                        self.root.after(0, lambda: self.update_status(f"日志捕获已停止\n空日志文件已保存到：{save_path}\n建议检查设备连接和权限设置", False))
                    else:
                        self.root.after(0, lambda: self.update_status(f"日志捕获已停止\n日志文件已保存到：{save_path}", True))
                    break
                        
                except PermissionError as e:
                    last_error = f"权限错误：{str(e)}"
                    if attempt < max_retries - 1:
                        # 缩短等待时间
                        time.sleep(0.5)
                        continue
                except Exception as e:
                    last_error = f"重命名失败：{str(e)}"
                    self.root.after(0, lambda: self.update_status(f"保存日志文件失败：{str(e)}", False))
                    break
    
            # 重置状态
            self.logging_active = False
                
            if not success_save:
                # 如果重命名失败，至少告诉用户原文件位置
                file_size_str = format_file_size(file_size) if file_size > 0 else "空文件"
                self.root.after(0, lambda: self.update_status(f"日志捕获已停止，但文件保存失败。\n原因：{last_error}\n原文件位置：{self.log_file_path}\n文件大小：{file_size_str}", False))
                
            # 清理进程引用
            self.logcat_subprocess = None
                
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"清理日志文件出错：{str(e)}", False))
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
                    stderr=subprocess.PIPE,
                    creationflags=creation_flags,
                    text=True,
                    bufsize=1
                )
                
                # 等待一小段时间确保进程启动
                time.sleep(0.5)
                
                # 验证进程是否成功启动
                if self.logcat_subprocess.poll() is not None:
                    # 进程已经退出，获取错误信息
                    stderr_output = self.logcat_subprocess.stderr.read() if self.logcat_subprocess.stderr else "未知错误"
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
                        os.fsync(f.fileno())  # 强制写入磁盘
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
                stderr_output = self.logcat_subprocess.stderr.read() if self.logcat_subprocess.stderr else "未知错误"
                self.update_status(f"logcat进程异常退出 (代码: {return_code}): {stderr_output}", False)
                
        except Exception as e:
            self.update_status(f"日志捕获过程出错: {str(e)}", False)
        finally:
            # 确保文件正确关闭和进程终止
            if self.logcat_subprocess and self.logcat_subprocess.poll() is None:
                try:
                    self.logcat_subprocess.terminate()
                    self.logcat_subprocess.wait(timeout=3)
                except:
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
            output, success = self.run_adb_with_target("adb logcat -c")
            if success:
                self.update_status("日志清除成功", True)
            else:
                self.update_status(output, False)
        else:
            self.update_status("已取消清理日志操作", True)

    @require_device_connected
    def get_package_name(self):
        """获取当前打开应用包名"""
        try:
            # 尝试第一个命令
            output, success = self.run_adb_with_target("adb shell dumpsys window windows | findstr mCurrentFocus")
            if not success or not output:
                # 如果第一个命令失败，尝试第二个命令
                output, success = self.run_adb_with_target("adb shell dumpsys window | findstr mCurrentFocus")
                if not success or not output:
                    # 如果还是失败，尝试第三个命令
                    output, success = self.run_adb_with_target("adb shell dumpsys activity activities | findstr mResumedActivity")
                    if not success or not output:
                        self.update_status("获取当前应用包名失败", False)
                        return

            # 调试输出
            self.update_status(f"原始输出: {output}", True)
            
            package_name = None
            # 尝试多种格式匹配
            if "u0" in output:
                # 格式1: mCurrentFocus=Window{...u0 包名/活动名}
                try:
                    package_name = output.split("u0 ")[1].split("/")[0].strip()
                except:
                    pass
            
            if not package_name and "Window{" in output:
                # 格式2: mCurrentFocus=Window{...包名/活动名}
                try:
                    package_name = output.split("Window{")[1].split("/")[0].split()[-1].strip()
                except:
                    pass
            
            if not package_name and "ResumedActivity" in output:
                # 格式3: ResumedActivity: ActivityRecord{...包名/活动名}
                try:
                    package_name = output.split("ResumedActivity")[1].split("/")[0].split()[-1].strip()
                except:
                    pass
            
            if not package_name:
                # 格式4: 尝试直接从/分隔的内容中提取
                try:
                    parts = output.split("/")
                    if len(parts) > 1:
                        package_name = parts[0].split()[-1].strip()
                except:
                    pass

            if package_name:
                # 验证包名格式
                if "." in package_name and not package_name.startswith(".") and not package_name.endswith("."):
                    self.update_status(f"当前应用包名: {package_name}", True)
                    # 保存包名到历史记录
                    self._save_pkg_to_history(package_name)
                    # 自动填充包名到输入框
                    if hasattr(self, 'pkg_combobox'):
                        self.pkg_combobox.delete(0, tk.END)
                        self.pkg_combobox.insert(0, package_name)
                    else:
                        self.pkg_entry.delete(0, tk.END)
                        self.pkg_entry.insert(0, package_name)
                else:
                    self.update_status("解析出的包名格式不正确", False)
            else:
                self.update_status("无法解析应用包名", False)
                
        except Exception as e:
            self.update_status(f"获取应用包名时出错: {str(e)}", False)

    @require_device_connected
    def get_package_path(self):
        """获取当前包名应用安装路径"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return
            
        try:
            output, success = self.run_adb_with_target(f"adb shell pm path {pkg_name}")
            if success and output:
                # 保存包名到历史记录
                self._save_pkg_to_history(pkg_name)
                # 移除"package:"前缀并清理输出
                path = output.replace("package:", "").strip()
                self.status_text.insert(tk.END, f"\n应用安装路径：{path}\n", "info")
                self.status_text.see(tk.END)
            else:
                self.update_status(f"未找到包名 {pkg_name} 的安装路径", False)
        except Exception as e:
            self.update_status(f"获取安装路径失败：{str(e)}", False)
        
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
                output, _ = self.run_adb_with_target(f"adb shell top -n 1 | grep {pkg_name}")
                
                if not output or not output.strip():
                    # 方式 2：使用 top -m 1 获取单行
                    output, _ = self.run_adb_with_target(f"adb shell top -m 1 | grep {pkg_name}")
                
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
            except:
                info_lines.append("\n⚠️ 无法获取详细内存信息")
                
            # 3. 获取进程信息
            try:
                output, _ = self.run_adb_with_target(f"adb shell ps -A | grep {pkg_name}")
                if output:
                    lines = output.strip().split('\n')
                    info_lines.append(f"\n【进程信息】")
                    info_lines.append(f"  进程数：{len(lines)}")
                    for i, line in enumerate(lines[:3], 1):  # 只显示前 3 个进程
                        parts = line.split()
                        if len(parts) >= 2:
                            pid = parts[0]
                            info_lines.append(f"  进程{i} PID: {pid}")
            except:
                info_lines.append("\n⚠️ 无法获取进程信息")
                
            # 4. 获取电池消耗（可选）
            try:
                output, _ = self.run_adb_with_target("adb shell dumpsys batterystats --checkin")
                if output and pkg_name in output:
                    info_lines.append("\n【电池消耗】")
                    # 简化显示
                    info_lines.append(f"  有电池消耗记录")
            except:
                pass
                
            info_lines.append("\n" + "="*60)
                
            # 在 UI 线程中显示
            result_text = "\n".join(info_lines)
            self.root.after(0, lambda: self.update_status(result_text, True, "info"))
                
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"获取资源占用失败：{str(e)}", False))
        
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
        """输出所有功能按钮及其对应的adb命令"""
        # 功能名与命令映射
        cmd_map = [
            ("连接 ADB", "adb connect <IP地址>"),
            ("断开所有ADB连接", "adb disconnect"),
            ("强制安装apk", "adb install -r -d <APK路径>"),
            ("卸载当前包名应用", "adb uninstall <包名>"),
            ("获取已安装应用包名列表", "adb shell pm list packages"),
            ("清除应用缓存", "adb shell pm clear <包名>"),
            ("获取Root权限", "adb root"),
            ("导出ANR文件", "adb pull /data/anr <本地目录>"),
            ("重新挂载分区", "adb remount"),
            ("获取当前包名版本号", "adb shell pm dump <包名> | 查找versionName"),
            ("重启设备", "adb reboot"),
            ("获取Android版本号", "adb shell getprop ro.build.version.release"),
            ("清除日志缓存", "adb logcat -c"),
            ("获取当前打开应用包名", "adb shell dumpsys window windows | findstr mCurrentFocus 或 adb shell dumpsys activity activities | findstr mResumedActivity"),
            ("截取当前屏幕", "adb shell screencap -p /sdcard/screenshot.png && adb pull /sdcard/screenshot.png <本地路径>"),
            ("获取设备串号", "adb shell getprop ro.serialno 或备用方案（优先硬件串号）"),
            ("启动日志捕获", "adb logcat -v time *:V > <本地路径>"),
            ("停止日志捕获", "结束logcat进程"),
            ("开始屏幕录制", "adb shell screenrecord /sdcard/temp_recording.mp4 && adb pull /sdcard/temp_recording.mp4 <本地路径>"),
            ("停止屏幕录制", "终止screenrecord进程并下载视频文件"),
            ("终止当前包名所有进程", "adb shell am force-stop <包名>"),
            ("获取当前包名应用安装路径", "adb shell pm path <包名>"),
        ]
        self.status_text.insert(tk.END, "\n功能按钮与对应 ADB 命令如下：\n", "info")
        for name, cmd in cmd_map:
            self.status_text.insert(tk.END, f"{name}：{cmd}\n", "info")
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
                self.status_text.insert(tk.END, f"  {cmd_index:2d}. {name:<20} → {cmd}\n", "info")
                cmd_index += 1
                
            # 组间空行
            self.status_text.insert(tk.END, "\n", "info")
            
        # 输出结尾
        self.status_text.insert(tk.END, "="*70 + "\n", "info")
        self.status_text.insert(tk.END, "💡 提示：将 <xxx> 替换为实际参数值\n", "info")
        self.status_text.insert(tk.END, "="*70 + "\n", "info")
        self.status_text.see(tk.END)
    
    def execute_quick_command(self):
        """执行快捷命令（支持用户自定义输入）"""
        try:
            # 获取输入的命令
            if not hasattr(self, 'quick_cmd_combobox'):
                return
            
            cmd = self.quick_cmd_combobox.get().strip()
            if not cmd:
                self.update_status("⚠️ 请输入 ADB 命令", False)
                return
            
            # 检查是否连接设备
            target_ip = self.get_ip_address()
            if not target_ip or target_ip == "192.168.":
                self.update_status("⚠️ 请先连接设备", False)
                return
            
            # 显示正在执行
            self.update_status(f"⏳ 正在执行命令：{cmd}\n", True)
            
            # 使用后台线程执行（优化：直接创建线程，不使用线程池）
            import threading
            thread = threading.Thread(target=lambda: self._execute_quick_command_async(cmd), daemon=True)
            thread.start()
            
            # 保存到历史记录
            self._save_command_to_history(cmd)
            
        except Exception as e:
            self.update_status(f"❌ 执行命令失败：{str(e)}", False)
    
    def _execute_quick_command_async(self, cmd: str):
        """异步执行快捷命令"""
        try:
            # 执行命令
            output, success = self.run_adb_with_target(cmd)
            
            # 在 UI 线程中显示结果
            if success:
                result_text = f"✅ 命令执行成功:\n{output}"
                self.root.after(0, lambda: self.update_status(result_text, True, "info"))
            else:
                result_text = f"❌ 命令执行失败:\n{output}"
                self.root.after(0, lambda: self.update_status(result_text, False))
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"❌ 执行出错：{str(e)}", False))
    
    def _save_command_to_history(self, cmd: str):
        """保存命令到历史记录"""
        try:
            # 获取当前历史记录
            if hasattr(self, 'quick_cmd_combobox'):
                current_values = list(self.quick_cmd_combobox['values'])
                
                # 如果命令已存在，先移除
                if cmd in current_values:
                    current_values.remove(cmd)
                
                # 添加到最前面
                current_values.insert(0, cmd)
                
                # 限制历史记录数量（最多 20 条）
                if len(current_values) > 20:
                    current_values = current_values[:20]
                
                # 更新下拉框
                self.quick_cmd_combobox['values'] = tuple(current_values)
        except:
            pass  # 失败不提示
    
    def refresh_device_list(self):
        """刷新设备列表（增强版 - 显示设备信息）"""
        try:
            # 执行 adb devices
            output, success = self.run_adb_command("adb devices")
            
            if success and output:
                # 解析设备列表
                devices = []
                lines = output.strip().split('\n')
                
                for line in lines[1:]:  # 跳过标题行
                    if '\t' in line:
                        parts = line.split('\t')
                        if len(parts) >= 2:
                            device_id = parts[0]
                            status = parts[1]
                            
                            if status == 'device':
                                # 获取设备型号（异步，超时 0.5 秒）
                                try:
                                    import subprocess
                                    result = subprocess.run(
                                        ['adb', '-s', device_id, 'shell', 'getprop', 'ro.product.model'],
                                        capture_output=True,
                                        text=True,
                                        timeout=0.5
                                    )
                                    model = result.stdout.strip()
                                    if model:
                                        devices.append(f"{model} - {device_id} ✓")
                                    else:
                                        devices.append(f"{device_id} ✓")
                                except:
                                    devices.append(f"{device_id} ✓")
                
                # 更新 IP 下拉框
                if hasattr(self, 'ip_combobox'):
                    current_ip = self.ip_combobox.get()
                    self.ip_combobox['values'] = tuple(devices)
                    
                    # 尝试恢复当前选择
                    if current_ip:
                        self.ip_combobox.set(current_ip)
                    elif devices:
                        self.ip_combobox.current(0)
        except:
            pass  # 失败不提示

    def _setup_drag_drop(self):
        """设置拖拽APK文件功能"""
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
            import tkinterdnd2 as tkdnd
            from tkinterdnd2 import DND_FILES
            
            def on_drop(event):
                """处理文件拖拽"""
                self.apk_entry.config(background="white")
                
                # 获取拖拽的文件路径
                files = event.data.split()
                if files:
                    file_path = files[0].strip('{}"')  # 移除可能的引号和大括号
                    
                    # 检查文件是否存在且为APK文件
                    if os.path.exists(file_path) and file_path.lower().endswith('.apk'):
                        # 清除占位符
                        self.apk_entry.delete(0, tk.END)
                        self.apk_entry.insert(0, file_path)
                        
                        # 显示文件信息
                        try:
                            file_size = format_file_size(os.path.getsize(file_path))
                            file_name = os.path.basename(file_path)
                            self.update_status(f"📦 已选择APK文件: {file_name}\n📊 文件大小: {file_size}", True)
                        except:
                            self.update_status(f"📦 已选择 APK 文件：{os.path.basename(file_path)}", True)
                                                
                        # 🆕 新增：自动提取包名并更新到输入框（异步执行，不阻塞界面）
                        self.root.after(0, lambda: self._extract_and_update_package_name(file_path))
                            
                        # 提示用户可以安装
                        self.update_status("🚀 请点击'强制安装apk'按钮进行安装", True)
                    else:
                        self.update_status("⚠️ 请拖拽有效的.apk文件", False)
            
            def on_drag_enter(event):
                """鼠标进入拖拽区域时的视觉反馈"""
                self.apk_entry.config(background="lightblue")
            
            def on_drag_leave(event):
                """鼠标离开拖拽区域时恢复原样"""
                self.apk_entry.config(background="white")
            
            # 注册拖拽事件
            self.apk_entry.drop_target_register(DND_FILES)
            self.apk_entry.dnd_bind('<<Drop>>', on_drop)
            self.apk_entry.dnd_bind('<<DragEnter>>', on_drag_enter)
            self.apk_entry.dnd_bind('<<DragLeave>>', on_drag_leave)
            
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
                    self.root.after(0, lambda: self._extract_and_update_package_name(file_path))
            
            # 为apk_entry添加右键菜单
            def show_context_menu(event):
                context_menu = tk.Menu(self.root, tearoff=0)
                context_menu.add_command(label="浏览文件", command=browse_apk_file)
                context_menu.add_separator()
                context_menu.add_command(label="清空", command=lambda: self.apk_entry.delete(0, tk.END))
                context_menu.post(event.x_root, event.y_root)
            
            self.apk_entry.bind("<Button-3>", show_context_menu)

    def show_cache_stats(self):
        """显示缓存统计信息"""
        stats = cache_manager.get_all_stats()
        stats_text = "缓存统计信息:\n"
        for cache_name, cache_stats in stats.items():
            stats_text += f"\n{cache_name}:\n"
            stats_text += f"  大小: {cache_stats['size']}/{cache_stats['max_size']}\n"
            stats_text += f"  超时: {cache_stats['timeout']}秒\n"
        
        self.update_status(stats_text, True)
        
    def clear_all_caches(self):
        """清空所有缓存"""
        result = messagebox.askyesno(
            "确认清空缓存",
            "您确定要清空所有缓存吗？\n\n清空后下次查询可能需要更长时间。",
            icon="question"
        )
        
        if result:
            cache_manager.clear_all()
            self.update_status("已清空所有缓存", True)
        else:
            self.update_status("已取消清空缓存操作", True)
    
    @require_device_connected
    def open_factory_menu(self):
        """打开工厂菜单"""
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
                self.update_status("工厂菜单已打开", True)
            else:
                self.update_status(f"打开工厂菜单失败：{output}", False)
        except Exception as e:
            self.update_status(f"打开工厂菜单时出错：{str(e)}", False)
        
    def open_cmd_window(self):
        """打开 CMD 窗口（在当前目录或设备相关目录）"""
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
                
            # 设置工作目录为应用所在目录
            work_dir = os.path.dirname(os.path.abspath(__file__))
                
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
                except:
                    pass
                
            cleanup_thread = threading.Thread(target=cleanup_bat, daemon=True)
            cleanup_thread.start()
                
            # 显示成功信息
            self.update_status("🖥️ CMD 窗口已打开", True)
                
        except Exception as e:
            self.update_status(f"打开 CMD 窗口失败：{str(e)}", False)

