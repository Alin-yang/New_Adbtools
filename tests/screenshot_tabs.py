"""启动应用并截图各 Tab，用于布局核对（纯辅助脚本，不参与打包）

用法: python tests/screenshot_tabs.py [输出目录]
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
from gui import layout_modern as layout

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shots')
os.makedirs(OUT_DIR, exist_ok=True)

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

    # DIB 是 BGRA，转成 RGBA 并把 alpha 置 255（否则 PNG 透明/反相）
    src = buf.raw
    out = bytearray(w * h * 4)
    for i in range(0, w * h * 4, 4):
        out[i] = src[i + 2]      # R
        out[i + 1] = src[i + 1]  # G
        out[i + 2] = src[i]      # B
        out[i + 3] = 255         # A
    raw = b''.join(b'\x00' + bytes(out[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6))
           + chunk(b'IEND', b''))
    path = os.path.join(OUT_DIR, filename)
    with open(path, 'wb') as f:
        f.write(png)
    print("saved:", path, f"{w}x{h}")


TABS = [
    ('device', '设备管理'),
    ('app', '应用管理'),
    ('log_screen', '日志录屏'),
    ('mirror', '投屏'),
    ('performance', '性能监控'),
    ('script_runner', '脚本运行'),
    ('advanced', '高级工具'),
]

lay = getattr(app, 'layout_instance', None)
print("布局实例:", lay)

state = {'i': 0}


def step():
    if state['i'] >= len(TABS):
        root.destroy()
        return
    key, name = TABS[state['i']]
    if lay and key in lay.tab_buttons:
        lay.tab_buttons[key].invoke()
    root.update()
    root.update_idletasks()
    time.sleep(0.3)
    root.update()
    grab(f"{key}.png")
    state['i'] += 1
    root.after(120, step)


root.after(400, step)
root.mainloop()
