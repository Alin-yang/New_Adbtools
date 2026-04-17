"""
缓存管理模块
实现 LRU 缓存机制和自适应缓存，提供高效的数据缓存功能
"""
from typing import Any, Dict, Optional
from config import Config
from adaptive_cache import AdaptiveLRUCache


class CacheManager:
    """缓存管理器，管理不同类型的缓存（支持自适应缓存）"""
    
    def __init__(self):
        """初始化缓存管理器"""
        # 设备连接状态缓存（短期）- 使用自适应缓存
        self.device_cache = AdaptiveLRUCache(
            max_size=50,
            base_timeout=Config.DEVICE_CACHE_TIMEOUT
        )
        
        # 应用包信息缓存（长期）- 使用自适应缓存
        self.package_cache = AdaptiveLRUCache(
            max_size=Config.MAX_CACHE_SIZE,
            base_timeout=Config.CACHE_TIMEOUT
        )
        
        # 系统信息缓存（长期）- 使用自适应缓存
        self.system_cache = AdaptiveLRUCache(
            max_size=20,
            base_timeout=Config.CACHE_TIMEOUT * 2  # 系统信息缓存时间更长
        )
    
    def get_device_status(self, device_id: str) -> Optional[bool]:
        """获取设备连接状态"""
        return self.device_cache.get(f"device_status_{device_id}")
    
    def set_device_status(self, device_id: str, status: bool) -> None:
        """设置设备连接状态"""
        self.device_cache.set(f"device_status_{device_id}", status)
    
    def get_package_info(self, package_name: str) -> Optional[Dict[str, Any]]:
        """获取应用包信息"""
        return self.package_cache.get(f"package_{package_name}")
    
    def set_package_info(self, package_name: str, info: Dict[str, Any]) -> None:
        """设置应用包信息"""
        self.package_cache.set(f"package_{package_name}", info)
    
    def get_system_info(self, info_type: str) -> Optional[str]:
        """获取系统信息"""
        return self.system_cache.get(f"system_{info_type}")
    
    def set_system_info(self, info_type: str, info: str) -> None:
        """设置系统信息"""
        self.system_cache.set(f"system_{info_type}", info)
    
    def clear_all(self) -> None:
        """清空所有缓存"""
        self.device_cache.clear()
        self.package_cache.clear()
        self.system_cache.clear()
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有缓存的统计信息"""
        return {
            'device_cache': self.device_cache.get_stats(),
            'package_cache': self.package_cache.get_stats(),
            'system_cache': self.system_cache.get_stats()
        }


# 全局缓存管理器实例
cache_manager = CacheManager()