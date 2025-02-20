def require_device_connected(func):
    """设备连接校验装饰器"""
    def wrapper(self):
        if not self.ensure_device_connected():
            return
        return func(self)
    return wrapper