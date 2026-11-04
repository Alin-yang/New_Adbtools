"""
设备切换浮层 —— 顶栏「设备 ▾」点开后弹出的设备列表

为什么需要它
------------
以前顶栏只有一个「设备 IP」输入框 + 一个状态徽标，导致：
- 刷新后明明检测到 1 台设备在线，顶栏却仍显示旧 IP + 「未连接」
  （徽标语义把「没有设备」和「设备在但不是我选的那个」混成了一句话）
- 多台设备在线时，用户只能手动去输入框里敲 IP 切换，
  没有「现在有哪些设备可切」的入口

本模块提供：
- **分组列表**：在线设备 / 离线与历史，各自带状态点
- **单击即切换**：点在线设备 → 设为当前目标 + 自动连接
- **型号懒加载**：先秒开列出 IP，型号在后台用一次全量 `getprop` 补齐
  （逐条 getprop 每条要 spawn 一个 adb 进程，10 台设备要 2 秒+）
- **纯 Tkinter**：不引第三方依赖，弹层用无边框 Toplevel

⚠️ 线程模型
   弹层本身在主线程创建/销毁；型号补齐走后台线程，
   完成后必须用 `app._run_in_ui()` 回主线程刷新 —— 后台线程直接碰
   Tk 控件会在主线程忙时抛 "main thread is not in main loop"。
"""
import logging
import tkinter as tk
from tkinter import ttk

from config import Config
from gui.theme import FONT_UI, FONT_MONO, FS_XS, FS_SM, FS_MD

# 弹层宽度（px）—— 够放下 IP + 型号副标题
POPUP_WIDTH = 360
# 弹层最大高度（px）—— 超过就滚动，防止历史设备多时浮层顶满屏幕
POPUP_MAX_HEIGHT = 340
# 单个设备条目高度（px）
ROW_HEIGHT = 44
# 离线历史最多展示几条
MAX_HISTORY_ROWS = 6
# 型号缓存有效期（秒）—— 型号不会频繁变，缓存久一点省 adb 调用
META_CACHE_TTL = 300


