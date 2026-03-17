def require_device_connected(func):
    """设备连接校验装饰器"""
    def wrapper(self):
        # 在执行功能前，强制刷新设备状态并显示最新信息
        if hasattr(self, 'show_current_device_status'):
            # 清除所有相关缓存以确保获取最新状态
            from cache_manager import cache_manager
            cache_manager.device_cache.clear()
            cache_manager.system_cache.clear()  # 清除系统缓存
            # 强制显示当前设备状态，使用特殊标记确保显示
            self.show_current_device_status(force_display=True, decorator_call=True)
        if not self.ensure_device_connected():
            return
        return func(self)
    return wrapper