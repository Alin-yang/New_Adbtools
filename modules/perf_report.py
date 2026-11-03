"""
性能测试报告窗口

测试结束后弹出的结果报告，包含：
- 顶部结论卡片（当前值 + 与基线对比 + 自动结论）
- 四个标签页：趋势曲线 / 线程占用 / 帧时间分布 / 原始数据
- 导出 HTML / CSV、存为基线

⚠️ 设计前提（两条来自用户的既有反馈，不能违反）：
1. **实时采样阶段保持数值表格**（用户明确否决过 Canvas 趋势图，
   认为数值比图形直观）—— 图表只出现在「结束后复盘」这一层。
2. **零绘图库依赖** —— 图表全部由 Tkinter Canvas 手绘。
"""
import os
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional

from modules import perf_analysis as A
from modules import perf_baseline as B
from modules import perf_chart as C
from modules import perf_scenario as S


class PerfReportWindow:
    """性能测试报告窗口"""

    WIDTH = 1000
    HEIGHT = 720
    MIN_SIZE = (760, 520)

    def __init__(self, app, session: Dict[str, Any],
                 baseline: Optional[Dict[str, Any]] = None):
        self.app = app
        self.session = session
        self.baseline = baseline
        self.comparison = (B.compare(session, baseline)
                           if baseline else None)
        self.theme = getattr(app, '_ui_theme', None)
        self.palette = C.ChartPalette(self.theme)

        self.win = tk.Toplevel(app.root)
        self.win.title("性能测试报告")
        self.win.transient(app.root)
        self.win.resizable(True, True)
        self.win.minsize(*self.MIN_SIZE)
        self._center()
        self._build()
        self._fill()

    # ------------------------------------------------------------ 布局
    def _center(self):
        self.win.update_idletasks()
        w, h = self.WIDTH, self.HEIGHT
        try:
            rw = self.app.root.winfo_width()
            rh = self.app.root.winfo_height()
            rx = self.app.root.winfo_rootx()
            ry = self.app.root.winfo_rooty()
            x = rx + max(0, (rw - w) // 2)
            y = ry + max(0, (rh - h) // 3)
            self.win.geometry(f'{w}x{h}+{x}+{y}')
        except Exception:
            self.win.geometry(f'{w}x{h}')

    def _t(self, key, default=''):
        return self.theme.color(key) if self.theme else default

    def _build(self):
        self.win.configure(bg=self._t('bg_app'))

        # ── 标题栏 ──────────────────────────────────────────
        head = tk.Frame(self.win, bg=self._t('bg_panel'), height=52)
        head.pack(fill=tk.X)
        head.pack_propagate(False)

        stats = self.session.get('stats', {})
        pkg = self.session.get('package') or '系统整体'
        tk.Label(
            head, text="性能测试报告", font=('Microsoft YaHei UI', 12, 'bold'),
            bg=self._t('bg_panel'), fg=self._t('fg'),
        ).pack(side=tk.LEFT, padx=16)

        tk.Label(
            head, text=pkg, font=('Microsoft YaHei UI', 9),
            bg=self._t('bg_panel'), fg=self._t('accent'),
        ).pack(side=tk.LEFT, padx=(0, 12))

        q = stats.get('quality', {})
        meta = (f"{time.strftime('%Y-%m-%d %H:%M')}  ·  "
                f"时长 {self._fmt_duration(stats.get('elapsed', 0))}  ·  "
                f"采样 {stats.get('sample_count', 0)} 次  ·  "
                f"PID {stats.get('pid') or '--'}")
        tk.Label(
            head, text=meta, font=('Microsoft YaHei UI', 8),
            bg=self._t('bg_panel'), fg=self._t('fg_dim'),
        ).pack(side=tk.RIGHT, padx=16)

        # ── 结论卡片 ────────────────────────────────────────
        self.cards_frame = tk.Frame(self.win, bg=self._t('bg_app'))
        self.cards_frame.pack(fill=tk.X, padx=16, pady=(14, 0))

        # ── 标签页 ──────────────────────────────────────────
        #    内容区放在可滚动的 Canvas 里：
        #    窗口不够高时用户能滚动，而不是把底部按钮挤出可视区。
        self.tabs = ttk.Frame(self.win, style='App.TFrame')
        self.tabs.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 0))

        holder = tk.Frame(self.tabs, bg=self._t('bg_app'))
        holder.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(holder, bg=self._t('bg_app'), highlightthickness=0)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=canvas.yview,
                            style='App.Vertical.TScrollbar')
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        inner = tk.Frame(canvas, bg=self._t('bg_app'))
        iid = canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfigure(iid, width=e.width))

        self.nb = ttk.Notebook(inner)
        self.nb.pack(fill=tk.BOTH, expand=True)
        try:
            self.nb.configure(style='App.TNotebook')
        except Exception:
            pass

        self.page_trend = tk.Frame(self.nb, bg=self._t('bg_panel'))
        self.page_threads = tk.Frame(self.nb, bg=self._t('bg_panel'))
        self.page_frames = tk.Frame(self.nb, bg=self._t('bg_panel'))
        self.page_raw = tk.Frame(self.nb, bg=self._t('bg_panel'))

        self.nb.add(self.page_trend, text='趋势曲线')
        self.nb.add(self.page_threads, text='线程占用')
        self.nb.add(self.page_frames, text='帧时间分布')
        self.nb.add(self.page_raw, text='原始数据')

        self._build_trend_page()
        self._build_threads_page()
        self._build_frames_page()
        self._build_raw_page()

        # ── 底部按钮 ────────────────────────────────────────
        foot = tk.Frame(self.win, bg=self._t('bg_app'))
        foot.pack(fill=tk.X, padx=16, pady=(10, 14))

        ttk.Button(foot, text="导出 HTML 报告", style='Primary.TButton',
                   command=self._export_html).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(foot, text="导出 CSV", style='Secondary.TButton',
                   command=self._export_csv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(foot, text="存为基线", style='Secondary.TButton',
                   command=self._save_baseline).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(foot, text="与基线对比", style='Secondary.TButton',
                   command=self._pick_baseline).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(foot, text="关闭", style='Secondary.TButton',
                   command=self.win.destroy).pack(side=tk.RIGHT)

        self.status = tk.Label(
            foot, text="", font=('Microsoft YaHei UI', 8),
            bg=self._t('bg_app'), fg=self._t('fg_dim'),
        )
        self.status.pack(side=tk.RIGHT, padx=(0, 12))

    # ------------------------------------------------------------ 趋势页
    def _build_trend_page(self):
        bar = tk.Frame(self.page_trend, bg=self._t('bg_panel'))
        bar.pack(fill=tk.X, padx=12, pady=(12, 4))

        self.metric_buttons: Dict[str, ttk.Button] = {}
        self._trend_metric = 'cpu'

        metrics = [('cpu', 'CPU 占用'), ('pss', '内存 PSS'),
                   ('rss', 'RSS 内存'), ('fps', '帧率'), ('jank', '卡顿率')]
        for key, label in metrics:
            btn = ttk.Button(bar, text=label, style='Secondary.TButton',
                             command=lambda k=key: self._switch_trend_metric(k))
            btn.pack(side=tk.LEFT, padx=(0, 6))
            self.metric_buttons[key] = btn

        self.trend_chart = C.LineChart(self.page_trend, self.palette, height=250)
        self.trend_chart.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))
        self.trend_chart.on_hover(self._on_trend_hover)

        self.hover_label = tk.Label(
            self.page_trend, text="", font=('Microsoft YaHei UI', 8),
            bg=self._t('bg_panel'), fg=self._t('fg_muted'),
        )
        self.hover_label.pack(fill=tk.X, padx=12, pady=(0, 8))

    def _switch_trend_metric(self, key):
        self._trend_metric = key
        self._refresh_trend()

    def _refresh_trend(self):
        history = self.session.get('history', [])
        key = self._trend_metric
        points = []
        for i, row in enumerate(history):
            v = row.get(key)
            if v is not None:
                points.append((float(i), float(v)))
        if not points:
            self.trend_chart.set_series([{'name': key, 'points': []}])
            return

        color = self.palette.accent
        series = [{'name': self._metric_label(key), 'points': points,
                   'color': color}]

        # 基线曲线叠加
        base = None
        if self.baseline:
            b_hist = self.baseline.get('history', [])
            b_pts = [(float(i), float(r.get(key)))
                     for i, r in enumerate(b_hist) if r.get(key) is not None]
            if b_pts:
                base = {'name': '上次', 'points': b_pts}

        self.trend_chart.set_series(series)
        self.trend_chart.set_baseline(base)
        self.trend_chart.y_label = self._metric_label(key)

    def _on_trend_hover(self, info):
        if not info:
            self.hover_label.configure(text="")
            return
        self.hover_label.configure(
            text=f"{info['name']}  采样#{int(info['x'])}   {info['y']:.2f}")

    # ------------------------------------------------------------ 线程页
    def _build_threads_page(self):
        bar = tk.Frame(self.page_threads, bg=self._t('bg_panel'))
        bar.pack(fill=tk.X, padx=12, pady=(12, 4))

        # ⚠️ 用 ttk.Button 模拟单选，而不是 ttk.Radiobutton：
        #    clam 主题下的 Radiobutton 是个小方块，看不出选中与否。
        self.thread_view = tk.StringVar(value='role')
        self._role_btn = ttk.Button(
            bar, text="按角色聚合", style='Primary.TButton', width=10,
            command=lambda: self._switch_thread_view('role'))
        self._role_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._thread_btn = ttk.Button(
            bar, text="按线程", style='Secondary.TButton', width=10,
            command=lambda: self._switch_thread_view('thread'))
        self._thread_btn.pack(side=tk.LEFT)

        self.role_chart = C.BarChart(self.page_threads, self.palette, height=170)
        self.role_chart.pack(fill=tk.X, padx=12, pady=(4, 4))

        self.thread_chart = C.BarChart(self.page_threads, self.palette, height=210)
        self.thread_chart.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))

        self.thread_note = tk.Label(
            self.page_threads, text="", font=('Microsoft YaHei UI', 8),
            bg=self._t('bg_panel'), fg=self._t('fg_dim'),
        )
        self.thread_note.pack(fill=tk.X, padx=12, pady=(0, 10))

    def _switch_thread_view(self, mode):
        """切换线程视图（角色聚合 / 按线程）"""
        self.thread_view.set(mode)
        if mode == 'role':
            self._role_btn.configure(style='Primary.TButton')
            self._thread_btn.configure(style='Secondary.TButton')
        else:
            self._role_btn.configure(style='Secondary.TButton')
            self._thread_btn.configure(style='Primary.TButton')
        self._refresh_threads()

    def _refresh_threads(self):
        stats = self.session.get('stats', {})
        threads = stats.get('threads', [])
        if self.thread_view.get() == 'role':
            roles = A.aggregate_by_role(threads)
            items = [{
                'label': f"{r['role']} ({r['count']})",
                'value': r['cur'],
                'color': self.palette.role_colors.get(r['color'],
                                                       self.palette.accent),
            } for r in roles]
            self.role_chart.set_items(items)
            self.thread_chart.set_items([])
            self.role_chart.canvas.pack_forget()
            self.thread_chart.canvas.pack_forget()
            self.role_chart.canvas.pack(fill=tk.X, padx=12, pady=(4, 8))
            self.thread_note.configure(
                text="按角色聚合：把 200+ 个线程名归成用户看得懂的类别"
                     "（渲染 / 音视频解码 / GC / IPC / 线程池 …）")
        else:
            items = [{
                'label': t['name'],
                'value': t['cur'],
                'color': self.palette.accent,
            } for t in threads[:15]]
            self.role_chart.canvas.pack_forget()
            self.thread_chart.canvas.pack_forget()
            self.thread_chart.set_items(items)
            self.thread_chart.canvas.pack(fill=tk.BOTH, expand=True,
                                        padx=12, pady=(4, 12))
            total = stats.get('thread_sum', 0)
            self.thread_note.configure(
                text=f"显示 TOP 15 线程（全部活跃线程合计 {total:.1f}%）")

    # ------------------------------------------------------------ 帧页
    def _build_frames_page(self):
        bar = tk.Frame(self.page_frames, bg=self._t('bg_panel'))
        bar.pack(fill=tk.X, padx=12, pady=(12, 4))
        tk.Label(
            bar, text="帧耗时分布 —— 比 FPS 更能看出卡在哪",
            font=('Microsoft YaHei UI', 8),
            bg=self._t('bg_panel'), fg=self._t('fg_dim'),
        ).pack(side=tk.LEFT)

        self.frame_chart = C.Histogram(self.page_frames, self.palette, height=240)
        self.frame_chart.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 8))

        self.frame_note = tk.Label(
            self.page_frames, text="", font=('Microsoft YaHei UI', 8),
            bg=self._t('bg_panel'), fg=self._t('fg_dim'), wraplength=880,
            justify=tk.LEFT,
        )
        self.frame_note.pack(fill=tk.X, padx=12, pady=(0, 12))

    def _refresh_frames(self):
        durations: List[float] = []
        for row in self.session.get('frame_samples', []):
            durations.extend(row.get('durations', []))
        if not durations:
            self.frame_chart.set_buckets([])
            self.frame_note.configure(
                text="本次未采集到逐帧数据。\n"
                     "· Android 10+ 才有 framestats 逐帧接口；\n"
                     "· 老版本只有累计帧数，能算 FPS 与窗口内卡顿率，但没有帧时间分布。")
            return

        buckets = C.build_frame_buckets(durations)
        # ⚠️ 着色按**桶的下界**判断，不是上界：
        #    "<8.3ms" 是最快的桶（绿色/主色），"33.3-50" 才是超标的（红色）。
        #    之前按 upper 判断，导致最快的桶被标成红色、完全反了。
        for b in buckets:
            lo = b['lower']
            if lo < 16.7:
                b['color'] = self.palette.role_colors['ok']       # 达标
            elif lo < 33.3:
                b['color'] = self.palette.role_colors['warn']     # 临界（掉到 30fps）
            else:
                b['color'] = self.palette.role_colors['bad']      # 超标（严重掉帧）
        markers = [
            {'ratio': 16.7 / 100.0, 'label': '16.7ms (60fps)',
             'color': self.palette.role_colors['ok']},
            {'ratio': 33.3 / 100.0, 'label': '33.3ms (30fps)',
             'color': self.palette.role_colors['warn']},
        ]
        self.frame_chart.set_buckets(buckets, markers)

        over = sum(1 for d in durations if d > 16.7)
        self.frame_note.configure(
            text=f"共 {len(durations)} 帧，其中 {over} 帧超过 16.7ms"
                 f"（60fps 预算）= {over / len(durations) * 100:.1f}%。\n"
                 f"注意：FPS=60 也可能是 60 个 30ms 的帧 —— 直方图能看出这种「均匀地慢」。")

    # ------------------------------------------------------------ 原始数据
    def _build_raw_page(self):
        wrap = tk.Frame(self.page_raw, bg=self._t('bg_panel'))
        wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        cols = ('ts', 'cpu', 'pss', 'rss', 'java', 'native', 'fps', 'jank')
        headers = {'ts': ('时间', 80), 'cpu': ('CPU %', 66),
                   'pss': ('PSS MB', 70), 'rss': ('RSS MB', 70),
                   'java': ('Java MB', 72), 'native': ('Native MB', 76),
                   'fps': ('FPS', 58), 'jank': ('卡顿 %', 66)}
        tree = ttk.Treeview(wrap, columns=cols, show='headings', height=18,
                            style='App.Treeview')
        for col, (text, w) in headers.items():
            tree.heading(col, text=text)
            tree.column(col, width=w, anchor='e' if col != 'ts' else 'center',
                        stretch=True)
        vsb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=tree.yview,
                            style='App.Vertical.TScrollbar')
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.raw_tree = tree

    def _refresh_raw(self):
        tree = self.raw_tree
        tree.delete(*tree.get_children())
        history = list(self.session.get('history', []))
        for row in reversed(history):     # 最新在上
            tree.insert('', 0, values=(
                row.get('ts', ''),
                '--' if row.get('cpu') is None else f"{row['cpu']:.2f}",
                '--' if row.get('pss') is None else f"{row['pss']:.1f}",
                '--' if row.get('rss') is None else f"{row['rss']:.1f}",
                '--' if row.get('java') is None else f"{row['java']:.1f}",
                '--' if row.get('native') is None else f"{row['native']:.1f}",
                '--' if row.get('fps') is None else f"{row['fps']:.2f}",
                '--' if row.get('jank') is None else f"{row['jank']:.2f}",
            ))

    # ------------------------------------------------------------ 填充
    def _fill(self):
        self._build_cards()
        self._refresh_trend()
        self._refresh_threads()
        self._refresh_frames()
        self._refresh_raw()

    def _build_cards(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()

        stats = self.session.get('stats', {})
        conclusions = self.session.get('conclusions', [])

        cards = [
            ('cpu', 'CPU 占用', '%'),
            ('pss', '内存 PSS', ' MB'),
            ('fps', '帧率', ''),
        ]
        for key, label, unit in cards:
            m = stats.get(key, {})
            cur = m.get('cur')
            sub = self._compare_sub(key)
            self._card(label,
                       '--' if cur is None else f"{cur:.1f}{unit}",
                       sub, self._metric_color(key, cur))

        # 结论卡
        if conclusions:
            worst = conclusions[0]
            color = {'bad': self.palette.role_colors['bad'],
                     'warn': self.palette.role_colors['warn'],
                     'good': self.palette.role_colors['ok'],
                     'info': self.palette.role_colors['other']}.get(
                         worst.get('level'), self.palette.accent)
            self._card('结论', worst.get('title', ''),
                       worst.get('detail', ''), color)
        else:
            self._card('结论', '无数据', '', self.palette.accent)

    def _card(self, label, value, sub, color):
        frame = tk.Frame(self.cards_frame, bg=self._t('bg_panel'),
                         highlightbackground=self._t('line'),
                         highlightthickness=1)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        tk.Label(frame, text=label, font=('Microsoft YaHei UI', 8),
                 bg=self._t('bg_panel'), fg=self._t('fg_dim')).pack(
            anchor=tk.W, padx=12, pady=(9, 0))
        tk.Label(frame, text=value, font=('Microsoft YaHei UI', 15, 'bold'),
                 bg=self._t('bg_panel'), fg=color).pack(
            anchor=tk.W, padx=12)
        tk.Label(frame, text=sub, font=('Microsoft YaHei UI', 8),
                 bg=self._t('bg_panel'), fg=self._t('fg_dim'),
                 wraplength=180, justify=tk.LEFT).pack(
            anchor=tk.W, padx=12, pady=(0, 9))

    def _compare_sub(self, key):
        if not self.comparison:
            return ''
        for m in self.comparison['metrics']:
            if m['key'] == key:
                if m['delta'] == 0:
                    return '与基线持平'
                arrow = '↑' if m['delta'] > 0 else '↓'
                color = ('#DC2626' if m['better'] is False else '#0E9F6E')
                return f"{arrow} 比基线 {m['delta']:+.1f}{m['unit']}"
        return ''

    def _metric_color(self, key, value):
        if value is None:
            return self._t('fg_dim')
        if key == 'cpu':
            if value > 80:
                return self.palette.role_colors['bad']
            if value > 50:
                return self.palette.role_colors['warn']
        if key == 'fps':
            if value < 24:
                return self.palette.role_colors['bad']
            if value < 50:
                return self.palette.role_colors['warn']
        return self._t('fg')

    # ------------------------------------------------------------ 操作
    def _export_html(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="导出 HTML 报告",
            defaultextension=".html",
            initialfile=(f"perf_{self.session.get('package', 'report')}_"
                         f"{time.strftime('%Y%m%d_%H%M%S')}.html"),
            filetypes=[("HTML 文件", "*.html")])
        if not path:
            return
        try:
            html = build_html_report(self.session, self.baseline,
                                     self.comparison)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            self.status.configure(text=f"已导出: {os.path.basename(path)}")
        except Exception as e:
            self.status.configure(text=f"导出失败: {e}")

    def _export_csv(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            title="导出 CSV", defaultextension=".csv",
            initialfile=(f"perf_{time.strftime('%Y%m%d_%H%M%S')}.csv"),
            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                import csv
                w = csv.writer(f)
                w.writerow(['时间', '进程CPU(%)', 'PSS内存(MB)', 'RSS内存(MB)',
                            'Java Heap(MB)', 'Native Heap(MB)', 'FPS', '卡顿率(%)'])
                for row in self.session.get('history', []):
                    w.writerow([row.get('ts', '')] +
                               ['' if row.get(k) is None else row.get(k)
                                for k in ('cpu', 'pss', 'rss', 'java',
                                          'native', 'fps', 'jank')])
            self.status.configure(text=f"已导出: {os.path.basename(path)}")
        except Exception as e:
            self.status.configure(text=f"导出失败: {e}")

    def _save_baseline(self):
        store = B.BaselineStore()
        path = store.save(self.session.get('package', ''), self.session)
        if path:
            self.status.configure(text=f"已存为基线: {os.path.basename(path)}")
        else:
            self.status.configure(text="保存失败")

    def _pick_baseline(self):
        from tkinter import filedialog
        store = B.BaselineStore()
        pkg = self.session.get('package', '')
        baselines = store.list_baselines(pkg)
        if not baselines:
            self.status.configure(text="还没有基线，先点「存为基线」")
            return
        names = [f"{b['saved_at_text']}"
                 + (f"  [{b['label']}]" if b.get('label') else '')
                 for b in baselines]
        picked = _pick_from_list(self.win, "选择基线", names)
        if picked is None:
            return
        idx = names.index(picked)
        self.baseline = baselines[idx]['session']
        self.comparison = B.compare(self.session, self.baseline)
        self._fill()

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _metric_label(key):
        return {'cpu': 'CPU 占用', 'pss': '内存 PSS', 'rss': 'RSS 内存',
                'fps': '帧率', 'jank': '卡顿率'}.get(key, key)


def _pick_from_list(parent, title, names):
    """简易列表选择对话框"""
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.geometry('420x320')
    result = {'value': None}

    lb = tk.Listbox(win, font=('Microsoft YaHei UI', 9), activestyle='none')
    lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    for n in names:
        lb.insert(tk.END, n)
    lb.selection_set(0)

    def ok():
        sel = lb.curselection()
        if sel:
            result['value'] = names[sel[0]]
        win.destroy()

    btns = tk.Frame(win)
    btns.pack(fill=tk.X, padx=10, pady=(0, 10))
    ttk.Button(btns, text="确定", style='Primary.TButton',
               command=ok).pack(side=tk.RIGHT, padx=(6, 0))
    ttk.Button(btns, text="取消", style='Secondary.TButton',
               command=win.destroy).pack(side=tk.RIGHT)
    lb.bind('<Double-Button-1>', lambda e: ok())
    win.grab_set()
    parent.wait_window(win)
    return result['value']


# ====================================================================== #
# HTML 导出（自包含，可直接发给同事）
# ====================================================================== #

def _fmt_metric(stats: Dict[str, Any], key: str, unit: str) -> str:
    """格式化指标；未测得时显示 --（不能用 0 冒充真实测得值）"""
    cur = (stats.get(key) or {}).get('cur')
    if cur is None:
        return '--'
    return f'{cur:.1f}{unit}'


def build_html_report(session: Dict[str, Any],
                      baseline: Optional[Dict[str, Any]] = None,
                      comparison: Optional[Dict[str, Any]] = None) -> str:
    """生成自包含的 HTML 报告（内联 SVG，无外部依赖）"""
    stats = session.get('stats', {})
    conclusions = session.get('conclusions', [])
    history = session.get('history', [])
    pkg = session.get('package', '')

    def svg_line(key, width=860, height=200):
        pts = [(i, float(r.get(key))) for i, r in enumerate(history)
               if r.get(key) is not None]
        if len(pts) < 2:
            return ''
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x_min, x_max = min(xs), max(xs)
        y_max = max(ys) or 1
        y_min = min(0, min(ys))
        pad_l, pad_t, pad_b = 46, 14, 26
        w, h = width - pad_l - 16, height - pad_t - pad_b

        def px(x):
            return pad_l + (x - x_min) / max(1e-9, x_max - x_min) * w

        def py(y):
            return pad_t + h - (y - y_min) / max(1e-9, y_max - y_min) * h

        path = ' '.join(f"{px(x):.1f},{py(y):.1f}" for x, y in pts)
        grid = ''.join(
            f'<line x1="{pad_l}" y1="{pad_t + h * i / 4:.1f}" '
            f'x2="{pad_l + w}" y2="{pad_t + h * i / 4:.1f}" '
            f'stroke="#EDEFF3" stroke-width="1"/>' for i in range(5))
        return (f'<svg viewBox="0 0 {width} {height}" width="100%">'
                f'{grid}'
                f'<polyline points="{path}" fill="none" stroke="#2563EB" '
                f'stroke-width="2"/>'
                f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + h}" '
                f'stroke="#D8DDE5"/>'
                f'<line x1="{pad_l}" y1="{pad_t + h}" x2="{pad_l + w}" '
                f'y2="{pad_t + h}" stroke="#D8DDE5"/>'
                f'</svg>')

    rows = ''.join(
        f'<tr><td>{r.get("ts", "")}</td>'
        + ''.join('<td>--</td>' if r.get(k) is None else f'<td>{r.get(k):.1f}</td>'
                  for k in ('cpu', 'pss', 'rss', 'java', 'native', 'fps', 'jank'))
        + '</tr>' for r in reversed(history))

    concl = ''.join(
        f'<li class="c-{c.get("level", "info")}">'
        f'<b>{c.get("title", "")}</b> — {c.get("detail", "")}</li>'
        for c in conclusions)

    cmp_html = ''
    if comparison:
        cells = ''.join(
            f'<tr><td>{m["label"]}</td><td>{m["cur"]:.1f}{m["unit"]}</td>'
            f'<td>{m["base"]:.1f}{m["unit"]}</td>'
            f'<td class="{"up" if m["delta"] > 0 else "dn"}">'
            f'{m["delta"]:+.1f}{m["unit"]}</td></tr>'
            for m in comparison['metrics'])
        cmp_html = (f'<h2>与基线对比</h2><table><tr><th>指标</th><th>本次</th>'
                    f'<th>基线</th><th>变化</th></tr>{cells}</table>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>性能测试报告 - {pkg}</title>
<style>
body{{font-family:system-ui,"Microsoft YaHei UI",sans-serif;margin:28px;color:#16191F;background:#F7F8FA}}
h1{{font-size:20px;font-weight:500;margin:0 0 4px}}
.sub{{color:#5A6472;font-size:13px;margin-bottom:20px}}
h2{{font-size:15px;font-weight:500;margin:24px 0 8px}}
.card{{background:#fff;border:1px solid #E3E6EB;border-radius:10px;padding:14px 16px;margin-bottom:12px}}
.k{{color:#8A94A3;font-size:12px}} .v{{font-size:22px;font-weight:500}}
table{{border-collapse:collapse;width:100%;background:#fff;border:1px solid #E3E6EB;border-radius:8px;overflow:hidden}}
th,td{{padding:7px 10px;border-bottom:1px solid #EDEFF3;font-size:12px;text-align:right}}
th:first-child,td:first-child{{text-align:left}} th{{background:#F1F3F6;font-weight:500}}
.up{{color:#DC2626}} .dn{{color:#0E9F6E}}
ul{{list-style:none;padding:0}} li{{padding:9px 12px;background:#fff;border:1px solid #E3E6EB;border-radius:8px;margin-bottom:6px;font-size:13px}}
.c-bad{{border-left:3px solid #DC2626}} .c-warn{{border-left:3px solid #D97706}}
.c-good{{border-left:3px solid #0E9F6E}} .c-info{{border-left:3px solid #2563EB}}
</style></head><body>
<h1>性能测试报告</h1>
<div class="sub">{pkg} · {time.strftime('%Y-%m-%d %H:%M')} ·
 时长 {stats.get('elapsed', 0):.0f}s · 采样 {stats.get('sample_count', 0)} 次 ·
 PID {stats.get('pid') or '--'} · 模式 {stats.get('mode', '--')}</div>
<div class="card"><div class="k">CPU 占用</div><div class="v">
{_fmt_metric(stats, 'cpu', '%')}</div></div>
<div class="card"><div class="k">内存 PSS</div><div class="v">
{_fmt_metric(stats, 'pss', ' MB')}</div></div>
<div class="card"><div class="k">帧率</div><div class="v">
{_fmt_metric(stats, 'fps', '')}</div></div>
<div class="card"><div class="k">卡顿率</div><div class="v">
{_fmt_metric(stats, 'jank', ' %')}</div></div>
<h2>结论</h2><ul>{concl}</ul>
{cmp_html}
<h2>CPU 趋势</h2><div class="card">{svg_line('cpu')}</div>
<h2>内存趋势</h2><div class="card">{svg_line('pss')}</div>
<h2>原始数据</h2><table><tr><th>时间</th><th>CPU %</th><th>PSS MB</th>
<th>RSS MB</th><th>Java MB</th><th>Native MB</th><th>FPS</th>
<th>卡顿 %</th></tr>{rows}</table>
</body></html>"""
