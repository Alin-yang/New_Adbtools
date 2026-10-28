import subprocess
import datetime
import os
import glob
import re
import time
from typing import Tuple, Optional, List, Dict
from config import Config
from modules.device_query import DeviceQuery

def set_device_validation_paused(paused: bool) -> None:
    """设置是否暂停设备可达性验证（重负载操作期间调用）

    重负载操作（安装/录屏等）期间暂停，避免 adb 请求打扰正在传输/安装的设备，
    反而把设备踢出列表。用计数器实现，重复/嵌套调用不会互相踩踏。
    """
    DeviceQuery.set_validation_paused(paused)


# ============================================================================
# 设备查询（实现已收敛到 modules/device_query.DeviceQuery）
# 这里保留同名函数作为兼容转发，调用方可逐个迁移。
# ⚠️ 关键语义：query_* 系列"失败返回 None"，list_* 系列"失败回退上次结果"。
#    分不清就会把"查不到"当成"设备没了"，造成误报断连。
# ============================================================================

def query_connected_devices() -> Optional[List[str]]:
    """查询已连接设备列表 —— 严格区分「查询失败」与「确实没有设备」

    Returns:
        Optional[List[str]]:
            - 成功：返回设备列表（没有设备时是空列表 []）
            - 失败（adb 异常/超时/返回码非 0）：返回 None
              ⚠️ None 表示"查不到"，绝不能当成"没有设备"，否则会误报断连。
    """
    return DeviceQuery.query()


def get_connected_devices_cached_safe() -> Optional[List[str]]:
    """带缓存的设备列表查询（安全版）

    ⚠️ 重负载操作（安装/录屏）期间返回 None：设备正忙着收大包时，任何 adb 命令
    都会和传输抢同一条通道，可能把传输挤断 → 误报「设备已断开」。
    暂停只影响"监控/验证"这一层，不影响 query_connected_devices 本身。

    Returns:
        Optional[List[str]]: 成功返回设备列表；查询失败返回 None（区别于"没有设备"）
    """
    if DeviceQuery.is_validation_paused():
        return None
    return DeviceQuery.query_cached()


def get_connected_devices_cached() -> List[str]:
    """获取当前连接的所有设备列表（带缓存优化）

    查询失败时回退到上一次成功的结果，避免把"adb 查询失败"当成"没有设备"。

    Returns:
        List[str]: 已连接设备的序列号/IP 地址列表
    """
    return DeviceQuery.list_cached()


def get_connected_devices(mode: str = "auto") -> List[str]:
    """获取当前连接的所有设备列表（智能版本）

    Args:
        mode: 检测模式
            - "auto": 自动选择（单设备不验证，多设备才并行验证）
            - "simple": 快速检测，不验证
            - "parallel": 并行验证
            - "full": 完整验证（带深度检查）

    Returns:
        List[str]: 已连接设备的序列号/IP 地址列表
    """
    if mode == "auto":
        return DeviceQuery.list_devices_auto()
    elif mode == "simple":
        return DeviceQuery.list_devices(verify=False)
    elif mode == "parallel":
        return DeviceQuery.list_devices(verify=True)
    else:  # mode == "full"
        return _get_connected_devices_full()


def _get_connected_devices_full() -> List[str]:
    """获取当前连接的所有设备列表（完整版本，带深度验证）
    
    Returns:
        List[str]: 已连接设备的序列号/IP 地址列表
    """
    try:
        result = subprocess.run(
            "adb devices", shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5
        )
        output = result.stdout.decode('utf-8', errors='ignore')
        devices = []
        for line in output.splitlines()[1:]:  # 跳过第一行标题
            # 检查行是否包含设备信息，排除模拟器和其他状态
            if '\t' in line and 'device' in line and 'unauthorized' not in line and 'offline' not in line:
                device_id = line.split('\t')[0].strip()
                if device_id and device_id != 'List':  # 排除可能的错误输出
                    # 额外验证设备是否真正可访问
                    try:
                        # 尝试对设备执行简单命令以验证其可达性
                        validation_result = subprocess.run(
                            f"adb -s {device_id} shell echo test", shell=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=3
                        )
                        if validation_result.returncode == 0:
                            devices.append(device_id)
                    except Exception:
                        # 如果验证失败，跳过此设备
                        continue
        return devices
    except Exception:
        return []


def filter_lines(text: str, *keywords: str) -> List[str]:
    """按关键字过滤多行输出（Python 侧过滤）

    ⚠️ 为什么不直接在命令里写 `| grep`：
    `adb shell xxx | grep yyy` 里的管道是**本机 cmd** 解析的，grep 在本机跑，
    用户环境（双击 exe）PATH 里通常没有 grep → 整条命令失败。
    且设备端也不一定有 grep（Android 4.x 没有）。
    所以一律在 Python 侧过滤。

    Args:
        text: 多行文本
        *keywords: 关键字，任一命中即保留该行；不传则返回全部行

    Returns:
        List[str]: 命中的行
    """
    if not text:
        return []
    lines = text.splitlines()
    if not keywords:
        return lines
    return [line for line in lines if any(k in line for k in keywords)]


