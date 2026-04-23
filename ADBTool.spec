# -*- mode: python ; coding: utf-8 -*-
#
# ADB Tool PyInstaller SPEC文件
# 自动生成，包含tkinterdnd2库的必要文件

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
        # 集成 scrcpy 投屏工具
        ('tools/scrcpy', 'tools/scrcpy'),
    ],
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
