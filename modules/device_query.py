"""设备查询统一入口

背景
----
之前 utils.py 里有 6 个做同一件事的函数：

    query_connected_devices()        -> Optional[List[str]]  失败 None / 无设备 []
    get_connected_devices_cached_safe() -> Optional[List[str]]  带缓存，失败 None
    get_connected_devices_cached()   -> List[str]           带缓存，失败回退上次结果
    get_connected_devices(mode)      -> List[str]           auto: 简单查 + 多设备时验证
    get_connected_devices_simple()   -> List[str]           只查不验证
    get_connected_devices_parallel() -> List[str]           逐台验证可达性

它们之间最关键的语义差异是「**查询失败返回 None**」与「**没有设备返回 []**」——
分不清就会把"查不到"当成"设备没了"，造成误报断连。6 个平行函数也让改动很容易漏。

这里把实现收敛成一份，语义集中在一处。utils 里保留同名函数作为兼容转发，
调用方可以逐个迁移到 DeviceQuery，不必一次性改完。
"""
import subprocess
import time
from typing import Dict, List, Optional

from config import Config


class DeviceQuery:
    """设备查询统一入口（全部为类方法，状态在类上共享）"""

    # 查询缓存
    _cache: Dict = {'devices': [], 'last_update': 0.0, 'ttl': 2.0, 'valid': False}
    # 暂停计数（重负载操作期间暂停设备查询，见 set_validation_paused）
    _pause_count: int = 0

    # ------------------------------------------------------------------ 基础查询

    @classmethod
    def query(cls) -> Optional[List[str]]:
        """执行一次 `adb devices` 查询

        Returns:
            Optional[List[str]]:
                - 成功：设备列表（没有设备时是空列表 []）
                - 失败（adb 异常/超时/返回码非 0）：None
                  ⚠️ None 表示"查不到"，绝不能当成"没有设备"。
        """
        try:
            result = subprocess.run(
                "adb devices", shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=Config.DEVICE_QUERY_TIMEOUT
            )
            if result.returncode != 0:
                # adb server 不可用 / 版本冲突等，视为查询失败
                return None
            output = result.stdout.decode('utf-8', errors='ignore')
            devices = []
            for line in output.splitlines()[1:]:  # 跳过标题行
                if '\t' in line and 'device' in line \
                        and 'unauthorized' not in line and 'offline' not in line:
                    device_id = line.split('\t')[0].strip()
                    if device_id and device_id != 'List':
                        devices.append(device_id)
            return devices
        except Exception:
            return None

    # ------------------------------------------------------------------ 缓存查询

    @classmethod
    def query_cached(cls) -> Optional[List[str]]:
        """带缓存的查询（TTL = Config.DEVICE_QUERY_TIMEOUT 同量级，默认 2 秒）

        Returns:
            Optional[List[str]]: 成功返回设备列表；失败返回 None
        """
        current = time.time()
        if (current - cls._cache['last_update']) < cls._cache['ttl']:
            if not cls._cache['valid']:
                return None
            return list(cls._cache['devices'])

        devices = cls.query()
        cls._cache['last_update'] = current
        if devices is None:
            # 查询失败：保留上一次的成功结果，标记本次不可信
            cls._cache['valid'] = False
            return None
        cls._cache['devices'] = devices
        cls._cache['valid'] = True
        return list(devices)

    @classmethod
    def list_cached(cls) -> List[str]:
        """带缓存的查询，失败时回退到上一次成功的结果（永不返回"凭空没有设备"）"""
        devices = cls.query_cached()
        if devices is not None:
            return devices
        return list(cls._cache['devices'])

    # ------------------------------------------------------------------ 可达性验证

    @classmethod
    def verify(cls, devices: List[str]) -> List[str]:
        """过滤出真正可达的设备

        用 `adb get-state` 而不是 `adb shell echo test`：
        get-state 是纯 adb server 查询（<10ms，不在设备上起进程）；
        shell echo 在设备忙时必然超时（2s），反而会把设备踢出列表。
        """
        if not devices:
            return []
        import concurrent.futures

        def _check(device_id):
            try:
                r = subprocess.run(
                    f"adb -s {device_id} get-state", shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=3
                )
                if r.returncode != 0:
                    return None
                state = r.stdout.decode('utf-8', errors='ignore').strip()
                return device_id if state == 'device' else None
            except Exception:
                return None

        result = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(devices))) as ex:
            futures = {ex.submit(_check, d): d for d in devices}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    v = fut.result(timeout=3)
                    if v:
                        result.append(v)
                except Exception:
                    continue
        return result

    # ------------------------------------------------------------------ 组合入口

    @classmethod
    def list_devices(cls, verify: bool = False) -> List[str]:
        """拿到设备列表

        Args:
            verify: True 时只返回真正可达的设备（逐台 get-state）
        """
        devices = cls.query()
        if devices is None:
            return []
        if not verify:
            return devices
        if cls.is_validation_paused():
            # 暂停期间不做验证（设备正忙着传输，验证会抢通道）
            return list(devices)
        return cls.verify(devices)

    @classmethod
    def list_devices_auto(cls) -> List[str]:
        """自动模式：只有多台设备时才逐台验证（单台时省掉验证开销）"""
        devices = cls.query()
        if devices is None:
            return []
        if len(devices) > 1:
            if cls.is_validation_paused():
                return list(devices)
            return cls.verify(devices)
        return devices

    # ------------------------------------------------------------------ 暂停开关

    @classmethod
    def set_validation_paused(cls, paused: bool) -> None:
        """暂停/恢复设备查询与验证

        重负载操作（安装大包、录屏）期间调用：设备正忙时任何 adb 命令都会和
        传输抢同一条通道，可能把传输挤断 → 误报「设备已断开」。

        用计数器实现，重复/嵌套调用不会互相踩踏。
        """
        if paused:
            cls._pause_count += 1
        else:
            cls._pause_count = max(0, cls._pause_count - 1)

    @classmethod
    def is_validation_paused(cls) -> bool:
        return cls._pause_count > 0

    @classmethod
    def reset_cache(cls) -> None:
        """清空缓存（设备重启/重连后调用）"""
        cls._cache.update({'devices': [], 'last_update': 0.0, 'valid': False})

    @classmethod
    def expire_cache(cls) -> None:
        """只让缓存过期，保留上一次查到的设备列表

        用于"模拟下次查询失败"：失败时 list_cached() 仍能回退到上一次的设备列表。
        """
        cls._cache['last_update'] = 0.0
        cls._cache['valid'] = False
