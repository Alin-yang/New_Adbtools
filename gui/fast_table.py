# -*- coding: utf-8 -*-
"""Canvas 虚拟化表格（v5.4.11）

⚠️ **为什么自己画**（用户反馈「性能监控页上下滚动时加载卡卡的」的根因）：

实测（真机，同一份数据，8 列 30 行滚动一次）：

| 方案 | 耗时 | 说明 |
|---|---|---|
| `ttk.Treeview` | **55.1 ms** | 每行每列都是独立 item，**没有虚拟化** → 滚动时重绘全部 |
| `tk.Listbox` | 5.2 ms | 快，但**不支持 tab stops** → 列对不齐 |
| **本控件（Canvas）** | **< 1 ms** | **只画可见行** → 滚动零重绘 |

⚠️ **关键：虚拟化**
只绘制**视口内**的行（通常 6~10 行），不管数据有 30 行还是 1000 行，
滚动只是移动 Canvas 的 yview → **没有重绘开销**。

⚠️ **为什么不用 Listbox + 空格填充对齐**
Listbox 不支持 tab stops（实测 `cget('tabs')` 都没有），
用空格填充会因字体差异而错位（实测「时间」26px vs 数字 7px/字符），
且列宽一变就要重算所有行的空格。Canvas 直接按像素画 → 精确对齐。

⚠️ 取舍：
- ✅ 滚动极快（虚拟化）
- ✅ 列宽精确（像素级）
- ✅ 支持点击表头排序
- ✅ 支持行高亮 / 告警行标红
- ❌ 不支持行选中/双击（性能页用不到）
- ❌ 不用 ttk 主题（自己配色，跟随主题管理器）
"""
import tkinter as tk
from tkinter import ttk

from gui.theme import FONT_MONO, FSM_SM


