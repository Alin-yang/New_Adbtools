import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import psutil
import subprocess
import os
import glob
from decorators import require_device_connected
from utils import (
    run_adb_command, timestamp_time,
    extract_version_info, ensure_directory,
    get_next_filename, load_ip_history, save_ip_history
)
import concurrent.futures

class ADBToolApp:
    # 预先声明所有动态绑定的GUI组件
    apk_entry:ttk.Entry
    ip_combobox:ttk.Combobox  # 修改为Combobox
    pkg_entry:ttk.Entry
    log_path_entry:ttk.Entry
    status_text:tk.Text
    progress: ttk.Progressbar # 进度条声明

    def __init__(self, root, layout_module):
        self.root = root
        self.root.title("ADB Tool")
        self.root.geometry("1078x464") # 设置初始窗口尺寸
        # self.root.minsize(width=1026, height=422) # 设置最小尺寸
        self.layout_module = layout_module
        self._init_variables()
        self._setup_gui()
        # 加载IP历史记录
        self._load_ip_history()

    def _init_variables(self):
        """初始化实例变量"""
        self.logcat_process = None
        self.default_log_path = "D:\\实时log"  # 设置默认日志路径
        self.log_file_path = None
        self.logging_active = False
        self.logcat_subprocess = None
        self.stop_event = threading.Event()
        self.progress = None
        # 添加缓存
        self._device_cache = {}
        self._package_cache = {}
        self._cache_timeout = 300  # 缓存超时时间(秒)
        self._last_cache_cleanup = time.time()
        # 添加IP历史记录列表
        self.ip_history = []

    def _load_ip_history(self):
        """加载IP历史记录到下拉框"""
        self.ip_history = load_ip_history()
        if hasattr(self, 'ip_combobox'):
            self.ip_combobox['values'] = self.ip_history

    def _cache_cleanup(self):
        """清理过期缓存"""
        current_time = time.time()
        if current_time - self._last_cache_cleanup > 60:  # 每分钟最多清理一次
            expired = current_time - self._cache_timeout
            self._device_cache = {k: v for k, v in self._device_cache.items() 
                                if v.get('timestamp', 0) > expired}
            self._package_cache = {k: v for k, v in self._package_cache.items() 
                                 if v.get('timestamp', 0) > expired}
            self._last_cache_cleanup = current_time

    def _setup_gui(self):
        # 动态调用布局模块的 setup_gui 方法
        self.layout_module.setup_gui(self)
        
        # 配置状态文本框的标签样式
        self.status_text.tag_configure("success", foreground="green")
        self.status_text.tag_configure("error", foreground="red")
        self.status_text.tag_configure("info", foreground="blue")

        # 设置日志路径输入框的默认值
        self.log_path_entry.delete(0, tk.END)
        self.log_path_entry.insert(0, self.default_log_path)

    # 状态更新方法
    def update_status(self, message, success):
        """更新状态文本框"""
        tag = "success" if success else "error"
        self.status_text.insert(tk.END, f"\n{message}\n", tag)
        self.status_text.see(tk.END)

    # 文件选择方法
    def browse_apk(self):
        """选择APK文件"""
        file_path = filedialog.askopenfilename(filetypes=[("APK files", "*.apk")])
        if file_path:
            self.apk_entry.delete(0, tk.END)
            self.apk_entry.insert(0, file_path)

    def choose_log_path(self):
        """打开目录选择对话框"""
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
        pkg_name = self.pkg_entry.get()
        if not pkg_name:
            self.update_status("请输入需要终止进程的应用包名", False)
            return

        if pkg_name:
            try:
                output, success = run_adb_command(f"adb shell am force-stop {pkg_name}")
                if success:
                    self.update_status(f"成功终止{pkg_name}应用所处进程", True)
                else:
                    self.update_status(f"终止{pkg_name}进程失败", False)
            except:
                self.update_status(f"未找到{pkg_name}所属进程:", False)


    # 核心ADB操作方法
    # @require_device_connected
    def connect_adb(self):
        """连接ADB设备"""
        ip_address = self.ip_combobox.get()
        if not ip_address:
            self.update_status(f"请输入IP地址", False)
            return False
        
        output, success = run_adb_command(f"adb connect {ip_address}")
        if "connected" in output.lower():
            # 保存新的IP到历史记录
            if ip_address not in self.ip_history:
                self.ip_history.insert(0, ip_address)
                save_ip_history(self.ip_history)
                self.ip_combobox['values'] = self.ip_history
            self.update_status(output, True)
        else:
            self.update_status(output, False)


    @require_device_connected
    def disconnect_adb(self):
        """断开ADB连接"""
        output, success = run_adb_command("adb disconnect")
        if "disconnected" in output.lower():
            self.update_status(output, True)
        else:
            self.update_status(output, False)

    def check_device_connected(self, ip_address=None):
        """检查设备连接状态(带缓存)"""
        cache_key = ip_address or 'default'
        cache_data = self._device_cache.get(cache_key, {})
        
        # 如果缓存未过期，直接返回缓存结果
        if time.time() - cache_data.get('timestamp', 0) < 5:  # 5秒缓存
            return cache_data.get('connected', False)
            
        output, success = run_adb_command("adb devices")
        if success:
            devices = [line.split("\t")[0] for line in output.splitlines()[1:] if "device" in line]
            ip_with_port = f"{ip_address}:5555" if ip_address else None
            is_connected = ip_address in devices or ip_with_port in devices
            
            # 更新缓存
            self._device_cache[cache_key] = {
                'connected': is_connected,
                'timestamp': time.time()
            }
            return is_connected
        return False

    def ensure_device_connected(self):
        """设备连接验证"""
        ip_address = self.ip_combobox.get()
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
            # 获取APK大小用于计算进度
            apk_size = os.path.getsize(apk_path)
            current_size = 0
            
            process = subprocess.Popen(
                f"adb install -r -d {apk_path}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            # 定义需要过滤的关键词
            filter_keywords = ["Performing Streamed Install"]
            installing_started = False

            # 实时捕获输出
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    stripped_output = output.strip()
                    
                    # 检测安装开始
                    if "Performing Streamed Install" in stripped_output:
                        installing_started = True
                        self.progress["mode"] = "determinate"
                        self.progress["maximum"] = 100
                        self.progress["value"] = 0
                        current_size = 0
                        continue

                    # 更新进度
                    if installing_started:
                        # 估算进度
                        current_size += len(output)  # 增加已处理的数据大小
                        progress = min(95, int((current_size / apk_size) * 100))
                        self.progress["value"] = progress
                        
                        if "Success" in stripped_output:
                            self.progress["value"] = 100
                            self._update_install_status("安装成功")
                        elif "Failure" in stripped_output:
                            self._update_install_status(f"安装失败: {stripped_output}")
                        elif not any(keyword in stripped_output for keyword in filter_keywords):
                            self._update_install_status(stripped_output)

            # 获取最终结果
            return_code = process.poll()
            success = return_code == 0
            
            # 重置进度条模式
            self.progress["mode"] = "indeterminate"
            self._hide_progress()
            
            final_output = "安装成功" if success else f"安装失败 (code {return_code})"
            self._update_install_status(final_output)
            
        except Exception as e:
            self._update_install_status(f"安装过程出错: {str(e)}")
            self._hide_progress()

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
        """卸载应用"""
        pkg_name = self.pkg_entry.get()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        output, success = run_adb_command(f"adb uninstall {pkg_name}")
        self.update_status(output, success)

    @require_device_connected
    def package_list(self):
        """获取已安装应用包名列表及其版本(优化版)"""
        try:
            self._cache_cleanup()  # 清理过期缓存
            
            # 获取所有已安装包名
            output, success = run_adb_command("adb shell pm list packages")
            if not success:
                self.update_status("获取应用列表失败", False)
                return

            # 清理并获取包名列表
            packages = [line.replace("package:", "").strip() 
                       for line in output.splitlines() if line.strip()]
            
            self.update_status("正在获取应用列表和版本信息...", True)
            
            # 使用线程池并行获取版本信息
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_package = {
                    executor.submit(self.get_package_version, package): package 
                    for package in packages
                }
                
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
                    self.status_text.see(tk.END)
                    
            self.update_status("\n获取应用列表完成", True)
            
        except Exception as e:
            self.update_status(f"获取应用列表时出错: {str(e)}", False)

    def get_package_version(self, package_name):
        """获取应用版本号(带缓存)"""
        # 检查缓存
        cache_data = self._package_cache.get(package_name, {})
        if time.time() - cache_data.get('timestamp', 0) < self._cache_timeout:
            return cache_data.get('version')
            
        cmd = f'adb shell dumpsys package {package_name} | findstr "versionName"'
        version_output, success = run_adb_command(cmd)
        
        if success and version_output:
            version = version_output.strip().split("=")[-1].strip()
            # 更新缓存
            self._package_cache[package_name] = {
                'version': version,
                'timestamp': time.time()
            }
            return version
        return None

    @require_device_connected
    def clear_cache(self):
        """清除应用缓存"""
        pkg_name = self.pkg_entry.get()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        output, success = run_adb_command(f"adb shell pm clear {pkg_name}")
        self.update_status(output, success)

    @require_device_connected
    def root_device(self):
        """获取root权限"""
        output, success = run_adb_command("adb root")
        self.update_status(output, success)

    @require_device_connected
    def pull_anr_file(self):
        """拉取ANR文件"""
        anr_dir = ensure_directory("D:\\ANR_File")
        output, success = run_adb_command(f"adb pull /data/anr {anr_dir}")
        self.update_status(f"ANR文件已保存至: {anr_dir}", success)

    @require_device_connected
    def remount(self):
        """重新挂载分区"""
        output, success = run_adb_command("adb remount")
        self.update_status(output, success)

    @require_device_connected
    def get_version(self):
        """获取应用版本"""
        pkg_name = self.pkg_entry.get()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return

        output, success = run_adb_command(f"adb shell pm dump {pkg_name}")
        if success:
            version = extract_version_info(output)
            if version:
                self.update_status(f"当前应用{pkg_name}版本: {version}", True)
            else:
                self.update_status("版本信息解析失败", False)
        else:
            self.update_status(output, False)

    @require_device_connected
    def reboot(self):
        """重启设备"""
        output, success = run_adb_command("adb reboot")
        self.update_status("设备重启中..." if success else output, success)

    @require_device_connected
    def get_android_version(self):
        """获取Android版本"""
        output, success = run_adb_command("adb shell getprop ro.build.version.release")
        if success:
            self.update_status(f"Android版本: {output.strip()}", True)
        else:
            self.update_status(output, False)

    @require_device_connected
    def screencap(self):
        """屏幕截图"""
        try:
            # 先显示提示信息
            self.update_status("正在截图，请稍候...", True)
            # 强制更新界面
            self.root.update()
            # 短暂延迟，确保提示信息显示
            time.sleep(0.5)
            
            # 先清理可能存在的旧截图
            run_adb_command("adb shell rm -f /sdcard/screenshot.png")
            
            # 创建保存目录
            save_dir = ensure_directory("D:\\TV截图")
            new_file = get_next_filename(os.path.join(save_dir, "截图"), ".png")
            
            # 最多尝试3次截图
            max_retries = 3
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
                    success = True
                    break
                else:
                    error_msg = "本地文件保存失败"
                    time.sleep(1)  # 等待1秒后重试
                    continue
            
            # 清理设备上的临时文件
            run_adb_command("adb shell rm -f /sdcard/screenshot.png")
            
            if success:
                self.update_status(f"截图已保存至路径: {new_file}", True)
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
        """获取设备序列号"""
        output, success = run_adb_command("adb shell getprop ro.serialno")
        if success:
            self.update_status(f"设备序列号: {output.strip()}  \n-注：由于串号格式差异，某些设备可能无法获取到正确的串号，请自行判断。", True)
        else:
            self.update_status(output, False)

    # 日志相关方法
    @require_device_connected
    def start_logcat(self):
        """启动日志捕获"""
        if self.logging_active:
            self.update_status("日志捕获已在运行", False)
            return

        # 获取用户输入的日志路径
        user_log_path = self.log_path_entry.get().strip()
        if not user_log_path:
            # 使用默认路径
            user_log_path = self.default_log_path
            self.log_path_entry.delete(0, tk.END)
            self.log_path_entry.insert(0, user_log_path)

        # 确保路径存在
        try:
            os.makedirs(user_log_path, exist_ok=True)
            # 测试写入权限
            test_file = os.path.join(user_log_path, "test_write.tmp")
            with open(test_file, 'w') as tf:
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
        self.logging_active = True
        self.stop_event.clear()

        # 启动日志捕获线程
        self.logcat_thread = threading.Thread(target=self._run_logcat)
        self.logcat_thread.start()
        self.update_status("日志捕获已启动", True)

    @require_device_connected
    def stop_logcat(self):
        """停止日志捕获"""
        if not self.logging_active:
            self.update_status("没有正在运行的日志捕获", False)
            return

        self.stop_event.set()
        # 确保进程终止
        self._terminate_logcat()

        # 确保文件路径存在
        if not os.path.exists(self.log_file_path):
            self.update_status("日志文件不存在", False)
            self.logging_active = False
            return

        original_path = os.path.dirname(self.log_file_path)
        new_name = os.path.join(original_path, f"{timestamp_time()}.log")

        # 重试机制（最多3次）
        max_retries = 3
        success_save = False
        for attempt in range(max_retries):
            try:
                os.rename(self.log_file_path, new_name)
                success_save = True
                # 构建提示信息
                save_path = os.path.abspath(new_name)  # 获取完整路径
                self.update_status(f"日志捕获已停止\n日志文件已保存到: {save_path}", True)
                # 尝试打开日志所在文件夹
                try:
                    os.startfile(os.path.dirname(new_name))
                except:
                    pass
                break
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(1)  # 每次重试间隔1秒
                    continue
                self.update_status("文件占用，重命名失败", False)
            except Exception as e:
                self.update_status(f"保存失败: {str(e)}", False)
                break

        self.logging_active = False
        if not success_save:
            self.update_status("日志捕获已停止，但文件保存失败", False)

    def _run_logcat(self):
        """实际执行日志捕获"""
        try:
            # 再次验证路径可写
            log_dir = os.path.dirname(self.log_file_path)
            if not os.access(log_dir, os.W_OK):
                self.update_status(f"日志文件目录不可写: {log_dir}", False)

            with open(self.log_file_path, "w") as f:
                # Windows 系统添加 CREATE_NO_WINDOW 标志
                creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

                self.logcat_subprocess = subprocess.Popen(
                    ["adb", "logcat", "-v", "time", "*:V"],
                    stdout=f,
                    stderr=subprocess.PIPE,
                    creationflags=creation_flags,
                    text=True
                )

                while self.logcat_subprocess.poll() is None:
                    if self.stop_event.wait(0.5):
                        self._terminate_logcat()
                        break
        except Exception as e:
            self.update_status(f"日志错误: {str(e)}", False)
        finally:
            if hasattr(f, "close"):
                f.close()

    def _terminate_logcat(self):
        '''终止日志捕获进程'''
        if self.logcat_subprocess and self.logcat_subprocess.poll() is None:
            try:
                # 先尝试正常终止
                self.logcat_subprocess.terminate()
                self.logcat_subprocess.wait(timeout=3)
            except (subprocess.TimeoutExpired, psutil.NoSuchProcess):
                # 强制终止进程树
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

    @require_device_connected
    def log_clear(self):
        """清除日志"""
        output, success = run_adb_command("adb logcat -c")
        if success:
            self.update_status("日志清除成功", True)
        else:
            self.update_status(output, False)

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
                    # 自动填充包名到输入框
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
        pkg_name = self.pkg_entry.get()
        if not pkg_name:
            self.update_status("请输入包名", False)
            return
        
        try:
            output, success = run_adb_command(f"adb shell pm path {pkg_name}")
            if success and output:
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
            
            "\n注意事项:\n"
            "1.确保设备已连接到同一网络。\n"
            "2.使用期间请保持ADB连接。\n"
            "3.查询应用版本、清缓存、卸载应用、kill进程时需输入对应的包名。\n"
            "4.抓取ANR文件、日志、TV截屏功能，会保存在指定目录，提示框会给出存储路径。\n"
            "5.串号查询功能,由于串号格式差异的原因,某些设备可能无法获取到正确的串号,请自行判断\n"
            "6.可自行调整输出框高度，鼠标可滚动查看历史信息。\n"
        )
        # messagebox.showinfo("操作说明和注意事项", help_text)
        self.update_status(help_text, True)


if __name__ == "__main__":
    root = tk.Tk()
    app = ADBToolApp(root)
    root.mainloop()