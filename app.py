import sys
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
    get_accurate_package_version, calculate_optimal_workers, format_file_size
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
        self._init_variables()
        self._setup_gui()
        # 加载IP历史记录
        self._load_ip_history()
        # 加载包名历史记录
        self._load_pkg_history()
        # 确保必要目录存在
        Config.ensure_directories()

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

    def _load_ip_history(self):
        """加载IP历史记录到下拉框"""
        self.ip_history = load_ip_history()
        if hasattr(self, 'ip_combobox'):
            self.ip_combobox['values'] = self.ip_history

    def _load_pkg_history(self):
        """加载包名历史记录到下拉框"""
        self.pkg_history = load_pkg_history()
        if hasattr(self, 'pkg_combobox'):
            self.pkg_combobox['values'] = self.pkg_history
    
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

        # 设置日志路径输入框的默认值
        self.log_path_entry.delete(0, tk.END)
        self.log_path_entry.insert(0, self.default_log_path)
        
        # 设置拖拽功能
        self._setup_drag_drop()

    # 状态更新方法
    def update_status(self, message: str, success: bool) -> None:
        """
        更新状态文本框
        
        Args:
            message: 要显示的消息
            success: 是否为成功状态，决定文本颜色
        """
        tag = "success" if success else "error"
        self.status_text.insert(tk.END, f"\n{message}\n", tag)
        self.status_text.see(tk.END)

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
        选择日志存储路径
        
        打开目录选择对话框让用户选择日志存储目录，
        并更新日志路径输入框。
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
            output, success = run_adb_command(f"adb shell am force-stop {pkg_name}")
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
        """连接ADB设备（优化版，增加连接质量检测）"""
        ip_address = self.get_ip_address()
        if not ip_address:
            self.update_status(f"请输入IP地址", False)
            return False
        
        # 先断开可能存在的旧连接
        self.update_status("正在清理旧连接...", True)
        run_adb_command("adb disconnect")
        time.sleep(1)  # 等待断开完成
        
        self.update_status(f"正在连接设备: {ip_address}", True)
        output, success = run_adb_command(f"adb connect {ip_address}")
        
        if "connected" in output.lower():
            # 连接成功后进行连接质量测试
            self.update_status("连接成功，正在验证连接质量...", True)
            
            # 测试连接质量
            test_output, test_success = run_adb_command("adb shell echo 'connection_test'")
            if test_success and "connection_test" in test_output:
                # 保存新的IP到历史记录
                if ip_address not in self.ip_history:
                    self.ip_history.insert(0, ip_address)
                    save_ip_history(self.ip_history)
                    if hasattr(self, 'ip_combobox'):
                        self.ip_combobox['values'] = self.ip_history
                        
                # 更新设备连接状态缓存
                cache_manager.set_device_status(ip_address, True)
                self.update_status(f"设备连接成功且连接质量良好: {ip_address}", True)
                return True
            else:
                self.update_status("连接已建立但连接质量不稳定，建议重新连接", False)
                cache_manager.set_device_status(ip_address, False)
                return False
        else:
            cache_manager.set_device_status(ip_address, False)
            self.update_status(f"连接失败: {output}", False)
            return False


    @require_device_connected
    def disconnect_adb(self):
        """断开ADB连接"""
        output, success = run_adb_command("adb disconnect")
        if "disconnected" in output.lower():
            self.update_status(output, True)
        else:
            self.update_status(output, False)

    def check_device_connected(self, ip_address: Optional[str] = None) -> bool:
        """检查设备连接状态(使用新的缓存系统)"""
        if not ip_address:
            ip_address = self.get_ip_address()
            
        if not ip_address:
            return False
            
        # 检查缓存
        cached_status = cache_manager.get_device_status(ip_address)
        if cached_status is not None:
            return cached_status
            
        output, success = run_adb_command("adb devices")
        if success:
            devices = [line.split("\t")[0] for line in output.splitlines()[1:] if "device" in line]
            ip_with_port = f"{ip_address}:5555" if ip_address else None
            is_connected = ip_address in devices or ip_with_port in devices
            
            # 更新缓存
            cache_manager.set_device_status(ip_address, is_connected)
            return is_connected
        return False

    def ensure_device_connected(self) -> bool:
        """设备连接验证和修复"""
        ip_address = self.get_ip_address()
        if not ip_address:
            self.update_status("请输入IP地址", False)
            return False
            
        # 检查连接状态
        if not self.check_device_connected(ip_address):
            self.update_status(f"设备未连接: {ip_address}", False)
            
            # 提供自动重连选项
            from tkinter import messagebox
            result = messagebox.askyesno(
                "连接问题",
                f"检测到设备 {ip_address} 未连接或连接不稳定。\n\n是否自动重新连接？",
                icon="question"
            )
            
            if result:
                self.update_status("正在尝试重新连接...", True)
                return self.connect_adb()
            else:
                return False
        return True
        
    def check_and_fix_connection(self) -> bool:
        """检查并修复连接问题"""
        ip_address = self.get_ip_address()
        if not ip_address:
            return False
            
        # 检查连接质量
        test_output, test_success = run_adb_command("adb shell echo 'test'")
        if not test_success or "test" not in test_output:
            self.update_status("检测到连接问题，正在尝试修复...", True)
            
            # 尝试重新连接
            run_adb_command("adb disconnect")
            time.sleep(2)
            
            output, success = run_adb_command(f"adb connect {ip_address}")
            if "connected" in output.lower():
                # 再次测试
                test_output2, test_success2 = run_adb_command("adb shell echo 'test'")
                if test_success2 and "test" in test_output2:
                    self.update_status("连接问题已修复", True)
                    return True
                    
            self.update_status("无法修复连接问题，请手动重新连接", False)
            return False
        return True

    def _show_progress(self):
        """显示进度条（简单模式）"""
        self.progress.grid()
        # 设置为确定性进度条，不显示文字
        self.progress["mode"] = "determinate"
        self.progress["maximum"] = 100
        self.progress["value"] = 0

    def _hide_progress(self):
        """隐藏进度条"""
        # 不需要stop()，因为我们使用确定性模式
        self.progress.grid_remove()


    @require_device_connected
    def force_install(self):
        """带进度显示的强制安装"""
        apk_path = self.apk_entry.get()
        if not apk_path:
            self.update_status("请选择APK文件", False)
            return

        # 检查APK文件是否存在
        if not os.path.exists(apk_path):
            self.update_status("APK文件不存在", False)
            return
            
        # 再次检查设备连接状态
        if not self.check_device_connected():
            self.update_status("设备连接状态异常，请重新连接后再试", False)
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
        """实际执行安装并捕获输出（真实进度版本）"""
        try:
            # 在安装前进行连接质量检查
            if not self.check_and_fix_connection():
                self._hide_progress()
                return
                        
            # 再次检测设备连接状态
            if not self.check_device_connected():
                self._update_install_status("设备连接已断开，安装失败")
                self._hide_progress()
                return
            
            # 获取APK大小用于进度计算
            apk_size = os.path.getsize(apk_path)
            self._update_install_status(f"APK文件大小: {self._format_file_size(apk_size)}")
            
            # 进度条已在_show_progress()中设置为确定性模式
            
            # 分阶段安装：推送文件(70%) + 安装处理(30%)
            success = self._install_with_real_progress(apk_path, apk_size)
            
            if not success:
                self._hide_progress()
                return

            
        except Exception as e:
            self._update_install_status(f"安装过程出错: {str(e)}")
            self._hide_progress()
            
    def _install_with_real_progress(self, apk_path, apk_size):
        """分阶段安装，显示真实进度（静默模式）"""
        try:
            # 阶段1: 准备安装 (5%)
            self._update_progress(5, "正在准备安装...")
            
            # 阶段2: 传输APK文件到设备 (5% -> 75%)
            if not self._transfer_apk_with_progress(apk_path, apk_size, 5, 70):
                return False
            
            # 阶段3: 执行安装命令 (75% -> 100%)
            return self._execute_install_with_progress(apk_path, 75, 25)
            
        except Exception as e:
            self._update_install_status(f"安装过程出错: {str(e)}")
            return False
    
    def _transfer_apk_with_progress(self, apk_path, apk_size, start_progress, progress_range):
        """传输APK文件到设备并显示进度（优化版）"""
        try:
            device_temp_path = "/data/local/tmp/temp_install.apk"
            
            # 先清理可能存在的旧文件
            run_adb_command(f"adb shell rm -f {device_temp_path}")
            
            # 使用 adb push 传输文件，并监控进度
            start_time = time.time()
            
            # 使用新的进程方式，可以更好地控制输出
            push_cmd = f'adb push "{apk_path}" {device_temp_path}'
            
            # 创建进程并启动监控
            push_process = subprocess.Popen(
                push_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # 计算传输速度和估算时间
            # 基于文件大小估算传输时间（考虑网络状况）
            if apk_size < 10 * 1024 * 1024:  # 10MB以下
                estimated_speed = 2 * 1024 * 1024  # 2MB/s
            elif apk_size < 50 * 1024 * 1024:  # 50MB以下
                estimated_speed = 5 * 1024 * 1024  # 5MB/s
            else:
                estimated_speed = 8 * 1024 * 1024  # 8MB/s
            
            estimated_time = max(1.5, apk_size / estimated_speed)
            
            # 监控传输进度
            last_progress = 0
            last_update_time = start_time
            while push_process.poll() is None:
                elapsed = time.time() - start_time
                current_time = time.time()
                
                # 使用非线性进度曲线，初期快速增长，后期缓慢
                if elapsed <= estimated_time:
                    # 使用平方根函数让初期进度较快
                    time_ratio = elapsed / estimated_time
                    progress_percent = int(min(98, time_ratio ** 0.7 * 100))
                else:
                    # 超时后缓慢增长到98%
                    progress_percent = min(98, 80 + int((elapsed - estimated_time) * 2))
                
                current_progress = start_progress + int((progress_percent / 100) * progress_range)
                
                # 只有当进度发生变化或时间间隔超过0.5秒时才更新界面
                if current_progress > last_progress or (current_time - last_update_time > 0.5):
                    last_progress = current_progress
                    last_update_time = current_time
                    
                    # 计算当前传输速度
                    if elapsed > 0:
                        # 估算已传输的字节数
                        transferred_bytes = (progress_percent / 100) * apk_size
                        current_speed = transferred_bytes / elapsed
                        speed_str = self._format_speed(current_speed)
                        
                        # 在输出框中显示传输进度和速度
                        self._update_progress(
                            current_progress, 
                            f"传输APK文件到设备... {progress_percent}% ({speed_str})"
                        )
                    else:
                        # 刚开始时显示基本信息
                        self._update_progress(
                            current_progress, 
                            f"传输APK文件到设备... {progress_percent}%"
                        )
                
                time.sleep(0.1)  # 适当减少更新频率
            
            # 检查 push 结果
            stdout, stderr = push_process.communicate()
            return_code = push_process.returncode
            
            if return_code == 0:
                # 验证文件是否成功传输
                verify_output, verify_success = run_adb_command(f"adb shell ls -l {device_temp_path}")
                if verify_success and "temp_install.apk" in verify_output:
                    self._update_progress(start_progress + progress_range, "文件传输完成")
                    return True
                else:
                    self._update_install_status("文件传输验证失败")
                    return False
            else:
                error_msg = stderr.strip() if stderr else "未知错误"
                self._update_install_status(f"文件传输失败: {error_msg}")
                return False
                
        except Exception as e:
            self._update_install_status(f"文件传输过程出错: {str(e)}")
            return False
    
    def _format_speed(self, bytes_per_second):
        """格式化传输速度显示"""
        if bytes_per_second < 1024:
            return f"{bytes_per_second:.0f}B/s"
        elif bytes_per_second < 1024 * 1024:
            return f"{bytes_per_second / 1024:.1f}KB/s"
        else:
            return f"{bytes_per_second / (1024 * 1024):.1f}MB/s"
    
    def _execute_install_with_progress(self, apk_path, start_progress, progress_range):
        """执行安装命令并显示进度（优化版）"""
        try:
            device_temp_path = "/data/local/tmp/temp_install.apk"
            
            # 使用设备上的文件进行安装
            install_process = subprocess.Popen(
                f'adb shell pm install -r -d {device_temp_path}',
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            # 定义安装阶段关键词和对应进度
            install_stages = [
                ("pkg:", 10, "解析APK包..."),
                ("Performing Streamed Install", 25, "开始流式安装..."),
                ("Streaming", 50, "正在流式传输..."),
                ("Installing", 70, "正在安装应用..."),
                ("Success", 100, "安装成功!")
            ]
            
            current_stage = 0
            output_lines = []
            install_start_time = time.time()
            last_update_time = time.time()
            
            # 初始进度
            self._update_progress(start_progress + 5, "正在执行安装...")
            
            while True:
                output = install_process.stdout.readline()
                if output == '' and install_process.poll() is not None:
                    break
                    
                if output:
                    output_lines.append(output.strip())
                    stripped_output = output.strip()
                    current_time = time.time()
                    
                    # 检查是否达到下一个阶段
                    if current_stage < len(install_stages):
                        keyword, stage_progress, stage_msg = install_stages[current_stage]
                        
                        if keyword in stripped_output:
                            current_stage += 1
                            progress_value = start_progress + int((stage_progress / 100) * progress_range)
                            # 在输出框中显示安装进度
                            self._update_progress(progress_value, stage_msg)
                            last_update_time = current_time
                        elif current_time - last_update_time > 2:  # 2秒无更新则递增进度
                            # 在当前阶段内缓慢递增
                            if current_stage > 0:
                                prev_progress = install_stages[current_stage-1][1] if current_stage > 0 else 0
                                next_progress = install_stages[current_stage][1] if current_stage < len(install_stages) else 100
                                
                                elapsed_in_stage = current_time - last_update_time + 2
                                stage_increment = min(5, elapsed_in_stage)  # 最多增加5%
                                
                                intermediate_progress = min(
                                    next_progress - 1, 
                                    prev_progress + stage_increment
                                )
                                progress_value = start_progress + int((intermediate_progress / 100) * progress_range)
                                # 在输出框中显示中间进度
                                self._update_progress(progress_value, f"安装中... {stripped_output[:25]}...")
                    
                    # 检查错误信息
                    if "Failure" in stripped_output or "INSTALL_FAILED" in stripped_output:
                        self._update_install_status(f"安装失败: {stripped_output}")
                        break
            
            # 清理临时文件
            run_adb_command(f"adb shell rm -f {device_temp_path}")
            
            # 检查安装结果
            return_code = install_process.returncode
            success = return_code == 0
            
            if success:
                self._update_progress(100, "安装成功!")
                
                # 显示安装成功信息
                install_time = time.time() - install_start_time
                apk_name = os.path.basename(apk_path)
                self._update_install_status(
                    f"安装成功 - {apk_name} (耗时: {install_time:.1f}秒)"
                )
            else:
                # 根据错误码提供详细信息
                error_code = return_code & 0xFFFFFFFF
                if error_code == 4294967295:
                    error_msg = f"安装失败：ADB连接异常 (错误码: {return_code})\n建议：断开连接后重新连接设备再试"
                elif return_code == 1:
                    error_msg = "安装失败：应用签名冲突或权限不足"
                elif return_code == 2:
                    error_msg = "安装失败：存储空间不足"
                else:
                    # 查找输出中的错误信息
                    error_detail = ""
                    for line in output_lines[-5:]:  # 检查最后5行
                        if "INSTALL_FAILED" in line or "Failure" in line:
                            error_detail = line.replace("Failure [", "").replace("]", "")
                            break
                    
                    error_msg = f"安装失败\n错误码: {return_code}"
                    if error_detail:
                        error_msg += f"\n详细信息: {error_detail}"
                    
                self._update_install_status(error_msg)
            
            # 等待一下让用户看到最终状态
            time.sleep(1.5)
            self._hide_progress()
            return success
            
        except Exception as e:
            self._update_install_status(f"安装过程出错: {str(e)}")
            return False
    
    def _update_progress(self, value, message=None):
        """更新进度条和输出状态信息
        
        Args:
            value: 进度值 (0-100)
            message: 状态信息，在输出框中显示
        """
        # 更新进度条数值
        self.progress["value"] = value
        
        # 在输出框中显示进度信息
        if message:
            progress_msg = f"[{int(value)}%] {message}"
            self._update_install_status(progress_msg)
        
        self.root.update()  # 强制更新界面
    
    def _format_file_size(self, size_bytes):
        """格式化文件大小显示"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def _update_install_status(self, message):
        """更新安装状态"""
        if "成功" in message:
            self.status_text.insert(tk.END, f"\n{message}\n", "success")
        elif "失败" in message or "错误" in message:
            self.status_text.insert(tk.END, f"\n{message}\n", "error")
        else:
            self.status_text.insert(tk.END, f"\n{message}\n")
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
            output, success = run_adb_command(f"adb uninstall {pkg_name}")
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
        """获取已安装应用包名列表及其版本(优化版，使用动态线程池并导出表格)"""
        try:
            # 获取所有已安装包名
            output, success = run_adb_command("adb shell pm list packages")
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
            app_list = []  # 存储包名和版本信息
            
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
                        
                        # 添加到列表中用于导出
                        app_list.append({
                            'package_name': package,
                            'version': version_str
                        })
                        
                        self.status_text.insert(
                            tk.END, 
                            f"\n{package} (版本: {version_str})", 
                            "info"
                        )
                    except Exception as e:
                        # 失败的也记录
                        app_list.append({
                            'package_name': package,
                            'version': f"获取失败 - {str(e)}"
                        })
                        
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
            
            # 完成获取后导出表格
            self.update_status(f"\n获取应用列表完成，共 {len(packages)} 个应用", True)
            self._export_app_list_to_table(app_list)
                    
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
    
    def _export_app_list_to_table(self, app_list):
        """导出APP列表到表格文件"""
        try:
            # 获取日志存储路径
            log_path = self.log_path_entry.get().strip()
            if not log_path:
                log_path = self.default_log_path
            
            # 确保目录存在
            ensure_directory(log_path)
            
            # 生成文件名：applist-appversion_MMDD-HHMMSS.csv
            current_time = timestamp_time()
            file_name = f"applist-appversion_{current_time}.csv"
            file_path = os.path.join(log_path, file_name)
            
            # 写入CSV文件
            import csv
            with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['package_name', 'version'])
                for app in app_list:
                    writer.writerow([app['package_name'], app['version']])
            
            self.update_status(f"应用列表已保存至: {file_path}", True)
        except Exception as e:
            self.update_status(f"导出应用列表时出错: {str(e)}", False)

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
            output, success = run_adb_command(f"adb shell pm clear {pkg_name}")
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
        # 首先尝试标准的adb root命令
        output, success = run_adb_command("adb root")
        if success and "restarting" in output.lower():
            self.update_status("获取root权限成功，设备正在重启adb服务...", True)
            # 等待设备重新连接
            time.sleep(3)
            # 重新检查连接状态
            if self.check_device_connected():
                self.update_status("设备已重新连接，root权限获取成功", True)
            else:
                self.update_status("设备重新连接失败，请手动重新连接设备", False)
            return
        
        # 如果标准方法失败，尝试使用su命令
        if not success or "cannot" in output.lower() or "unable" in output.lower():
            self.update_status("adb root命令失败，正在尝试使用su命令...", True)
            # 尝试使用su命令获取root权限
            su_output, su_success = run_adb_command("adb shell su --version")
            if su_success:
                self.update_status("检测到设备支持su命令，已获取root权限", True)
                return
            else:
                self.update_status("su命令不可用，无法获取root权限", False)
                return
        
        self.update_status(output, success)

    @require_device_connected
    def pull_anr_file(self):
        """拉取ANR文件"""
        try:
            # 获取用户设置的日志存储路径
            log_path = self.log_path_entry.get().strip()
            if not log_path:
                log_path = self.default_log_path
            
            # 创建ANR文件夹
            anr_dir = os.path.join(log_path, "ANR")
            anr_dir = ensure_directory(anr_dir)
            
            # 先检查/data/anr目录内容
            self.update_status("正在检查ANR目录内容...", True)
            check_output, check_success = run_adb_command("adb shell ls -la /data/anr")
            
            if not check_success:
                self.update_status(f"无法访问ANR目录: {check_output}", False)
                return False
            
            # 显示目录内容（用于调试）
            self.update_status(f"ANR目录内容:\n{check_output}", True)
            
            # 检查目录是否为空
            if "total 0" in check_output or check_output.strip() == "" or "No such file" in check_output:
                self.update_status("ANR文件目录为空，没有可导出的文件", False)
                return False
            
            # 使用更稳健的方式拉取ANR文件
            self.update_status("正在拉取ANR文件...", True)
            
            # 先尝试拉取整个目录
            output, success = run_adb_command(f"adb pull /data/anr/ \"{anr_dir}\"")
            
            # 如果失败，尝试逐个文件拉取
            if not success:
                self.update_status("尝试逐个拉取ANR文件...", True)
                # 先创建临时目录
                temp_dir = os.path.join(anr_dir, "temp_anr")
                os.makedirs(temp_dir, exist_ok=True)
                
                # 获取文件列表
                list_output, list_success = run_adb_command("adb shell ls /data/anr")
                if list_success:
                    files = list_output.strip().split('\n')
                    for file_name in files:
                        if file_name.strip() and not file_name.startswith('total'):
                            # 逐个拉取文件
                            file_output, file_success = run_adb_command(f"adb pull \"/data/anr/{file_name}\" \"{temp_dir}\"")
                            if not file_success:
                                self.update_status(f"拉取文件 {file_name} 失败: {file_output}", False)
                
                # 检查是否有成功拉取的文件
                if os.listdir(temp_dir):
                    success = True
                    output = "部分文件拉取成功"
                else:
                    # 清理空的临时目录
                    os.rmdir(temp_dir)
            
            if success:
                # 检查是否真的有文件被拉取
                anr_files = os.listdir(anr_dir)
                if anr_files or (os.path.exists(os.path.join(anr_dir, "temp_anr")) and os.listdir(os.path.join(anr_dir, "temp_anr"))):
                    self.update_status(f"ANR文件已保存至: {anr_dir}", True)
                    # 尝试打开ANR文件夹
                    try:
                        os.startfile(anr_dir)
                    except:
                        pass
                    return True
                else:
                    self.update_status("ANR文件拉取完成但目录为空", False)
                    return False
            else:
                # 提供更详细的错误信息
                error_msg = output if output else "未知错误"
                self.update_status(f"ANR文件拉取失败: {error_msg}", False)
                return False
        except Exception as e:
            self.update_status(f"拉取ANR文件时出错: {str(e)}", False)
            return False

    @require_device_connected
    def remount(self):
        """重新挂载分区"""
        output, success = run_adb_command("adb remount")
        self.update_status(output, success)

    @require_device_connected
    def get_version(self):
        """获取应用版本"""
        pkg_name = self.get_package_name_from_input()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        output, success = run_adb_command(f"adb shell pm dump {pkg_name}")
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
            output, success = run_adb_command("adb reboot")
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
            
        output, success = run_adb_command("adb shell getprop ro.build.version.release")
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
            run_adb_command("adb shell rm -f /sdcard/screenshot.png")
            
            # 获取用户设置的日志存储路径
            log_path = self.log_path_entry.get().strip()
            if not log_path:
                log_path = self.default_log_path
            
            # 创建保存目录
            save_dir = ensure_directory(log_path)
            new_file = get_next_filename(os.path.join(save_dir, "截图"), ".png")
            
            # 最多尝试指定次数截图
            max_retries = Config.MAX_INSTALL_RETRIES
            success = False
            error_msg = ""
            
            for attempt in range(max_retries):
                # 截图到设备
                output1, success1 = run_adb_command("adb shell screencap -p /sdcard/screenshot.png")
                if not success1:
                    error_msg = output1
                    time.sleep(1)  # 等待1秒后重试
                    continue
                
                # 验证文件是否生成
                output2, success2 = run_adb_command("adb shell ls -l /sdcard/screenshot.png")
                if not success2 or "No such file" in output2:
                    error_msg = "截图文件未生成"
                    time.sleep(1)  # 等待1秒后重试
                    continue
                
                # 拉取文件到电脑
                output3, success3 = run_adb_command(f"adb pull /sdcard/screenshot.png {new_file}")
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
            run_adb_command("adb shell rm -f /sdcard/screenshot.png")
            
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
        test_output, test_success = run_adb_command("adb shell screenrecord --help")
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
                self.update_status("屏幕录制已成功启动！\n点击'停止录制'结束录制", True)
            else:
                self.update_status("录制线程启动失败", False)
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

        # 立即显示友好的停止提示，提升交互性
        self.update_status("🔴 正在停止屏幕录制...", True)
        self.update_status("⏳ 请稍等，正在安全关闭录制进程并下载文件...", True)
        
        # 强制更新界面，让用户立即看到提示
        self.root.update()
        
        # 设置停止状态
        self.recording_active = False

        # 在后台线程中执行停止操作，避免阻塞界面
        stop_thread = threading.Thread(
            target=self._handle_stop_recording,
            name="StopRecordingThread",
            daemon=True
        )
        stop_thread.start()
    
    def _handle_stop_recording(self):
        """处理停止屏幕录制的后台操作"""
        try:
            # 显示进程终止提示
            self.update_status("🔍 正在终止录制进程...", True)
            self.root.update()

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
                        self.update_status("⚠️ 强制终止录制进程", True)
                        self.root.update()
                    except:
                        pass
                except Exception:
                    pass

            # 显示等待线程结束提示
            self.update_status("🕰️ 正在等待录制线程安全结束...", True)
            self.root.update()

            # 等待录制线程结束（参考日志抓取的逻辑）
            if self.recording_thread and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=10)  # 增加等待时间到10秒，给足够时间完成重命名
                if self.recording_thread.is_alive():
                    self.update_status("⚠️ 录制线程仍在运行，可能正在处理文件操作...", True)
                    self.root.update()
            
            # 重置状态
            self.recording_active = False
            self.recording_subprocess = None
            
            self.update_status("✅ 录制停止操作完成", True)
            
        except Exception as e:
            self.update_status(f"停止录制过程中发生错误: {str(e)}", False)
            self.recording_active = False
            self.recording_subprocess = None

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
            run_adb_command(f"adb shell rm -f {device_temp_file}")
            
            self.update_status("开始录制屏幕，保存中...", True)

            # Windows 系统添加 CREATE_NO_WINDOW 标志
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

            # 启动screenrecord进程（使用较低的分辨率和码率以保证兼容性）
            self.recording_subprocess = subprocess.Popen([
                "adb", "shell", "screenrecord", 
                "--bit-rate", "4000000",  # 4Mbps
                "--size", "1280x720",     # 720p
                device_temp_file
            ],
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
            check_output, check_success = run_adb_command(f"adb shell ls -la {device_temp_file}")
            if not check_success or "No such file" in check_output:
                self.update_status(f"设备上的录制文件不存在: {device_temp_file}", False)
                return
            
            # 从设备上下载录制文件
            pull_output, pull_success = run_adb_command(f'adb pull "{device_temp_file}" "{self.recording_file_path}"')
            
            if pull_success:
                # 清理设备上的临时文件
                run_adb_command(f"adb shell rm -f {device_temp_file}")
                
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
        test_output, test_success = run_adb_command("adb logcat -d -t 1")
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
        self.update_status(f"正在启动日志捕获...\n目标文件: {self.log_file_path}", True)

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
                self.update_status("日志捕获已成功启动！\n点击'停止日志捕获'结束捕获", True)
            else:
                self.update_status("日志捕获线程启动失败", False)
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

        # 立即显示友好的停止提示，提升交互性
        self.update_status("🔴 正在停止日志捕获...", True)
        self.update_status("⏳ 请稍等，正在安全关闭进程并保存文件...", True)
        
        # 强制更新界面，让用户立即看到提示
        self.root.update()
        
        # 设置停止信号
        self.stop_event.set()
        
        # 在后台线程中执行停止操作，避免阻塞界面
        stop_thread = threading.Thread(
            target=self._handle_stop_logcat,
            name="StopLogcatThread",
            daemon=True
        )
        stop_thread.start()
    
    def _handle_stop_logcat(self):
        """处理停止日志捕获的后台操作"""
        try:
            # 显示进度提示
            self.update_status("🔍 正在终止日志进程...", True)
            self.root.update()
        
            # 确保进程终止
            # 确保进程终止
            self._terminate_logcat()
        
            # 显示等待线程结束提示
            self.update_status("🕰️ 正在等待线程安全结束...", True)
            self.root.update()
        
            # 等待线程结束，给足够的时间让文件句柄释放
            if hasattr(self, 'logcat_thread') and self.logcat_thread.is_alive():
                # 等待线程正常结束
                self.logcat_thread.join(timeout=5)  # 增加等待时间到5秒
            
                # 如果线程仍未结束，通常说明有异常情况
                if self.logcat_thread.is_alive():
                    self.update_status("⚠️ 线程仍在处理，请稍候...", True)
                    self.root.update()
        
            # 显示文件处理提示
            self.update_status("💾 正在处理日志文件...", True)
            self.root.update()
        
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
                self.update_status("⚠️ 检测到空日志文件，可能原因：\n1. 设备无日志输出\n2. ADB连接不稳定\n3. 权限不足\n4. 捕获时间过短", True)
            else:
                file_size_str = format_file_size(file_size)
                self.update_status(f"✅ 日志捕获成功，文件大小: {file_size_str}", True)
        
            self.root.update()

            # 显示文件保存提示
            self.update_status("💾 正在保存日志文件...", True)
            self.root.update()

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
                        self.update_status(f"🕰️ 文件仍被占用，等待释放... (尝试 {attempt + 1}/{max_retries})", True)
                        self.root.update()
                        time.sleep(2)
                        continue
                
                    # 尝试重命名文件
                    os.rename(self.log_file_path, new_name)
                    success_save = True
                
                    # 构建提示信息
                    save_path = os.path.abspath(new_name)
                    if file_size == 0:
                        self.update_status(f"✅ 日志捕获已停止\n空日志文件已保存到: {save_path}\n建议检查设备连接和权限设置", False)
                    else:
                        self.update_status(f"✅ 日志捕获已停止\n日志文件已保存到: {save_path}", True)
                
                    # 尝试打开日志所在文件夹
                    try:
                        os.startfile(os.path.dirname(new_name))
                    except:
                        pass  # 忽略打开文件夹的错误
                    break
                
                except PermissionError as e:
                    last_error = f"权限错误: {str(e)}"
                    if attempt < max_retries - 1:
                        self.update_status(f"🕰️ 文件被占用，等待释放... (尝试 {attempt + 1}/{max_retries})", True)
                        self.root.update()
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
        
        except Exception as e:
            self.update_status(f"停止日志捕获过程中发生错误: {str(e)}", False)
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
                self.logcat_subprocess = subprocess.Popen(
                    ["adb", "logcat", "-v", "time", "*:V"],
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
            output, success = run_adb_command("adb logcat -c")
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
            output, success = run_adb_command("adb shell dumpsys window windows | findstr mCurrentFocus")
            if not success or not output:
                # 如果第一个命令失败，尝试第二个命令
                output, success = run_adb_command("adb shell dumpsys window | findstr mCurrentFocus")
                if not success or not output:
                    # 如果还是失败，尝试第三个命令
                    output, success = run_adb_command("adb shell dumpsys activity activities | findstr mResumedActivity")
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
            output, success = run_adb_command(f"adb shell pm path {pkg_name}")
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
    def show_help(self):
        """显示帮助信息"""
        help_text = (
            "操作说明:\n"
            "1. 输入设备的IP地址并点击'Connect ADB'连接设备。\n"
            "2. 点击'DisConnect ADB'断开所有连接设备。\n"
            "3. 点击'Browse'可选择需要安装的apk文件。\n"
            "4. 选择APK文件并点击'Force Install'安装应用。\n"
            "5. 使用'Uninstall'卸载应用。\n"
            "6. 点击'Package List'查看已安装应用。\n"
            "7. 使用'Clear Cache'清除应用缓存。\n"
            "8. 点击'Root'获取root权限。\n"
            "9. 点击'Pull_ANR'抓取ANR文件。\n"
            "10 点击'Remount'重新挂载设备。\n"
            "11. 点击'Get Version'查询应用版本。\n"
            "12. 点击'Reboot'重启设备。\n"
            "13. 点击'Android Version'查询TVAndroid版本。\n"
            "14. 点击'Start Logcat'开始日志抓取。\n"
            "15. 点击'Stop  Logcat'停止日志抓取。\n"
            "16. 点击'Screencap'截取TV屏幕图。\n"
            "17. 点击'Get_SN'获取串号信息。\n"
            "18. 点击'Help'查看帮助信息。\n"
            "19. 点击'Get Package Name'自动获取当前应用包名并填充包名。\n"
            "20. 点击'LogClear'清除设备日志缓冲区（包括系统日志和应用日志）。\n"
            "21. 点击'Browse_Log_Path'选择日志保存路径，若不选择，默认保存到D盘根目录。\n"
            "22. 点击'Kill_All_Processes'强制kill当前应用进程。\n"
            "23. 点击'Get_PackageName'获取当前打开应用包名,包名会自动填充到输入框中。\n"
            "24. 点击'开始屏幕录制'开始录制设备屏幕。\n"
            "25. 点击'停止屏幕录制'结束录制并保存视频文件。\n"
            
            "\n注意事项:\n"
            "1.确保设备已连接到同一网络。\n"
            "2.使用期间请保持ADB连接。\n"
            "3.查询应用版本、清缓存、卸载应用、kill进程时需输入对应的包名。\n"
            "4.抓取ANR文件、日志、TV截屏、屏幕录制功能，会保存在指定目录，提示框会给出存储路径。\n"
            "5.串号查询功能,由于串号格式差异的原因,某些设备可能无法获取到正确的串号,请自行判断\n"
            "6.可自行调整输出框高度，鼠标可滚动查看历史信息。\n"
            "7.屏幕录制功能需要Android 4.4+，且设备支持screenrecord命令。\n"
            "\n故障排除:\n"
            "• 如果安装时出现错误码4294967295，这通常表示ADB连接不稳定:\n"
            "  - 断开连接后重新连接设备\n"
            "  - 检查网络连接质量\n"
            "  - 避免在连接不稳定时进行安装操作\n"
            "  - 工具已自动增加连接质量检测，会在操作前验证连接状态\n"
        )
        # messagebox.showinfo("操作说明和注意事项", help_text)
        self.update_status(help_text, True)

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
        """设置拖拽APK文件和包名功能"""
        
        # 先设置APK输入框的占位符文本
        def setup_apk_placeholder():
            if not self.apk_entry.get():
                self.apk_entry.insert(0, "可直接拖拽APK文件到此处...")
                
        def on_apk_focus_in(event):
            if self.apk_entry.get() == "可直接拖拽APK文件到此处...":
                self.apk_entry.delete(0, tk.END)
                
        def on_apk_focus_out(event):
            if not self.apk_entry.get():
                setup_apk_placeholder()
        
        # 绑定APK输入框焦点事件
        self.apk_entry.bind('<FocusIn>', on_apk_focus_in)
        self.apk_entry.bind('<FocusOut>', on_apk_focus_out)
        setup_apk_placeholder()
        
        # 检查根窗口是否支持拖拽
        root_class = str(type(self.root))
        if 'TkinterDnD' not in root_class:
            self.update_status("💡 当前窗口不支持拖拽功能", True)
            self.update_status("💡 请使用'选择安装包路径'按钮安装APK", True)
            return
        
        # 尝试设置拖拽功能
        try:
            # 尝试导入tkinterdnd2模块
            import tkinterdnd2 as tkdnd
            from tkinterdnd2 import DND_FILES, DND_TEXT
            
            def on_apk_drop(event):
                """处理APK文件拖拽"""
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
            
            def on_pkg_drop(event):
                """处理包名文本拖拽"""
                self.pkg_combobox.config(background="white")
                
                # 获取拖拽的文本内容
                text_data = event.data.strip()
                
                # 检查是否为有效的包名格式
                if text_data and "." in text_data and not text_data.startswith(".") and not text_data.endswith("."):
                    # 去除可能的空格和特殊字符
                    clean_pkg = text_data.replace(" ", "").replace("\n", "").replace("\r", "")
                    
                    # 再次验证包名格式
                    if len(clean_pkg.split(".")) >= 2 and all(part.replace("_", "").isalnum() for part in clean_pkg.split(".")):
                        self.pkg_combobox.delete(0, tk.END)
                        self.pkg_combobox.insert(0, clean_pkg)
                        self.update_status(f"📦 已输入包名: {clean_pkg}", True)
                        
                        # 保存包名到历史记录
                        self._save_pkg_to_history(clean_pkg)
                    else:
                        self.update_status("⚠️ 请拖拽有效的包名格式(如: com.example.app)", False)
                else:
                    self.update_status("⚠️ 请拖拽有效的包名文本", False)
            
            def on_apk_drag_enter(event):
                """鼠标进入APK拖拽区域时的视觉反馈"""
                self.apk_entry.config(background="lightblue")
                return tkdnd.COPY
                
            def on_apk_drag_leave(event):
                """鼠标离开APK拖拽区域时恢复正常颜色"""
                self.apk_entry.config(background="white")
            
            def on_pkg_drag_enter(event):
                """鼠标进入包名拖拽区域时的视觉反馈"""
                self.pkg_combobox.config(background="lightgreen")
                return tkdnd.COPY
                
            def on_pkg_drag_leave(event):
                """鼠标离开包名拖拽区域时恢复正常颜色"""
                self.pkg_combobox.config(background="white")
            
            # 尝试注册APK文件拖拽事件
            self.apk_entry.drop_target_register(DND_FILES)
            self.apk_entry.dnd_bind('<<DropEnter>>', on_apk_drag_enter)
            self.apk_entry.dnd_bind('<<DropLeave>>', on_apk_drag_leave) 
            self.apk_entry.dnd_bind('<<Drop>>', on_apk_drop)
            
            # 尝试注册包名文本拖拽事件
            self.pkg_combobox.drop_target_register(DND_TEXT)
            self.pkg_combobox.dnd_bind('<<DropEnter>>', on_pkg_drag_enter)
            self.pkg_combobox.dnd_bind('<<DropLeave>>', on_pkg_drag_leave) 
            self.pkg_combobox.dnd_bind('<<Drop>>', on_pkg_drop)
            
            # 拖拽功能设置成功
            self.update_status("🚀 拖拽功能已启用！", True)
            self.update_status("📦 APK文件可拖拽到APK输入框", True)
            self.update_status("📝 包名文本可拖拽到包名输入框", True)
            return
            
        except ImportError as e:
            # tkinterdnd2 模块导入失败
            self.update_status("💡 请使用'选择安装包路径'按钮安装APK", True)
        except Exception as e:
            # 其他拖拽设置错误
            self.update_status("💡 请使用'选择安装包路径'按钮安装APK", True)
        
        # 如果到这里，说明拖拽功能不可用
        self.update_status("💡 请手动输入包名到包名输入框", True)
            
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
