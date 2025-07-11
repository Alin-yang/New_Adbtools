"""
设备管理模块
负责ADB设备连接、状态检查等功能
"""
from typing import Optional, Tuple
from utils import run_adb_command, save_ip_history, is_valid_ip
from cache_manager import cache_manager
from config import Config


class DeviceManager:
    """设备管理器类"""
    
    def __init__(self, app):
        """
        初始化设备管理器
        
        Args:
            app: 主应用实例
        """
        self.app = app
    
    def get_ip_address(self) -> Optional[str]:
        """
        获取IP地址（仅支持中文版本）
        
        Returns:
            Optional[str]: IP地址字符串，如果未输入则返回None
        """
        if hasattr(self.app, 'ip_combobox'):
            return self.app.ip_combobox.get().strip()
        return None
    
    def connect_adb(self) -> bool:
        """
        连接ADB设备
        
        Returns:
            bool: 连接是否成功
        """
        ip_address = self.get_ip_address()
        if not ip_address:
            self.app.update_status("请输入IP地址", False)
            return False
        
        if not is_valid_ip(ip_address):
            self.app.update_status("IP地址格式不正确", False)
            return False
        
        output, success = run_adb_command(f"adb connect {ip_address}")
        if "connected" in output.lower():
            # 保存新的IP到历史记录
            if ip_address not in self.app.ip_history:
                self.app.ip_history.insert(0, ip_address)
                save_ip_history(self.app.ip_history)
                if hasattr(self.app, 'ip_combobox'):
                    self.app.ip_combobox['values'] = self.app.ip_history
            
            # 更新设备连接状态缓存
            cache_manager.set_device_status(ip_address, True)
            self.app.update_status(output, True)
            return True
        else:
            cache_manager.set_device_status(ip_address, False)
            self.app.update_status(output, False)
            return False
    
    def disconnect_adb(self) -> bool:
        """
        断开ADB连接
        
        Returns:
            bool: 断开是否成功
        """
        output, success = run_adb_command("adb disconnect")
        if success:
            # 清除所有设备连接状态缓存
            cache_manager.device_cache.clear()
            if "disconnected" in output.lower():
                self.app.update_status(output, True)
                return True
        
        self.app.update_status(output, False)
        return False
    
    def check_device_connected(self, ip_address: Optional[str] = None) -> bool:
        """
        检查设备连接状态(使用新的缓存系统)
        
        Args:
            ip_address: 要检查的IP地址，如果为None则使用当前输入的IP
            
        Returns:
            bool: 设备是否已连接
        """
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
        """
        设备连接验证
        
        Returns:
            bool: 设备是否已连接
        """
        ip_address = self.get_ip_address()
        if not ip_address:
            self.app.update_status("请输入IP地址", False)
            return False
        if not self.check_device_connected(ip_address):
            self.app.update_status(f"设备未连接: {ip_address}", False)
            return False
        return True
    
    def get_device_list(self) -> Tuple[list, bool]:
        """
        获取已连接的设备列表
        
        Returns:
            Tuple[list, bool]: (设备列表, 是否成功)
        """
        output, success = run_adb_command("adb devices")
        if success:
            devices = []
            for line in output.splitlines()[1:]:
                if line.strip() and "device" in line:
                    device_id = line.split("\t")[0]
                    devices.append(device_id)
            return devices, True
        return [], False
    
    def reboot_device(self) -> bool:
        """
        重启设备
        
        Returns:
            bool: 重启命令是否执行成功
        """
        output, success = run_adb_command("adb reboot")
        if success:
            self.app.update_status("设备重启中...", True)
            # 清空设备缓存，因为重启后连接状态会发生变化
            cache_manager.device_cache.clear()
            return True
        else:
            self.app.update_status(output, False)
            return False