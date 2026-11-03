"""
进程定位 —— 找出目标包名对应的 PID

⚠️ 这是一个**独立模块**，因为它是整个性能监控最容易出错、后果最严重的地方：

   `adb shell pidof <包名>` 在**部分 Android 设备上是坏的**。
   实测小米盒子（MiBOX4 / Android 6.0.1，192.168.0.3:5555）：

       $ adb shell pidof com.gitvdemo.video
       1 2 3 5 7 8 9 10 11 12 14 15 ...   ← 155 个 PID，含 init(1)

   它**完全忽略了包名参数**，返回了系统所有进程的 PID。
   旧实现 `parse_pidof()` 取第一个数字 → **PID = 1（init 进程）**，
   于是 CPU 与线程表测的全是内核 init 的数据（≈0%），而内存和帧
   因为用的是包名所以正常 —— 表现为「CPU 一直是 0，线程表全是
   kthreadd / kworker / rcu_preempt 这种内核线程」。

所以这里**不能只依赖 pidof**，必须有多级回退并做交叉校验。
"""
import logging
import re
from typing import List, Optional

from utils import run_adb_command


class ProcessLocator:
    """按包名定位 PID（多级回退 + 交叉校验）"""

    # 各定位方法的可靠性排序（越靠前越准）
    def __init__(self, device: Optional[str] = None):
        self.device = device

    def _run(self, cmd: str):
        out, ok = run_adb_command(cmd, target_device=self.device)
        return out if ok else ''

    # ------------------------------------------------------------ 定位
    def find_pids(self, package_name: str) -> List[int]:
        """找出包名对应的所有 PID（主进程 + 子进程）

        Returns:
            PID 列表，第一个是主进程（通常）；找不到返回空列表
        """
        if not package_name:
            return []

        # 逐级尝试，第一个「看起来可信」的结果就采用
        for finder in (self._via_pidof, self._via_ps,
                       self._via_dumpsys_processes):
            try:
                pids = finder(package_name)
            except Exception as e:
                logging.debug(f"[性能] PID 定位 {finder.__name__} 异常: {e}")
                continue
            if pids:
                logging.info(f"[性能] PID 定位走 {finder.__name__}: {pids[:5]}")
                return pids

        logging.warning(f"[性能] 未能定位 {package_name} 的 PID")
        return []

    # ------------------------------------------------------------ 各级实现
    def _via_pidof(self, package_name: str) -> List[int]:
        """方法 1：pidof

        ⚠️ 必须做**合理性校验**：这台设备返回 155 个 PID（含 PID 1），
        显然是把参数忽略了。判据：
          - 结果数量 > 20 → 不可信（正常应用最多几十个子进程）
          - 包含 PID 1（init）→ 不可信
          - 数量为 0 → 不可信
        """
        out = self._run(f"adb shell pidof {package_name}")
        pids = [int(p) for p in out.split() if p.isdigit()]
        if not pids:
            return []
        if len(pids) > 20 or 1 in pids:
            logging.debug(
                f"[性能] pidof 返回异常（{len(pids)} 个，含 init={1 in pids}），"
                f"判定为不可信")
            return []
        return pids

    def _via_ps(self, package_name: str) -> List[int]:
        """方法 2：ps + 文本匹配

        不依赖设备上的 grep（有些设备没有），在 Python 侧过滤。
        """
        out = self._run("adb shell ps")
        if not out:
            return []
        pids = []
        for line in out.splitlines():
            if package_name not in line:
                continue
            parts = line.split()
            # ps 输出格式： USER PID PPID VSIZE RSS WCHAN PC NAME
            # PID 总是第 2 列（索引 1）
            if len(parts) >= 2 and parts[1].isdigit():
                pid = int(parts[1])
                if pid > 1:
                    pids.append(pid)
        return pids

    def _via_dumpsys_processes(self, package_name: str) -> List[int]:
        """方法 3：dumpsys activity processes

        最可靠（AMS 自己的记录），但输出很大。只在前两级都失败时用。
        """
        out = self._run("adb shell dumpsys activity processes")
        if not out:
            return []
        pids = []
        # 形如： ProcessRecord{... 27690:com.gitvdemo.video/u0a120}
        for m in re.finditer(r'\b(\d+):' + re.escape(package_name) + r'[/\s}]',
                             out):
            pid = int(m.group(1))
            if pid > 1 and pid not in pids:
                pids.append(pid)
        return pids

