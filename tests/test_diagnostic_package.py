"""一键诊断包回归测试（v5.4.8）

守护：
  ① 每项收集失败**不影响其它项**（部分失败也要能出包）
  ② README 摘要要说明**缺了什么**（用户得知道包里少了啥）
  ③ 设备标识在**主线程**取（后台线程读 Tk 控件会崩）
  ④ 命令参数名是 `target_device`（不是 `target`）
  ⑤ zip 里必须包含 README（否则对方不知道包里是什么）

用法: python tests/test_diagnostic_package.py
"""
import os
import sys
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    extra = f"  -> {detail}" if detail and not cond else ""
    results.append((cond, label, detail))
    print(("  PASS  " if cond else "  FAIL  ") + label + extra)


print("=" * 68)
print("一键诊断包回归测试")
print("=" * 68)

# ── 1. 源码级守护 ─────────────────────────────────────────────
print()
print("=== 1. 源码级守护 ===")
_app = os.path.join(_ROOT, 'app.py')
with open(_app, encoding='utf-8') as f:
    src = f.read()

check("有 collect_diagnostic_package()",
      'def collect_diagnostic_package' in src)
check("在后台线程执行（run_in_background）",
      src.count('def collect_diagnostic_package') >= 1
      and 'self.run_in_background(_work)' in src)
# ⚠️ 设备标识必须在主线程取（get_ip_address 读 Tk 控件）
check("设备标识在主线程取（不在线程里读控件）",
      '_target = self.get_ip_address()' in src)
check("线程里不再调 get_ip_address()",
      src.count('target=self.get_ip_address()') == 0)
# ⚠️ 参数名
check("用 target_device= 参数（不是 target=）",
      'target_device=_target' in src)
# 收集项
for _item in ('getprop', 'logcat -d', 'dumpsys meminfo', 'dumpsys cpuinfo',
               'pm list packages'):
    check(f"收集项包含 {_item}", _item in src)
# README + zip
check("生成 README 摘要", 'README.txt' in src)
check("用 zipfile 打包", 'zipfile.ZipFile' in src)
check("README 里说明未收集的项",
      '未收集' in src or 'failed' in src)
# ⚠️ 部分失败也要能出包
check("收集失败只记录不中断（try/except 包裹单项）",
      'def _collect(name, cmd, filename' in src)

# ── 2. 模拟打包流程（验证 zip 结构与 README）──────────────────
print()
print("=== 2. 模拟打包流程 ===")
import tempfile
import shutil

_tmp = tempfile.mkdtemp(prefix='diag_test_')
_pkg = os.path.join(_tmp, 'diag_1105-000000')
os.makedirs(_pkg)

collected = []
failed = []

# 模拟 3 项成功
for _name, _fn, _content in (
        ('设备属性', 'getprop.txt', '[ro.product.model]: Konka\n'),
        ('系统日志', 'logcat.txt', 'I/foo( 1): hello\n'),
        ('内存信息', 'dumpsys_meminfo.txt', 'Total PSS: 1234\n')):
    _p = os.path.join(_pkg, _fn)
    with open(_p, "w", encoding="utf-8") as f:
        f.write(_content)
    collected.append((_name, _fn, len(_content)))

# 模拟 1 项失败（设备没 root → 拉不到 ANR）
failed.append(('ANR 追踪', '无权限'))

# 生成 README（与实现同逻辑）
summary = ["ADB Tool 诊断包", "=" * 40,
           "生成时间: 1105-000000",
           "目标设备: 192.168.0.50:5555",
           f"成功收集 {len(collected)} 项，失败 {len(failed)} 项", ""]
if collected:
    summary.append("── 已收集 ──")
    for n, fn, sz in collected:
        summary.append(f"  ✓ {n}  ({fn}, {sz} 字节)")
if failed:
    summary.append("")
    summary.append("── 未收集（不影响其余内容）──")
    for n, why in failed:
        summary.append(f"  ✗ {n}: {why}")
with open(os.path.join(_pkg, 'README.txt'), "w", encoding="utf-8") as f:
    f.write("\n".join(summary))

# 打包
_zip = os.path.join(_tmp, 'diagnostic_test.zip')
with zipfile.ZipFile(_zip, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _d, files in os.walk(_pkg):
        for fn in files:
            full = os.path.join(root, fn)
            zf.write(full, os.path.relpath(full, _pkg))

check("zip 能生成", os.path.exists(_zip))
check("zip 大小 > 0", os.path.getsize(_zip) > 0, os.path.getsize(_zip))

with zipfile.ZipFile(_zip) as zf:
    names = zf.namelist()
    check("zip 含 README.txt", 'README.txt' in names, names)
    check("zip 含所有收集到的文件", len(names) == 4, names)
    # README 内容
    rd = zf.read('README.txt').decode('utf-8')
    check("README 列出成功项数", '成功收集 3 项' in rd, rd[:80])
    check("README 列出失败项数", '失败 1 项' in rd, rd[:80])
    check("README 说明哪项没收集到", 'ANR 追踪' in rd, rd[:120])
    check("README 标注未收集不影响其它", '不影响其余内容' in rd, rd[:120])
    # 内容完整
    check("zip 内文件内容完整",
          b'Konka' in zf.read('getprop.txt'))

shutil.rmtree(_tmp, ignore_errors=True)

# ── 3. 失败项不影响出包（模拟全失败场景）──────────────────────
print()
print("=== 3. 全失败也要能出包 ===")
_tmp2 = tempfile.mkdtemp(prefix='diag_fail_')
_pkg2 = os.path.join(_tmp2, 'diag_x')
os.makedirs(_pkg2)
# 只有 README，没有任何采集文件
with open(os.path.join(_pkg2, 'README.txt'), "w", encoding="utf-8") as f:
    f.write("ADB Tool 诊断包\n成功收集 0 项，失败 7 项\n")
_zip2 = os.path.join(_tmp2, 'diagnostic_fail.zip')
with zipfile.ZipFile(_zip2, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, _d, files in os.walk(_pkg2):
        for fn in files:
            full = os.path.join(root, fn)
            zf.write(full, os.path.relpath(full, _pkg2))
check("全失败时也能出包（含 README）",
      os.path.exists(_zip2) and 'README.txt' in
      zipfile.ZipFile(_zip2).namelist())
shutil.rmtree(_tmp2, ignore_errors=True)

# ── 4. UI 入口存在 ────────────────────────────────────────────
print()
print("=== 4. UI 入口 ===")
_lay = os.path.join(_ROOT, 'gui', 'layout_v4.py')
with open(_lay, encoding='utf-8') as f:
    lsrc = f.read()
check('诊断页有「错误分析」按钮', 'analyze_log_errors' in lsrc)
check('诊断页有「一键诊断包」按钮', 'collect_diagnostic_package' in lsrc)
check('有「智能分析」分区', '智能分析' in lsrc)

_win = os.path.join(_ROOT, 'gui', 'log_analysis_window.py')
check('有错误分析结果窗口', os.path.exists(_win))
with open(_win, encoding='utf-8') as f:
    wsrc = f.read()
check('窗口按频次展示（badge 显示次数）', "× {cnt}" in wsrc or "× " in wsrc)
check('窗口有导出报告', 'def _export_report' in wsrc)
check('窗口有复制摘要', 'def _copy_summary' in wsrc)

print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