def normalize_device_serial(device: Optional[str]) -> Optional[str]:
    """把用户输入的设备标识标准化成 `adb devices` 里的完整序列号

    IP 地址不带端口时补上默认的 5555（adb connect 的默认端口），
    保证 scrcpy / adb 等直接接受 `-s <serial>` 的地方能选中设备。

    Args:
        device: 用户输入的 IP 或序列号

    Returns:
        Optional[str]: 标准化后的序列号
    """
    if not device:
        return device
    device = device.strip().strip('"').strip("'")
    if not device:
        return device
    # 已是 IP:端口 或 USB 序列号，原样返回
    if ':' in device:
        return device
    # 纯 IP → 补默认端口
    if '.' in device:
        return f"{device}:5555"
    return device


def parse_getprop_all(output: str) -> Dict[str, str]:
    """解析 `adb shell getprop` 的全量输出

    输出格式形如：
        [ro.product.model]: [Pixel 6]
        [ro.build.version.release]: [13]

    ⚠️ 为什么用全量 getprop：
    逐条 `adb shell getprop <key>` 每条都要 spawn 一个 adb 进程（~200ms），
    设备详情要 19 条 → 4 秒。而不带参数的 `getprop` 一次输出全部属性（几 KB），
    一次命令搞定，快 19 倍。

    Args:
        output: getprop 命令的原始输出

    Returns:
        Dict[str, str]: 属性名 -> 属性值
    """
    props: Dict[str, str] = {}
    if not output:
        return props
    for line in output.splitlines():
        m = re.match(r'\s*\[(.+?)\]:\s*\[(.*)\]\s*$', line)
        if m:
            props[m.group(1)] = m.group(2)
    return props


def get_connected_devices_simple() -> List[str]:
    """获取当前连接的所有设备列表（快速版本，不深度验证）

    Returns:
        List[str]: 已连接设备的序列号/IP 地址列表
    """
    devices = DeviceQuery.query()
    return devices if devices is not None else []

def get_connected_devices_parallel() -> List[str]:
    """并行检测多个设备并验证可达性

    Returns:
        List[str]: 已连接且可访问的设备列表
    """
    return DeviceQuery.list_devices(verify=True)


def build_adb_command_with_device(command: str, target_ip: Optional[str] = None) -> str:
    """构建带设备选择的ADB命令
    
    当连接多台设备时，自动添加 -s 参数指定目标设备
    
    Args:
        command: 原始ADB命令
        target_ip: 目标设备IP地址（可选，支持完整IP或简写）
        
    Returns:
        str: 处理后的ADB命令
    """
    # 如果命令已经包含 -s 参数，直接返回
    if ' -s ' in command:
        return command
    
    # 如果指定了目标设备，始终添加 -s 参数（关键修复！）
    # 这样可以避免 "more than one device/emulator" 错误
    if target_ip:
        # 清理目标IP（去除空格和引号），并补齐端口号
        target_ip = normalize_device_serial(target_ip)
        if not target_ip:
            return command

        # 直接添加 -s 参数，不依赖设备数量检测
        # 这样可以确保即使有隐藏设备也不会报错
        if command.startswith('adb '):
            return command.replace('adb ', f'adb -s {target_ip} ', 1)
        elif command.startswith('adb'):
            return f'adb -s {target_ip} {command[3:]}'
    
    # 如果没有指定目标IP，才检测设备数量
    # ⚠️ 必须用缓存版：这条路径**每条命令**都会走一次。
    #    原来用 get_connected_devices()（auto 模式）—— 每条命令都跑一次 adb devices，
    #    多设备时还要每台再跑一次 get-state。高频调用时开销极大
    #    （一次 package_list 的兜底路径就是几百次）。
    devices = get_connected_devices_cached_safe()
    if devices is None:
        # 查询失败 → 沿用上一次成功的结果，别当成"没有设备"
        devices = get_connected_devices_cached()

    # 只有检测到多台设备时才需要指定（使用第一台）
    if len(devices) > 1:
        if devices:
            if command.startswith('adb '):
                return command.replace('adb ', f'adb -s {devices[0]} ', 1)
            elif command.startswith('adb'):
                return f'adb -s {devices[0]} {command[3:]}'
    
    # 只有一台或没有设备时，不需要指定设备
    return command


