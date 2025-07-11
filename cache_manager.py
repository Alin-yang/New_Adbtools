"""
缓存管理模块
实现LRU缓存机制，提供高效的数据缓存功能
"""
import time
from typing import Any, Dict, Optional, Tuple
from collections import OrderedDict
from config import Config


class LRUCache:
    """LRU (Least Recently Used) 缓存实现"""
    
    def __init__(self, max_size: int = None, timeout: int = None):
        """
        初始化LRU缓存
        
        Args:
            max_size: 最大缓存条目数，默认使用配置值
            timeout: 缓存超时时间(秒)，默认使用配置值
        """
        self.max_size = max_size or Config.MAX_CACHE_SIZE
        self.timeout = timeout or Config.CACHE_TIMEOUT
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self.last_cleanup = time.time()
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[Any]: 缓存值，如果不存在或已过期则返回None
        """
        if key not in self.cache:
            return None
            
        value, timestamp = self.cache[key]
        
        # 检查是否过期
        if time.time() - timestamp > self.timeout:
            del self.cache[key]
            return None
        
        # 移动到最后（最近使用）
        self.cache.move_to_end(key)
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        current_time = time.time()
        
        if key in self.cache:
            # 更新现有键
            self.cache[key] = (value, current_time)
            self.cache.move_to_end(key)
        else:
            # 添加新键
            if len(self.cache) >= self.max_size:
                # 移除最久未使用的项
                self.cache.popitem(last=False)
            self.cache[key] = (value, current_time)
        
        # 定期清理过期项
        self._cleanup_if_needed()
    
    def delete(self, key: str) -> bool:
        """
        删除缓存项
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 是否成功删除
        """
        if key in self.cache:
            del self.cache[key]
            return True
        return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        self.cache.clear()
    
    def size(self) -> int:
        """获取当前缓存大小"""
        return len(self.cache)
    
    def _cleanup_if_needed(self) -> None:
        """如果需要，清理过期的缓存项"""
        current_time = time.time()
        if current_time - self.last_cleanup > Config.CACHE_CLEANUP_INTERVAL:
            self._cleanup_expired()
            self.last_cleanup = current_time
    
    def _cleanup_expired(self) -> None:
        """清理所有过期的缓存项"""
        current_time = time.time()
        expired_keys = []
        
        for key, (_, timestamp) in self.cache.items():
            if current_time - timestamp > self.timeout:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.cache[key]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'timeout': self.timeout,
            'last_cleanup': self.last_cleanup
        }


class CacheManager:
    """缓存管理器，管理不同类型的缓存"""
    
    def __init__(self):
        """初始化缓存管理器"""
        # 设备连接状态缓存（短期）
        self.device_cache = LRUCache(
            max_size=50,
            timeout=Config.DEVICE_CACHE_TIMEOUT
        )
        
        # 应用包信息缓存（长期）
        self.package_cache = LRUCache(
            max_size=Config.MAX_CACHE_SIZE,
            timeout=Config.CACHE_TIMEOUT
        )
        
        # 系统信息缓存（长期）
        self.system_cache = LRUCache(
            max_size=20,
            timeout=Config.CACHE_TIMEOUT * 2  # 系统信息缓存时间更长
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