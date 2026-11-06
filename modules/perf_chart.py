"""
纯 Tkinter Canvas 图表库（零依赖）

为什么不用 matplotlib
-------------------
- 引入 matplotlib 会让 exe 体积 +40MB，且团队里每个人 Python 环境不同
  （项目约定：不引入外部依赖，用标准库）
- 实测 Canvas 手绘 128 点折线 + 网格 + 标记 = **0.7ms**，完全够用

提供三种图：
- `LineChart`   折线（多序列，可叠加基线对比）
- `BarChart`    横向条形（线程占用 / 角色聚合）
- `Histogram`   直方图（帧时间分布）
"""
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


# 图表里用的颜色（跟随主题，由调用方注入）
class ChartPalette:
    """图表配色（来自 gui/theme.py 的令牌）"""

    def __init__(self, theme=None):
        if theme is not None:
            c = theme.color
            self.bg = c('bg_panel')
            self.grid = c('line_soft')
            self.axis = c('line')
            self.text = c('fg_muted')
            self.text_dim = c('fg_dim')
            self.accent = c('accent')
            self.series = [c('accent'), c('success'), c('warning'),
                           c('error'), c('purple'), c('fg_muted')]
            self.baseline = c('fg_dim')
            self.role_colors = {
                'render': c('accent'),
                'decode': c('purple'),
                'gc': c('warning'),
                'ipc': c('success'),
                'net': c('accent'),
                'pool': c('fg_muted'),
                'bg': c('fg_dim'),
                'sdk': c('warning'),
                'sys': c('fg_dim'),
                'other': c('fg_muted'),
                'ok': c('success'),
                'warn': c('warning'),
                'bad': c('error'),
            }
        else:
            self.bg = '#FFFFFF'
            self.grid = '#EDEFF3'
            self.axis = '#D8DDE5'
            self.text = '#5A6472'
            self.text_dim = '#8A94A3'
            self.accent = '#2563EB'
            self.series = ['#2563EB', '#0E9F6E', '#D97706',
                           '#DC2626', '#7C3AED', '#5A6472']
            self.baseline = '#8A94A3'
            self.role_colors = {k: self.series[i % len(self.series)]
                                for i, k in enumerate(
                                    ['render', 'decode', 'gc', 'ipc', 'net',
                                     'pool', 'bg', 'sdk', 'sys', 'other',
                                     'ok', 'warn', 'bad'])}


class ChartBase:
    """图表基类：负责画布、网格、坐标轴"""

    PAD_L = 46
    PAD_R = 16
    PAD_T = 24      # 顶部留出标签与图例的位置
    PAD_B = 26

    def __init__(self, parent, palette: ChartPalette, height: int = 220):
        self.palette = palette
        self.canvas = tk.Canvas(parent, height=height, bg=palette.bg,
                                 highlightthickness=1,
                                 highlightbackground=palette.grid)
        self._hover_cb: Optional[Callable] = None
        self._data: Dict[str, Any] = {}
        self.canvas.bind('<Configure>', lambda e: self.redraw())

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def grid(self, **kw):
        self.canvas.grid(**kw)
        return self

    def on_hover(self, cb: Optional[Callable]):
        self._hover_cb = cb
        self.canvas.bind('<Motion>', self._on_motion)
        self.canvas.bind('<Leave>', lambda e: self._on_motion(e, leave=True))

    def _on_motion(self, event, leave=False):
        if self._hover_cb:
            try:
                self._hover_cb(None if leave else self._hover_info(event))
            except Exception:
                pass

    def _hover_info(self, event) -> Optional[Dict[str, Any]]:
        return None

    def redraw(self):
        self.canvas.delete('all')
        self._draw()

    # ---------------------------------------------------------- 工具
    def _plot_area(self) -> Tuple[int, int, int, int]:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1:
            w = 560
        if h <= 1:
            h = 220
        return (self.PAD_L, self.PAD_T,
                w - self.PAD_L - self.PAD_R,
                h - self.PAD_T - self.PAD_B)

    def _draw_grid(self, x0, y0, w, h, y_ticks: int = 4):
        p = self.palette
        for i in range(y_ticks + 1):
            y = y0 + h * i / y_ticks
            self.canvas.create_line(x0, y, x0 + w, y, fill=p.grid, width=0.5)

    def _nice_max(self, value: float) -> float:
        """把上限取整成好看的刻度"""
        if value <= 0:
            return 1.0
        import math
        exp = math.floor(math.log10(value))
        base = 10 ** exp
        for mult in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
            if value <= base * mult:
                return base * mult
        return base * 10


