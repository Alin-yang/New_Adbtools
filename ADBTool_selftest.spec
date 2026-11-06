# -*- mode: python ; coding: utf-8 -*-
"""打包产物自检 exe 的 spec（onedir）"""
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

ROOT = os.path.abspath('.')

tkdnd_binaries = []
try:
    import tkinterdnd2
    tkdnd_binaries = collect_data_files('tkinterdnd2')
except Exception:
    pass

scrcpy_dir = os.path.join(ROOT, 'tools', 'scrcpy')
scrcpy_files = []
if os.path.exists(scrcpy_dir):
    for root, dirs, files in os.walk(scrcpy_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, scrcpy_dir)
            scrcpy_files.append((full, os.path.join('tools', 'scrcpy',
                                                    os.path.dirname(rel))))

a = Analysis(
    ['tools/selftest_device_picker.py'],
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
    ] + scrcpy_files,
    hiddenimports=[
        'tkinterdnd2',
        'tkinterdnd2.TkinterDnD',
        'modules.perf_locator',
        'modules.perf_parsers',
        'modules.perf_collector',
        'modules.perf_analysis',
        'modules.perf_chart',
        'modules.perf_report',
        'modules.perf_baseline',
        'modules.perf_scenario',
        'gui.device_picker',
        'gui.nav_icons',
        'modules.log_analyzer',
        'gui.log_analysis_window',
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
    name='ADBTool_selftest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # 自检要看到输出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ADBTool_selftest',
)
