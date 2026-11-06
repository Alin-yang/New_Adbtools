"""错误分析结果窗口（v5.4.8）

展示 `modules/log_analyzer.py` 的聚类结果：
  - 顶部摘要：共几类错误 / 几次 / 各类占比
  - 主体：Top N 错误列表（按频次降序），展开看栈帧
  - 底部：导出报告 / 复制

⚠️ 设计要点：
  - **按频次排序**是核心 —— 用户要的是「哪个错误最频繁」，
    不是按时间顺序翻日志
  - 每类可展开看**归一化后的栈帧**（行号已抹掉，所以两次崩溃显示一样）
  - 主题感知（深/浅两套）
"""
import os
import tkinter as tk
from tkinter import ttk

from gui.theme import FONT_UI, FONT_MONO, FS_XS, FS_SM, FS_MD, FSM_SM

# 各类故障的中文名
_KIND_NAMES = {
    'java': 'Java 异常',
    'fatal': '致命崩溃',
    'native': 'native 崩溃',
    'anr': 'ANR 卡死',
    'died': '进程死亡',
    'error': '普通错误',
}

# 各类故障的颜色键
_KIND_COLORS = {
    'java': 'error',
    'fatal': 'error',
    'native': 'error',
    'anr': 'warning',
    'died': 'warning',
    'error': 'fg_dim',
}


