#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动生成PyInstaller SPEC文件
用于正确打包包含tkinterdnd2库的应用程序
"""

import os
import sys
import platform
import tkinterdnd2
from pathlib import Path


def detect_tkdnd_platform_dir():
    """检测当前平台对应的tkdnd目录"""
    tkdnd_base = Path(tkinterdnd2.__file__).parent / "tkdnd"
    
    # 根据当前平台架构选择合适的目录
    arch = platform.architecture()[0]  # '32bit' or '64bit'
    system = platform.system().lower()  # 'windows', 'linux', 'darwin'(macOS)
    
    # 平台映射
    if system == "windows":
        if arch == "64bit":
            # 优先使用x64，如果不存在则使用x86
            if (tkdnd_base / "win-x64").exists():
                return tkdnd_base / "win-x64"
            elif (tkdnd_base / "win32").exists():
                return tkdnd_base / "win32"
            elif (tkdnd_base / "win64").exists():
                return tkdnd_base / "win64"
            else:
                # 尝试其他可能的目录名
                for d in tkdnd_base.iterdir():
                    if d.is_dir() and "win" in d.name.lower():
                        return d
        else:  # 32位
            if (tkdnd_base / "win32").exists():
                return tkdnd_base / "win32"
            elif (tkdnd_base / "win-x86").exists():
                return tkdnd_base / "win-x86"
    elif system == "darwin":  # macOS
        if arch == "64bit":
            if (tkdnd_base / "osx-x64").exists():
                return tkdnd_base / "osx-x64"
        # 尝试ARM64 (Apple Silicon)
        if (tkdnd_base / "osx-arm64").exists():
            return tkdnd_base / "osx-arm64"
    elif system == "linux":
        if arch == "64bit":
            if (tkdnd_base / "linux-x64").exists():
                return tkdnd_base / "linux-x64"
        # 尝试ARM64
        if (tkdnd_base / "linux-arm64").exists():
            return tkdnd_base / "linux-arm64"
    
    # 如果都没找到，返回tkdnd基目录，让PyInstaller包含整个目录
    return tkdnd_base


def generate_spec_file():
    """生成SPEC文件"""
    tkdnd_path = detect_tkdnd_platform_dir()
    
    # 获取tkinterdnd2库的路径
    tkinterdnd2_path = Path(tkinterdnd2.__file__).parent
    
    # 生成包含tkdnd所有平台文件的路径列表
    tkdnd_base = Path(tkinterdnd2.__file__).parent / "tkdnd"
    tkdnd_binaries = []
    
    # 包含所有平台的tkdnd文件（以确保兼容性）
    for platform_dir in tkdnd_base.iterdir():
        if platform_dir.is_dir():
            tkdnd_binaries.append((str(platform_dir.as_posix()), f'tkinterdnd2/tkdnd/{platform_dir.name}'))
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
#
# ADB Tool PyInstaller SPEC文件
# 自动生成，包含tkinterdnd2库的必要文件

block_cipher = None

# 包含所有平台的tkdnd文件以确保兼容性
tkdnd_binaries = [
{chr(10).join([f"    ('{item[0]}', '{item[1]}')," for item in tkdnd_binaries])}
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=tkdnd_binaries,
    datas=[
        ('gui', 'gui'),
        ('modules', 'modules'),
        ('config.py', '.'),
        ('decorators.py', '.'),
        ('utils.py', '.'),
        ('cache_manager.py', '.'),
    ],
    hiddenimports=[
        'tkinterdnd2',
        'tkinterdnd2.TkinterDnD',
        'tkinterdnd2.tkDnD',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ADBTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
)
'''
    
    with open('ADBTool.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print(f"SPEC文件已生成：ADBTool.spec")
    print(f"检测到的tkdnd路径：{tkdnd_path}")
    print(f"tkinterdnd2库路径：{tkinterdnd2_path}")
    print(f"包含的tkdnd平台目录：")
    for item in tkdnd_binaries:
        print(f"  {item[0]} -> {item[1]}")
    print()


if __name__ == "__main__":
    print("正在生成PyInstaller SPEC文件...")
    generate_spec_file()
    print("SPEC文件生成完成！")
    print("现在可以运行 'pyinstaller ADBTool.spec' 进行打包。")