class LineChart(ChartBase):
    """折线图（多序列 + 基线对比）"""

    def __init__(self, parent, palette: ChartPalette, height: int = 220):
        super().__init__(parent, palette, height)
        self.series: List[Dict[str, Any]] = []   # {name, points, color, dashed}
        self.baseline: Optional[Dict[str, Any]] = None
        self.y_label = ''
        self.x_label = ''
        # ⚠️ v5.4.10：**X 轴的时间标签**（用户反馈「连时间标示都没有」）
        #   {序号: 'HH:MM:SS'} —— 与 points 的 x（序号）对应
        self.x_labels: Dict[int, str] = {}
        # 单位（如 'MB' / '%' / 'fps'）—— 显示在 Y 轴刻度旁
        self.y_unit = ''
        # 空数据时的提示（区分「设备不支持」和「没采到」）
        self.empty_hint = ''
        self._hover_points: List[Tuple[float, Dict[str, Any]]] = []

    def set_series(self, series: List[Dict[str, Any]]):
        """series: [{'name': str, 'points': [(x, y), ...], 'color': str}]"""
        self.series = series
        self.redraw()

    def set_baseline(self, baseline: Optional[Dict[str, Any]]):
        self.baseline = baseline
        self.redraw()

    def _draw(self):
        c = self.canvas
        p = self.palette
        x0, y0, w, h = self._plot_area()

        all_pts = [pt for s in self.series for pt in s.get('points', [])]
        if self.baseline:
            all_pts += list(self.baseline.get('points', []))
        if not all_pts:
            # ⚠️ v5.4.10：**区分「为什么没数据**」——
            #    「设备不支持」和「没采到」对用户是完全不同的两件事。
            self._draw_empty(x0, y0, w, h)
            return

        xs = [pt[0] for pt in all_pts]
        ys = [pt[1] for pt in all_pts if pt[1] is not None]
        if not ys:
            self._draw_empty(x0, y0, w, h)
            return

        x_min, x_max = min(xs), max(xs)
        if x_max - x_min < 1e-9:
            x_max = x_min + 1
        y_min = min(0.0, min(ys))
        y_max = self._nice_max(max(ys))

        def px(x):
            return x0 + (x - x_min) / (x_max - x_min) * w

        def py(y):
            return y0 + h - (y - y_min) / (y_max - y_min) * h

        # 网格 + Y 轴刻度
        self._draw_grid(x0, y0, w, h, 4)
        for i in range(5):
            yv = y_min + (y_max - y_min) * i / 4
            yy = py(yv)
            # 顶部刻度下移 4px，避免与绘图区上方的标签撞在一起
            # ⚠️ v5.4.10：**带上单位**（原来只有裸数字 → 看不出是 MB 还是 %）
            _txt = f"{yv:.0f}"
            # ⚠️ v5.4.10：**单位只标在顶部刻度** ——
            #    原来 0 和 4 都标 → 左下角「0 %」与坐标轴文字撞在一起。
            #    单位在顶部更醒目（那里是最大值），且不与 X 轴标签打架。
            if self.y_unit and i == 4:
                _txt += f" {self.y_unit}"
            c.create_text(x0 - 6, yy + (4 if i == 0 else 0),
                          text=_txt, anchor='e',
                          fill=p.text_dim, font=('Microsoft YaHei UI', 8))
        # 坐标轴
        c.create_line(x0, y0, x0, y0 + h, fill=p.axis, width=1)
        c.create_line(x0, y0 + h, x0 + w, y0 + h, fill=p.axis, width=1)
        # 纵轴标题（放在绘图区**左上角内侧**）
        # ⚠️ v5.4.10：原来放在 y0-8（绘图区上方），会与顶部刻度标签、
        #    图例挤在一起 → 视觉重叠。移到左上角内侧更清爽。
        if self.y_label:
            # ⚠️ v5.4.10：下移 2px —— 原来贴得太紧，会与顶部刻度标签重叠
            c.create_text(x0 + 4, y0 + 5, text=self.y_label, anchor='nw',
                          fill=p.text_dim, font=('Microsoft YaHei UI', 8))

        # ── X 轴刻度（v5.4.10）──────────────────────────────
        # ⚠️ 用户反馈「连时间标示都没有」——原来 X 轴**完全空白**，
        #    只有一条横线，看不出每个点对应哪一刻。
        self._draw_x_axis(x0, y0, w, h, px, x_min, x_max)

        # 基线（虚线）
        if self.baseline and self.baseline.get('points'):
            bpts = [(x, y) for x, y in self.baseline['points'] if y is not None]
            if len(bpts) >= 2:
                c.create_line([v for pt in bpts for v in (px(pt[0]), py(pt[1]))],
                              fill=p.baseline, width=1.5, dash=(4, 3))

        # 主序列
        self._hover_points = []
        for idx, s in enumerate(self.series):
            pts = [(x, y) for x, y in s.get('points', []) if y is not None]
            if len(pts) >= 2:
                color = s.get('color') or p.series[idx % len(p.series)]
                c.create_line([v for pt in pts for v in (px(pt[0]), py(pt[1]))],
                              fill=color, width=2, smooth=True)
                # ⚠️ v5.4.10：**画数据点标记** ——
                #    光一条平滑曲线看不出「实际采样了多少个点」、
                #    「点之间是不是有跳变」。小圆点让采样点一目了然。
                #    点太多时（>60）会糊成一片 → 跳过。
                if len(pts) <= 60:
                    for x, y in pts:
                        c.create_oval(px(x) - 2, py(y) - 2,
                                       px(x) + 2, py(y) + 2,
                                       fill=color, outline=p.bg, width=1)
                for x, y in pts:
                    self._hover_points.append((px(x), {'name': s.get('name', ''),
                                                       'x': x, 'y': y}))
            # 图例（靠右排列，避免与左侧的纵轴标签重叠）
            color = s.get('color') or p.series[idx % len(p.series)]
            name = s.get('name', '')
            tw = len(name) * 6 + 22
            lx = x0 + w - (len(self.series) - idx) * tw
            c.create_line(lx, y0 - 8, lx + 14, y0 - 8, fill=color, width=2)
            c.create_text(lx + 19, y0 - 8, text=name, anchor='w',
                          fill=p.text, font=('Microsoft YaHei UI', 8))

    def _draw_x_axis(self, x0, y0, w, h, px, x_min, x_max):
        """画 X 轴刻度 + **时间标签**（v5.4.10）

        ⚠️ 用户反馈「连时间标示都没有」——
           原来 X 轴只有一条横线，完全看不出数据对应哪一刻。

        做法：
          - 最多 6 个刻度（多了会挤在一起）
          - 优先用 `x_labels`（{序号: 'HH:MM:SS'}）里的真实时间戳
          - 没有时间戳时退回序号（1、2、3…）
        """
        c = self.canvas
        p = self.palette
        span = x_max - x_min
        if span <= 0:
            return
        # 刻度数量：按宽度决定，最多 6 个
        n = max(2, min(6, int(w // 70) + 2))
        # 取整到"好看"的间隔
        raw = span / (n - 1)
        step = max(1, int(raw))
        # 从第一个有标签的点开始
        start = int(x_min)
        ticks = []
        v = start
        while v <= x_max and len(ticks) < n:
            ticks.append(v)
            v += step
        if not ticks:
            return

        for tv in ticks:
            tx = px(tv)
            if tx < x0 - 2 or tx > x0 + w + 2:
                continue
            # 刻度线（短竖线）
            c.create_line(tx, y0 + h, tx, y0 + h + 3, fill=p.axis, width=1)
            # 标签：有时间戳用时间戳，否则用序号
            lbl = self.x_labels.get(tv)
            if lbl is None:
                lbl = f"{int(tv) + 1}"
            # 首尾标签靠边对齐，避免超出画布
            anchor = 'center'
            if tx - x0 < 24:
                anchor = 'w'
            elif x0 + w - tx < 24:
                anchor = 'e'
            c.create_text(tx, y0 + h + 6, text=lbl, anchor=anchor,
                          fill=p.text_dim, font=('Microsoft YaHei UI', 7))

        # X 轴标题（右下角，不与刻度打架）
        if self.x_label:
            c.create_text(x0 + w, y0 + h + 16, text=self.x_label, anchor='e',
                          fill=p.text_dim, font=('Microsoft YaHei UI', 7))

    def _draw_empty(self, x0, y0, w, h):
        """画「没有数据」时的提示

        ⚠️ v5.4.10：**要说明原因** ——
           「设备不支持该指标」和「本次没采到数据」是完全不同的两件事，
           都写「暂无数据」会让用户以为是工具坏了。
        """
        c = self.canvas
        p = self.palette
        c.create_text(x0 + w / 2, y0 + h / 2 - 10,
                      text="暂无数据", fill=p.text_dim,
                      font=('Microsoft YaHei UI', 9))
        if self.empty_hint:
            c.create_text(x0 + w / 2, y0 + h / 2 + 8,
                          text=self.empty_hint, fill=p.text_dim,
                          font=('Microsoft YaHei UI', 8),
                          width=w - 20, justify='center')

    def _hover_info(self, event) -> Optional[Dict[str, Any]]:
        best = None
        best_d = 14
        for hx, info in self._hover_points:
            d = abs(event.x - hx)
            if d < best_d:
                best_d = d
                best = info
        return best


class BarChart(ChartBase):
    """横向条形图（线程占用 / 角色聚合）"""

    PAD_L = 128
    ROW_H = 22          # 每条的高度
    BAR_H = 14

    def __init__(self, parent, palette: ChartPalette, height: int = 220):
        super().__init__(parent, palette, height)
        self.items: List[Dict[str, Any]] = []   # {label, value, color, sub}

    def set_items(self, items: List[Dict[str, Any]]):
        self.items = items
        # 高度按条目数自适应，避免少量条目时留一大片空白
        want = max(60, len(items) * self.ROW_H + 30)
        self.canvas.configure(height=want)
        self.redraw()

    def _draw(self):
        c = self.canvas
        p = self.palette
        x0, y0, w, h = self._plot_area()
        if not self.items:
            c.create_text(x0 + w / 2, y0 + h / 2, text="暂无数据",
                          fill=p.text_dim, font=('Microsoft YaHei UI', 9))
            return

        vmax = self._nice_max(max((i['value'] for i in self.items), default=1))
        n = len(self.items)
        row_h = min(self.ROW_H, h / max(1, n))
        bar_h = min(self.BAR_H, row_h * 0.62)

        for i, it in enumerate(self.items):
            y = y0 + i * row_h
            color = it.get('color') or p.accent
            # 标签
            c.create_text(x0 - 8, y + bar_h / 2, text=str(it.get('label', ''))[:20],
                          anchor='e', fill=p.text,
                          font=('Microsoft YaHei UI', 8))
            # 轨道
            c.create_rectangle(x0, y, x0 + w, y + bar_h, outline=p.grid,
                               fill=p.bg, width=0.5)
            # 条
            bw = max(1.0, (it['value'] / vmax) * w) if vmax else 0
            if bw > 0:
                c.create_rectangle(x0, y, x0 + bw, y + bar_h,
                                   outline=color, fill=color, width=0)
            # 数值
            c.create_text(x0 + bw + 6 if bw + 30 < x0 + w else x0 + w - 4,
                          y + bar_h / 2,
                          text=f"{it['value']:.1f}%",
                          anchor='e' if bw + 30 >= x0 + w else 'w',
                          fill=p.text_dim, font=('Microsoft YaHei UI', 8))

        c.create_line(x0, y0, x0, y0 + h, fill=p.axis, width=1)


class Histogram(ChartBase):
    """直方图（帧时间分布）"""

    PAD_L = 46

    def __init__(self, parent, palette: ChartPalette, height: int = 220):
        super().__init__(parent, palette, height)
        self.buckets: List[Dict[str, Any]] = []
        self.markers: List[Dict[str, Any]] = []   # {value, label, color}

    def set_buckets(self, buckets: List[Dict[str, Any]],
                    markers: Optional[List[Dict[str, Any]]] = None):
        self.buckets = buckets
        self.markers = markers or []
        self.redraw()

    def _draw(self):
        c = self.canvas
        p = self.palette
        x0, y0, w, h = self._plot_area()
        if not self.buckets:
            c.create_text(x0 + w / 2, y0 + h / 2, text="暂无帧数据",
                          fill=p.text_dim, font=('Microsoft YaHei UI', 9))
            return

        vmax = self._nice_max(max(b['count'] for b in self.buckets))
        n = len(self.buckets)
        bw = w / max(1, n)

        self._draw_grid(x0, y0, w, h, 4)
        for i in range(5):
            yv = vmax * i / 4
            yy = y0 + h - (yv / vmax) * h if vmax else y0 + h
            c.create_text(x0 - 6, yy, text=f"{yv:.0f}", anchor='e',
                          fill=p.text_dim, font=('Microsoft YaHei UI', 8))

        for i, b in enumerate(self.buckets):
            bh = (b['count'] / vmax) * h if vmax else 0
            x = x0 + i * bw
            color = b.get('color') or p.accent
            if bh > 0:
                c.create_rectangle(x + 1, y0 + h - bh, x + bw - 1, y0 + h,
                                   outline=color, fill=color, width=0)
            c.create_text(x + bw / 2, y0 + h + 9, text=str(b.get('label', '')),
                          fill=p.text_dim, font=('Microsoft YaHei UI', 8))

        # 预算线（16.7ms / 33.3ms）
        for mk in self.markers:
            # mk: {'ratio': 0~1, 'label': str, 'color': str}
            rx = x0 + mk['ratio'] * w
            c.create_line(rx, y0, rx, y0 + h, fill=mk.get('color', p.axis),
                          width=1, dash=(3, 3))
            c.create_text(rx + 3, y0 + 2, text=mk.get('label', ''), anchor='nw',
                          fill=mk.get('color', p.text_dim),
                          font=('Microsoft YaHei UI', 8))

        c.create_line(x0, y0 + h, x0 + w, y0 + h, fill=p.axis, width=1)


def build_frame_buckets(durations: List[float],
                        edges: Sequence[float] = (8.3, 16.7, 20, 33.3, 50, 100)) -> List[Dict[str, Any]]:
    """把帧耗时列表分桶

    Returns:
        [{'label': '<8.3', 'count': n, 'lower': lo, 'upper': hi}]
    """
    if not durations:
        return []
    bounds = [0.0] + list(edges) + [float('inf')]
    out = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        cnt = sum(1 for d in durations if lo <= d < hi)
        if hi == float('inf'):
            label = f'>{int(lo)}'
        else:
            label = f'{lo:g}-{hi:g}'
        out.append({'label': label, 'count': cnt, 'lower': lo, 'upper': hi})
    return out
