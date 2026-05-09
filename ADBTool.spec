# -*- mode: python ; coding: utf-8 -*-
#
# ADB Tool PyInstaller SPEC文件
# 自动生成，包含tkinterdnd2库的必要文件

import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# 包含所有平台的tkdnd文件以确保兼容性
tkdnd_binaries = [
    ('D:/python/Lib/site-packages/tkinterdnd2/tkdnd/linux-arm64', 'tkinterdnd2/tkdnd/linux-arm64'),
    ('D:/python/Lib/site-packages/tkinterdnd2/tkdnd/linux-x64', 'tkinterdnd2/tkdnd/linux-x64'),
    ('D:/python/Lib/site-packages/tkinterdnd2/tkdnd/osx-arm64', 'tkinterdnd2/tkdnd/osx-arm64'),
    ('D:/python/Lib/site-packages/tkinterdnd2/tkdnd/osx-x64', 'tkinterdnd2/tkdnd/osx-x64'),
    ('D:/python/Lib/site-packages/tkinterdnd2/tkdnd/win-arm64', 'tkinterdnd2/tkdnd/win-arm64'),
    ('D:/python/Lib/site-packages/tkinterdnd2/tkdnd/win-x64', 'tkinterdnd2/tkdnd/win-x64'),
    ('D:/python/Lib/site-packages/tkinterdnd2/tkdnd/win-x86', 'tkinterdnd2/tkdnd/win-x86'),
]

# 收集 scrcpy 目录下的所有文件
scrcpy_dir = 'tools/scrcpy'
scrcpy_files = []
if os.path.exists(scrcpy_dir):
    for root, dirs, files in os.walk(scrcpy_dir):
        for file in files:
            full_path = os.path.join(root, file)
            # 计算相对路径
            rel_path = os.path.relpath(full_path, scrcpy_dir)
            dest_dir = os.path.join('tools/scrcpy', os.path.dirname(rel_path))
            scrcpy_files.append((full_path, dest_dir))

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
        ('device_monitor.py', '.'),
        ('adaptive_cache.py', '.'),
    ] + scrcpy_files,  # 添加 scrcpy 文件
    hiddenimports=[
        'tkinterdnd2',
        'tkinterdnd2.TkinterDnD',
        'tkinterdnd2.tkDnD',
    ],
    hookspath=[],
    hooksconfig={},
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