def run_adb_command(command: str, retries: int = None, timeout: int = None, target_device: Optional[str] = None) -> Tuple[str, bool]:
    """执行ADB命令并返回结果（支持多设备）
    
    Args:
        command: ADB命令字符串
        retries: 重试次数，默认使用配置值
        timeout: 超时时间，默认使用配置值
        target_device: 目标设备IP地址（多设备时使用）
        
    Returns:
        Tuple[str, bool]: (输出结果, 是否成功)
    """
    if retries is None:
        retries = Config.MAX_ADB_RETRIES
    if timeout is None:
        timeout = Config.ADB_COMMAND_TIMEOUT
    
    # 构建带设备选择的命令
    command = build_adb_command_with_device(command, target_device)
    
    last_error = ""
    
    for attempt in range(retries):
        try:
            result = subprocess.run(
                command, shell=True, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout
            )
            return result.stdout.decode('utf-8', errors='ignore'), True
            
        except subprocess.TimeoutExpired:
            last_error = f"Command timed out after {timeout} seconds"
            if attempt < retries - 1:
                time.sleep(1)  # 重试前等待1秒
                continue
                
        except subprocess.CalledProcessError as e:
            # ⚠️ 必须用 utf-8：ADB 输出的是 UTF-8，用 GBK 解码会乱码
            #    （stdout 早就改成 utf-8 了，stderr 这里漏了）。
            #    用 replace 而不是 ignore：ignore 会静默丢字节，错误信息缺字。
            try:
                error_output = e.stderr.decode('utf-8', errors='replace')
            except Exception:
                error_output = "Command failed and unable to decode error output."
            last_error = f"Command failed with error: {error_output}"

            # 某些错误不需要重试（重试也没用，只会白等）
            # ⚠️ 要同时认中英文：部分设备的 adb 输出是中文的
            _fatal_markers = ("device not found", "no devices/emulators found",
                              "offline", "未找到设备", "设备未找到", "离线", "没有设备")
            _low = last_error.lower()
            if any(m in _low for m in _fatal_markers):
                break

            if attempt < retries - 1:
                time.sleep(1)  # 重试前等待1秒
                continue
                
        except Exception as e:
            last_error = f"Unexpected error: {str(e)}"
            if attempt < retries - 1:
                time.sleep(1)
                continue
    
    return last_error, False

def timestamp_time() -> str:
    """生成时间戳文件名
    
    Returns:
        str: 格式为 MMDD-HHMMSS 的时间戳字符串
    """
    return datetime.datetime.now().strftime("%m%d-%H%M%S")

def extract_version_info(output: str) -> Optional[str]:
    """从 adb shell 命令输出中提取版本号（简化增强版）
    
    Args:
        output: ADB 命令的输出
        
    Returns:
        Optional[str]: 版本号字符串，如果未找到则返回 None
    """
    if not output:
        return None
        
    lines = output.split('\n')
    
    # 方法 1：直接查找 versionName=的行（最快最直接）
    for line in lines:
        line = line.strip()
        if 'versionName=' in line and not line.startswith('#'):
            try:
                version = line.split('versionName=')[1].strip()
                if version and version != 'null' and len(version) > 0:
                    # 验证版本号格式
                    import re
                    if re.match(r'^[\d\.]+[\w\.-]*$', version):
                        return version
            except (IndexError, ValueError):
                continue
    
    # 方法 2：查找包含 versionName 的行并使用等号分割
    for line in lines:
        line = line.strip()
        if 'versionName' in line and '=' in line and not line.startswith('#'):
            try:
                version = line.split('=')[1].strip()
                if version and version != 'null' and len(version) > 0:
                    # 验证版本号格式
                    import re
                    if re.match(r'^[\d\.]+[\w\.-]*$', version):
                        return version
            except (IndexError, ValueError):
                continue
    
    # 方法 3：使用原来的复杂逻辑作为备选
    versions = []
    for i, line in enumerate(lines):
        line = line.strip()
        if 'versionName' in line and '=' in line:
            try:
                version = line.split('=')[1].strip()
                if version and version != 'null':
                    # 检查上下文信息
                    context_lines = lines[max(0, i-5):i+5]
                    context = '\n'.join(context_lines)
                    
                    # 优先级评分：用户安装 > 系统预装 > 其他
                    priority = 0
                    if 'User ' in context or 'userId=' in context:
                        priority = 3  # 用户安装，最高优先级
                    elif 'timeStamp=' in context:
                        priority = 2  # 有安装时间戳，较高优先级
                    elif 'System' in context:
                        priority = 1  # 系统应用，较低优先级
                    else:
                        priority = 0  # 其他情况，最低优先级但仍然有效
                    
                    versions.append((version, priority, context))
            except IndexError:
                continue
    
    if versions:
        # 按优先级排序，选择最高优先级的版本
        versions.sort(key=lambda x: x[1], reverse=True)
        
        # 如果有多个相同优先级的版本，选择版本号最大的
        top_priority = versions[0][1]
        top_versions = [v for v in versions if v[1] == top_priority]
        
        if len(top_versions) > 1:
            # 比较版本号，选择最新的
            top_versions.sort(key=lambda x: parse_version_number(x[0]), reverse=True)
        
        return top_versions[0][0]
    
    return None


