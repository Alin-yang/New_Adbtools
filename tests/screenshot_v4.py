"""v4 新布局截图脚本（开发辅助，不参与打包）

用法: python tests/screenshot_v4.py [输出目录]
"""
import sys, os, ctypes, ctypes.wintypes, time, struct, zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

try:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
except ImportError:
    root = tk.Tk()

from app import ADBToolApp
from gui import layout_v4 as layout

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '_shots_v4')
os.makedirs(OUT_DIR, exist_ok=True)

root.geometry('1400x820')
app = ADBToolApp(root, layout_module=layout)
root.update()
root.update_idletasks()
root.lift()
root.attributes('-topmost', True)
root.update()

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def grab(filename):
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        print("窗口尺寸异常", w, h)
        return

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    SRCCOPY = 0x00CC0020
    gdi32.BitBlt(mem_dc, 0, 0, w, h, hwnd_dc, 0, 0, SRCCOPY)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    src = buf.raw
    out = bytearray(w * h * 4)
    for i in range(0, w * h * 4, 4):
        out[i] = src[i + 2]
        out[i + 1] = src[i + 1]
        out[i + 2] = src[i]
        out[i + 3] = 255
    raw = b''.join(b'\x00' + bytes(out[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(tag, data):
        # ⚠️ 长度字段必须是 data 的长度（不含 tag），
        #    写成 len(tag+data) 会让 PNG 的 CRC 校验失败、文件无法打开。
        d = tag + data
        return struct.pack('>I', len(data)) + d + struct.pack('>I', zlib.crc32(d) & 0xffffffff)

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6))
           + chunk(b'IEND', b''))
    path = os.path.join(OUT_DIR, filename)
    with open(path, 'wb') as f:
        f.write(png)
    print("saved:", path, f"{w}x{h}")


DEMO_LOG = """[16:00:01] [✓] 设备监控已启动
[16:00:02] [✓] 连接成功 192.168.0.51:5555
[16:00:03] [✗] 安装失败 (code 1)
[16:00:04] [i] 正在传输... 45%（43.28MB / 96.20MB）
[16:00:05] [E] java.lang.NullPointerException at Foo.bar
[16:00:06] [✓] 传输完成
[16:00:07] [i] 设备已连接 192.168.0.51:5555
[16:00:08] [✓] ✓ 已校验 versionCode = 223229
"""

lay = app.layout_instance

# 填充演示日志
try:
    app.status_text.delete('1.0', tk.END)
    app.status_text.insert(tk.END, DEMO_LOG)
except Exception as e:
    print('demo log failed:', e)

PAGES = [
    ('install', '安装应用'),
    ('diagnose', '问题诊断'),
    ('device', '设备控制'),
    ('perf', '性能监控'),
    ('mirror', '投屏控制'),
    ('script', '脚本执行'),
]


def shoot_all(theme):
    app._ui_theme.set_theme(theme)
    root.update()
    root.update_idletasks()
    for key, name in PAGES:
        lay.switch_nav(key)
        # ⚠️ 面板是懒加载 + tkraise 切换，必须多次 update 让
        #    「构建 → 布局 → 重绘」走完，否则截到的是上一个面板
        for _ in range(3):
            root.update_idletasks()
            root.update()
            time.sleep(0.08)
        root.update()
        grab(f"{theme}_{key}.png")
    # 终端折叠态
    lay.switch_nav('install')
    for _ in range(3):
        root.update_idletasks()
        root.update()
    lay._toggle_terminal()
    for _ in range(3):
        root.update_idletasks()
        root.update()
        time.sleep(0.06)
    root.update()
    grab(f"{theme}_install_collapsed.png")
    lay._toggle_terminal()
    root.update()


shoot_all('dark')
shoot_all('light')


