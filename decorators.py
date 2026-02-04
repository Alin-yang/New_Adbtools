def require_device_connected(func):
    """设备连接校验装饰器"""
    def wrapper(self):
        # 显示当前设备连接状态
        if hasattr(self, 'show_current_device_status'):
            self.show_current_device_status()
        if not self.ensure_device_connected():
            return
        return func(self)
    return wrapper