def extract_package_name_from_apk(apk_path: str) -> Optional[str]:
    """从 APK 文件中提取应用包名（本地解析，无需设备连接）
    
    使用 aapt2 或 aapt 工具解析 APK 文件的 AndroidManifest.xml
    
    Args:
        apk_path: APK 文件路径
        
    Returns:
        Optional[str]: 应用包名，失败时返回 None
    """
    if not apk_path or not os.path.exists(apk_path):
        return None
    
    # 尝试使用的工具列表（按优先级）
    tools = ['aapt2', 'aapt']
    
    for tool in tools:
        try:
            # 构建命令
            if tool == 'aapt2':
                # aapt2 dump badging 输出格式更友好
                cmd = f'{tool} dump badging "{apk_path}"'
            else:
                # aapt dump badging 传统格式
                cmd = f'{tool} dump badging "{apk_path}"'
            
            result = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            if result.returncode == 0:
                output = result.stdout
                # 解析 package: 行
                for line in output.split('\n'):
                    line = line.strip()
                    if line.startswith('package:'):
                        # 格式：package: name='com.example.app' versionCode='1' ...
                        import re
                        match = re.search(r"name='([^']+)'", line)
                        if match:
                            package_name = match.group(1)
                            if package_name and is_valid_package_name(package_name):
                                return package_name
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            # 工具不可用或执行失败，尝试下一个
            continue
    
    # 如果所有工具都失败，尝试使用 zipfile 解析 AndroidManifest.xml（备用方案）
    try:
        info = _extract_apk_info_from_zip(apk_path)
        if info.get('package') and is_valid_package_name(info['package']):
            return info['package']
    except Exception:
        pass

    return None


def _extract_apk_info_from_zip(apk_path: str) -> dict:
    """从 APK 内 AndroidManifest.xml 提取 package/versionName/versionCode（zipfile 方案）

    纯本地解析，不依赖 aapt/aapt2，不依赖设备连接。
    一次读取 AndroidManifest.xml 并解析所有属性，避免重复 IO。

    Args:
        apk_path: APK 文件路径

    Returns:
        dict: {'package':..., 'versionName':..., 'versionCode':...}，未取到时对应值为 None
    """
    result = {'package': None, 'versionName': None, 'versionCode': None}
    if not apk_path or not os.path.exists(apk_path):
        return result

    import zipfile

    with zipfile.ZipFile(apk_path, 'r') as zip_ref:
        manifest_data = zip_ref.read('AndroidManifest.xml')

    # 优先用纯 Python 解析二进制 AXML 格式（Android 标准格式）
    info = _extract_apk_info_from_axml(manifest_data)
    if info.get('package') or info.get('versionName') or info.get('versionCode'):
        return info

    # 极少数情况下 Manifest 是文本格式，用正则匹配兜底
    try:
        manifest_str = manifest_data.decode('utf-8', errors='ignore')
        import re

        for key in ('package', 'versionName', 'versionCode'):
            m = re.search(rf'{key}=["\']([^"\']+)["\']', manifest_str)
            if m:
                result[key] = m.group(1)
    except Exception:
        pass

    return result


def extract_apk_info(apk_path: str) -> dict:
    """从 APK 中提取 package/versionName/versionCode（一次解析，本地无设备依赖）

    Args:
        apk_path: APK 文件路径

    Returns:
        dict: {'package':..., 'versionName':..., 'versionCode':...}，未取到时为 None
    """
    result = {'package': None, 'versionName': None, 'versionCode': None}
    if not apk_path or not os.path.exists(apk_path):
        return result

    # 先用 aapt2/aapt 一次性拿到全部字段
    for tool in ('aapt2', 'aapt'):
        try:
            cmd = f'{tool} dump badging "{apk_path}"'
            r = subprocess.run(
                cmd, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=10, text=True,
                encoding='utf-8', errors='ignore'
            )
            if r.returncode == 0:
                import re
                out = r.stdout
                # package: name='...' versionCode='...' versionName='...'
                pkg_m = re.search(r"name=['\"]([^'\"]+)['\"]", out)
                vc_m = re.search(r"versionCode=['\"]([^'\"]*)['\"]", out)
                vn_m = re.search(r"versionName=['\"]([^'\"]*)['\"]", out)
                if pkg_m:
                    result['package'] = pkg_m.group(1)
                if vc_m:
                    result['versionCode'] = vc_m.group(1)
                if vn_m:
                    result['versionName'] = vn_m.group(1)
                if result['package'] and result['versionName']:
                    return result
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

    # 回退 zipfile + AXML 解析
    try:
        info = _extract_apk_info_from_zip(apk_path)
        if info.get('package'):
            result['package'] = info['package']
        if info.get('versionName'):
            result['versionName'] = info['versionName']
        if info.get('versionCode'):
            result['versionCode'] = info['versionCode']
    except Exception:
        pass

    return result