# ── 性能报告窗口截图 ────────────────────────────────────────────
def _fake_session():
    """造一份有内容的会话数据（不依赖真机，图形更丰富）"""
    import random
    random.seed(7)
    history = []
    t = 0
    for i in range(60):
        t += 2
        cpu = 30 + 18 * (i / 60) + random.randint(-6, 6)
        pss = 220 + i * 1.3 + random.randint(-3, 3)
        fps = 58 if i % 17 else 22
        jank = 0.4 if i % 17 else 14.0
        history.append({
            'ts': f'15:{t // 60:02d}:{t % 60:02d}',
            'cpu': round(cpu, 2), 'pss': round(pss, 1),
            'rss': round(pss + 90, 1), 'java': round(pss * 0.4, 1),
            'native': round(pss * 0.3, 1), 'fps': fps, 'jank': jank,
        })
    durations = [8.1] * 40 + [12.5] * 25 + [17.8] * 15 + [24.0] * 8 + [45.2] * 4
    threads = [
        {'tid': 28055, 'name': 'PumaProgMgr', 'cur': 18.5, 'avg': 16.2, 'peak': 24.1},
        {'tid': 28068, 'name': 'gala.SSDPSS/', 'cur': 14.2, 'avg': 13.1, 'peak': 19.8},
        {'tid': 27700, 'name': 'HeapTaskDaemon', 'cur': 9.6, 'avg': 8.4, 'peak': 13.2},
        {'tid': 28933, 'name': 'Thread-2327', 'cur': 7.1, 'avg': 6.2, 'peak': 10.4},
        {'tid': 27947, 'name': 'apm_tracker', 'cur': 5.3, 'avg': 4.8, 'peak': 7.1},
        {'tid': 27741, 'name': 'CurlMultiHandle', 'cur': 3.8, 'avg': 3.2, 'peak': 5.6},
        {'tid': 27742, 'name': 'QtpEngine', 'cur': 2.4, 'avg': 2.1, 'peak': 3.9},
        {'tid': 27698, 'name': 'FinalizerDaemon', 'cur': 1.6, 'avg': 1.2, 'peak': 2.4},
        {'tid': 27769, 'name': 'T-log', 'cur': 1.1, 'avg': 0.9, 'peak': 1.8},
    ]
    stats = {
        'cpu': {'cur': 48.3, 'avg': 41.2, 'peak': 62.7, 'p95': 58.4, 'p05': 26.1},
        'pss': {'cur': 295.4, 'avg': 258.1, 'peak': 302.8, 'p95': 298.6, 'p05': 218.4},
        'rss': {'cur': 385.2, 'avg': 348.0, 'peak': 392.6, 'p95': 388.4, 'p05': 308.1},
        'java': {'cur': 118.2, 'avg': 103.3, 'peak': 121.0, 'p95': 119.5, 'p05': 87.4},
        'native': {'cur': 88.6, 'avg': 77.4, 'peak': 90.8, 'p95': 89.7, 'p05': 65.5},
        'fps': {'cur': 58.0, 'avg': 55.2, 'peak': 60.0, 'p95': 60.0, 'p05': 22.0},
        'jank': {'cur': 2.1, 'avg': 3.4, 'peak': 16.8, 'p95': 14.2, 'p05': 0.3},
        'p95_frame': {'cur': 18.6, 'avg': 16.2, 'peak': 24.0, 'p95': 21.3, 'p05': 12.8},
        'p99_frame': {'cur': 32.4, 'avg': 28.1, 'peak': 45.2, 'p95': 38.6, 'p05': 18.4},
        'alert': False, 'threads': threads,
        'thread_sum': sum(t['cur'] for t in threads),
        'sample_count': 60, 'elapsed': 120.0, 'pid': 27690, 'pids': [27690],
        'mode': 'proc',
        'quality': {'ok_points': 60, 'fail_points': 0, 'total_points': 60,
                    'success_rate': 100.0, 'interval_actual': 2.1,
                    'interval_set': 2.0,
                    'costs': {'proc': 0.42, 'gfxinfo': 1.1, 'meminfo': 1.6},
                    'degraded': False, 'mode': 'proc', 'clk_tck': 100,
                    'clk_tck_estimated': False, 'cpu_max': 400.0},
    }
    session = {'package': 'com.gitvdemo.video', 'pid': 27690, 'stats': stats,
               'history': history,
               'frame_samples': [{'ts': h['ts'], 'durations': durations,
                                  'jank_pct': h['jank']} for h in history],
               'quality': stats['quality'], 'scenario': 'video'}
    from modules import perf_analysis as A
    session['conclusions'] = A.analyze(session)
    return session


from modules.perf_report import PerfReportWindow

