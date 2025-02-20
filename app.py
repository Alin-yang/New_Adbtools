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
    get_next_filename
)
from gui.layout import setup_gui

class ADBToolApp:
    # 预先声明所有动态绑定的GUI组件
    apk_entry:ttk.Entry
    ip_entry:ttk.Entry
    pkg_entry:ttk.Entry
    status_text:tk.Text
    progress: ttk.Progressbar # 进度条声明

    def __init__(self, root):
        self.root = root
        self.root.title("ADB Tool")
        self._init_variables()
        self._setup_gui()

    def _init_variables(self):
        """初始化实例变量"""
        self.logcat_process = None
        self.log_file_path = f"D:\\{timestamp_time()}.log"
        self.logging_active = False
        self.logcat_subprocess = None
        self.stop_event = threading.Event()
        self.progress = None  # 添加进度条引用

    def _setup_gui(self):
        from gui.layout import setup_gui
        # print("调试：加载GUI前是否有ip_entry属性?", hasattr(self, 'ip_entry'))  # 应输出False
        setup_gui(self)
        # print("调试：加载GUI后是否有ip_entry属性?", hasattr(self, 'ip_entry'))  # 应输出True

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

    # 核心ADB操作方法
    # @require_device_connected
    def connect_adb(self):
        """连接ADB设备"""
        ip_address = self.ip_entry.get()
        output, success = run_adb_command(f"adb connect {ip_address}")
        if "connected" in output.lower():
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
        """检查设备连接状态"""
        output, success = run_adb_command("adb devices")
        if success:
            devices = [line.split("\t")[0] for line in output.splitlines()[1:] if "device" in line]
            ip_with_port = f"{ip_address}:5555" if ip_address else None
            return ip_address in devices or ip_with_port in devices
        return False

    def ensure_device_connected(self):
        """设备连接验证"""
        ip_address = self.ip_entry.get()
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
            process = subprocess.Popen(
                f"adb install -r -d {apk_path}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            # 定义需要过滤的关键词
            filter_keywords = ["Performing Streamed Install"]

            # 实时捕获输出
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    stripped_output = output.strip()
                    if not any(keyword in stripped_output for keyword in filter_keywords):
                        self._update_install_status(stripped_output)  # 仅传递有效内容

            # 获取最终结果
            return_code = process.poll()
            success = return_code == 0
            final_output = "安装成功" if success else f"安装失败 (code {return_code})"

        except Exception as e:
            final_output = f"安装异常: {str(e)}"
            success = False

        # 更新最终状态
        self.root.after(0, lambda: [
            self._hide_progress(),
            self.update_status(final_output, success)
        ])


    def _update_install_status(self, message):
        """线程安全的状态更新"""
        self.root.after(0, lambda: self.status_text.insert(
            tk.END, f"\n{message}\n", "success" if "Success" in message else "error"
        ))

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
        """显示已安装包列表"""
        output, success = run_adb_command("adb shell pm list packages")
        if success:
            packages = "\n".join(output.strip().split("\n")[1:])
            self.update_status(f"已安装应用包名:\n{packages}", True)
        else:
            self.update_status(output, False)



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
        output, success = run_adb_command("adb shell screencap -p /sdcard/screenshot.png")
        if success:
            save_dir = ensure_directory("D:\\TV截图")
            new_file = get_next_filename(os.path.join(save_dir, "截图"), ".png")
            run_adb_command(f"adb pull /sdcard/screenshot.png {new_file}")
            self.update_status(f"截图已保存至路径: {new_file}", True)
        else:
            self.update_status(output, False)

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

        self.logging_active = True
        self.stop_event.clear()
        self.log_file_path = f"D:\\{timestamp_time()}.log"

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
        self.logcat_thread.join(timeout=5)

        if os.path.exists(self.log_file_path):
            new_name = f"D:\\{timestamp_time()}.log"
            os.rename(self.log_file_path, new_name)
            self.update_status(f"日志文件已保存至: {new_name}", True)
        else:
            self.update_status("未找到日志文件", False)
        self.logging_active = False

    def _run_logcat(self):
        """实际执行日志捕获"""
        try:
            with open(self.log_file_path, "w") as f:
                self.logcat_subprocess = subprocess.Popen(
                    ["adb", "logcat", "-v", "time", "*:V"],
                    stdout=f,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )

                while self.logcat_subprocess.poll() is None:
                    if self.stop_event.wait(0.5):
                        self._terminate_logcat()
                        break
        except Exception as e:
            self.update_status(f"日志错误: {str(e)}", False)

    def _terminate_logcat(self):
        """终止日志进程"""
        if self.logcat_subprocess and self.logcat_subprocess.poll() is None:
            try:
                self.logcat_subprocess.send_signal(subprocess.signal.CTRL_BREAK_EVENT)
                self.logcat_subprocess.wait(timeout=3)
            except (subprocess.TimeoutExpired, AttributeError):
                parent = psutil.Process(self.logcat_subprocess.pid)
                for child in parent.children(recursive=True):
                    child.kill()
                parent.kill()

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


            "\n注意事项:\n"
            "1. 确保设备已连接到同一网络。\n"
            "2. 使用期间请保持ADB连接。\n"
            "3. 使用前请备份重要数据。\n"
            "4. 查询应用版本、清缓存、卸载应用时需输入对应的包名。\n"
            "5. 抓取ANR文件、日志、TV截屏功能，会保存在指定目录，提示框会给出存储路径。\n"
            "6. 串号查询功能，由于串号格式差异的原因，某些设备可能无法获取到正确的串号，请自行判断。\n"
        )
        messagebox.showinfo("操作说明和注意事项", help_text)

if __name__ == "__main__":
    root = tk.Tk()
    app = ADBToolApp(root)
    root.mainloop()