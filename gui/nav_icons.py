"""侧边栏导航图标（纯 Canvas 手绘矢量图标）

⚠️ 为什么不用 Unicode 符号（⇩ ⚕ ⌘ ◔ ▣）：
   这些字符在「微软雅黑 UI」里**字形缺失或严重变形** ——
   实测 `⌘` 渲染成一个糊成一团的小方块，`◔` 变成半个糊圈，
   用户反馈「表情符号感觉不清晰也不好看」。
   而且 `⌘` 被「设备控制」和「脚本执行」同时复用，两个图标一模一样，
   完全无法区分。

   Unicode 符号区（U+2xxx / U+25xx）本来就是「几何图形」，
   不是给字体渲染用的 —— 依赖它做 UI 图标在任何字体环境下都不可靠。

✅ 这里的做法：用 Canvas 画线条/圆弧/矩形组成图标。
   - 像素级可控，任何机器上渲染结果一致
   - 颜色跟随主题（主题切换时重画）
   - 语义明确：下载=箭头入盒、诊断=放大镜、性能=折线图……
"""
import tkinter as tk

# 图标画布尺寸（px）
ICON_SIZE = 16
# 图标线条宽度
ICON_LINE = 1.6


def draw_icon(canvas, kind, color, size=ICON_SIZE, line=ICON_LINE):
    """在 canvas 上绘制一个图标

    Args:
        canvas: 目标 tk.Canvas
        kind:   图标类型（见下方 ICON_KINDS）
        color:  线条颜色
        size:   画布边长
        line:   线宽
    """
    c = size / 2.0
    r = size * 0.32          # 基础半径
    tag = f'icon_{kind}'

    def ln(x1, y1, x2, y2, width=None, cap='round'):
        canvas.create_line(x1, y1, x2, y2, fill=color,
                           width=width or line, capstyle=cap,
                           smooth=False, tags=(tag,))

    def rect(x1, y1, x2, y2, width=None, fill=''):
        canvas.create_rectangle(x1, y1, x2, y2, outline=color,
                                width=width or line, fill=fill,
                                tags=(tag,))

    def oval(x1, y1, x2, y2, width=None, fill=''):
        canvas.create_oval(x1, y1, x2, y2, outline=color,
                           width=width or line, fill=fill,
                           tags=(tag,))

    def arc(x1, y1, x2, y2, start, extent, width=None, style='arc'):
        canvas.create_arc(x1, y1, x2, y2, start=start, extent=extent,
                          style=style, outline=color,
                          width=width or line, tags=(tag,))

    def poly(points, width=None, fill=''):
        canvas.create_line(*points, fill=color, width=width or line,
                           capstyle='round', joinstyle='round',
                           smooth=False, tags=(tag,))
        if fill:
            canvas.create_polygon(*points, fill=fill, outline='',
                                  tags=(tag,))

    if kind == 'install':
        # 下载：向下箭头 + 底部托盘
        ln(c, size * 0.18, size * 0.16, c, size * 0.55)
        poly([c - size * 0.14, size * 0.42,
              c, size * 0.58,
              c + size * 0.14, size * 0.42])
        ln(size * 0.22, size * 0.78, size * 0.78, size * 0.78)

    elif kind == 'diagnose':
        # 诊断：放大镜
        oval(size * 0.14, size * 0.14, size * 0.66, size * 0.66)
        ln(size * 0.62, size * 0.62, size * 0.84, size * 0.84, width=line * 1.3)

    elif kind == 'device':
        # 设备控制：手机（圆角矩形 + 底部横线）
        rect(size * 0.30, size * 0.10, size * 0.70, size * 0.86,
             width=line, fill='')
        ln(size * 0.44, size * 0.72, size * 0.56, size * 0.72)

    elif kind == 'perf':
        # 性能监控：折线图 + 坐标轴
        ln(size * 0.16, size * 0.16, size * 0.16, size * 0.80)
        ln(size * 0.16, size * 0.80, size * 0.86, size * 0.80)
        poly([size * 0.28, size * 0.62,
              size * 0.44, size * 0.34,
              size * 0.58, size * 0.52,
              size * 0.80, size * 0.24])

    elif kind == 'mirror':
        # 投屏控制：屏幕（矩形 + 底部支架）
        rect(size * 0.14, size * 0.18, size * 0.86, size * 0.64)
        ln(size * 0.50, size * 0.64, size * 0.50, size * 0.82)
        ln(size * 0.30, size * 0.84, size * 0.70, size * 0.84)

    elif kind == 'script':
        # 脚本执行：终端窗口（矩形 + 提示符 >_）
        rect(size * 0.12, size * 0.20, size * 0.88, size * 0.80)
        poly([size * 0.28, size * 0.38, size * 0.42, size * 0.50,
              size * 0.28, size * 0.62])
        ln(size * 0.50, size * 0.64, size * 0.70, size * 0.64)

    else:
        # 兜底：小圆点
        oval(c - r / 2, c - r / 2, c + r / 2, c + r / 2, fill=color)


# 图标类型 → 语义说明（供悬停提示用）
ICON_HINTS = {
    'install':  '选择 APK 并安装到设备',
    'diagnose': '诊断设备连接与安装问题',
    'device':   '设备信息与应用管理',
    'perf':     '采集 CPU / 内存 / 帧率',
    'mirror':   'scrcpy 低延迟投屏',
    'script':   '推送并执行 Shell 脚本',
}
