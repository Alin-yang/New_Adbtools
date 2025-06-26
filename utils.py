import subprocess
import datetime
import os
import glob

def run_adb_command(command):
    """执行ADB命令并返回结果"""
    try:
        result = subprocess.run(
            command, shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return result.stdout.decode('utf-8'), True
    except subprocess.CalledProcessError as e:
        try:
            error_output = e.stderr.decode('gbk', errors='ignore')
            return f"Command failed with error: {error_output}", False
        except UnicodeDecodeError:
            return "Command failed and unable to decode error output.", False

def timestamp_time():
    """生成时间戳文件名"""
    return datetime.datetime.now().strftime("%m%d-%H%M%S")

def extract_version_info(output):
    """从adb shell pm dump输出中提取版本号"""
    for line in output.split('\n'):
        if 'versionName' in line:
            return line.split('=')[1].strip()
    return None

def ensure_directory(path):
    """确保目录存在"""
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def get_next_filename(pattern, ext):
    """获取自增文件名"""
    file_count = len(glob.glob(f"{pattern}*{ext}"))
    return f"{pattern}_{file_count+1}{ext}"

def load_ip_history():
    """加载IP历史记录"""
    history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ip_history.txt')
    try:
        if os.path.exists(history_file):
            with open(history_file, 'r') as f:
                return [line.strip() for line in f.readlines() if line.strip()]
    except Exception as e:
        print(f"加载IP历史记录失败: {e}")
    return []

def save_ip_history(ip_list):
    """保存IP历史记录"""
    history_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ip_history.txt')
    try:
        # 确保列表中没有重复项，且最新的IP在最前面
        unique_ips = []
        for ip in ip_list:
            if ip not in unique_ips and ip.strip():
                unique_ips.append(ip)
        # 只保留最近的10个IP
        with open(history_file, 'w') as f:
            f.write('\n'.join(unique_ips[:10]))
    except Exception as e:
        print(f"保存IP历史记录失败: {e}")