def _parse_axml_string_pool(data: bytes, chunk_start: int) -> list:
    """解析 AXML 的 StringPool chunk，返回字符串列表

    Args:
        data: 完整的 AXML 二进制数据
        chunk_start: StringPool chunk 在 data 中的起始偏移

    Returns:
        list: 字符串列表，索引与 AXML 中的字符串索引一一对应
    """
    import struct

    # StringPool chunk header 共 28 字节：
    # type(2) + headerSize(2) + chunkSize(4) + stringCount(4) + styleCount(4)
    # + flags(4) + stringsOffset(4) + stylesOffset(4)
    if chunk_start + 28 > len(data):
        return []

    try:
        # _type, _header_size, _chunk_size, string_count, _style_count, flags, \
        # strings_offset, _styles_offset
        header = struct.unpack_from('<HHIIIIII', data, chunk_start)
        string_count = header[3]
        flags = header[5]
        strings_offset = header[6]
    except struct.error:
        return []

    # 字符串偏移量表起始位置（相对 chunk 开始）
    offsets_start = chunk_start + 28
    # 字符串数据区起始位置（相对文件开始）
    strings_data_start = chunk_start + strings_offset

    is_utf8 = bool(flags & 0x100)

    strings = []
    for i in range(string_count):
        try:
            # 读取字符串偏移量（4 字节，相对 chunk 开始）
            offset = struct.unpack_from('<I', data, offsets_start + i * 4)[0]
            pos = strings_data_start + offset
            if pos >= len(data):
                strings.append('')
                continue

            if is_utf8:
                # UTF-8 字符串：前两个字节是 u16 长度和 u8 长度
                # 短字符串（u8len <= 0x7FFF）只用 1 字节长度，长字符串用 2 字节
                # 实际 AOSP: 前两个 u16 都用，但简化处理：读取前两字节
                # 如果第一字节高位为 0，说明单字节长度；否则双字节
                b1 = data[pos]
                if b1 & 0x80:
                    # 双字节长度（大端）
                    u16_len = ((b1 & 0x7F) << 8) | data[pos + 1]
                    u8_len_byte = data[pos + 2]
                    str_start = pos + 4
                    str_len = u8_len_byte
                else:
                    # 单字节长度
                    u8_len_byte = data[pos + 1]
                    str_start = pos + 2
                    str_len = u8_len_byte

                raw = data[str_start:str_start + str_len]
                strings.append(raw.decode('utf-8', errors='replace'))
            else:
                # UTF-16LE 字符串：前 2 字节是字符数（u16 长度）
                u16_len = struct.unpack_from('<H', data, pos)[0]
                # 长字符串用 4 字节前缀（高字节非 0）
                if u16_len & 0x8000:
                    u16_len = ((u16_len & 0x7FFF) << 16) | struct.unpack_from('<H', data, pos + 2)[0]
                    str_start = pos + 4
                else:
                    str_start = pos + 2

                raw = data[str_start:str_start + u16_len * 2]
                strings.append(raw.decode('utf-16-le', errors='replace'))
        except Exception:
            strings.append('')

    return strings


def _extract_apk_info_from_axml(manifest_data: bytes) -> dict:
    """纯 Python 解析二进制 AXML 格式的 AndroidManifest.xml，提取 package/versionName/versionCode

    不依赖任何第三方库，仅用标准库 struct 解析二进制格式。
    一次遍历属性表同时收集三个属性，避免重复解析。

    Args:
        manifest_data: AndroidManifest.xml 的原始二进制数据

    Returns:
        dict: {'package':..., 'versionName':..., 'versionCode':...}，未取到时对应值为 None
    """
    import struct

    result = {'package': None, 'versionName': None, 'versionCode': None}

    if not manifest_data or len(manifest_data) < 8:
        return result

    try:
        # 文件头 8 字节：type(2) + headerSize(2) + fileSize(4)
        file_type, file_header_size, _file_size = struct.unpack_from('<HHI', manifest_data, 0)
    except struct.error:
        return result

    # AXML 文件 type 应为 0x0003
    if file_type != 0x0003:
        return result

    # 遍历 chunks
    pos = file_header_size  # 跳过文件头
    string_pool = []
    first_start_tag_attrs = None  # manifest 根标签的 attributes

    while pos + 8 <= len(manifest_data):
        try:
            chunk_type, chunk_header_size, chunk_size = struct.unpack_from('<HHI', manifest_data, pos)
        except struct.error:
            break

        if chunk_size < 8 or pos + chunk_size > len(manifest_data):
            break

        if chunk_type == 0x0001:
            # RES_STRING_POOL_TYPE = 0x0001（字符串池 chunk）
            string_pool = _parse_axml_string_pool(manifest_data, pos)
        elif chunk_type == 0x0102:
            # RES_XML_START_ELEMENT_TYPE = 0x0102（StartTag chunk）
            # 布局: chunk_header(headerSize 字段值) + lineNumber(4) + comment(4)
            #       + attrExt(20字节) + attributes 数据
            # attributeStart 字段值 = 相对 attrExt 起始的字节偏移
            attr_ext_start = pos + chunk_header_size
            # attrExt 20 字节: ns(4) + name(4) + attributeStart(2) + attributeSize(2)
            # + attributeCount(2) + idIdx(2) + classIdx(2) + styleIdx(2)
            if attr_ext_start + 20 <= len(manifest_data):
                try:
                    _ns, _name = struct.unpack_from('<II', manifest_data, attr_ext_start)
                    attr_start_off, attr_size, attr_count = struct.unpack_from(
                        '<HHH', manifest_data, attr_ext_start + 8
                    )
                    # attributes 起始 = attrExt 起始 + attributeStart 字段值
                    # attributeStart 通常=20（attrExt 自身大小）
                    if attr_start_off < 20:
                        attr_start_off = 20
                    attr_data_start = attr_ext_start + attr_start_off
                    # 每个 attribute 20 字节：ns_uri(4) + name(4) + raw_value(4)
                    # + typed_size(2) + typed_res0(1) + typed_type(1) + typed_data(4)
                    if attr_size == 0:
                        attr_size = 20
                    first_start_tag_attrs = (attr_data_start, attr_count, attr_size)
                    break  # 只需第一个 StartTag（manifest 根标签）
                except struct.error:
                    pass

        # 下一个 chunk
        pos += chunk_size

    if not first_start_tag_attrs or not string_pool:
        return result

    attr_data_start, attr_count, attr_size = first_start_tag_attrs

    for i in range(attr_count):
        attr_pos = attr_data_start + i * attr_size
        if attr_pos + 20 > len(manifest_data):
            break
        try:
            # ns_uri_idx(4) + name_idx(4) + raw_value_idx(4) + typed_size(2)
            # + typed_res0(1) + typed_type(1) + typed_data(4)
            _ns_idx, name_idx, raw_value_idx, _t_size, _t_res0, t_type, t_data = struct.unpack_from(
                '<IIIHBBi', manifest_data, attr_pos
            )
        except struct.error:
            continue

        # name_idx 指向字符串池中的属性名
        if name_idx >= len(string_pool):
            continue
        attr_name = string_pool[name_idx]
        # 兼容 'android:versionName' 带命名空间前缀的写法
        attr_name_simple = attr_name.split(':')[-1] if ':' in attr_name else attr_name

        # 优先取 typed_value（type=0x03 STRING，data 是字符串索引）
        # 兜底取 raw_value_idx（也指向字符串池）
        def _str_value(ttype, tdata, raw_idx):
            if ttype == 0x03 and 0 <= tdata < len(string_pool):
                return string_pool[tdata]
            if 0 <= raw_idx < len(string_pool):
                return string_pool[raw_idx]
            return None

        if attr_name_simple == 'package':
            result['package'] = _str_value(t_type, t_data, raw_value_idx)
        elif attr_name_simple == 'versionName':
            result['versionName'] = _str_value(t_type, t_data, raw_value_idx)
        elif attr_name_simple == 'versionCode':
            # versionCode 通常是 INT 类型(0x10=INT_DEC 或 0x01=INT_HEX)，data 是整数值
            if t_type in (0x10, 0x01):
                result['versionCode'] = str(t_data)
            else:
                v = _str_value(t_type, t_data, raw_value_idx)
                if v is not None:
                    result['versionCode'] = v

    return result


