def require_device_connected(func):
    """设备连接校验装饰器 (优化版，不阻塞 UI)"""
    def wrapper(self):
        # 快速检查设备连接，不阻塞 UI
        ip_address = self.get_ip_address()
        if not ip_address:
            self.update_status("请选择 IP 地址", False)
            return
        
        # 快速检查缓存中的设备状态 (不强制刷新)
        from cache_manager import cache_manager
        cached_status = cache_manager.get_device_status(ip_address)
        
        # 如果缓存中有且已连接，直接执行
        if cached_status is True:
            return func(self)
        
        # 如果缓存中没有或显示未连接，在后台异步检查
        import threading
        check_thread = threading.Thread(
            target=self._check_device_and_execute,
            args=(func,),
            daemon=True
        )
        check_thread.start()
        
        # 立即返回，不阻塞 UI
        return None
    return wrapper