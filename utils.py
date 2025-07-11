import subprocess
import datetime
import os
import glob
import time
from typing import Tuple, Optional, List
from config import Config

def run_adb_command(command: str, retries: int = None, timeout: int = None) -> Tuple[str, bool]:
    """执行ADB命令并返回结果
    
    Args:
        command: ADB命令字符串
        retries: 重试次数，默认使用配置值
        timeout: 超时时间，默认使用配置值
        
    Returns:
        Tuple[str, bool]: (输出结果, 是否成功)
    """
    if retries is None:
        retries = Config.MAX_ADB_RETRIES
    if timeout is None:
        timeout = Config.ADB_COMMAND_TIMEOUT
        
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