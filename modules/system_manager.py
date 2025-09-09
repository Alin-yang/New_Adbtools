"""
系统管理模块
负责系统信息获取、截图、ANR文件等功能
"""
import os
import time
from typing import Optional
from utils import run_adb_command, ensure_directory, get_next_filename, format_file_size
from cache_manager import cache_manager
from config import Config


class SystemManager:
    """系统管理器类"""
    
    def __init__(self, app):
        """
        初始化系统管理器
        
        Args:
            app: 主应用实例
        """
        self.app = app
    
    def get_android_version(self) -> Optional[str]:
        """
        获取Android版本(使用缓存)
        
        Returns:
            Optional[str]: Android版本号
        """
        # 检查系统信息缓存
        cached_version = cache_manager.get_system_info("android_version")
        if cached_version:
            self.app.update_status(f"Android版本: {cached_version}", True)
            return cached_version
            
        output, success = run_adb_command("adb shell getprop ro.build.version.release")
        if success:
            version = output.strip()
            cache_manager.set_system_info("android_version", version)
            self.app.update_status(f"Android版本: {version}", True)
            return version
        else:
            self.app.update_status(output, False)
            return None
    
    def get_serial_number(self) -> Optional[str]:
        """
        获取设备序列号(优化版，多策略获取)
        
        Returns:
            Optional[str]: 设备序列号
        """
        from utils import get_device_serial_number
        
        # 检查系统信息缓存
        cached_serial = cache_manager.get_system_info("serial_number")
        if cached_serial:
            self.app.update_status(
                f"设备序列号: {cached_serial}  \\n-注：已优化获取策略，自动适配连接方式。", 
                True
            )
            return cached_serial
            
        # 使用多策略获取设备标识
        serial = get_device_serial_number()
        if serial:
            cache_manager.set_system_info("serial_number", serial)
            
            # 根据结果类型提供不同的提示信息（优先硬件串号）
            if ':' in serial and serial.count('.') == 3:
                # IP地址格式，说明是网络连接标识（备用方案）
                info_msg = f"设备标识: {serial} (网络连接)\\n-注：已优化获取策略，优先硬件串号。"
            elif len(serial) == 16 and all(c in '0123456789abcdefABCDEF' for c in serial):
                # 16位十六进制，可能是Android ID（备用方案）
                info_msg = f"设备标识: {serial} (Android ID)\\n-注：已优化获取策略，优先硬件串号。"
            else:
                # 硬件序列号或其他格式（首选）
                info_msg = f"设备序列号: {serial}\\n-注：已优化获取策略，优先硬件串号。"
            
            self.app.update_status(info_msg, True)
            return serial
        else:
            self.app.update_status("无法获取设备序列号，请检查设备连接和权限。", False)
            return None
    
    def screencap(self) -> bool:
        """
        屏幕截图(优化版)
        
        Returns:
            bool: 截图是否成功
        """
        try:
            # 先显示提示信息
            self.app.update_status("正在截图，请稍候...", True)
            # 强制更新界面
            self.app.root.update()
            # 短暂延迟，确保提示信息显示
            time.sleep(0.5)
            
            # 先清理可能存在的旧截图
            run_adb_command("adb shell rm -f /sdcard/screenshot.png")
            
            # 获取用户设置的日志存储路径
            log_path = self.app.log_path_entry.get().strip()
            if not log_path:
                log_path = self.app.default_log_path
            
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
                output3, success3 = run_adb_command(f"adb pull /sdcard/screenshot.png \"{new_file}\"")
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
                self.app.update_status(f"截图已保存至路径: {new_file}\\n文件大小: {file_size}", True)
                # 尝试打开截图所在文件夹
                try:
                    os.startfile(os.path.dirname(new_file))
                except:
                    pass
                return True
            else:
                self.app.update_status(f"截图失败: {error_msg}", False)
                return False
                
        except Exception as e:
            self.app.update_status(f"截图过程出错: {str(e)}", False)
            return False
    
    def pull_anr_file(self) -> bool:
        """
        拉取ANR文件
        
        Returns:
            bool: 拉取是否成功
        """
        try:
            anr_dir = ensure_directory(Config.DEFAULT_ANR_PATH)
            output, success = run_adb_command(f"adb pull /data/anr \"{anr_dir}\"")
            
            if success:
                self.app.update_status(f"ANR文件已保存至: {anr_dir}", True)
                # 尝试打开ANR文件夹
                try:
                    os.startfile(anr_dir)
                except:
                    pass
                return True
            else:
                self.app.update_status(f"ANR文件拉取失败: {output}", False)
                return False
        except Exception as e:
            self.app.update_status(f"拉取ANR文件时出错: {str(e)}", False)
            return False
    
    def root_device(self) -> bool:
        """
        获取root权限
        
        Returns:
            bool: root是否成功
        """
        output, success = run_adb_command("adb root")
        if success:
            # 清除设备缓存，因为root后连接状态可能变化
            cache_manager.device_cache.clear()
        self.app.update_status(output, success)
        return success
    
    def remount(self) -> bool:
        """
        重新挂载分区
        
        Returns:
            bool: 重新挂载是否成功
        """
        output, success = run_adb_command("adb remount")
        self.app.update_status(output, success)
        return success
    
    def get_package_name(self) -> Optional[str]:
        """
        获取当前打开应用包名
        
        Returns:
            Optional[str]: 当前应用包名
        """
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
                        self.app.update_status("获取当前应用包名失败", False)
                        return None

            # 调试输出
            self.app.update_status(f"原始输出: {output}", True)
            
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
                    self.app.update_status(f"当前应用包名: {package_name}", True)
                    # 自动填充包名到输入框
                    self.app.pkg_entry.delete(0, tk.END)
                    self.app.pkg_entry.insert(0, package_name)
                    return package_name
                else:
                    self.app.update_status("解析出的包名格式不正确", False)
            else:
                self.app.update_status("无法解析应用包名", False)
                
        except Exception as e:
            self.app.update_status(f"获取应用包名时出错: {str(e)}", False)
        
        return None
    
    def get_device_info(self) -> dict:
        """
        获取设备详细信息
        
        Returns:
            dict: 设备信息字典
        """
        info = {}
        
        # 获取设备型号
        output, success = run_adb_command("adb shell getprop ro.product.model")
        if success:
            info["model"] = output.strip()
        
        # 获取设备品牌
        output, success = run_adb_command("adb shell getprop ro.product.brand")
        if success:
            info["brand"] = output.strip()
        
        # 获取Android API级别
        output, success = run_adb_command("adb shell getprop ro.build.version.sdk")
        if success:
            info["api_level"] = output.strip()
        
        # 获取屏幕分辨率
        output, success = run_adb_command("adb shell wm size")
        if success:
            info["screen_size"] = output.strip()
        
        return info