class DevicePicker:
    """设备切换浮层

    用法：
        picker = DevicePicker(app, theme, anchor_widget)
        picker.toggle()          # 打开/关闭
        picker.refresh()         # 重新拉设备列表并重绘
    """

    def __init__(self, app, theme, anchor):
        self.app = app
        self.theme = theme
        self.anchor = anchor

        self.win = None          # 无边框 Toplevel
        self._rows = []          # 当前渲染的条目 [(device_id, widgets...)]
        self._meta_cache = {}    # {device_id: {'model':..., 'version':...}}
        self._meta_time = {}     # {device_id: 时间戳}
        self._loading_meta = set()

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------

    def toggle(self):
        """打开 / 关闭浮层"""
        try:
            if self.win is not None and self.win.winfo_exists():
                if self.win.winfo_ismapped():
                    self.hide()
                else:
                    self.show()
            else:
                self.show()
        except Exception as e:
            logging.error(f"[设备切换] 浮层开关失败: {e}", exc_info=True)

    def show(self):
        """显示浮层"""
        try:
            self._build()
            self.refresh()
            self._place()
            self.win.deiconify()
            self.win.lift()
            # 点外面关闭：抢一次焦点，按钮再点一次会先触发这里
            self.win.focus_force()
        except Exception as e:
            logging.error(f"[设备切换] 显示浮层失败: {e}", exc_info=True)

    def hide(self):
        """隐藏浮层"""
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.withdraw()
        except Exception:
            pass

    def is_open(self) -> bool:
        try:
            return (self.win is not None and self.win.winfo_exists()
                    and self.win.winfo_ismapped())
        except Exception:
            return False

    def _place(self):
        """把浮层定位到锚点按钮下方

        ⚠️ 必须用 root 坐标（winfo_rootx）—— Toplevel 的 geometry 用的是
           屏幕绝对坐标，不是相对父容器的坐标。
        """
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            self.win.update_idletasks()
            anchor = self.anchor
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height() + 2
            # 高度取「内容自然高度」与「最大高度」的较小值
            height = min(self.win.winfo_reqheight(), POPUP_MAX_HEIGHT)
            self.win.geometry(f"{POPUP_WIDTH}x{height}+{x}+{y}")
        except Exception as e:
            logging.debug(f"[设备切换] 浮层定位失败: {e}")

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self):
        """创建浮层窗口（只建一次，之后只重绘内容）"""
        if self.win is not None and self.win.winfo_exists():
            return

        win = tk.Toplevel(self.app.root)
        win.withdraw()
        win.overrideredirect(True)          # 无边框
        win.attributes('-topmost', True)   # 置顶
        self.win = win

        # 主题感知：弹层背景用 bg_elev（比面板略亮，浮起来一层）
        bg = self.theme.color('bg_elev')
        win.configure(bg=bg)

        # 主体容器
        body = tk.Frame(win, bg=bg, highlightbackground=self.theme.color('line'),
                        highlightthickness=1)
        body.pack(fill=tk.BOTH, expand=True)

        # 标题行
        header = tk.Frame(body, bg=bg)
        header.pack(fill=tk.X, padx=12, pady=(10, 6))
        self.theme.register(header, 'elev')

        tk.Label(header, text="切换设备", font=(FONT_UI, FS_MD, 'bold'),
                 bg=bg, fg=self.theme.color('fg')).pack(side=tk.LEFT)
        self._count_label = tk.Label(header, text="", font=(FONT_UI, FS_SM),
                                     bg=bg, fg=self.theme.color('fg_dim'))
        self._count_label.pack(side=tk.RIGHT)
        self.theme.register(self._count_label, 'elev_label')

        # 分隔线
        sep = tk.Frame(body, bg=self.theme.color('line'), height=1)
        sep.pack(fill=tk.X)
        self.theme.register(sep, 'sep')

        # 内容容器（在线 / 离线分组都塞这里）
        # ⚠️ 放进 Canvas 里做滚动：历史设备可能十几条，
        #    不限高的话浮层会顶满屏幕。
        self._canvas = tk.Canvas(
            win, bg=bg, highlightthickness=0, borderwidth=0,
            height=200, width=POPUP_WIDTH - 12)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.theme.register(self._canvas, 'elev')

        self._content = tk.Frame(self._canvas, bg=bg)
        self._content_window = self._canvas.create_window(
            (0, 0), window=self._content, anchor=tk.NW)

        # 内容高度变化时同步滚动区域
        self._content.bind('<Configure>', self._on_content_configure)
        # 滚轮滚动
        self._canvas.bind('<MouseWheel>', self._on_mousewheel)
        self._content.bind('<MouseWheel>', self._on_mousewheel)

        # 底部：手动输入提示
        foot = tk.Frame(body, bg=bg)
        foot.pack(fill=tk.X, padx=12, pady=(4, 10))
        self.theme.register(foot, 'elev')
        tk.Label(foot, text="＋ 手动输入 IP 地址（直接在上方输入框输入后点连接）",
                 font=(FONT_UI, FS_XS), bg=bg,
                 fg=self.theme.color('fg_dim')).pack(side=tk.LEFT)
        self.theme.register(foot, 'elev')

        # 点击浮层外部关闭
        win.bind('<ButtonPress>', self._on_outside_click)
        # Esc 关闭
        win.bind('<Escape>', lambda e: self.hide())
        # 主题切换后重刷配色
        self.theme.on_change(lambda name: self._retheme())

    def _on_content_configure(self, event=None):
        """内容高度变化 → 更新滚动区域"""
        try:
            self._canvas.configure(scrollregion=self._canvas.bbox('all'))
        except Exception:
            pass

    def _on_mousewheel(self, event):
        """滚轮滚动"""
        try:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        except Exception:
            pass

    def _retheme(self):
        """主题切换后重刷浮层配色"""
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            bg = self.theme.color('bg_elev')
            self.win.configure(bg=bg)
            self.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def refresh(self):
        """重新拉设备列表并重绘内容"""
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            devices = self.app.get_online_devices()
            self._render(devices)
        except Exception as e:
            logging.error(f"[设备切换] 刷新列表失败: {e}", exc_info=True)

    def _render(self, online_devices):
        """按「在线 / 离线与历史」分组渲染条目"""
        try:
            # 清空旧内容
            for child in self._content.winfo_children():
                child.destroy()
            self._rows = []

            current = self.app.get_ip_address()
            online_norm = set()
            for d in online_devices:
                online_norm.add(self._normalize(d))

            # ── 在线设备分组 ────────────────────────────────
            if online_devices:
                self._add_group_title("在线设备")
                for device in online_devices:
                    self._add_row(device, online=True, is_current=(
                        current is not None and self._normalize(device) == current))
            else:
                self._add_group_title("在线设备")
                self._add_empty_hint("当前没有在线设备")

            # ── 离线与历史分组 ──────────────────────────────
            history = [d for d in self.app.ip_history
                       if self._normalize(d) not in online_norm]
            if history:
                self._add_group_title("离线与历史")
                for device in history[:MAX_HISTORY_ROWS]:
                    self._add_row(device, online=False, is_current=(
                        current is not None and self._normalize(device) == current))
                # 历史太多时给个提示
                if len(history) > MAX_HISTORY_ROWS:
                    lbl = tk.Label(
                        self._content,
                        text=f"还有 {len(history) - MAX_HISTORY_ROWS} 条历史记录…",
                        font=(FONT_UI, FS_XS), bg=self.theme.color('bg_elev'),
                        fg=self.theme.color('fg_dim'), anchor=tk.W)
                    lbl.pack(fill=tk.X, padx=6, pady=(2, 4))
                    self.theme.register(lbl, 'elev_label')

            # 更新标题右侧的计数
            if hasattr(self, '_count_label') and self._count_label.winfo_exists():
                n = len(online_devices)
                self._count_label.config(text=f"在线 {n} 台")
        except Exception as e:
            logging.error(f"[设备切换] 渲染失败: {e}", exc_info=True)

    def _add_group_title(self, text):
        """分组小标题"""
        lbl = tk.Label(self._content, text=text, font=(FONT_UI, FS_XS),
                       bg=self.theme.color('bg_elev'),
                       fg=self.theme.color('fg_dim'), anchor=tk.W)
        lbl.pack(fill=tk.X, padx=6, pady=(6, 2))
        self.theme.register(lbl, 'elev_label')

    def _add_empty_hint(self, text):
        """空态提示"""
        lbl = tk.Label(self._content, text=text, font=(FONT_UI, FS_SM),
                       bg=self.theme.color('bg_elev'),
                       fg=self.theme.color('fg_dim'), anchor=tk.W)
        lbl.pack(fill=tk.X, padx=6, pady=(2, 4))
        self.theme.register(lbl, 'elev_label')

    def _add_row(self, device, online, is_current):
        """单个设备条目"""
        bg = self.theme.color('bg_elev')
        row = tk.Frame(self._content, bg=bg, cursor='hand2')
        row.pack(fill=tk.X, pady=1)
        self.theme.register(row, 'elev')

        # 状态点：用 ● / ○ 字符（微软雅黑 UI 有这两个字形）
        dot_color = (self.theme.color('success') if online
                     else self.theme.color('fg_dim'))
        dot = tk.Label(row, text="●" if online else "○", font=(FONT_UI, FS_SM),
                       bg=bg, fg=dot_color, width=1)
        dot.pack(side=tk.LEFT, padx=(6, 4))

        # 文本区：主行 = 设备标识，副行 = 型号 · 版本
        text_box = tk.Frame(row, bg=bg)
        text_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.theme.register(text_box, 'elev')

        main = tk.Label(text_box, text=self._display_id(device),
                        font=(FONT_MONO, FS_MD), bg=bg,
                        fg=self.theme.color('fg'), anchor=tk.W)
        main.pack(fill=tk.X)
        self.theme.register(main, 'elev_label')

        sub = tk.Label(text_box, text=self._meta_text(device, online),
                       font=(FONT_UI, FS_XS), bg=bg,
                       fg=self.theme.color('fg_dim'), anchor=tk.W)
        sub.pack(fill=tk.X)
        self.theme.register(sub, 'elev_label')

        # 右侧标记
        if is_current:
            mark = tk.Label(row, text="当前", font=(FONT_UI, FS_XS), bg=bg,
                            fg=self.theme.color('accent'))
            mark.pack(side=tk.RIGHT, padx=(4, 8))
            self.theme.register(mark, 'elev_label')
        elif online:
            mark = tk.Label(row, text="可切换", font=(FONT_UI, FS_XS), bg=bg,
                            fg=self.theme.color('fg_dim'))
            mark.pack(side=tk.RIGHT, padx=(4, 8))
            self.theme.register(mark, 'elev_label')

        # 整行可点
        for widget in (row, dot, main, sub, text_box):
            widget.bind('<Button-1>',
                        lambda e, d=device: self._on_pick(d))
            widget.configure(cursor='hand2')

        self._rows.append((device, row, main, sub))

        # 在线设备 → 后台补型号
        if online:
            self._load_meta_async(device, sub)

    def _on_pick(self, device):
        """点击某个设备 → 设为当前目标"""
        try:
            self.hide()
            self.app.select_device(device)
        except Exception as e:
            logging.error(f"[设备切换] 选中设备失败: {e}", exc_info=True)

    def _on_outside_click(self, event):
        """点击浮层外部 → 关闭"""
        try:
            widget = self.app.root.winfo_containing(
                event.x_root, event.y_root)
            if widget is None:
                self.hide()
                return
            # 在浮层内部则不关
            if str(widget).startswith(str(self.win)):
                return
            self.hide()
        except Exception:
            self.hide()

    # ------------------------------------------------------------------
    # 型号懒加载
    # ------------------------------------------------------------------

    def _display_id(self, device):
        """展示用的设备标识（IP 去掉端口）"""
        return self._normalize(device)

    @staticmethod
    def _normalize(device):
        """IP 设备去掉端口号，USB 序列号原样保留"""
        if not device:
            return ''
        if ':' in device and '.' in device:
            return device.split(':')[0]
        return device

    def _meta_text(self, device, online):
        """副标题：型号 · Android 版本（没有就显示在线状态）"""
        meta = self._meta_cache.get(device)
        if meta:
            parts = [p for p in (meta.get('model'), meta.get('version')) if p]
            if parts:
                return ' · '.join(parts)
        return '在线' if online else '已离线'

    def _load_meta_async(self, device, label):
        """后台补型号信息（一次全量 getprop，别逐条查）"""
        import time
        now = time.time()
        cached_at = self._meta_time.get(device, 0)
        if device in self._meta_cache and (now - cached_at) < META_CACHE_TTL:
            return
        if device in self._loading_meta:
            return
        self._loading_meta.add(device)

        def _work():
            try:
                meta = self._fetch_meta(device)
                if meta:
                    self._meta_cache[device] = meta
                    self._meta_time[device] = time.time()
                    # ⚠️ 必须回主线程刷新 UI
                    self.app._run_in_ui(
                        lambda d=device, m=meta: self._apply_meta(d, m))
            except Exception as e:
                logging.debug(f"[设备切换] 读取型号失败 {device}: {e}")
            finally:
                self._loading_meta.discard(device)

        try:
            self.app.run_in_background(_work)
        except Exception:
            self._loading_meta.discard(device)

    def _apply_meta(self, device, meta):
        """把型号信息刷到对应的副标题上"""
        try:
            if not self.is_open():
                return
            for d, _row, _main, sub in self._rows:
                if d == device:
                    parts = [p for p in (meta.get('model'), meta.get('version'))
                             if p]
                    if parts:
                        sub.config(text=' · '.join(parts))
                    break
        except Exception:
            pass

    def _fetch_meta(self, device):
        """取设备型号与 Android 版本

        ⚠️ 一次 `adb shell getprop`（不带参数）拿全部属性 ——
           逐条 getprop 每条都要 spawn 一个 adb 进程（~200ms），
           取 2 个属性 10 台设备要 4 秒；全量一次只要 ~0.3 秒/台。
        """
        from utils import run_adb_command, parse_getprop_all
        # -s 用带端口的完整标识，USB 设备用序列号
        target = device
        output, ok = run_adb_command(
            "adb shell getprop", retries=1, timeout=8, target_device=target)
        if not ok or not output:
            return {}
        props = parse_getprop_all(output)
        return {
            'model': props.get('ro.product.model', ''),
            'version': props.get('ro.build.version.release', ''),
        }
