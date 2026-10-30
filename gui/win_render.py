"""
Windows 渲染优化 —— 让字体锐利、不发虚

为什么需要这个
--------------
Tkinter 在 Windows 上有两个「字发虚」的常见原因：

1. **进程没有声明 DPI 感知**（最主要）
   系统缩放 125%/150% 时，DPI-unaware 进程会被 Windows 用**位图拉伸**
   放大整个窗口 —— 文字是插值出来的，必然模糊发虚。
   必须在创建 Tk 根窗口**之前**调用 `SetProcessDpiAwareness`，
   而且要用 Per-Monitor V2（`SetProcessDpiAwarenessContext`）才跟得上
   用户拖到不同缩放比的显示器。

2. **字体用了「点」(point) 而不是「像素」(pixel)**
   Tk 里字号为负数表示像素，为正数表示点。点会跟随 DPI 缩放，
   在非整数缩放比下（如 125%、150%）会被舍入到不同的像素高度，
   小字号（8~9pt）容易出现字形被压扁或截断。
   用像素（负数）能让字形高度稳定、栅格化更规整。

3. **ClearType 抗锯齿被关掉**
   部分 Windows 环境下 Tk 的字体渲染不走 ClearType。

用法：在创建 root 之前调用 `enable_dpi_awareness()`，它幂等且静默失败。
"""
import ctypes
import sys


def enable_dpi_awareness():
    """声明进程 DPI 感知（Per-Monitor V2）

    ⚠️ 必须在创建 Tk 根窗口**之前**调用，否则设置不生效。
    失败不影响功能，只是字体会略糊一点 —— 所以全程 try/except 静默。
    """
    if sys.platform != 'win32':
        return False

    try:
        # Windows 10 1703+：Per-Monitor V2（最完整：窗口、字体、非客户区全部感知）
        try:
            fn = ctypes.windll.user32.SetProcessDpiAwarenessContext
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            fn.restype = ctypes.c_bool
            fn.argtypes = [ctypes.c_void_p]
            if fn(ctypes.c_void_p(-4)):
                return True
        except (AttributeError, OSError):
            pass

        # Windows 8.1+：Per-Monitor
        try:
            fn = ctypes.windll.shcore.SetProcessDpiAwareness(2)
            if fn == 0:
                return True
        except (AttributeError, OSError):
            pass

        # Vista+：System DPI aware（兜底）
        try:
            if ctypes.windll.user32.SetProcessDPIAware():
                return True
        except (AttributeError, OSError):
            pass
    except Exception:
        pass

    return False


def enable_clear_type():
    """尝试为进程启用 ClearType 字体抗锯齿

    Tk 通过 GDI 渲染字体，ClearType 是否生效由系统的
    「字体平滑」设置决定。这里尽力开启，失败无所谓。
    """
    if sys.platform != 'win32':
        return False
    try:
        # SPI_SETFONTSMOOTHING = 0x004A
        ctypes.windll.user32.SystemParametersInfoW(0x004A, 0, 1, 0)
        # SPI_SETFONTSMOOTHINGTYPE = 0x200A, FE_DONTCARE = 0
        ctypes.windll.user32.SystemParametersInfoW(0x200A, 0, 0, 0)
        return True
    except Exception:
        return False