for _theme in ('dark', 'light'):
    app._ui_theme.set_theme(_theme)
    root.update_idletasks()
    root.update()
    _win = PerfReportWindow(app, _fake_session())
    _win.win.lift()
    _win.win.attributes('-topmost', True)
    for _ in range(4):
        root.update_idletasks()
        root.update()
    for _idx, _name in enumerate(['trend', 'threads', 'frames', 'raw']):
        _win.nb.select(_idx)
        for _ in range(4):
            root.update_idletasks()
            root.update()
        time.sleep(0.25)
        root.update()
        _hwnd = user32.GetParent(_win.win.winfo_id()) or _win.win.winfo_id()
        grab(f'report_{_theme}_{_name}.png')
    _win.win.destroy()


# ── 「监控进行中」截图（验证实时刷新在视觉上正常）─────────────────
# ⚠️ 需要真机；没设备时跳过（截图脚本不能因为缺设备就失败）
import subprocess
_dev_ok = False
try:
    _out = subprocess.run('adb devices', shell=True, capture_output=True,
                          timeout=15).stdout.decode('utf-8', 'ignore')
    _devices = [l.split('\t')[0].strip() for l in _out.splitlines()
                 if '\tdevice' in l]
    _dev_ok = bool(_devices)
except Exception:
    _devices = []
    _dev_ok = False

if _dev_ok:
    import time as _t
    for _theme in ('dark', 'light'):
        app._ui_theme.set_theme(_theme)
        root.update_idletasks()
        root.update()
        lay.switch_nav('perf')
        for _ in range(3):
            root.update_idletasks()
            root.update()
        # 找一个**正在运行**的第三方应用
        # ⚠️ 必须选正在运行的：应用没启动 → PID 定位失败 → 降级 cpuinfo
        #    → cpuinfo 里也没有它的记录 → 界面全是「--」，截不到有效画面。
        # 用 `ps` 直接看运行中的进程（比 pm list packages 准）。
        _pkg = ''
        _target_dev = ''
        _sys = ('com.android.', 'com.google.android.', 'android.',
                'com.qualcomm.', 'org.chromium.', 'com.mediatek.',
                'com.svox.pico', 'com.cyanogen.')
        for _dev in _devices:
            try:
                _ps = subprocess.run(
                    f'adb -s {_dev} shell ps', shell=True,
                    capture_output=True, timeout=25).stdout.decode('utf-8', 'ignore')
            except Exception:
                continue
            _cands = []
            for _l in _ps.splitlines():
                _parts = _l.split()
                if not _parts:
                    continue
                _last = _parts[-1]
                # ⚠️ 两种 ps 输出格式都要兼容：
                #    新版 Android：NAME = "1234/com.foo.bar"
                #    老版 toybox（实测 Android 6）：NAME = "com.foo.bar"（无 PID 前缀）
                _name = _last.split('/', 1)[1] if '/' in _last else _last
                if not _name.startswith(('com.', 'net.', 'org.')):
                    continue
                if _name.startswith(_sys):
                    continue
                if _name not in _cands:
                    _cands.append(_name)
            if _cands:
                _pkg = _cands[0]
                _target_dev = _dev
                break
        if not _pkg:
            print('未找到正在运行的第三方应用，跳过「监控中」截图')
            continue
        print(f'「监控中」截图使用设备 {_target_dev} 包名 {_pkg}')
        try:
            app.perf_package_entry.delete(0, tk.END)
            app.perf_package_entry.insert(0, _pkg)
            # 让采集器用找到的那台设备
            try:
                app.performance_monitor.device = _target_dev
                app.performance_monitor.locator.device = _target_dev
            except Exception:
                pass
            app.start_performance_monitor()
            # 等到有 3 次采样
            for _ in range(30):
                _t.sleep(1)
                root.update_idletasks()
                root.update()
                if app.performance_monitor.stats().get('sample_count', 0) >= 3:
                    break
            _t.sleep(0.6)
            root.update_idletasks()
            root.update()
            grab(f'live_monitoring_{_theme}.png')
            app.stop_performance_monitor()
            for _ in range(3):
                root.update_idletasks()
                root.update()
        except Exception as e:
            print(f'live monitoring screenshot skipped: {e}')

root.destroy()
print("done")