class LogAnalysisWindow:
    """错误分析结果窗口"""

    def __init__(self, app, report):
        self.app = app
        self.report = report
        self.theme = app._ui_theme

        self.win = tk.Toplevel(app.root)
        self.win.title("错误分析")
        self.win.geometry("880x620")
        self.win.transient(app.root)
        self.win.minsize(720, 460)

        self._build()
        self._center()

    # ------------------------------------------------------------------
    def _t(self, key, default=''):
        return self.theme.color(key)

    def _center(self):
        """在主窗口居中"""
        try:
            self.win.update_idletasks()
            w = self.win.winfo_width()
            h = self.win.winfo_height()
            x = self.app.root.winfo_rootx() + (self.app.root.winfo_width() - w) // 2
            y = self.app.root.winfo_rooty() + (self.app.root.winfo_height() - h) // 2
            self.win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _build(self):
        bg = self._t('bg_app')
        panel = self._t('bg_panel')

        # ── 摘要卡片 ─────────────────────────────────────────
        rep = self.report
        head = tk.Frame(self.win, bg=panel)
        head.pack(fill=tk.X, padx=14, pady=(12, 8))

        tk.Label(
            head, text=rep.get('summary', ''),
            font=(FONT_UI, FS_MD, 'bold'), bg=panel, fg=self._t('fg'),
            anchor=tk.W, justify=tk.LEFT,
        ).pack(fill=tk.X)

        # 各类故障的数量
        kc = rep.get('kind_counts', {})
        if kc:
            row = tk.Frame(head, bg=panel)
            row.pack(fill=tk.X, pady=(6, 0))
            for kind, cnt in sorted(kc.items(), key=lambda kv: -kv[1]):
                tk.Label(
                    row, text=f"{_KIND_NAMES.get(kind, kind)} {cnt}",
                    font=(FONT_UI, FS_SM), bg=panel,
                    fg=self._t(_KIND_COLORS.get(kind, 'fg_dim')),
                    padx=8,
                ).pack(side=tk.LEFT)

        # ── 错误列表 ─────────────────────────────────────────
        wrap = tk.Frame(self.win, bg=bg)
        wrap.pack(fill=tk.BOTH, expand=True, padx=14)

        canvas = tk.Canvas(wrap, bg=bg, highlightthickness=0, bd=0)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=canvas.yview,
                            style='App.Vertical.TScrollbar')
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=sb.set)

        inner = tk.Frame(canvas, bg=bg)
        win_id = canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        inner.bind('<Configure>',
                   lambda e, cv=canvas, wid=win_id: cv.configure(
                       scrollregion=cv.bbox('all'),
                       width=cv.winfo_width()))
        canvas.bind('<Configure>',
                    lambda e, cv=canvas, wid=win_id: cv.itemconfigure(
                        wid, width=cv.winfo_width()))

        clusters = rep.get('clusters', [])
        if not clusters:
            tk.Label(inner, text="未发现错误", font=(FONT_UI, FS_MD),
                     bg=bg, fg=self._t('fg_dim')).pack(pady=20)
        for c in clusters:
            self._build_row(inner, c)

        # ── 底部按钮 ─────────────────────────────────────────
        foot = tk.Frame(self.win, bg=bg)
        foot.pack(fill=tk.X, padx=14, pady=(8, 12))

        ttk.Button(foot, text="导出分析报告", style='Primary.TButton',
                   command=self._export_report).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(foot, text="复制摘要", style='Secondary.TButton',
                   command=self._copy_summary).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(foot, text="关闭", style='Secondary.TButton',
                   command=self.win.destroy).pack(side=tk.RIGHT)

        self.status = tk.Label(foot, text="", font=(FONT_UI, FS_SM),
                               bg=bg, fg=self._t('fg_dim'))
        self.status.pack(side=tk.RIGHT, padx=(0, 12))

    # ------------------------------------------------------------------
    def _build_row(self, parent, c):
        """一条聚类结果"""
        bg = self._t('bg_app')
        panel = self._t('bg_panel')

        row = tk.Frame(parent, bg=panel)
        row.pack(fill=tk.X, pady=(0, 6))
        self.theme.register(row, 'panel')

        # 左侧色条：按故障类型着色
        color = self._t(_KIND_COLORS.get(c.get('kind', ''), 'fg_dim'))
        stripe = tk.Frame(row, bg=color, width=4)
        stripe.pack(side=tk.LEFT, fill=tk.Y)
        self.theme.register(stripe, 'panel')

        body = tk.Frame(row, bg=panel)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 8), pady=8)
        self.theme.register(body, 'panel')

        # 频次徽标（越大越靠前，越显眼）
        cnt = c.get('count', 1)
        badge = tk.Label(body, text=f"× {cnt}", font=(FONT_MONO, FSM_SM, 'bold'),
                         bg=color, fg=self._t('bg_app'),
                         padx=6, pady=1)
        badge.pack(side=tk.LEFT, anchor=tk.N)

        # 类型 + 标题
        title = tk.Label(
            body, text=f"[{_KIND_NAMES.get(c.get('kind', ''), c.get('kind', ''))}] "
                       f"{c.get('title', '')}",
            font=(FONT_UI, FS_MD), bg=panel, fg=self._t('fg'),
            anchor=tk.W, justify=tk.LEFT, wraplength=640)
        title.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        # 位置信息
        pos = tk.Label(
            body,
            text=f"第 {c.get('first_line', 0)}–{c.get('last_line', 0)} 行"
                 + (f"  · 标签: {'、'.join(c.get('tags', [])[:3])}"
                    if c.get('tags') else ""),
            font=(FONT_UI, FS_XS), bg=panel, fg=self._t('fg_dim'),
            anchor=tk.W)
        pos.pack(fill=tk.X, padx=(8, 0), pady=(2, 0))

        # 栈帧（缩进显示）
        frames = c.get('frames') or []
        causes = c.get('causes') or []
        if frames or causes:
            detail = tk.Frame(body, bg=panel)
            detail.pack(fill=tk.X, padx=(8, 0), pady=(3, 0))
            for i, f in enumerate(frames[:8]):
                tk.Label(detail, text=f"at {f}", font=(FONT_MONO, FSM_SM),
                         bg=panel, fg=self._t('fg_muted'),
                         anchor=tk.W).pack(fill=tk.X)
            for cz in causes:
                tk.Label(detail, text=f"Caused by: {cz}",
                         font=(FONT_MONO, FSM_SM), bg=panel,
                         fg=self._t('warning'), anchor=tk.W).pack(fill=tk.X)

    # ------------------------------------------------------------------
    def _report_text(self):
        """生成可导出的文本报告"""
        rep = self.report
        lines = ["=" * 60, "日志错误分析报告", "=" * 60,
                 rep.get('summary', ''), ""]
        clusters = rep.get('clusters', [])
        for i, c in enumerate(clusters, 1):
            lines.append(f"[{i}] × {c.get('count', 1)}  "
                         f"[{_KIND_NAMES.get(c.get('kind', ''), c.get('kind', ''))}]")
            lines.append(f"    {c.get('title', '')}")
            lines.append(f"    位置: 第 {c.get('first_line', 0)}–"
                         f"{c.get('last_line', 0)} 行")
            for f in (c.get('frames') or [])[:8]:
                lines.append(f"      at {f}")
            for cz in (c.get('causes') or []):
                lines.append(f"      Caused by: {cz}")
            lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _export_report(self):
        """导出分析报告"""
        try:
            from tkinter import filedialog
            import datetime
            default_name = (f"log_analysis_"
                            f"{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
            path = filedialog.asksaveasfilename(
                title="导出错误分析报告", defaultextension=".txt",
                initialfile=default_name,
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._report_text())
            self.status.configure(text=f"已导出: {os.path.basename(path)}")
        except Exception as e:
            self.status.configure(text=f"导出失败: {e}")

    def _copy_summary(self):
        """复制摘要到剪贴板"""
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(self._report_text())
            self.status.configure(text="已复制到剪贴板")
        except Exception as e:
            self.status.configure(text=f"复制失败: {e}")