def parse_version_number(version_str: str) -> tuple:
    """解析版本号为可比较的元组
    
    Args:
        version_str: 版本号字符串
        
    Returns:
        tuple: 可比较的版本元组
    """
    import re
    
    if not version_str:
        return (0,)
    
    # 提取数字部分
    numbers = re.findall(r'\d+', str(version_str))
    if numbers:
        try:
            return tuple(int(n) for n in numbers)
        except ValueError:
            pass
    
    # 如果无法解析数字，返回字符串长度作为备选
    return (len(version_str), version_str)


def get_device_serial_number() -> Optional[str]:
    """获取设备序列号（优先硬件串号）
    
    优先获取设备的硬件序列号，而不是网络连接标识：
    1. 优先使用硬件序列号（ro.serialno）
    2. 备用启动序列号（ro.boot.serialno）
    3. 备用ADB官方方法（可能返回IP地址）
    4. 最后使用Android ID
    
    Returns:
        Optional[str]: 设备序列号，失败时返回None
    """
    # 策略列表（按优先级排序：优先硬件串号）
    strategies = [
        ("adb shell getprop ro.serialno", "硬件序列号"),
        ("adb shell getprop ro.boot.serialno", "启动序列号"),
        ("adb get-serialno", "ADB官方方法"),
        ("adb shell settings get secure android_id", "Android系统ID")
    ]
    
    for command, description in strategies:
        output, success = run_adb_command(command)
        if success:
            serial = output.strip()
            if serial and serial != "unknown" and serial != "" and len(serial) > 0:
                return serial
    
    return None

def ensure_directory(path: str) -> str:
    """确保目录存在
    
    Args:
        path: 目录路径
        
    Returns:
        str: 目录路径
        
    Raises:
        OSError: 当无法创建目录时
    """
    try:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return path
    except OSError as e:
        raise OSError(f"无法创建目录 {path}: {str(e)}")

def get_next_filename(pattern: str, ext: str) -> str:
    """获取自增文件名
    
    Args:
        pattern: 文件名模式
        ext: 文件扩展名
        
    Returns:
        str: 新的文件名
    """
    try:
        file_count = len(glob.glob(f"{pattern}*{ext}"))
        return f"{pattern}_{file_count+1}{ext}"
    except Exception:
        # 如果出错，使用时间戳作为后缀
        return f"{pattern}_{timestamp_time()}{ext}"

