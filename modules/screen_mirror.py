"""
投屏管理模块 - 基于 scrcpy 实现
提供 Android 设备屏幕镜像和交互功能
"""
import subprocess
import threading
import logging
import os
import sys
from typing import Optional
from config import Config


class ScreenMirrorManager:
    """投屏管理器 - 使用 scrcpy 实现"""
    
    def __init__(self, app):
        """
        初始化投屏管理器
        
        Args:
            app: ADBToolApp 实例
        """
        self.app = app
        self.scrcpy_process: Optional[subprocess.Popen] = None
        self.is_mirroring = False
        self.mirror_thread: Optional[threading.Thread] = None
        
    def start_mirroring(self, device_ip: str = None) -> bool:
        """
        启动投屏
        
        Args:
            device_ip: 设备 IP 地址或序列号，如果为 None 则使用当前选中的设备
            
        Returns:
            bool: 是否成功启动
        """
        if self.is_mirroring:
            logging.warning("[投屏] 投屏已在运行中")
            self.app.update_status("⚠ 投屏已在运行中", False)
            return False
        
        # 获取设备标识
        if not device_ip:
            device_ip = self.app.get_ip_address()
        
        if not device_ip or device_ip == "192.168.":
            self.app.update_status("✗ 请先输入设备 IP 地址或选择设备", False)
            return False
        
        try:
            # 检查 scrcpy 是否存在
            scrcpy_path = self._get_scrcpy_path()
            if not scrcpy_path or not os.path.exists(scrcpy_path):
                error_msg = (
                    "未找到 scrcpy.exe\n"
                    "请下载 scrcpy 并放置到 tools/scrcpy/ 目录\n"
                    "下载地址: https://github.com/Genymobile/scrcpy/releases"
                )
                logging.error(f"[投屏] {error_msg}")
                self.app.update_status(f"✗ {error_msg}", False)
                return False
            
            # 构建 scrcpy 命令
            cmd = self._build_scrcpy_command(scrcpy_path, device_ip)
            
            logging.info(f"[投屏] 启动命令: {' '.join(cmd)}")
            self.app.update_status(f"⏳ 正在启动投屏 ({device_ip})...", True, "info")
            
            # 在后台线程中启动 scrcpy（避免阻塞 UI）
            self.mirror_thread = threading.Thread(
                target=self._launch_scrcpy,
                args=(cmd,),
                daemon=True,
                name="ScreenMirror"
            )
            self.mirror_thread.start()
            
            return True
            
        except Exception as e:
            error_msg = f"启动投屏失败: {str(e)}"
            logging.error(f"[投屏] {error_msg}", exc_info=True)
            self.app.update_status(f"✗ {error_msg}", False)
            self.is_mirroring = False
            return False
    
    def stop_mirroring(self) -> bool:
        """
        停止投屏
        
        Returns:
            bool: 是否成功停止
        """
        if not self.is_mirroring or not self.scrcpy_process:
            logging.warning("[投屏] 投屏未在运行")
            self.app.update_status("⚠ 投屏未在运行", False)
            return False
        
        try:
            logging.info("[投屏] 正在停止投屏...")
            self.app.update_status("⏳ 正在停止投屏...", True, "info")
            
            # 终止进程
            self.scrcpy_process.terminate()
            
            # 等待进程结束（最多 5 秒）
            try:
                self.scrcpy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logging.warning("[投屏] 进程未在 5 秒内结束，强制终止")
                self.scrcpy_process.kill()
                self.scrcpy_process.wait()
            
            self.is_mirroring = False
            self.scrcpy_process = None
            
            logging.info("[投屏] 投屏已停止")
            self.app.update_status("✓ 投屏已停止", True)
            return True
            
        except Exception as e:
            error_msg = f"停止投屏失败: {str(e)}"
            logging.error(f"[投屏] {error_msg}", exc_info=True)
            self.app.update_status(f"✗ {error_msg}", False)
            
            # 强制清理状态
            self.is_mirroring = False
            self.scrcpy_process = None
            return False
    
    def _get_scrcpy_path(self) -> Optional[str]:
        """
        获取 scrcpy 可执行文件路径（支持打包后运行）
        
        Returns:
            Optional[str]: scrcpy.exe 的完整路径，如果不存在则返回 None
        """
        # 尝试多个可能的路径
        possible_paths = []
        
        # 1. 打包后的临时目录（PyInstaller 解压后的位置）
        if hasattr(sys, '_MEIPASS'):
            possible_paths.append(os.path.join(sys._MEIPASS, 'tools', 'scrcpy', 'scrcpy.exe'))
        
        # 2. 开发环境 - 相对路径
        possible_paths.append(os.path.join(os.getcwd(), 'tools', 'scrcpy', 'scrcpy.exe'))
        
        # 3. 开发环境 - 基于模块路径
        possible_paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools', 'scrcpy', 'scrcpy.exe'))
        
        # 4. 配置文件中定义的路径
        possible_paths.append(Config.get_actual_path(Config.SCRCPY_PATH))
        
        # 尝试所有可能的路径
        for path in possible_paths:
            normalized_path = os.path.normpath(path)
            if os.path.exists(normalized_path):
                logging.info(f"[投屏] 找到 scrcpy: {normalized_path}")
                return normalized_path
        
        logging.warning(f"[投屏] 未找到 scrcpy.exe，已尝试路径: {possible_paths}")
        return None
    
    def _build_scrcpy_command(self, scrcpy_path: str, device_ip: str) -> list:
        """
        构建 scrcpy 命令
        
        Args:
            scrcpy_path: scrcpy.exe 的路径
            device_ip: 设备 IP 或序列号
            
        Returns:
            list: 命令参数列表
        """
        cmd = [
            scrcpy_path,
            "--video-bit-rate", Config.SCRCPY_BITRATE,  # 修改为 --video-bit-rate
            "--max-size", Config.SCRCPY_MAX_SIZE,
            "--max-fps", Config.SCRCPY_MAX_FPS,
            "--window-title", f"ADB Tool - {device_ip}",
            "--stay-awake",  # 保持设备唤醒
            # "--turn-screen-off",  # 注释掉：关闭设备屏幕（可选，默认开启）
            "--show-touches",  # 显示触摸点
        ]
        
        # 如果指定了设备，添加 -s 参数
        if device_ip:
            cmd.extend(["-s", device_ip])
        
        return cmd
    
    def _launch_scrcpy(self, cmd: list):
        """
        在后台线程中启动 scrcpy
        
        Args:
            cmd: scrcpy 命令参数列表
        """
        try:
            logging.info(f"[投屏] 启动 scrcpy 进程...")
            
            # 启动 scrcpy 进程
            self.scrcpy_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            self.is_mirroring = True
            
            # 在主线程中更新 UI
            self.app.root.after(0, lambda: self.app.update_status(
                f"✓ 投屏已启动 - {self._get_device_name_from_cmd(cmd)}", 
                True
            ))
            
            logging.info(f"[投屏] scrcpy 进程已启动 (PID: {self.scrcpy_process.pid})")
            
            # 等待进程结束
            stdout, stderr = self.scrcpy_process.communicate()

            # 关键修复：先取出退出码，再清理引用
            # 原代码先置 None 再判断 returncode，导致正常退出分支永远不可达
            returncode = self.scrcpy_process.returncode
            self.is_mirroring = False
            self.scrcpy_process = None

            # 检查退出码
            if returncode == 0:
                logging.info("[投屏] scrcpy 正常退出")
                self.app.root.after(0, lambda: self.app.update_status("✓ 投屏已正常结束", True))
            else:
                error_output = stderr.decode('utf-8', errors='ignore') if stderr else ""
                logging.warning(f"[投屏] scrcpy 异常退出 (returncode: {returncode})")
                if error_output:
                    logging.warning(f"[投屏] 错误输出: {error_output[:500]}")
                    # 在主线程中显示错误信息
                    self.app.root.after(0, lambda msg=error_output[:200]: self.app.update_status(f"✗ 投屏错误: {msg}", False))
                self.app.root.after(0, lambda: self.app.update_status("⚠ 投屏已断开", False))
                
        except FileNotFoundError:
            error_msg = "未找到 scrcpy.exe，请确保已下载并放置在 tools/scrcpy/ 目录"
            logging.error(f"[投屏] {error_msg}")
            self.app.root.after(0, lambda: self.app.update_status(f"✗ {error_msg}", False))
            self.is_mirroring = False
            
        except Exception as e:
            error_msg = f"启动 scrcpy 失败: {str(e)}"
            logging.error(f"[投屏] {error_msg}", exc_info=True)
            self.app.root.after(0, lambda msg=error_msg: self.app.update_status(f"✗ {msg}", False))
            self.is_mirroring = False
    
    def _get_device_name_from_cmd(self, cmd: list) -> str:
        """从命令中提取设备名称"""
        try:
            if "-s" in cmd:
                idx = cmd.index("-s")
                if idx + 1 < len(cmd):
                    return cmd[idx + 1]
        except Exception:
            pass
        return "Device"
    
    def get_mirror_status(self) -> dict:
        """
        获取投屏状态
        
        Returns:
            dict: 包含投屏状态信息的字典
        """
        return {
            "is_mirroring": self.is_mirroring,
            "process_running": self.scrcpy_process is not None and self.scrcpy_process.poll() is None,
            "pid": self.scrcpy_process.pid if self.scrcpy_process else None,
        }
