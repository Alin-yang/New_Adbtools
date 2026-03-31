import subprocess
import datetime
import os
import glob
import time
from typing import Tuple, Optional, List
from config import Config

def get_connected_devices() -> List[str]:
    """获取当前连接的所有设备列表（标准版本，带验证）
    
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


def get_connected_devices_simple() -> List[str]:
    """获取当前连接的所有设备列表（快速版本，不深度验证）
    
    用于启动时快速检测，不进行额外的命令验证
    
    Returns:
        List[str]: 已连接设备的序列号/IP 地址列表
    """
    try:
        result = subprocess.run(
            "adb devices", shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=3  # 更短的超时时间
        )
        output = result.stdout.decode('utf-8', errors='ignore')
        devices = []
        for line in output.splitlines()[1:]:  # 跳过第一行标题
            # 只检查基本格式，不进行深度验证
            if '\t' in line and 'device' in line and 'unauthorized' not in line and 'offline' not in line:
                device_id = line.split('\t')[0].strip()
                if device_id and device_id != 'List':
                    devices.append(device_id)
        return devices
    except Exception:
        return []

def get_connected_devices_parallel() -> List[str]:
    """并行检测多个设备并验证可达性（优化版）
    
    使用线程池并行验证设备，提升多设备场景下的检测速度
    
    Returns:
        List[str]: 已连接且可访问的设备列表
    """
    try:
        # 先快速获取所有设备列表
        result = subprocess.run(
            "adb devices", shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=3
        )
        output = result.stdout.decode('utf-8', errors='ignore')
        
        # 提取设备 ID
        device_ids = []
        for line in output.splitlines()[1:]:
            if '\t' in line and 'device' in line and 'unauthorized' not in line and 'offline' not in line:
                device_id = line.split('\t')[0].strip()
                if device_id and device_id != 'List':
                    device_ids.append(device_id)
        
        if not device_ids:
            return []
        
        # 使用线程池并行验证设备可达性
        import concurrent.futures
        
        def validate_single_device(device_id):
            """验证单个设备是否可达"""
            try:
                validation_result = subprocess.run(
                    f"adb -s {device_id} shell echo test", shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=2
                )
                return device_id if validation_result.returncode == 0 else None
            except Exception:
                return None
        
        # 并行验证所有设备（最多 5 个并发）
        validated_devices = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(device_ids))) as executor:
            future_to_device = {
                executor.submit(validate_single_device, device_id): device_id 
                for device_id in device_ids
            }
            
            # 收集所有验证通过的设备
            for future in concurrent.futures.as_completed(future_to_device):
                try:
                    result = future.result(timeout=2)
                    if result:
                        validated_devices.append(result)
                except:
                    # 超时或失败的设备跳过
                    continue
        
        return validated_devices
        
    except Exception:
        return []


def get_unique_physical_devices() -> List[str]:
    """获取唯一的物理设备列表（合并同一设备的不同连接方式）
    
    Returns:
        List[str]: 唯一物理设备列表
    """
    try:
        result = subprocess.run(
            "adb devices -l", shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5
        )
        output = result.stdout.decode('utf-8', errors='ignore')
        
        # 解析带有详细信息的设备列表
        device_lines = output.splitlines()[1:]  # 跳过第一行标题
        
        unique_devices = {}  # 使用字典来去重，键是物理设备标识
        
        for line in device_lines:
            # 检查行是否包含设备信息，排除模拟器和其他状态
            if 'device' in line and 'unauthorized' not in line and 'offline' not in line:
                # 使用更灵活的方式来分割设备ID和属性
                # 第一个空白字符前的部分通常是设备ID
                parts = line.split(None, 1)  # 按第一个空白字符分割
                if parts:
                    device_id = parts[0].strip()
                    if not device_id:
                        continue
                    
                    # 验证设备是否真正可访问
                    try:
                        validation_result = subprocess.run(
                            f"adb -s {device_id} shell echo test", shell=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=3
                        )
                        if validation_result.returncode != 0:
                            continue  # 跳过不可访问的设备
                    except Exception:
                        continue  # 跳过验证失败的设备
                    
                    # 提取设备属性信息
                    attributes = parts[1] if len(parts) > 1 else ''
                    
                    # 尝试从属性中提取序列号等唯一标识符
                    # 对于网络连接，提取IP地址部分
                    if ':' in device_id:  # 网络连接
                        ip_part = device_id.split(':')[0]
                        # 尝试找到同一IP的USB连接设备作为唯一标识
                        unique_key = ip_part
                    else:  # USB连接
                        unique_key = device_id
                        
                    # 如果还没有使用这个唯一键，或者当前设备ID更完整，则保存
                    if unique_key not in unique_devices or len(device_id) > len(unique_devices[unique_key]):
                        unique_devices[unique_key] = device_id
        
        return list(unique_devices.values())
    except Exception:
        # 如果失败，回退到原始方法
        return get_connected_devices()


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
    
    # 获取当前连接的设备列表
    devices = get_connected_devices()
    
    # 只有一台设备时，不需要指定设备
    if len(devices) <= 1:
        return command
    
    # 多台设备时，需要指定目标设备
    if target_ip:
        # 清理目标IP（去除空格和引号）
        target_ip = target_ip.strip().strip('"').strip("'")
        
        # 标准化IP地址格式（确保包含端口号）
        if ':' not in target_ip:
            target_ip_with_port = f"{target_ip}:5555"
        else:
            target_ip_with_port = target_ip
        
        # 检查目标设备是否在已连接列表中
        matched_device = None
        for device in devices:
            # 精确匹配（包括端口号）
            if device == target_ip_with_port or device == target_ip:
                matched_device = device
                break
            # IP前缀匹配（确保是完整IP段匹配，而非部分匹配）
            elif device.startswith(target_ip + ':'):
                matched_device = device
                break
        
        if matched_device:
            # 在 adb 命令后立即插入 -s 参数
            if command.startswith('adb '):
                return command.replace('adb ', f'adb -s {matched_device} ', 1)
            elif command.startswith('adb'):
                return f'adb -s {matched_device} {command[3:]}'
    
    # 如果没有指定目标IP或目标设备未连接，返回原命令（会操作第一台设备）
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
            try:
                error_output = e.stderr.decode('gbk', errors='ignore')
                last_error = f"Command failed with error: {error_output}"
            except UnicodeDecodeError:
                last_error = "Command failed and unable to decode error output."
            
            # 某些错误不需要重试
            if "device not found" in last_error.lower() or "offline" in last_error.lower():
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
        import zipfile
        import xml.etree.ElementTree as ET
        from io import BytesIO
        
        with zipfile.ZipFile(apk_path, 'r') as zip_ref:
            # 读取 AndroidManifest.xml
            manifest_data = zip_ref.read('AndroidManifest.xml')
            
            # 尝试解析二进制 XML（需要额外的库，这里只做简单尝试）
            # 注意：完整的二进制 XML 解析比较复杂，这里仅作为备选方案
            # 如果 Manifest 是文本格式（罕见），可以直接解析
            try:
                manifest_str = manifest_data.decode('utf-8', errors='ignore')
                if 'package=' in manifest_str:
                    import re
                    match = re.search(r'package=["\']([^"\']+)["\']', manifest_str)
                    if match:
                        package_name = match.group(1)
                        if is_valid_package_name(package_name):
                            return package_name
            except:
                pass
    except:
        pass
    
    return None


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

def load_ip_history() -> List[str]:
    """加载IP历史记录
    
    Returns:
        List[str]: IP地址历史记录列表
    """
    history_file = Config.get_history_file_path()
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

def save_ip_history(ip_list: List[str]) -> None:
    """保存IP历史记录
    
    Args:
        ip_list: IP地址列表
    """
    history_file = Config.get_history_file_path()
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
    """验证IP地址格式是否正确
    
    Args:
        ip: IP地址字符串
        
    Returns:
        bool: 是否为有效的IP地址
    """
    import re
    # 支持IPv4和带端口的格式
    ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?::\d+)?$'
    return bool(re.match(ipv4_pattern, ip.strip()))


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


def safe_decode(data: bytes, encoding: str = 'utf-8') -> str:
    """安全地解码字节数据
    
    Args:
        data: 要解码的字节数据
        encoding: 编码格式
        
    Returns:
        str: 解码后的字符串
    """
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        try:
            return data.decode('gbk', errors='ignore')
        except UnicodeDecodeError:
            return data.decode('utf-8', errors='ignore')


def get_accurate_package_version(package_name: str) -> Optional[str]:
    """获取应用的精确版本号（优先获取当前用户安装的最新版本）
    
    Args:
        package_name: 应用包名
        
    Returns:
        Optional[str]: 版本号，如果获取失败则返回None
    """
    # 获取第一个连接的设备
    devices_output, devices_success = run_adb_command("adb devices")
    if not devices_success:
        return None
    
    device_id = None
    lines = devices_output.split('\n')[1:]  # 跳过标题行
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
    """获取用户自定义的数据存储路径
    
    Args:
        app_instance: 应用实例，用于获取数据路径输入框的值
        
    Returns:
        str: 用户自定义的路径或默认路径
    """
    if app_instance and hasattr(app_instance, 'log_path_entry'):
        user_path = app_instance.log_path_entry.get().strip()
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


def load_pkg_history() -> List[str]:
    """加载包名历史记录
    
    Returns:
        List[str]: 包名历史记录列表
    """
    history_file = Config.get_pkg_history_file_path()
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


def save_pkg_history(pkg_list: List[str]) -> None:
    """保存包名历史记录
    
    Args:
        pkg_list: 包名列表
    """
    history_file = Config.get_pkg_history_file_path()
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