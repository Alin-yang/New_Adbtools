import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import psutil
import subprocess
import os
import glob
from typing import Optional, Tuple, Dict, Any
from decorators import require_device_connected
from utils import (
    run_adb_command, timestamp_time,
    extract_version_info, ensure_directory,
    get_next_filename, load_ip_history, save_ip_history,
    load_pkg_history, save_pkg_history, is_valid_package_name,
    get_accurate_package_version, calculate_optimal_workers, format_file_size,
    get_connected_devices
)
from config import Config
from cache_manager import cache_manager
import concurrent.futures

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
        self._status_throttle_interval = 0.1  # 100ms节流间隔
        
        self._init_variables()
        self._setup_gui()
        
        # 延迟加载非关键组件以提高启动速度
        self.root.after(100, self._delayed_initialization)

    def _delayed_initialization(self):
        """延迟初始化非关键组件"""
        # 在后台线程中执行设备检测（使用原有的完整检测逻辑）
        device_thread = threading.Thread(target=self._async_device_detection_full, daemon=True)
        device_thread.start()
        
        # 延迟加载历史记录
        self.root.after(200, self._load_ip_history)
        self.root.after(300, self._load_pkg_history)
        self.root.after(400, Config.ensure_directories)

    def _async_device_detection_full(self):
        """完整的异步设备检测（包含IP历史记录更新）"""
        try:
            # 在主线程中执行完整的设备检测逻辑
            self.root.after(0, self._detect_connected_devices_on_startup)
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"启动时设备检测失败: {str(e)}", False))

    def _async_device_detection(self):
        """异步设备检测（简化版本）"""
        try:
            connected_devices = get_connected_devices()
            # 在主线程中更新UI
            self.root.after(0, lambda: self._handle_detected_devices(connected_devices))
        except Exception as e:
            self.root.after(0, lambda: self.update_status(f"启动时设备检测失败: {str(e)}", False))

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

    def _load_ip_history(self):
        """加载 IP 历史记录到下拉框（合并已检测到的设备）"""
        # 从文件加载历史记录
        file_history = load_ip_history()
            
        # 合并已检测到的设备（如果有）
        merged_history = []
        # 先添加已检测到的设备
        for device in self.ip_history:
            if device not in merged_history:
                merged_history.append(device)
        # 再添加文件中的历史记录（去重）
        for item in file_history:
            if item not in merged_history:
                merged_history.append(item)
            
        # 限制数量
        merged_history = merged_history[:Config.MAX_IP_HISTORY]
            
        # 更新实例变量和下拉框
        self.ip_history = merged_history
        if hasattr(self, 'ip_combobox'):
            self.ip_combobox['values'] = self.ip_history

    def _load_pkg_history(self):
        """加载包名历史记录到下拉框"""
        self.pkg_history = load_pkg_history()
        if hasattr(self, 'pkg_combobox'):
            self.pkg_combobox['values'] = self.pkg_history
    
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
        """当IP地址改变时触发，显示当前设备状态"""
        # 立即更新连接状态（不使用防抖）
        self.update_connection_status()
        
        # 获取当前IP地址
        current_ip = self.get_ip_address()
        if current_ip and current_ip != "192.168.":
            # 强制清除相关缓存，确保获取最新状态
            cache_manager.device_cache.clear()
            
            # 区分不同类型的事件
            if event and event.type == 'VirtualEvent' and event.name == 'ComboboxSelected':
                # 下拉框选择事件，立即显示
                self.show_current_device_status(force_display=True)
            elif not event:
                # 程序调用，立即显示
                self.show_current_device_status(force_display=True)
            else:
                # 其他事件（如FocusOut），也强制显示以确保同步
                self.show_current_device_status(force_display=True)

    def update_connection_status(self, ip_address: Optional[str] = None):
        """更新连接状态标签（优化版本，减少不必要的设备检查）"""
        if not hasattr(self, 'connection_status_label'):
            return
        
        if not ip_address:
            ip_address = self.get_ip_address()
        
        if not ip_address or ip_address == "192.168.":
            self.connection_status_label.config(text="未连接", foreground="gray")
            return
        
        # 优化：只在必要时检查设备连接状态
        # 检查是否已经有缓存的结果
        cached_status = cache_manager.get_device_status(ip_address)
        if cached_status is not None:
            # 使用缓存结果
            if cached_status:
                self.connection_status_label.config(text="✓ 已连接", foreground="green")
            else:
                self.connection_status_label.config(text="✗ 未连接", foreground="red")
            return
        
        # 只有缓存失效时才检查设备
        devices = get_connected_devices()
        
        # 标准化IP地址
        if ':' not in ip_address:
            ip_with_port = f"{ip_address}:5555"
        else:
            ip_with_port = ip_address
        
        # 检查是否匹配任何已连接设备
        is_connected = False
        for device in devices:
            if device == ip_with_port or device == ip_address or ip_address in device:
                is_connected = True
                break
        
        # 更新缓存
        cache_manager.set_device_status(ip_address, is_connected)
        
        if is_connected:
            self.connection_status_label.config(text="✓ 已连接", foreground="green")
        else:
            self.connection_status_label.config(text="✗ 未连接", foreground="red")

    def show_device_info(self):
        """显示当前连接的设备信息"""
        devices = get_connected_devices()
        current_ip = self.get_ip_address()
        
        if not devices:
            self.update_status("当前没有连接的设备", False)
            self.update_connection_status()
            return
        
        device_info = f"已连接 {len(devices)} 台设备:\n"
        for i, device in enumerate(devices, 1):
            # 精确匹配当前选中的设备
            marker = ""
            if current_ip:
                # 标准化当前IP（确保包含端口号）
                normalized_current_ip = current_ip
                if ':' not in current_ip:
                    normalized_current_ip = f"{current_ip}:5555"
                
                # 精确匹配：完全匹配或IP前缀匹配（带冒号）
                if device == normalized_current_ip or device == current_ip:
                    marker = " ← 当前选中"
                elif device.startswith(current_ip + ':'):
                    marker = " ← 当前选中"
            
            device_info += f"  {i}. {device}{marker}\n"
        
        self.update_status(device_info, True)
        self.update_connection_status()
    
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
            status_info += ", 未选择目标设备"
        
        self.update_status(status_info, True)
        # 更新上次显示时间
        self.last_device_status_time = current_time
        # 保存当前显示的IP地址用于下次比较
        self._last_displayed_ip = current_ip if current_ip else ""



    def _setup_gui(self) -> None:
        """
        设置图形用户界面
        
        动态调用布局模块的setup_gui方法，配置状态文本框的
        标签样式，并设置默认日志路径。
        """
        # 动态调用布局模块的 setup_gui 方法
        self.layout_module.setup_gui(self)
        
        # 配置状态文本框的标签样式
        self.status_text.tag_configure("success", foreground="green")
        self.status_text.tag_configure("error", foreground="red")
        self.status_text.tag_configure("info", foreground="blue")
        self.status_text.tag_configure("warning", foreground="orange")  # 添加警告颜色
        
        # 使用after确保所有GUI组件都创建完成后再进行后续操作
        self.root.after(100, self._setup_post_components)
    
    def _setup_post_components(self):
        """设置GUI组件创建完成后的操作"""
        # 设置默认值
        try:
            if hasattr(self, 'log_path_entry') and self.log_path_entry.winfo_exists():
                self.log_path_entry.delete(0, tk.END)
                self.log_path_entry.insert(0, self.default_log_path)
        except Exception:
            pass
        
        # 设置拖拽功能
        self._setup_drag_drop()

    # 状态更新方法
    def update_status(self, message: str, success: bool, msg_type: str = "normal") -> None:
        """
        更新状态文本框（优化版）
        
        Args:
            message: 要显示的消息
            success: 是否为成功状态，决定文本颜色
            msg_type: 消息类型 (normal/success/error/warning/info/system)
        """
        # 生成带时间戳的格式化消息
        timestamp = time.strftime("[%H:%M:%S] ", time.localtime())
        
        # 根据消息类型选择标签和格式
        if msg_type == "system":
            # 系统信息：灰色，带系统标识
            formatted_message = f"{timestamp}[系统] {message}"
            tag = "info"
        elif msg_type == "warning":
            # 警告信息：橙色
            formatted_message = f"{timestamp}[警告] {message}"
            tag = "warning"
        elif msg_type == "info":
            # 一般信息：蓝色
            formatted_message = f"{timestamp}[信息] {message}"
            tag = "info"
        elif success and msg_type == "success":
            # 成功信息：绿色，带成功标识
            formatted_message = f"{timestamp}[✓] {message}"
            tag = "success"
        elif not success and msg_type == "error":
            # 错误信息：红色，带错误标识
            formatted_message = f"{timestamp}[✗] {message}"
            tag = "error"
        else:
            # 默认处理：根据success参数
            prefix = "[✓] " if success else "[✗] "
            formatted_message = f"{timestamp}{prefix}{message}"
            tag = "success" if success else "error"
        
        # 插入消息到状态文本框
        self.status_text.insert(tk.END, f"\n{formatted_message}\n", tag)
        self.status_text.see(tk.END)
        
        # 强制更新界面（确保消息立即显示）
        self.root.update_idletasks()

    # 文件选择方法
    def browse_apk(self) -> None:
        """
        选择APK文件
        
        打开文件对话框让用户选择APK文件，并将文件路径
        填入到APK输入框中。
        """
        file_path = filedialog.askopenfilename(filetypes=[("APK files", "*.apk")])
        if file_path:
            self.apk_entry.delete(0, tk.END)
            self.apk_entry.insert(0, file_path)

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


    def get_ip_address(self) -> Optional[str]:
        """
        获取IP地址（仅支持中文版本的Combobox）
        
        Returns:
            Optional[str]: IP地址字符串，如果未输入则返回None
        """
        if hasattr(self, 'ip_combobox'):
            return self.ip_combobox.get().strip()
        return None

    # @require_device_connected
    def connect_adb(self):
        """连接ADB设备"""
        # 显示当前设备状态
        self.show_current_device_status()
        
        ip_address = self.get_ip_address()
        if not ip_address:
            self.update_status(f"请输入IP地址", False)
            self.update_connection_status()
            return False
        
        output, success = self.run_adb_with_target(f"adb connect {ip_address}")
        if "connected" in output.lower():
            # 保存新的IP到历史记录
            if ip_address not in self.ip_history:
                self.ip_history.insert(0, ip_address)
                save_ip_history(self.ip_history)
                if hasattr(self, 'ip_combobox'):
                    self.ip_combobox['values'] = self.ip_history
            self.update_status(output, True)
            # 更新连接状态
            self.update_connection_status(ip_address)
        else:
            self.update_status(output, False)
            self.update_connection_status(ip_address)


    @require_device_connected
    def disconnect_adb(self):
        """断开ADB连接"""
        # 强制显示当前设备状态
        self.show_current_device_status(force_display=True)
        
        output, success = self.run_adb_with_target("adb disconnect")
        if "disconnected" in output.lower():
            self.update_status(output, True)
        else:
            self.update_status(output, False)
        # 更新连接状态
        self.update_connection_status()

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
        self.progress.grid()
        self.progress.start()

    def _hide_progress(self):
        """隐藏进度条"""
        self.progress.stop()
        self.progress.grid_remove()


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
            # 获取目标设备IP
            target_ip = self.get_ip_address()
            
            # 获取所有已连接设备并构建支持多设备的安装命令
            from utils import build_adb_command_with_device
            
            # 获取APK大小用于计算进度
            apk_size = os.path.getsize(apk_path)
            current_size = 0
            
            # 构建支持多设备的安装命令
            install_cmd = f"adb install -r -d \"{apk_path}\""
            install_cmd = build_adb_command_with_device(install_cmd, target_ip)
            
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
        """更新操作状态显示（统一格式）
        
        Args:
            operation: 操作名称（如"日志捕获"、"屏幕录制"）
            status: 状态（如"开始"、"进行中"、"完成"、"失败"）
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
        self.root.update_idletasks()
    
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
                self.update_status(f"当前应用{pkg_name}版本: {version}", True)
            else:
                self.update_status("版本信息解析失败", False)
        else:
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
            self.update_status(f"Android版本: {version}", True)
        else:
            self.update_status(output, False)

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
                self.update_status(f"截图已保存至路径: {new_file}\n文件大小: {file_size}", True)
                # 尝试打开截图所在文件夹
                try:
                    os.startfile(os.path.dirname(new_file))
                except:
                    pass
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
            
            time.sleep(1)
            
            if self.recording_thread.is_alive() and self.recording_active:
                self._update_operation_status("屏幕录制", "运行中", "点击'停止录制'结束录制", "success")
            else:
                self._update_operation_status("屏幕录制", "启动失败", "", "error")
                self.recording_active = False
                
        except Exception as e:
            self.update_status(f"启动录制线程时出错: {str(e)}", False)
            self.recording_active = False

    @require_device_connected  
    def stop_recording(self):
        """停止屏幕录制（按照日志抓取的逻辑，以终止时间命名）"""
        if not self.recording_active:
            self.update_status("没有正在进行的录制", False)
            return

        self.update_status("正在停止屏幕录制...", True)
        self.recording_active = False

        # 终止screenrecord进程
        if self.recording_subprocess and self.recording_subprocess.poll() is None:
            try:
                self.recording_subprocess.terminate()
                self.recording_subprocess.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # 如果温和终止失败，强制杀死
                try:
                    self.recording_subprocess.kill()
                    self.recording_subprocess.wait(timeout=2)
                except:
                    pass
            except Exception:
                pass

        # 等待录制线程结束（参考日志抓取的逻辑）
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=10)  # 增加等待时间到10秒，给足够时间完成重命名
            if self.recording_thread.is_alive():
                self.update_status("警告：录制线程仍在运行，可能正在处理文件操作...", False)
        
        # 重置状态
        self.recording_active = False
        self.recording_subprocess = None
        
        self.update_status("录制停止操作完成", True)

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
            record_cmd = build_adb_command_with_device(f"adb shell screenrecord --bit-rate 4000000 --size 1280x720 {device_temp_file}", target_ip)
            
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
                            
                            # 尝试打开文件夹
                            try:
                                os.startfile(os.path.dirname(new_name))
                            except:
                                pass
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
            
            # 等待一小段时间检查线程是否成功启动
            time.sleep(1)
            
            if self.logcat_thread.is_alive() and self.logging_active:
                self._update_operation_status("日志捕获", "运行中", "点击'停止日志捕获'结束捕获", "success")
            else:
                self._update_operation_status("日志捕获", "启动失败", "", "error")
                self.logging_active = False
                
        except Exception as e:
            self.update_status(f"启动日志捕获线程失败: {str(e)}", False)
            self.logging_active = False

    @require_device_connected
    def stop_logcat(self):
        """停止日志捕获（修复版，解决文件重命名问题）"""
        if not self.logging_active:
            self.update_status("没有正在运行的日志捕获", False)
            return

        # 设置停止信号
        self.stop_event.set()
        self._update_operation_status("日志捕获", "正在停止", "")
        
        # 确保进程终止
        self._terminate_logcat()
        
        # 等待线程结束，给足够的时间让文件句柄释放
        if hasattr(self, 'logcat_thread') and self.logcat_thread.is_alive():
            # 等待线程正常结束
            self.logcat_thread.join(timeout=5)  # 增加等待时间到5秒
            
            # 如果线程仍未结束，通常说明有异常情况
            # 但大多数情况下线程都会正常结束，所以不显示警告
            if self.logcat_thread.is_alive():
                # 只在调试模式下显示，不干扰用户
                pass  # self.update_status("调试：线程仍在运行，将继续等待", True)
        
        # 额外等待确保文件句柄完全释放
        time.sleep(2)

        # 检查文件是否存在和大小
        if not os.path.exists(self.log_file_path):
            self.update_status("日志文件不存在，可能捕获过程中出现错误", False)
            self.logging_active = False
            return
            
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
                    self.update_status(f"日志捕获已停止\n空日志文件已保存到: {save_path}\n建议检查设备连接和权限设置", False)
                else:
                    self.update_status(f"日志捕获已停止\n日志文件已保存到: {save_path}", True)
                
                # 尝试打开日志所在文件夹
                try:
                    os.startfile(os.path.dirname(new_name))
                except:
                    pass  # 忽略打开文件夹的错误
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

        # 重置状态
        self.logging_active = False
        
        if not success_save:
            # 如果重命名失败，至少告诉用户原文件位置
            file_size_str = format_file_size(file_size) if file_size > 0 else "空文件"
            self.update_status(f"日志捕获已停止，但文件保存失败。\n原因: {last_error}\n原文件位置: {self.log_file_path}\n文件大小: {file_size_str}", False)
        
        # 清理进程引用
        self.logcat_subprocess = None

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
                self.status_text.insert(tk.END, f"\n应用安装路径: {path}\n", "info")
                self.status_text.see(tk.END)
            else:
                self.update_status(f"未找到包名 {pkg_name} 的安装路径", False)
        except Exception as e:
            self.update_status(f"获取安装路径失败: {str(e)}", False)

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
        self.status_text.insert(tk.END, "\n功能按钮与对应ADB命令如下：\n", "info")
        for name, cmd in cmd_map:
            self.status_text.insert(tk.END, f"{name}：{cmd}\n", "info")
        self.status_text.see(tk.END)

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
                            self.update_status(f"📦 已选择APK文件: {os.path.basename(file_path)}", True)
                            
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
                    self.update_status(f"已选择APK文件: {os.path.basename(file_path)}", True)
            
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
                self.update_status(f"打开工厂菜单失败: {output}", False)
        except Exception as e:
            self.update_status(f"打开工厂菜单时出错: {str(e)}", False)

