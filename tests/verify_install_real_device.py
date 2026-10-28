"""真机验证：安装结果判定修复（针对定制 ROM 的误报失败）

用法:
    D:\\tool\\python\\python.exe tests/verify_install_real_device.py <apk路径> <设备IP>

背景:
    某些定制 ROM（TCL 的 com.tcl.guard 等）上，`adb install` 会**实际安装成功**
    （设备端输出 "install apk has been enabled from pm by user!" + "Success"），
    但 adb 客户端仍以退出码 1 结束（"Get install_switch_flag: 1"）。
    旧实现只看 returncode，把成功误报成失败。

本脚本直接调用 app 里的安装流程，验证判定是否正确。
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APK = sys.argv[1] if len(sys.argv) > 1 else None
DEVICE = sys.argv[2] if len(sys.argv) > 2 else None

if not APK or not os.path.exists(APK):
    print("用法: python tests/verify_install_real_device.py <apk路径> <设备IP>")
    sys.exit(2)

import utils
from utils import extract_package_name_from_apk, verify_install_result, get_installed_version_code

print("=" * 72)
print("真机验证：安装结果判定")
print("=" * 72)
print(f"APK   : {os.path.basename(APK)}")
print(f"设备  : {DEVICE}")

pkg = extract_package_name_from_apk(APK)
print(f"包名  : {pkg}")

apk_code = utils.get_apk_version_code(APK)
print(f"APK versionCode : {apk_code}")

before = get_installed_version_code(pkg, DEVICE)
print(f"安装前设备 versionCode : {before}")
print()

# --- 模拟工具里的判定逻辑 ---
print("-" * 72)
print("步骤 1: push 路径的可读性预检（_check_remote_file_readable 的逻辑）")
print("-" * 72)

import subprocess
remote_tmp = "/data/local/tmp/_adbtool_install.apk"
push_cmd = utils.build_adb_command_with_device(
    f'adb push "{APK}" {remote_tmp}', DEVICE)
push = subprocess.run(push_cmd, shell=True,
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      text=True, encoding='utf-8', errors='replace', timeout=300)
print(f"  push 返回码: {push.returncode}")
print(f"  push 输出: {(push.stdout or '').strip()[-200:]}")

check_cmd = utils.build_adb_command_with_device(
    f'adb shell "head -c 4 {remote_tmp} > /dev/null && echo READABLE"', DEVICE)
chk = subprocess.run(check_cmd, shell=True,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, encoding='utf-8', errors='replace', timeout=15)
out = (chk.stdout or '').strip()
readable = 'READABLE' in out
print(f"  可读性检查: {'可读 ✓' if readable else '不可读 ✗'}  输出: {out[:120]}")
if not readable:
    print("  → 工具会跳过 push 路径，直接走 adb install（不浪费一次传输）")

print()
print("-" * 72)
print("步骤 2: adb install（模拟 _install_via_adb_install 的判定）")
print("-" * 72)
install_cmd = utils.build_adb_command_with_device(
    f'adb install -r -d "{APK}"', DEVICE)
inst = subprocess.run(install_cmd, shell=True,
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      text=True, encoding='utf-8', errors='replace', timeout=600)
inst_out = (inst.stdout or '')
print(f"  adb 返回码: {inst.returncode}")
for line in inst_out.splitlines():
    print(f"    | {line}")

saw_success = any(
    ln.strip() == "Success" or ln.strip().endswith(" Success")
    for ln in inst_out.splitlines())
print()
print(f"  设备端 Success 信号: {'有 ✓' if saw_success else '无 ✗'}")
print(f"  旧判定（只看 returncode）: {'成功' if inst.returncode == 0 else '失败 ✗ 误报'}")
new_ok = (inst.returncode == 0) or saw_success
print(f"  新判定（含 Success 信号）: {'成功 ✓' if new_ok else '失败'}")

print()
print("-" * 72)
print("步骤 3: 安装后校验（verify_install_result）")
print("-" * 72)
verified, msg = verify_install_result(APK, pkg, DEVICE)
print(f"  校验结果: {'成功 ✓' if verified else '失败 ✗'}")
print(f"  说明    : {msg}")

after = get_installed_version_code(pkg, DEVICE)
print(f"  安装后设备 versionCode : {after}")

# 清理
utils.build_adb_command_with_device(
    f'adb shell rm -f {remote_tmp}', DEVICE)

print()
print("=" * 72)
ok = verified and new_ok
print("总体结论:", "全部通过 ✓" if ok else "存在问题 ✗")
print("=" * 72)
sys.exit(0 if ok else 1)
