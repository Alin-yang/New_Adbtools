"""设备切换浮层截图（开发辅助）

用法: python tests/shot_device_picker.py [输出目录]
"""
import sys, os, ctypes, ctypes.wintypes, time

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

root.geometry('1200x680+60+40')
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
    mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mfc_dc, bmp)
    gdi32.BitBlt(mfc_dc, 0, 0, w, h, hwnd_dc, 0, 0, 0x00CC0020)

    class BITMAPINFOHEADER(ctypes.Structure):
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

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mfc_dc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mfc_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    import struct, zlib
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
    path = os.path.join(OUT_DIR, filename)
    with open(path, 'wb') as f:
        f.write(png)
    print("saved:", path, w, 'x', h)


def pump(n=8):
    for _ in range(n):
        root.update_idletasks()
        root.update()
        time.sleep(0.03)


# 模拟多设备场景
app.ip_history = ['192.168.0.3', '192.168.0.8', '192.168.1.7', '192.168.1.20',
                  '192.168.2.3', '192.168.2.44', '192.168.3.9', '10.1.246.77']
app.get_online_devices = lambda: ['10.1.246.185:5555', '192.168.1.99:5555']
# 当前目标 = 第一台在线设备（带端口，与真实情况一致）
app.ip_combobox.set('10.1.246.185:5555')
app.update_connection_status(ip_address='10.1.246.185',
                             devices=['10.1.246.185:5555', '192.168.1.99:5555'])
pump()

app.layout_instance._toggle_device_picker()
pump(12)
grab('picker_dark.png')

# 浅色主题
app._ui_theme.set_theme('light')
pump(12)
grab('picker_light.png')

root.destroy()
