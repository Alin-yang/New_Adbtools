def require_device_connected(func):
    """设备连接校验装饰器（增强版 - 使用缓存优化）"""
    def wrapper(self, *args, **kwargs):
        # 🆕 优化2：使用缓存版本检查设备连接
        from utils import get_connected_devices_cached
        devices = get_connected_devices_cached()
        
        if not devices:
            # 没有设备连接，显示友好提示
            self.root.after(0, lambda: self.update_status("⚠️ 设备未连接，请先连接设备后再执行此操作", False, "warning"))
            return None
        
        # 如果有设备，检查当前选择的设备是否在已连接列表中
        current_ip = self.get_ip_address() if hasattr(self, 'get_ip_address') else None
        
        if current_ip and current_ip != "192.168.":
            # 检查当前选择的设备是否已连接
            is_connected = False
            for device in devices:
                if device == current_ip or device.startswith(current_ip + ':'):
                    is_connected = True
                    break
            
            if not is_connected:
                # 当前选择的设备未连接
                self.root.after(0, lambda ip=current_ip: self.update_status(f"⚠️ 设备 {ip} 未连接，请检查连接状态", False, "warning"))
                return None
        
        # 设备已连接，执行原函数
        return func(self, *args, **kwargs)
    return wrapper