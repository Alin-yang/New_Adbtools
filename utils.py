import subprocess
import datetime
import os
import glob
import time
from typing import Tuple, Optional, List
from config import Config

def get_connected_devices() -> List[str]:
    """获取当前连接的所有设备列表
    
    Returns:
        List[str]: 已连接设备的序列号/IP地址列表
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
            # 精确匹配
            if device == target_ip_with_port or device == target_ip:
                matched_device = device
                break
            # 如果输入的是简写IP（如 3.13），尝试匹配完整IP
            elif target_ip in device:
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
    """从 adb shell pm dump 输出中提取版本号（优化版，支持多版本情况）
    
    Args:
        output: adb shell pm dump 命令的输出
        
    Returns:
        Optional[str]: 版本号字符串，如果未找到则返回None
    """
    if not output:
        return None
        
    versions = []
    lines = output.split('\n')
    
    # 查找所有的 versionName 行
    for i, line in enumerate(lines):
        line = line.strip()
        if 'versionName' in line and '=' in line:
            try:
                version = line.split('=')[1].strip()
                if version and version != 'null':
                    # 检查是否为用户安装的版本（通常在 User 段中）
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
                    
                    versions.append((version, priority, context))
            except IndexError:
                continue
    
    if not versions:
        return None
    
    # 按优先级排序，选择最高优先级的版本
    versions.sort(key=lambda x: x[1], reverse=True)
    
    # 如果有多个相同优先级的版本，选择版本号最大的
    top_priority = versions[0][1]
    top_versions = [v for v in versions if v[1] == top_priority]
    
    if len(top_versions) > 1:
        # 比较版本号，选择最新的
        top_versions.sort(key=lambda x: parse_version_number(x[0]), reverse=True)
    
    return top_versions[0][0]


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
    # 策略1：优先使用 pm list packages -3 获取用户安装的应用版本
    cmd1 = f'adb shell pm list packages -3 {package_name}'
    output1, success1 = run_adb_command(cmd1)
    
    if success1 and package_name in output1:
        # 如果是用户安装的应用，使用 dumpsys package 获取详细信息
        cmd2 = f'adb shell dumpsys package {package_name}'
        output2, success2 = run_adb_command(cmd2)
        
        if success2:
            version = extract_version_info(output2)
            if version:
                return version
    
    # 策略2：使用 pm dump 命令获取全部信息
    cmd3 = f'adb shell pm dump {package_name}'
    output3, success3 = run_adb_command(cmd3)
    
    if success3:
        version = extract_version_info(output3)
        if version:
            return version
    
    # 策略3：使用 dumpsys package 并过滤 versionName
    cmd4 = f'adb shell dumpsys package {package_name} | grep -i versionName'
    output4, success4 = run_adb_command(cmd4)
    
    if success4 and 'versionName' in output4:
        # 解析过滤后的版本信息
        for line in output4.split('\n'):
            if 'versionName' in line and '=' in line:
                try:
                    version = line.split('=')[1].strip()
                    if version and version != 'null':
                        return version
                except IndexError:
                    continue
    
    # 策略4：使用 Windows 的 findstr 命令
    cmd5 = f'adb shell dumpsys package {package_name} | findstr "versionName"'
    output5, success5 = run_adb_command(cmd5)
    
    if success5 and 'versionName' in output5:
        # 从简单的输出中提取版本号
        lines = output5.split('\n')
        for line in lines:
            if 'versionName' in line and '=' in line:
                try:
                    version = line.split('=')[1].strip()
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