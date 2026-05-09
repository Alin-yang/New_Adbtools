"""
性能监控模块
实时监控Android设备的CPU、内存、FPS等性能指标
"""
import re
import time
import threading
import logging
from typing import Optional, Dict, List, Callable
from utils import run_adb_command


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self, app):
        """
        初始化性能监控器
        
        Args:
            app: ADBToolApp实例
        """
        self.app = app
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # 性能数据缓存
        self.performance_data = {
            'cpu_usage': [],      # CPU使用率历史
            'memory_usage': [],   # 内存使用历史
            'fps': [],           # FPS历史
            'temperature': [],   # 温度历史
            'timestamps': []     # 时间戳
        }
        
        # 回调函数（用于更新UI）
        self.update_callback: Optional[Callable] = None
        
    def start_monitoring(self, package_name: Optional[str] = None, interval: int = 1):
        """
        开始性能监控
        
        Args:
            package_name: 要监控的应用包名（None表示监控整体系统）
            interval: 采样间隔（秒）
        """
        if self.monitoring:
            logging.warning("[性能监控] 监控已在运行中")
            return False
        
        target_package = package_name or self.app.get_package_name_from_input()
        if not target_package and package_name is not None:
            self.app.update_status("✗ 请输入要监控的应用包名", False)
            return False
        
        self.monitoring = True
        self.stop_event.clear()
        
        # 清空历史数据
        self._clear_data()
        
        # 启动监控线程
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(target_package, interval),
            daemon=True,
            name="PerformanceMonitor"
        )
        self.monitor_thread.start()
        
        msg = f"✓ 开始性能监控" + (f" - {target_package}" if target_package else " - 系统整体")
        self.app.update_status(msg, True, "info")
        logging.info(f"[性能监控] 开始监控: {target_package or '系统'}, 间隔: {interval}s")
        
        return True
    
    def stop_monitoring(self):
        """停止性能监控"""
        if not self.monitoring:
            logging.warning("[性能监控] 监控未在运行")
            return False
        
        self.monitoring = False
        self.stop_event.set()
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=3)
            self.monitor_thread = None
        
        self.app.update_status("✓ 性能监控已停止", True)
        logging.info("[性能监控] 监控已停止")
        
        return True
    
    def get_current_performance(self, package_name: Optional[str] = None) -> Dict:
        """
        获取当前性能数据（单次快照）
        
        Args:
            package_name: 应用包名（None表示系统整体）
            
        Returns:
            Dict: 包含CPU、内存、FPS等性能数据
        """
        result = {
            'cpu': self._get_cpu_usage(package_name),
            'memory': self._get_memory_usage(package_name),
            'fps': self._get_fps(),
            'temperature': self._get_temperature(),
            'timestamp': time.strftime("%H:%M:%S")
        }
        
        return result
    
    def _monitor_loop(self, package_name: Optional[str], interval: int):
        """
        监控循环（在后台线程中运行）
        
        Args:
            package_name: 应用包名
            interval: 采样间隔
        """
        try:
            while not self.stop_event.is_set():
                # 获取性能数据
                perf_data = self.get_current_performance(package_name)
                
                # 保存到历史数据
                self._save_to_history(perf_data)
                
                # 调用回调更新UI
                if self.update_callback:
                    self.app.root.after(0, lambda data=perf_data: self.update_callback(data))
                
                # 等待下一个采样周期
                self.stop_event.wait(interval)
                
        except Exception as e:
            logging.error(f"[性能监控] 监控循环异常: {str(e)}", exc_info=True)
            self.app.root.after(0, lambda: self.app.update_status(f"✗ 性能监控错误: {str(e)}", False))
        finally:
            self.monitoring = False
    
    def _get_cpu_usage(self, package_name: Optional[str] = None) -> float:
        """
        获取CPU使用率
        
        Args:
            package_name: 应用包名
            
        Returns:
            float: CPU使用率百分比
        """
        try:
            if package_name:
                # 获取特定应用的CPU使用率
                cmd = f"adb shell top -n 1 | grep {package_name}"
                output, success = run_adb_command(cmd)
                
                if success and output.strip():
                    logging.debug(f"[CPU监控] top输出: {output}")
                    # 解析top输出中的CPU列
                    for line in output.split('\n'):
                        if package_name in line:
                            parts = line.split()
                            # 寻找包含%的数字
                            for part in parts:
                                if '%' in part:
                                    try:
                                        cpu = float(part.replace('%', ''))
                                        logging.debug(f"[CPU监控] 应用CPU: {cpu}%")
                                        return cpu
                                    except:
                                        continue
            else:
                # 获取系统整体CPU使用率
                cmd = "adb shell cat /proc/stat"
                output, success = run_adb_command(cmd)
                
                if success:
                    lines = output.strip().split('\n')
                    if lines:
                        cpu_line = lines[0]  # cpu行
                        values = cpu_line.split()[1:]  # 跳过'cpu'标识
                        if len(values) >= 4:
                            user = int(values[0])
                            nice = int(values[1])
                            system = int(values[2])
                            idle = int(values[3])
                            
                            total = user + nice + system + idle
                            if total > 0:
                                usage = ((user + nice + system) / total) * 100
                                logging.debug(f"[CPU监控] 系统CPU: {usage:.2f}%")
                                return round(usage, 2)
        
        except Exception as e:
            logging.debug(f"[性能监控] 获取CPU失败: {str(e)}")
        
        return 0.0
    
    def _get_memory_usage(self, package_name: Optional[str] = None) -> Dict:
        """
        获取内存使用情况
        
        Args:
            package_name: 应用包名
            
        Returns:
            Dict: {'total': MB, 'used': MB, 'usage_percent': %}
        """
        try:
            if package_name:
                # 获取特定应用的内存使用
                cmd = f"adb shell dumpsys meminfo {package_name}"
                output, success = run_adb_command(cmd)
                
                if success:
                    logging.debug(f"[内存监控] meminfo输出前20行: {output[:500]}")
                    # 查找TOTAL行
                    for line in output.split('\n'):
                        if 'TOTAL' in line and ':' in line:
                            match = re.search(r'TOTAL[:\s]+(\d+)', line)
                            if match:
                                total_kb = int(match.group(1))
                                logging.debug(f"[内存监控] 应用内存: {total_kb}KB")
                                return {
                                    'total': round(total_kb / 1024, 2),  # 转换为MB
                                    'used': round(total_kb / 1024, 2),
                                    'usage_percent': 0  # 应用内存不计算百分比
                                }
            else:
                # 获取系统整体内存
                cmd = "adb shell cat /proc/meminfo"
                output, success = run_adb_command(cmd)
                
                if success:
                    mem_info = {}
                    for line in output.split('\n'):
                        if 'MemTotal' in line:
                            match = re.search(r'MemTotal:\s+(\d+)', line)
                            if match:
                                mem_info['total'] = int(match.group(1))
                        elif 'MemAvailable' in line:
                            match = re.search(r'MemAvailable:\s+(\d+)', line)
                            if match:
                                mem_info['available'] = int(match.group(1))
                    
                    if 'total' in mem_info and 'available' in mem_info:
                        total_kb = mem_info['total']
                        available_kb = mem_info['available']
                        used_kb = total_kb - available_kb
                        
                        logging.debug(f"[内存监控] 系统内存: {used_kb}KB / {total_kb}KB")
                        return {
                            'total': round(total_kb / 1024, 2),
                            'used': round(used_kb / 1024, 2),
                            'usage_percent': round((used_kb / total_kb) * 100, 2)
                        }
        
        except Exception as e:
            logging.debug(f"[性能监控] 获取内存失败: {str(e)}")
        
        return {'total': 0, 'used': 0, 'usage_percent': 0}
    
    def _get_fps(self) -> float:
        """
        获取当前FPS（帧率）
        
        Returns:
            float: FPS值
        """
        try:
            # 使用简化方法：通过dumpsys gfxinfo获取最近帧信息
            cmd = "adb shell dumpsys gfxinfo frames"
            output, success = run_adb_command(cmd)
            
            if success and output.strip():
                lines = output.strip().split('\n')
                # 过滤掉空行和标题行
                valid_lines = [l for l in lines if l.strip() and not l.startswith(' ')]
                frame_count = len(valid_lines)
                
                if frame_count > 0:
                    # 返回一个合理的FPS估计值
                    fps = min(frame_count, 60)  # 最多60FPS
                    return round(fps, 2)
            
            # 备用方案：返回0表示无法获取
            return 0.0
        
        except Exception as e:
            logging.debug(f"[性能监控] 获取FPS失败: {str(e)}")
        
        return 0.0
    
    def _get_temperature(self) -> float:
        """
        获取设备温度
        
        Returns:
            float: 温度值（摄氏度）
        """
        try:
            # 尝试多个温度传感器路径
            temp_paths = [
                "/sys/class/thermal/thermal_zone0/temp",
                "/sys/devices/virtual/thermal/thermal_zone0/temp",
                "/sys/class/thermal/thermal_zone1/temp",
            ]
            
            for path in temp_paths:
                cmd = f"adb shell cat {path}"
                output, success = run_adb_command(cmd)
                
                if success and output.strip():
                    try:
                        # 温度值通常是毫摄氏度，需要除以1000
                        temp = int(output.strip()) / 1000.0
                        return round(temp, 1)
                    except:
                        continue
        
        except Exception as e:
            logging.debug(f"[性能监控] 获取温度失败: {str(e)}")
        
        return 0.0
    
    def _save_to_history(self, perf_data: Dict):
        """
        保存性能数据到历史记录
        
        Args:
            perf_data: 性能数据字典
        """
        max_history = 300  # 最多保留300个数据点（5分钟@1s间隔）
        
        self.performance_data['cpu_usage'].append(perf_data['cpu'])
        self.performance_data['memory_usage'].append(perf_data['memory']['used'])
        self.performance_data['fps'].append(perf_data['fps'])
        self.performance_data['temperature'].append(perf_data['temperature'])
        self.performance_data['timestamps'].append(perf_data['timestamp'])
        
        # 限制历史记录长度
        for key in self.performance_data:
            if len(self.performance_data[key]) > max_history:
                self.performance_data[key].pop(0)
    
    def _clear_data(self):
        """清空历史数据"""
        for key in self.performance_data:
            self.performance_data[key].clear()
    
    def get_performance_summary(self) -> str:
        """
        获取性能摘要报告
        
        Returns:
            str: 格式化的性能摘要
        """
        if not self.performance_data['cpu_usage']:
            return "暂无性能数据"
        
        cpu_avg = sum(self.performance_data['cpu_usage']) / len(self.performance_data['cpu_usage'])
        cpu_max = max(self.performance_data['cpu_usage'])
        
        mem_values = [m for m in self.performance_data['memory_usage'] if m > 0]
        mem_avg = sum(mem_values) / len(mem_values) if mem_values else 0
        mem_max = max(mem_values) if mem_values else 0
        
        fps_values = [f for f in self.performance_data['fps'] if f > 0]
        fps_avg = sum(fps_values) / len(fps_values) if fps_values else 0
        fps_min = min(fps_values) if fps_values else 0
        
        temp_values = [t for t in self.performance_data['temperature'] if t > 0]
        temp_avg = sum(temp_values) / len(temp_values) if temp_values else 0
        temp_max = max(temp_values) if temp_values else 0
        
        summary = f"""
📊 性能监控摘要
{'='*50}
CPU使用率:
  平均: {cpu_avg:.1f}%
  峰值: {cpu_max:.1f}%

内存使用:
  平均: {mem_avg:.1f} MB
  峰值: {mem_max:.1f} MB

帧率(FPS):
  平均: {fps_avg:.1f}
  最低: {fps_min:.1f}

设备温度:
  平均: {temp_avg:.1f}°C
  最高: {temp_max:.1f}°C

采样点数: {len(self.performance_data['cpu_usage'])}
{'='*50}
"""
        return summary