def load_ip_history(app_instance=None) -> List[str]:
    """加载IP历史记录
    
    Args:
        app_instance: 应用实例，用于获取用户定义的日志路径
    
    Returns:
        List[str]: IP地址历史记录列表
    """
    history_file = Config.get_history_file_path(app_instance)
    try:
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                ips = [line.strip() for line in f.readlines() if line.strip()]
                # 验证IP格式并去重
                valid_ips = []
                for ip in ips:
                    if is_valid_ip(ip) and ip not in valid_ips:
                        valid_ips.append(ip)
                return valid_ips[:Config.MAX_IP_HISTORY]
    except Exception as e:
        print(f"加载IP历史记录失败: {e}")
    return []

def save_ip_history(ip_list: List[str], app_instance=None) -> None:
    """保存IP历史记录
    
    Args:
        ip_list: IP地址列表
        app_instance: 应用实例，用于获取用户定义的日志路径
    """
    history_file = Config.get_history_file_path(app_instance)
    try:
        # 确保列表中没有重复项，且最新的IP在最前面
        unique_ips = []
        for ip in ip_list:
            if ip and ip.strip() and is_valid_ip(ip.strip()) and ip.strip() not in unique_ips:
                unique_ips.append(ip.strip())
        
        # 只保留最近的指定数量的IP
        unique_ips = unique_ips[:Config.MAX_IP_HISTORY]
        
        with open(history_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(unique_ips))
    except Exception as e:
        print(f"保存IP历史记录失败: {e}")


def is_valid_ip(ip: str) -> bool:
    """验证IP地址或设备标识格式是否正确（支持IP地址和USB设备序列号）
    
    Args:
        ip: IP地址字符串或设备序列号
        
    Returns:
        bool: 是否为有效的IP地址或设备序列号
    """
    import re
    # 支持IPv4和带端口的格式
    ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?::\d+)?$'
    # USB设备序列号通常由字母、数字、下划线、连字符组成，长度在5-50之间
    usb_serial_pattern = r'^[A-Za-z0-9_-]{5,50}$'
    
    ip_stripped = ip.strip()
    # 检查是否为有效的IPv4地址（可选端口）
    if re.match(ipv4_pattern, ip_stripped):
        return True
    # 检查是否为有效的USB设备序列号
    if re.match(usb_serial_pattern, ip_stripped):
        return True
    return False


def calculate_optimal_workers(task_count: int) -> int:
    """计算最优的线程池大小
    
    Args:
        task_count: 任务数量
        
    Returns:
        int: 最优的工作线程数
    """
    if task_count <= 0:
        return Config.MIN_THREAD_WORKERS
        
    # 根据任务数量动态计算线程数
    optimal_workers = min(
        Config.MAX_THREAD_WORKERS,
        max(
            Config.MIN_THREAD_WORKERS,
            task_count // Config.THREAD_WORKERS_RATIO + 1
        )
    )
    return optimal_workers


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小显示
    
    Args:
        size_bytes: 文件大小（字节）
        
    Returns:
        str: 格式化后的文件大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def get_all_package_versions(target_device: Optional[str] = None) -> Dict[str, str]:
    """一次拿到所有已安装包的版本号

    ⚠️ 为什么不用逐包 `dumpsys package <pkg>`：
    设备上装 300 个包时，逐个查要 300 条 adb 命令（每条 ~300ms）→ 90 秒以上；
    `dumpsys package packages` 一条命令输出全部包（几百 KB），0.5 秒搞定。

    Args:
        target_device: 目标设备 IP/序列号

    Returns:
        Dict[str, str]: 包名 -> 版本号
    """
    versions: Dict[str, str] = {}

    # 1) 定位设备（用缓存，别每次都跑 adb devices）
    device_id = None
    if target_device:
        target = normalize_device_serial(target_device)
        for dev in (get_connected_devices_cached_safe() or []):
            if dev == target or dev.startswith(target_device.strip() + ':'):
                device_id = dev
                break
    if not device_id:
        devices = get_connected_devices_cached_safe() or []
        if devices:
            device_id = devices[0]
    if not device_id:
        return versions

    # 2) 一条命令拿全部
    try:
        output, ok = run_adb_command(
            f"adb -s {device_id} shell dumpsys package packages", timeout=30)
    except Exception:
        return versions
    if not ok or not output:
        return versions

    # 3) 解析：按 "Package [xxx]" 分块，块内找 versionName
    for block in re.split(r'\n\s*Package \[', output)[1:]:
        m = re.match(r'([^\]]+)\]', block)
        if not m:
            continue
        pkg = m.group(1).strip()
        vm = re.search(r'versionName=([^\s]+)', block)
        if vm:
            ver = vm.group(1).strip()
            if ver and ver != 'null':
                versions[pkg] = ver
    return versions


