# -*- mode: python ; coding: utf-8 -*-
#
# ADB Tool PyInstaller SPEC —— ONEDIR 版本
#
# 与 ADBTool.spec（onefile）的区别：
#   onefile: 打包成单个 exe，每次启动都要把内嵌 archive 解压到 %TEMP%，
#            实测多花 ~9.5 秒启动时间（用户反馈"每次启动都很慢"的主因）。
#   onedir:  exe + 依赖文件放在同一个文件夹，启动不需要解压 —— 快 10 倍。
#
# 用法：
#   D:\tool\python\python.exe -m PyInstaller ADBTool_onedir.spec --noconfirm --clean
#   产物：dist\ADBTool\ADBTool.exe（整个 dist\ADBTool 文件夹一起分发）

import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# 动态收集 tkinterdnd2 的 tkdnd 二进制（兼容任意 Python 安装路径，不再硬编码 D:/python）
tkdnd_binaries = []
try:
    import tkinterdnd2
    _tkdnd_dir = os.path.join(os.path.dirname(tkinterdnd2.__file__), 'tkdnd')
    if os.path.isdir(_tkdnd_dir):
        for _root, _dirs, _files in os.walk(_tkdnd_dir):
            for _f in _files:
                _src = os.path.join(_root, _f)
                _rel = os.path.relpath(_root, _tkdnd_dir)
                _dst = 'tkinterdnd2/tkdnd' if _rel == '.' else os.path.join('tkinterdnd2/tkdnd', _rel).replace('\\', '/')
                tkdnd_binaries.append((_src, _dst))
except ImportError:
    # 未安装 tkinterdnd2 时静默；后续 hiddenimports 会在运行时暴露问题
    pass

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
    [],
    exclude_binaries=True,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ADBTool',
)
