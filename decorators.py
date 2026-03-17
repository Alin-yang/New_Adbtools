def require_device_connected(func):
    """设备连接校验装饰器（异步优化版）"""
    def wrapper(self, *args, **kwargs):
        # 在异步环境下，只验证连接，不强制刷新 UI
        # UI 刷新由 execute_task_async 中的 task_wrapper 处理
        if hasattr(self, 'ensure_device_connected') and not self.ensure_device_connected():
            return None
        return func(self, *args, **kwargs)
    return wrapper