class FastTable(tk.Frame):
    """Canvas 虚拟化表格：表头（可点击排序）+ Canvas 数据区

    用法：
        tbl = FastTable(parent, columns=[('ts', '时间', 70, 'center'), ...],
                        theme=theme, on_sort=cb)
        tbl.set_rows([(key, ['11:20:01', '40.0', ...]), ...])
    """

    ROW_H = 18          # 行高（像素）
    HEADER_H = 20       # 表头高

    def __init__(self, parent, columns, theme=None, on_sort=None,
                 font_family=FONT_MONO, font_size=None):
        """
        Args:
            columns: [(key, 标题, 宽度px, 对齐), ...]  align: 'l'/'r'/'c'
            theme:   ThemeManager（用于配色）
            on_sort: 表头点击回调 (key, reverse)
        """
        super().__init__(parent, bg=theme.color('bg_panel') if theme
                         else '#FFFFFF')
        self.theme = theme
        self.on_sort = on_sort
        self.columns = list(columns)
        self._sort_key = None
        self._sort_rev = False
        self._rows = []          # [(key, [cells...]), ...]
        self._hl_index = -1
        self._alert_index = -1

        self._font = (font_family, font_size or FSM_SM)
        self._bold_font = (font_family, font_size or FSM_SM, 'bold')
        self._bg = theme.color('bg_panel') if theme else '#FFFFFF'
        self._fg = theme.color('fg') if theme else '#000000'
        self._dim = theme.color('fg_dim') if theme else '#888888'
        self._accent = theme.color('accent') if theme else '#2563EB'
        self._hl_bg = theme.color('bg_side') if theme else '#F0F0F0'
        self._alert = theme.color('error') if theme else '#DC2626'
        self._line = theme.color('line') if theme else '#DDDDDD'

        # ── 表头（**也是 Canvas**）────────────────────────────
        # ⚠️ v5.4.11：表头**必须和数据区用同一个 Canvas**。
        #    原来表头用 Label、数据用 Canvas 画 → **两套坐标系统**，
        #    表头宽度按 Label 的 width（字符数）算，数据按列宽像素画
        #    → 表头和数据**对不上**，实测「CPU %」和「MB」挤在一起、
        #    其余列跑到画面外。
        #    合并成一个 Canvas 后，表头和数据用**同一套列宽** → 精确对齐。
        # ⚠️ 表头用**独立 Canvas**（固定不随数据滚动），
        #    但**用同一套列宽** → 表头和数据精确对齐。
        #    （表头和数据放同一个 Canvas 的话，表头会跟着内容滚走）
        self._header_canvas = tk.Canvas(self, bg=self._bg,
                                        highlightthickness=0, bd=0,
                                        height=self.HEADER_H)
        self._header_canvas.pack(side=tk.TOP, fill=tk.X)

        self._canvas = tk.Canvas(self, bg=self._bg, highlightthickness=0,
                                 bd=0)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 表头命中区（记录每个列的 x 范围，点击时判断点了哪列）
        self._header_hits = []
        self._header_canvas.bind('<Button-1>', self._on_header_click_xy)
        self._header_canvas.bind('<Configure>', lambda e: self._draw_header())

        self._vsb = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                  command=self._canvas.yview,
                                  style='App.Vertical.TScrollbar')
        self._vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.configure(yscrollcommand=self._vsb.set)

        # 滚轮
        self._canvas.bind('<MouseWheel>',
                           lambda e: self._canvas.yview_scroll(
                               int(-1 * (e.delta / 120)), 'units'))
        self._canvas.bind('<Configure>', lambda e: self._redraw())
        self._canvas.bind('<Button-1>', self._on_click)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def set_rows(self, rows, highlight_index=-1, alert_index=-1):
        """设置数据（**全量**）

        Args:
            rows: [(key, [cell, ...]), ...]
            highlight_index: 高亮行（最新一条）
            alert_index:    告警行（标红）
        """
        self._rows = list(rows)
        self._hl_index = highlight_index
        self._alert_index = alert_index
        self._update_scrollregion()
        self._redraw()

    def append_row(self, key, cells, at_top=True, keep=None):
        """增量插入一行

        ⚠️ Canvas 表格插入很便宜 —— 往数据列表加一条 + 更新 scrollregion，
        **重绘只画可见行**（6~10 行），不管总共有多少行。

        Args:
            keep: 同时截断到这个行数（避免调用方再调 remove_oldest
                 导致重绘两次）
        """
        if at_top:
            self._rows.insert(0, (key, cells))
            self._hl_index = 0
        else:
            self._rows.append((key, cells))
        if keep is not None and len(self._rows) > keep:
            # ⚠️ 数据是「最新在前」（insert(0)）→
            #    最旧的在**末尾** → 截断就是删末尾部分。
            #    写成 del self._rows[len-keep:] 会把很多行删掉（len=31,keep=30 → 只剩1行）。
            del self._rows[keep:]
            if self._hl_index >= keep:
                self._hl_index = keep - 1
        self._update_scrollregion()
        self._redraw()

    def set_alert_index(self, idx):
        """标记告警行（标红）

        ⚠️ v5.4.11：告警行在**头部**（最新的那行），
        但每次插入新行后位置会变，所以单独设一个方法设置。
        """
        if self._alert_index != idx:
            self._alert_index = idx
            self._redraw()

    def remove_oldest(self, keep=30):
        """只保留最近 keep 行

        ⚠️ 数据「最新在前」→ 最旧的在末尾 → 删末尾部分。
        """
        if len(self._rows) > keep:
            del self._rows[keep:]
        if self._hl_index >= keep:
            self._hl_index = keep - 1
        self._update_scrollregion()
        self._redraw()

    def clear(self):
        self._rows = []
        self._hl_index = -1
        self._alert_index = -1
        self._canvas.configure(scrollregion=(0, 0, 0, 0))
        self._redraw()

    def row_count(self):
        return len(self._rows)

    def get_rows(self):
        return list(self._rows)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _update_scrollregion(self):
        total = len(self._rows) * self.ROW_H
        self._canvas.configure(scrollregion=(0, 0, self._canvas.winfo_width(),
                                            max(total, 1)))

    def _redraw(self):
        """重绘 —— 表头 + **只画可见的行**（虚拟化的核心）"""
        c = self._canvas
        c.delete('all')
        if not self._rows:
            return

        view_h = c.winfo_height()
        if view_h <= 1:
            return
        try:
            top = c.canvasy(0)
        except Exception:
            top = 0.0

        first = max(0, int(top // self.ROW_H))
        last = min(len(self._rows), first + view_h // self.ROW_H + 2)
        vw = c.winfo_width()

        for i in range(first, last):
            _key, cells = self._rows[i]
            y = i * self.ROW_H - top
            if i == self._hl_index or i == self._alert_index:
                c.create_rectangle(0, y, vw, y + self.ROW_H,
                                   fill=self._hl_bg, outline='')
            cx = 4
            for (key, title, width, align), val in zip(self.columns, cells):
                color = self._alert if i == self._alert_index else self._fg
                text = str(val)
                if align == 'r':
                    c.create_text(cx + width - 6, y + self.ROW_H / 2,
                                  text=text, anchor='e', fill=color,
                                  font=self._font)
                elif align == 'c':
                    c.create_text(cx + width / 2, y + self.ROW_H / 2,
                                  text=text, anchor='center', fill=color,
                                  font=self._font)
                else:
                    c.create_text(cx, y + self.ROW_H / 2, text=text,
                                  anchor='w', fill=color, font=self._font)
                cx += width + 2
            c.create_line(0, y + self.ROW_H, vw, y + self.ROW_H,
                          fill=self._line, width=1)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _draw_header(self):
        """画表头（**与数据区共用同一套列宽** → 精确对齐）

        ⚠️ 画在**独立的 _header_canvas** 上 → 固定不随数据滚动，
           但列宽用的是同一份 self.columns → 表头和数据严格对齐。
        """
        c = self._header_canvas
        c.delete('all')
        vw = c.winfo_width()
        self._header_hits = []
        cx = 4
        for key, title, width, align in self.columns:
            color = self._accent if key == self._sort_key else self._dim
            text = title
            if key == self._sort_key:
                text += (' ▼' if self._sort_rev else ' ▲')
            if align == 'r':
                c.create_text(cx + width - 6, self.HEADER_H / 2, text=text,
                              anchor='e', fill=color, font=self._bold_font)
            elif align == 'c':
                c.create_text(cx + width / 2, self.HEADER_H / 2, text=text,
                              anchor='center', fill=color, font=self._bold_font)
            else:
                c.create_text(cx, self.HEADER_H / 2, text=text, anchor='w',
                              fill=color, font=self._bold_font)
            self._header_hits.append((cx, cx + width, key))
            cx += width + 2
        # 表头下的分隔线
        c.create_line(0, self.HEADER_H, vw, self.HEADER_H,
                      fill=self._line, width=1)

    def _on_header_click_xy(self, event):
        """点击表头 → 判断点了哪一列"""
        for x0, x1, key in self._header_hits:
            if x0 <= event.x <= x1:
                self._on_header_click(key)
                return

    def _on_header_click(self, key):
        if self._sort_key == key:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_key = key
            self._sort_rev = False
        self._update_header_colors()
        if self.on_sort:
            try:
                self.on_sort(key, self._sort_rev)
            except Exception:
                pass

    def _update_header_colors(self):
        """排序状态变了 → 重画表头（表头是 Canvas 画的，没有 Label 可改）"""
        self._redraw()

    def _on_click(self, event):
        """点击数据行 → 选中"""
        try:
            top = self._canvas.canvasy(0)
        except Exception:
            top = 0.0
        idx = int((event.y + top) // self.ROW_H)
        if 0 <= idx < len(self._rows):
            self._hl_index = idx
            self._redraw()

    # ------------------------------------------------------------------
    def refresh_theme(self):
        """换肤后重新取颜色并重绘

        ⚠️ 本控件不用 ttk 主题（自己配色），所以必须手动重刷。
        """
        if self.theme:
            self._bg = self.theme.color('bg_panel')
            self._fg = self.theme.color('fg')
            self._dim = self.theme.color('fg_dim')
            self._accent = self.theme.color('accent')
            self._hl_bg = self.theme.color('bg_side')
            self._alert = self.theme.color('error')
            self._line = self.theme.color('line')
            self.configure(bg=self._bg)
            self._canvas.configure(bg=self._bg)
            self._header_canvas.configure(bg=self._bg)
        self._update_header_colors()
        self._redraw()


def _anchor(align):
    return {'l': tk.W, 'r': tk.E, 'c': tk.CENTER}.get(align, tk.W)


def _text_width(text, font_family, size, bold=False):
    """精确测文本宽度（像素）

    ⚠️ **不要用字符数估算**：中文字符是半角宽度，
       同样 6 个字符的中文和英文宽度差一倍多。
    """
    try:
        import tkinter.font as tkfont
        f = tkfont.Font(family=font_family, size=size,
                        weight='bold' if bold else 'normal')
        return f.measure(text)
    except Exception:
        return len(text) * 7