def get_accurate_package_version(package_name: str, target_device: Optional[str] = None) -> Optional[str]:
    """获取应用的精确版本号（优先获取当前用户安装的最新版本）
    
    Args:
        package_name: 应用包名
        target_device: 目标设备IP地址（可选）
        
    Returns:
        Optional[str]: 版本号，如果获取失败则返回None
    """
    # 获取连接的设备列表（用缓存：别每个包都重跑一次 adb devices）
    devices_output, devices_success = get_connected_devices_cached_safe(), True
    if not devices_success or not devices_output:
        return None

    device_id = None
    lines = [f"{d}\tdevice" for d in devices_output]

    # 如果指定了目标设备，优先匹配目标设备
    if target_device:
        target_device = target_device.strip().strip('"').strip("'")
        # 标准化IP地址格式
        target_with_port = normalize_device_serial(target_device)

        # 查找匹配的设备
        for line in lines:
            if '\t' in line and 'device' in line:
                dev = line.split('\t')[0].strip()
                if dev == target_with_port or dev == target_device or dev.startswith(target_device + ':'):
                    device_id = dev
                    break

    # 如果没有指定目标设备或未找到匹配的设备，使用第一个设备
    if not device_id:
        for line in lines:
            if '\t' in line and 'device' in line:
                device_id = line.split('\t')[0].strip()
                break
    
    if not device_id:
        return None
    
    # 策略1：使用 dumpsys package 命令
    cmd1 = f'adb -s {device_id} shell dumpsys package {package_name}'
    output1, success1 = run_adb_command(cmd1)
    
    if success1:
        version = extract_version_info(output1)
        if version:
            return version
    
    # 策略2：使用 pm dump 命令
    cmd2 = f'adb -s {device_id} shell pm dump {package_name}'
    output2, success2 = run_adb_command(cmd2)
    
    if success2:
        version = extract_version_info(output2)
        if version:
            return version
    
    # 策略3：直接在完整输出中查找versionName
    if success1:
        lines = output1.split('\n')
        for line in lines:
            if 'versionName=' in line:
                try:
                    version = line.split('versionName=')[1].strip()
                    if version and version != 'null':
                        return version
                except IndexError:
                    continue
    
    return None


def get_user_defined_log_path(app_instance=None) -> str:
    """获取用户自定义的数据存储路径（线程安全）

    后台线程不能直接读 Tk 控件（会抛 "main thread is not in main loop"），
    所以优先读 app 缓存的路径快照（由 Entry 的 trace 回调在主线程更新）。

    Args:
        app_instance: 应用实例，用于获取数据路径输入框的值

    Returns:
        str: 用户自定义的路径或默认路径
    """
    if app_instance is not None:
        user_path = ''

        # 优先用缓存（任何线程都能安全读）
        cached = getattr(app_instance, '_user_log_path', None)
        if cached:
            user_path = cached.strip()
        else:
            # 没有缓存时退回直接读控件（仅主线程安全，失败就当没设置）
            entry = getattr(app_instance, 'log_path_entry', None)
            if entry is not None:
                try:
                    user_path = entry.get().strip()
                except Exception:
                    user_path = ''

        if user_path:
            # 确保路径以分隔符结尾
            if not user_path.endswith('\\') and not user_path.endswith('/'):
                user_path += os.sep
            return user_path

    # 如果无法获取用户路径，返回默认路径
    return Config.get_actual_path(Config.DEFAULT_LOG_PATH)

def is_valid_package_name(pkg_name: str) -> bool:
    """验证包名格式是否正确
    
    Args:
        pkg_name: 包名字符串
        
    Returns:
        bool: 是否为有效的包名
    """
    import re
    # Android包名格式：由字母、数字、下划线和点号组成，至少包含一个点号
    pkg_pattern = r'^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+$'
    return bool(re.match(pkg_pattern, pkg_name.strip()))


def load_pkg_history(app_instance=None) -> List[str]:
    """加载包名历史记录
    
    Args:
        app_instance: 应用实例，用于获取用户定义的日志路径
    
    Returns:
        List[str]: 包名历史记录列表
    """
    history_file = Config.get_pkg_history_file_path(app_instance)
    try:
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                packages = [line.strip() for line in f.readlines() if line.strip()]
                # 验证包名格式并去重
                valid_packages = []
                for pkg in packages:
                    if is_valid_package_name(pkg) and pkg not in valid_packages:
                        valid_packages.append(pkg)
                return valid_packages[:Config.MAX_PKG_HISTORY]
    except Exception as e:
        print(f"加载包名历史记录失败: {e}")
    return []


def save_pkg_history(pkg_list: List[str], app_instance=None) -> None:
    """保存包名历史记录
    
    Args:
        pkg_list: 包名列表
        app_instance: 应用实例，用于获取用户定义的日志路径
    """
    history_file = Config.get_pkg_history_file_path(app_instance)
    try:
        # 确保列表中没有重复项，且最新的包名在最前面
        unique_packages = []
        for pkg in pkg_list:
            if pkg and pkg.strip() and is_valid_package_name(pkg.strip()) and pkg.strip() not in unique_packages:
                unique_packages.append(pkg.strip())
        
        # 只保留最近的指定数量的包名
        unique_packages = unique_packages[:Config.MAX_PKG_HISTORY]
        
        with open(history_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(unique_packages))
    except Exception as e:
        print(f"保存包名历史记录失败: {e}")