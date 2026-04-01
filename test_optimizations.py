"""
性能优化测试脚本
测试新增的优化功能
"""
import sys
import time
from utils import get_connected_devices_simple, get_connected_devices_parallel


def test_parallel_detection():
    """测试并行设备检测功能"""
    print("=" * 60)
    print("测试：并行设备检测")
    print("=" * 60)
    
    # 测试快速检测
    start = time.time()
    devices_fast = get_connected_devices_simple()
    fast_time = (time.time() - start) * 1000
    
    # 测试并行检测
    start = time.time()
    devices_parallel = get_connected_devices_parallel()
    parallel_time = (time.time() - start) * 1000
    
    print(f"\n快速检测结果：{len(devices_fast)} 台设备，耗时：{fast_time:.2f}ms")
    print(f"并行验证结果：{len(devices_parallel)} 台设备，耗时：{parallel_time:.2f}ms")
    
    if devices_parallel:
        print(f"\n已验证的设备列表：")
        for device in devices_parallel:
            print(f"  - {device}")
    
    print("\n✓ 并行设备检测测试完成")
    return True


def test_adaptive_cache():
    """测试自适应缓存功能"""
    print("\n" + "=" * 60)
    print("测试：自适应缓存")
    print("=" * 60)
    
    from adaptive_cache import AdaptiveLRUCache
    
    # 创建缓存实例
    cache = AdaptiveLRUCache(max_size=5, base_timeout=3)
    
    # 测试基本操作
    print("\n1. 测试基本缓存操作")
    cache.set("key1", "value1")
    result = cache.get("key1")
    print(f"   设置 key1 -> value1, 获取结果：{result}")
    
    # 测试访问计数
    print("\n2. 测试访问频率对 TTL 的影响")
    cache.set("frequent_key", "frequent_value")
    
    # 多次访问
    for i in range(10):
        cache.get("frequent_key")
    
    stats = cache.get_stats()
    print(f"   平均访问次数：{stats['avg_access_count']}")
    print(f"   缓存大小：{stats['size']}")
    
    # 测试 LRU 淘汰
    print("\n3. 测试 LRU 淘汰机制")
    for i in range(6):
        cache.set(f"test_key_{i}", f"value_{i}")
        print(f"   添加 test_key_{i}")
    
    print(f"   最终缓存大小：{cache.size()} (最大应为 5)")
    
    print("\n✓ 自适应缓存测试完成")
    return True


def test_device_monitor():
    """测试设备监控功能（模拟）"""
    print("\n" + "=" * 60)
    print("测试：设备监控（模拟）")
    print("=" * 60)
    
    # 注意：这个测试需要实际的 ADB 设备连接
    # 如果没有设备，只会测试基础功能
    
    try:
        from device_monitor import DeviceMonitor
        
        class MockApp:
            def __init__(self):
                self.root = None
                self.ip_history = []
                self._last_displayed_ip = ""
                
            def update_connection_status(self):
                pass
                
            def update_status(self, msg, success):
                print(f"   [状态更新] {msg}")
        
        mock_app = MockApp()
        monitor = DeviceMonitor(mock_app)
        
        # 测试启动监控
        print("\n1. 启动设备监控")
        monitor.start_monitoring()
        print("   ✓ 监控已启动")
        
        # 等待几秒
        time.sleep(5)
        
        # 测试停止监控
        print("\n2. 停止设备监控")
        monitor.stop_monitoring()
        print("   ✓ 监控已停止")
        
        print("\n✓ 设备监控测试完成")
        return True
        
    except Exception as e:
        print(f"\n⚠️ 设备监控测试跳过（需要实际运行环境）: {e}")
        return False


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("ADB 工具性能优化测试")
    print("=" * 60)
    
    tests = [
        ("并行设备检测", test_parallel_detection),
        ("自适应缓存", test_adaptive_cache),
        ("设备监控", test_device_monitor),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} 测试失败：{e}")
            results.append((name, False))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status} - {name}")
    
    total_passed = sum(1 for _, r in results if r)
    total_tests = len(results)
    print(f"\n总计：{total_passed}/{total_tests} 个测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
