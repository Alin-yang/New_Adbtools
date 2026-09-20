"""
自适应缓存模块
实现智能 TTL 调整机制，根据访问频率动态优化缓存策略
"""
import time
from typing import Any, Dict, Optional, Tuple
from collections import OrderedDict
from config import Config


class AdaptiveLRUCache:
    """自适应 LRU 缓存，根据访问频率自动调整 TTL"""
    
    def __init__(self, max_size: int = None, base_timeout: int = None):
        """
        初始化自适应缓存
        
        Args:
            max_size: 最大缓存条目数，默认使用配置值
            base_timeout: 基础超时时间 (秒)，默认使用配置值
        """
        self.max_size = max_size or Config.MAX_CACHE_SIZE
        self.base_timeout = base_timeout or Config.CACHE_TIMEOUT
        self.cache: OrderedDict[str, Tuple[Any, float, int]] = OrderedDict()  # (value, timestamp, access_count)
        self.last_cleanup = time.time()
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值（智能调整 TTL）

        访问次数越多，_get_current_ttl 返回的 TTL 越长，
        高频访问的缓存项会自然获得更长的有效期，无需手动续期。

        Args:
            key: 缓存键

        Returns:
            Optional[Any]: 缓存值，如果不存在或已过期则返回 None
        """
        if key not in self.cache:
            return None

        value, timestamp, access_count = self.cache[key]
        current_time = time.time()

        # 检查是否过期（TTL 由访问次数决定）
        if current_time - timestamp > self._get_current_ttl(access_count):
            del self.cache[key]
            return None

        # 命中：累加访问计数，访问越多下次 TTL 越长
        new_access_count = access_count + 1
        self.cache[key] = (value, timestamp, new_access_count)

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
            # 更新现有键，保留访问计数
            _, _, old_access_count = self.cache[key]
            self.cache[key] = (value, current_time, old_access_count + 1)
            self.cache.move_to_end(key)
        else:
            # 添加新键
            if len(self.cache) >= self.max_size:
                # 移除最久未使用的项
                self.cache.popitem(last=False)
            self.cache[key] = (value, current_time, 0)  # 初始访问计数为 0
        
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
    
    def _get_current_ttl(self, access_count: int) -> float:
        """
        根据访问次数计算当前 TTL
        
        Args:
            access_count: 访问次数
            
        Returns:
            float: 实际 TTL 时间（秒）
        """
        if access_count == 0:
            return self.base_timeout
        
        # 访问次数越多，TTL 越长（上限为 2 倍基础 TTL）
        multiplier = min(2.0, 1.0 + (access_count * 0.1))
        return self.base_timeout * multiplier
    
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
        
        for key, (_, timestamp, access_count) in self.cache.items():
            ttl = self._get_current_ttl(access_count)
            if current_time - timestamp > ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.cache[key]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_access_count = sum(count for _, _, count in self.cache.values())
        avg_access_count = total_access_count / len(self.cache) if self.cache else 0
        
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'base_timeout': self.base_timeout,
            'avg_access_count': round(avg_access_count, 2),
            'last_cleanup': self.last_cleanup
        }


# 保持向后兼容，原有的 LRUCache 继续使用
class LRUCache:
    """LRU (Least Recently Used) 缓存实现（保留原版）"""
    
    def __init__(self, max_size: int = None, timeout: int = None):
        """
        初始化 LRU 缓存
        
        Args:
            max_size: 最大缓存条目数，默认使用配置值
            timeout: 缓存超时时间 (秒)，默认使用配置值
        """
        self.max_size = max_size or Config.MAX_CACHE_SIZE
        self.timeout = timeout or Config.CACHE_TIMEOUT
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self.last_cleanup = time.time()
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
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
        """设置缓存值"""
        current_time = time.time()
        
        if key in self.cache:
            self.cache[key] = (value, current_time)
            self.cache.move_to_end(key)
        else:
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
            self.cache[key] = (value, current_time)
        
        self._cleanup_if_needed()
    
    def delete(self, key: str) -> bool:
        """删除缓存项"""
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
