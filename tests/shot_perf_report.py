# -*- coding: utf-8 -*-
"""截性能报告窗口（开发辅助）—— 造模拟数据，能看到时间轴效果

用法: python tests/shot_perf_report.py [输出文件名]
"""
import sys
import os
import time
import ctypes
import ctypes.wintypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import tkinter as tk

from modules.perf_report import PerfReportWindow


def _grab(window, path):
    """用 GDI 抓窗口（与 shot_full.py 同一套逻辑）"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    gdi32.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.wintypes.DWORD),
                    ("biWidth", ctypes.wintypes.LONG),
                    ("biHeight", ctypes.wintypes.LONG),
                    ("biPlanes", ctypes.wintypes.WORD),
                    ("biBitCount", ctypes.wintypes.WORD),
                    ("biCompression", ctypes.wintypes.DWORD),
                    ("biSizeImage", ctypes.wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.wintypes.LONG),
                    ("biYPelsPerMeter", ctypes.wintypes.LONG),
                    ("biClrUsed", ctypes.wintypes.DWORD),
                    ("biClrImportant", ctypes.wintypes.DWORD)]

    bi = BIH()
    bi.biSize = ctypes.sizeof(BIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)

    import struct
    import zlib
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        row = buf[y * w * 4:(y + 1) * w * 4]
        for x in range(w):
            b_, g_, r_ = row[x * 4], row[x * 4 + 1], row[x * 4 + 2]
            raw += bytes((r_, g_, b_))

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw), 6))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)
    print('saved:', path, w, 'x', h)


def _make_session():
    """造一份带时间戳的模拟 session"""
    history = []
    base_t = time.time() - 20 * 60
    for i in range(24):
        ts = time.strftime('%H:%M:%S', time.localtime(base_t + i * 50))
        wave = (i % 6) * 4 + 30
        history.append({
            'ts': ts,
            'cpu': 35.0 + wave * 0.8 + (i % 3) * 2.1,
            'pss': 58.0 + wave * 0.35,
            'rss': 92.0 + wave * 0.4,
            'java': 31.5 + wave * 0.12,
            'native': 21.8 + wave * 0.08,
            'fps': 58.4 - (i % 4) * 0.7,
            'jank': 1.2 + (i % 5) * 0.4,
        })

    def agg(vals):
        return {'cur': vals[-1], 'avg': sum(vals) / len(vals),
                'peak': max(vals), 'p95': sorted(vals)[int(len(vals) * 0.95)],
                'p05': sorted(vals)[int(len(vals) * 0.05)]}

    cpu = [h['cpu'] for h in history]
    pss = [h['pss'] for h in history]
    java = [h['java'] for h in history]
    native = [h['native'] for h in history]
    fps = [h['fps'] for h in history]
    jank = [h['jank'] for h in history]

    return {
        'package': 'com.konka.livelauncher',
        'pid': 23681,
        'stats': {
            'cpu': agg(cpu), 'pss': agg(pss), 'rss': agg([h['rss'] for h in history]),
            'java': agg(java), 'native': agg(native),
            'fps': agg(fps), 'jank': agg(jank),
            'p95_frame': agg([16.0]), 'p99_frame': agg([22.0]),
            'threads': [], 'thread_sum': 0.0, 'sample_count': len(history),
            'elapsed': 1200.0, 'mode': 'proc',
        },
        'history': history,
        'frame_samples': [],
        'conclusions': [],
    }


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'perf_report.png'
    path = os.path.join(_ROOT, 'tests', '_shots_v4', out)

    # ⚠️ 用**真实 app**（而不是 mock）—— 报告窗口依赖 app._ui_theme，
    #    mock 出来的 FakeApp 缺主题 → 颜色名解析失败。
    from app import ADBToolApp
    from gui import layout_v4 as layout

    root = tk.Tk()
    app = ADBToolApp(root, layout)
    for _ in range(4):
        root.update_idletasks()
        root.update()

    win = PerfReportWindow(app, _make_session(), None)
    # ⚠️ PerfReportWindow 是包装类，真正的 Toplevel 是 win.win
    win.win.geometry('1180x760+40+40')
    win.win.update()
    win.win.update_idletasks()
    for _ in range(10):
        win.win.update()
        time.sleep(0.03)

    for _ in range(6):
        win.win.update()
        time.sleep(0.03)

    _grab(win.win, path)
    win.win.destroy()
    root.destroy()


if __name__ == '__main__':
    main()
