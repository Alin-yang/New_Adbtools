"""
设备监控模块
实现后台实时设备状态监控功能
"""
import threading
import time
from typing import Callable, Optional, List
from utils import get_connected_devices_cached  # 🆕 使用缓存版本
from config import Config


class DeviceMonitor:
    """设备状态监控器，提供实时设备连接状态更新"""
    
    def __init__(self, app):
        """
        初始化设备监控器
        
        Args:
            app: 主应用实例
        """
        self.app = app
        self.monitoring = False
        self.monitor_thread = None
        self.check_interval = Config.DEVICE_MONITOR_INTERVAL  # 从配置读取检查间隔
        self.callbacks = []  # 状态变化回调函数列表
    
    def start_monitoring(self):
        """启动后台设备监控"""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        if self.app:
            self.app.update_status("设备监控已启动", True)
    
    def stop_monitoring(self):
        """停止设备监控"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        if self.app:
            self.app.update_status("设备监控已停止", True)
    
    def add_callback(self, callback: Callable[[List[str]], None]):
        """
        添加设备状态变化回调
        
        Args:
            callback: 回调函数，接收设备列表参数
        """
        if callback not in self.callbacks:
            self.callbacks.append(callback)
    
    def remove_callback(self, callback: Callable):
        """移除回调函数"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def _monitor_loop(self):
        """监控循环（在后台线程运行）"""
        last_devices = []
        
        while self.monitoring:
            try:
                # 🆕 优化2：使用缓存版本快速获取设备列表
                current_devices = get_connected_devices_cached()
                
                # 检测设备列表变化
                if set(current_devices) != set(last_devices):
                    # 设备列表发生变化，触发回调
                    for callback in self.callbacks:
                        try:
                            # 在主线程中执行回调
                            if self.app:
                                self.app.root.after(0, lambda d=current_devices: callback(d))
                            else:
                                callback(current_devices)
                        except Exception as e:
                            # 回调执行失败不影响其他回调
                            pass
                    
                    # 更新 UI 显示（使用防抖）
                    if self.app:
                        self.app.root.after(0, lambda: self._update_device_status_ui(current_devices))
                    
                    last_devices = current_devices
                
                # 等待下一次检查
                time.sleep(self.check_interval)
                
            except Exception as e:
                # 监控出错不中断循环
                time.sleep(self.check_interval)
    
    def _update_device_status_ui(self, devices: List[str]):
        """在 UI 上更新设备状态"""
        if not self.app or not hasattr(self.app, 'update_connection_status'):
            return
        
        # 更新连接状态标签
        self.app.update_connection_status()
        
        # 如果当前没有设备但之前有，提示用户
        if not devices and hasattr(self.app, '_last_displayed_ip') and self.app._last_displayed_ip:
            self.app.update_status("⚠️ 所有设备已断开连接", False)
        elif devices and not hasattr(self.app, '_last_displayed_ip') or not self.app._last_displayed_ip:
            self.app.update_status(f"📱 检测到 {len(devices)} 台设备连接", True)


class DeviceStatusManager:
    """设备状态管理器，提供更智能的设备连接管理"""
    
    def __init__(self, app):
        """
        初始化设备状态管理器
        
        Args:
            app: 主应用实例
        """
        self.app = app
        self.monitor = DeviceMonitor(app)
        self._device_change_callbacks = []
    
    def start_auto_monitor(self):
        """启动自动监控模式"""
        # 添加默认回调：更新 IP 下拉框
        self.monitor.add_callback(self._on_device_list_changed)
        
        # 启动监控
        self.monitor.start_monitoring()
    
    def stop_auto_monitor(self):
        """停止自动监控模式"""
        self.monitor.stop_monitoring()
    
    def _on_device_list_changed(self, devices: List[str]):
        """
        设备列表变化时的处理
        
        Args:
            devices: 新的设备列表
        """
        if not self.app or not hasattr(self.app, 'ip_combobox'):
            return
        
        # 更新 IP 历史记录
        current_history = list(self.app.ip_history)
        
        # 添加新设备到历史记录（标准化格式：IP去端口，USB设备直接保存）
        for device in devices:
            # 标准化设备标识：如果是IP地址带端口，去除端口号
            normalized_device = device
            if ':' in device and '.' in device:  # IP地址格式（包含冒号和点号）
                normalized_device = device.split(':')[0]  # 只保留IP部分
            
            # 如果设备不在历史记录中，添加到最前面
            if normalized_device not in current_history:
                current_history.insert(0, normalized_device)
        
        # 限制历史记录数量
        current_history = current_history[:15]  # 最多保留 15 条
        
        # 更新 UI
        self.app.ip_history = current_history
        self.app.ip_combobox['values'] = current_history
        
        # 调度保存到文件（防抖）
        if hasattr(self.app, '_schedule_history_save'):
            self.app._schedule_history_save()
        
        # 通知其他组件
        for callback in self._device_change_callbacks:
            try:
                callback(devices)
            except:
                pass
    
    def add_device_change_callback(self, callback: Callable[[List[str]], None]):
        """
        添加设备变化回调
        
        Args:
            callback: 回调函数
        """
        self._device_change_callbacks.append(callback)
