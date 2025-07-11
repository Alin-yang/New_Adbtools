"""
应用管理模块
负责APK安装、卸载、应用列表等功能
"""
import os
import time
import threading
import subprocess
import concurrent.futures
from typing import Optional, List, Dict, Any
from tkinter import messagebox
import tkinter as tk

from utils import (
    run_adb_command, extract_version_info, get_next_filename,
    calculate_optimal_workers, format_file_size, get_accurate_package_version
)
from cache_manager import cache_manager
from config import Config


class AppManager:
    """应用管理器类"""
    
    def __init__(self, app):
        """
        初始化应用管理器
        
        Args:
            app: 主应用实例
        """
        self.app = app
    
    def force_install(self) -> None:
        """带进度显示的强制安装"""
        apk_path = self.app.apk_entry.get().strip()
        if not apk_path:
            self.app.update_status("请选择APK文件", False)
            return
        
        if not os.path.exists(apk_path):
            self.app.update_status("APK文件不存在", False)
            return

        # 显示进度条
        self.app._show_progress()
        self.app.update_status("开始安装应用...", True)

        # 启动安装线程
        install_thread = threading.Thread(
            target=self._run_install_with_progress,
            args=(apk_path,),
            daemon=True
        )
        install_thread.start()
    
    def _run_install_with_progress(self, apk_path: str) -> None:
        """实际执行安装并捕获输出"""
        try:
            # 获取APK大小用于计算进度
            apk_size = os.path.getsize(apk_path)
            current_size = 0
            
            process = subprocess.Popen(
                f"adb install -r -d \"{apk_path}\"",
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
                        self.app.progress["mode"] = "determinate"
                        self.app.progress["maximum"] = 100
                        self.app.progress["value"] = 0
                        current_size = 0
                        continue

                    # 更新进度
                    if installing_started:
                        # 估算进度
                        current_size += len(output)  # 增加已处理的数据大小
                        progress = min(95, int((current_size / apk_size) * 100))
                        self.app.progress["value"] = progress
                        
                        if "Success" in stripped_output:
                            self.app.progress["value"] = 100
                            self._update_install_status("安装成功")
                        elif "Failure" in stripped_output:
                            self._update_install_status(f"安装失败: {stripped_output}")
                        elif not any(keyword in stripped_output for keyword in filter_keywords):
                            self._update_install_status(stripped_output)

            # 获取最终结果
            return_code = process.poll()
            success = return_code == 0
            
            # 重置进度条模式
            self.app.progress["mode"] = "indeterminate"
            self.app._hide_progress()
            
            final_output = "安装成功" if success else f"安装失败 (code {return_code})"
            self._update_install_status(final_output)
            
            # 如果安装成功，显示APK信息
            if success:
                file_size = format_file_size(os.path.getsize(apk_path))
                apk_name = os.path.basename(apk_path)
                self.app.update_status(f"安装完成\\n文件: {apk_name}\\n大小: {file_size}", True)
            
        except Exception as e:
            self._update_install_status(f"安装过程出错: {str(e)}")
            self.app._hide_progress()
    
    def _update_install_status(self, message: str) -> None:
        """更新安装状态"""
        if "成功" in message:
            self.app.status_text.insert(tk.END, f"\\n{message}\\n", "success")
        elif "失败" in message or "错误" in message:
            self.app.status_text.insert(tk.END, f"\\n{message}\\n", "error")
        else:
            self.app.status_text.insert(tk.END, f"\\n{message}\\n")
        self.app.status_text.see(tk.END)
    
    def uninstall(self) -> bool:
        """
        卸载应用(带确认对话框)
        
        Returns:
            bool: 卸载是否成功
        """
        pkg_name = self.app.pkg_entry.get().strip()
        if not pkg_name:
            self.app.update_status("请输入包名", False)
            return False

        # 显示确认对话框
        result = messagebox.askyesno(
            "确认卸载",
            f"您确定要卸载应用吗？\\n\\n包名: {pkg_name}\\n\\n注意：卸载后应用数据将被永久删除。",
            icon="warning"
        )
        
        if result:
            output, success = run_adb_command(f"adb uninstall {pkg_name}")
            if success:
                # 清除包信息缓存
                cache_manager.package_cache.delete(f"package_{pkg_name}")
            self.app.update_status(output, success)
            return success
        else:
            self.app.update_status("已取消卸载操作", True)
            return False
    
    def package_list(self) -> None:
        """获取已安装应用包名列表及其版本(优化版，使用动态线程池)"""
        try:
            # 获取所有已安装包名
            output, success = run_adb_command("adb shell pm list packages")
            if not success:
                self.app.update_status("获取应用列表失败", False)
                return

            # 清理并获取包名列表
            packages = [line.replace("package:", "").strip() 
                       for line in output.splitlines() if line.strip()]
            
            if not packages:
                self.app.update_status("未找到已安装的应用", False)
                return
            
            self.app.update_status(f"正在获取 {len(packages)} 个应用的版本信息...", True)
            
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
                        self.app.status_text.insert(
                            tk.END, 
                            f"\\n{package} (版本: {version_str})", 
                            "info"
                        )
                    except Exception as e:
                        self.app.status_text.insert(
                            tk.END,
                            f"\\n{package} (版本: 获取失败 - {str(e)})",
                            "error"
                        )
                    
                    processed_count += 1
                    # 每处理10个显示一次进度
                    if processed_count % 10 == 0:
                        self.app.status_text.insert(
                            tk.END,
                            f"\\n已处理 {processed_count}/{len(packages)} 个应用",
                            "info"
                        )
                    
                    self.app.status_text.see(tk.END)
                    
            self.app.update_status(f"\\n获取应用列表完成，共 {len(packages)} 个应用", True)
            
        except Exception as e:
            self.app.update_status(f"获取应用列表时出错: {str(e)}", False)
    
    def get_package_version(self, package_name: str) -> Optional[str]:
        """
        获取应用版本号(优化版，优先获取最新版本)
        
        Args:
            package_name: 应用包名
            
        Returns:
            Optional[str]: 版本号，如果获取失败则返回None
        """
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
    
    def clear_cache(self) -> bool:
        """
        清除应用缓存(带确认对话框)
        
        Returns:
            bool: 清除是否成功
        """
        pkg_name = self.app.pkg_entry.get().strip()
        if not pkg_name:
            self.app.update_status("请输入包名", False)
            return False

        # 显示确认对话框
        result = messagebox.askyesno(
            "确认清理缓存",
            f"您确定要清理应用缓存吗？\\n\\n包名: {pkg_name}\\n\\n注意：清理后应用需要重新加载数据。",
            icon="question"
        )
        
        if result:
            output, success = run_adb_command(f"adb shell pm clear {pkg_name}")
            if success:
                # 清除包信息缓存
                cache_manager.package_cache.delete(f"package_{pkg_name}")
            self.app.update_status(output, success)
            return success
        else:
            self.app.update_status("已取消清理缓存操作", True)
            return False
    
    def get_version(self) -> Optional[str]:
        """
        获取应用版本(优化版，优先获取最新版本)
        
        Returns:
            Optional[str]: 应用版本号
        """
        pkg_name = self.app.pkg_entry.get().strip()
        if not pkg_name:
            self.app.update_status("请输入包名", False)
            return None

        # 先检查缓存
        cached_info = cache_manager.get_package_info(pkg_name)
        if cached_info and 'version' in cached_info:
            version = cached_info['version']
            self.app.update_status(f"当前应用{pkg_name}版本: {version}", True)
            return version

        # 使用新的精确版本获取方法
        version = get_accurate_package_version(pkg_name)
        if version:
            # 更新缓存
            package_info = {'version': version, 'name': pkg_name}
            cache_manager.set_package_info(pkg_name, package_info)
            self.app.update_status(f"当前应用{pkg_name}版本: {version}", True)
            return version
        else:
            self.app.update_status("版本信息解析失败", False)
        return None
    
    def kill_app_process(self) -> bool:
        """
        强制停止应用进程
        
        Returns:
            bool: 停止是否成功
        """
        pkg_name = self.app.pkg_entry.get().strip()
        if not pkg_name:
            self.app.update_status("请输入需要终止进程的应用包名", False)
            return False

        try:
            output, success = run_adb_command(f"adb shell am force-stop {pkg_name}")
            if success:
                self.app.update_status(f"成功终止{pkg_name}应用所处进程", True)
                return True
            else:
                self.app.update_status(f"终止{pkg_name}进程失败", False)
                return False
        except Exception as e:
            self.app.update_status(f"未找到{pkg_name}所属进程: {str(e)}", False)
            return False
    
    def get_package_path(self) -> Optional[str]:
        """
        获取当前包名应用安装路径
        
        Returns:
            Optional[str]: 应用安装路径
        """
        pkg_name = self.app.pkg_entry.get().strip()
        if not pkg_name:
            self.app.update_status("请输入包名", False)
            return None
        
        try:
            output, success = run_adb_command(f"adb shell pm path {pkg_name}")
            if success and output:
                # 移除"package:"前缀并清理输出
                path = output.replace("package:", "").strip()
                self.app.status_text.insert(tk.END, f"\\n应用安装路径: {path}\\n", "info")
                self.app.status_text.see(tk.END)
                return path
            else:
                self.app.update_status(f"未找到包名 {pkg_name} 的安装路径", False)
                return None
        except Exception as e:
            self.app.update_status(f"获取安装路径失败: {str(e)}", False)
            return None