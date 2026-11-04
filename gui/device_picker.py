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
- **纯 Tkinter**：不引第三方依赖

⚠️ 三条硬约束（都是实际踩过的坑）

1. **必须是主窗口的子控件，不能用 Toplevel**
   Toplevel 是独立的 OS 顶层窗口 —— 移动主窗口它纹丝不动，
   用户会以为「弹窗卡住了」。所以这里用 `place` 把浮层**盖在主窗口内部**。

2. **整行都是点击热区，且必须给出视觉提示**
   之前只在 IP 文字上绑了点击，右边的「可切换」文字看着像按钮却点不动，
   用户完全不知道该点哪。现在：
   - 整行（含状态点、IP、型号、右侧标记）都可点
   - 右侧「可切换」改成**显式的按钮样式**（带边框底色的胶囊）
   - 鼠标悬停整行高亮

3. **列表必须用纯 Canvas 绘制，不能塞 Frame 树**
   Canvas 里嵌 Frame + 几十个 Label，滚动时每个 Label 都要单独重绘 →
   实测明显卡顿。改成纯 Canvas 画 item（create_text/create_rectangle），
   滚动只重绘画布，流畅得多。

⚠️ 线程模型
   浮层本身在主线程创建/销毁；型号补齐走后台线程，
   完成后必须用 `app._run_in_ui()` 回主线程刷新 —— 后台线程直接碰
   Tk 控件会在主线程忙时抛 "main thread is not in main loop"。
"""
import logging
import tkinter as tk

from gui.theme import FONT_UI, FONT_MONO, FS_XS, FS_SM, FS_MD

# 浮层宽度（px）—— 够放下 IP + 型号副标题
POPUP_WIDTH = 360
# 浮层最大高度（px）—— 超过就滚动，防止历史设备多时浮层顶满屏幕
POPUP_MAX_HEIGHT = 340
# 浮层固定 chrome 的高度（标题行 + 分隔线 + 底部提示）
# 视口高度 = 浮层高度 - 这个值，否则 footer 会被 canvas 挤掉
CHROME_HEIGHT = 62
# 单行高度（px）
ROW_HEIGHT = 46
# 分组标题高度（px）
GROUP_HEIGHT = 26
# 离线历史最多展示几条
MAX_HISTORY_ROWS = 8
# 型号缓存有效期（秒）—— 型号不会频繁变，缓存久一点省 adb 调用
META_CACHE_TTL = 300


class DevicePicker:
    """设备切换浮层（盖在主窗口内部，不是独立窗口）

    用法：
        picker = DevicePicker(app, theme, anchor_widget, host_widget)
        picker.toggle()          # 打开/关闭
        picker.refresh()         # 重新拉设备列表并重绘
    """

    def __init__(self, app, theme, anchor, host):
        self.app = app
        self.theme = theme
        self.anchor = anchor      # 「设备 ▾」按钮（定位锚点）
        self.host = host          # 浮层的父容器（主窗口内的 Frame）

        self.win = None           # 浮层容器（host 的子控件）
        self._canvas = None       # 列表画布
        self._rows = []           # 渲染后的条目 [(device_id, y0, y1)]
        self._meta_cache = {}     # {device_id: {'model':..., 'version':...}}
        self._meta_time = {}      # {device_id: 时间戳}
        self._loading_meta = set()
        self._hover_index = -1

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------

    def toggle(self):
        """打开 / 关闭浮层"""
        try:
            if self.is_open():
                self.hide()
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
            self.win.place_info()  # 触发一次布局
            self.win.lift()
            # 抢焦点，让 Esc 能关
            self.win.focus_set()
        except Exception as e:
            logging.error(f"[设备切换] 显示浮层失败: {e}", exc_info=True)

    def hide(self):
        """隐藏浮层"""
        try:
            if self.win is not None and self.win.winfo_exists():
                self.win.place_forget()
        except Exception:
            pass

    def is_open(self) -> bool:
        try:
            return (self.win is not None and self.win.winfo_exists()
                    and self.win.winfo_ismapped())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build(self):
        """创建浮层（只建一次，之后只重绘内容）"""
        if self.win is not None and self.win.winfo_exists():
            return

        bg = self.theme.color('bg_elev')
        win = tk.Frame(self.host, bg=bg,
                       highlightbackground=self.theme.color('line'),
                       highlightthickness=1)
        self.win = win
        self.theme.register(win, 'elev')

        # ── 标题行 ────────────────────────────────────────────
        header = tk.Frame(win, bg=bg)
        header.pack(fill=tk.X, padx=12, pady=(9, 6))
        self.theme.register(header, 'elev')

        tk.Label(header, text="切换设备", font=(FONT_UI, FS_MD, 'bold'),
                 bg=bg, fg=self.theme.color('fg')).pack(side=tk.LEFT)
        self._count_label = tk.Label(header, text="", font=(FONT_UI, FS_SM),
                                     bg=bg, fg=self.theme.color('fg_dim'))
        self._count_label.pack(side=tk.RIGHT)
        self.theme.register(self._count_label, 'elev_label')

        # 分隔线
        sep = tk.Frame(win, bg=self.theme.color('line'), height=1)
        sep.pack(fill=tk.X)
        self.theme.register(sep, 'sep')

        # ── 底部提示 ──────────────────────────────────────────
        # ⚠️ **必须先 pack footer，再 pack canvas**：
        #    pack 按调用顺序分配空间，canvas 在前的话它会先把高度占满，
        #    footer 被挤到浮层外面（y 变成负数）→ 提示文字看不见。
        foot = tk.Frame(win, bg=bg)
        foot.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(3, 9))
        self.theme.register(foot, 'elev')
        tk.Label(foot, text="点击任意一行即可切换到该设备",
                 font=(FONT_UI, FS_XS), bg=bg,
                 fg=self.theme.color('fg_dim')).pack(side=tk.LEFT)
        self.theme.register(foot, 'elev')

        # ── 列表画布（纯 Canvas，不用 Frame 树）──────────────
        # ⚠️ **不能用 expand=True**：canvas 会撑满父容器的剩余空间，
        #    忽略我设的 height → 视口比预期高，滚动区对不上，
        #    底部内容看起来像被裁断。高度由 _render() 按内容算好后设置。
        self._canvas = tk.Canvas(
            win, bg=bg, highlightthickness=0, borderwidth=0,
            height=200, width=POPUP_WIDTH - 12)
        self._canvas.pack(fill=tk.X, padx=6, pady=4)
        self.theme.register(self._canvas, 'elev')

        # 交互
        self._canvas.bind('<Button-1>', self._on_click)
        self._canvas.bind('<Motion>', self._on_motion)
        self._canvas.bind('<MouseWheel>', self._on_mousewheel)
        self._canvas.bind('<Leave>', self._on_leave)

        # Esc 关闭（浮层在主窗口内，所以绑在浮层上）
        win.bind('<Escape>', lambda e: self.hide())

        # 点击主窗口其它地方关闭
        self.app.root.bind('<Button-1>', self._on_root_click, add='+')

        # 主题切换后重刷配色
        self.theme.on_change(lambda name: self._retheme())

    def _retheme(self):
        """主题切换后重刷浮层配色"""
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            self.win.configure(bg=self.theme.color('bg_elev'))
            self.refresh()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 定位
    # ------------------------------------------------------------------

    def _place(self):
        """把浮层定位到锚点按钮下方

        ⚠️ 浮层是**主窗口的子控件**（place 到 host 里），
           所以坐标是相对 host 的，不是屏幕坐标 ——
           这样主窗口移动/缩放时浮层自动跟随（这正是用 Toplevel 做不到的）。

        ⚠️ **左对齐到按钮左边缘**，不要右对齐：
           按钮在顶栏偏右（x≈270），浮层宽 360，右对齐算出来的 x 是负数
           → 被 clamp 到 4 → 浮层跑到窗口最左边挡住侧边栏导航。
           左对齐既符合下拉菜单的直觉，也不会越界。
        """
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            self.host.update_idletasks()
            self.anchor.update_idletasks()

            # 锚点按钮在 host 内的相对位置
            ax = self.anchor.winfo_rootx() - self.host.winfo_rootx()
            ay = self.anchor.winfo_rooty() - self.host.winfo_rooty()
            ah = self.anchor.winfo_height()

            width = POPUP_WIDTH
            host_w = self.host.winfo_width()
            host_h = self.host.winfo_height()

            # 浮层总高 = 视口高 + chrome（标题/分隔线/底部提示）
            # ⚠️ chrome 高度用**实测反推**：先按估算 place 一次，
            #    再看 canvas 实际被挤掉多少（footer 先占位 + canvas pady），
            #    补回差值，footer 才不会被挤出可视区。
            #    比硬编码常量准 —— pack 的实际分配比预估多几个像素。
            view_h = getattr(self, '_view_height', 200)
            chrome = getattr(self, '_chrome_height', CHROME_HEIGHT)
            height = view_h + chrome

            # 左对齐按钮左边缘，并夹在 host 内
            x = ax
            if x + width > host_w - 4:
                x = host_w - width - 4
            x = max(4, x)

            y = ay + ah + 2
            # 下方空间不够就往上弹
            if y + height > host_h - 4:
                y = max(4, ay - height - 2)

            self.win.place(x=x, y=y, width=width, height=height)

            # ── 反推真实 chrome 高度并修正 ──────────────────────
            # 第一次 place 后 canvas 才有实际高度。
            # canvas 实际高 < 视口高 → chrome 占了更多，浮层要再加高这么多。
            try:
                self.host.update_idletasks()
                actual_view = self._canvas.winfo_height()
                if 40 < actual_view < view_h:
                    delta = view_h - actual_view
                    height += delta
                    self._chrome_height = chrome + delta
                    if y + height > host_h - 4:
                        y = max(4, ay - height - 2)
                    self.win.place_configure(height=height, y=y)
            except Exception:
                pass
        except Exception as e:
            logging.debug(f"[设备切换] 浮层定位失败: {e}")

    # ------------------------------------------------------------------
    # 渲染（纯 Canvas）
    # ------------------------------------------------------------------

    def refresh(self):
        """重新拉设备列表并重绘内容"""
        try:
            if self.win is None or not self.win.winfo_exists():
                return
            devices = self.app.get_online_devices()
            self._render(devices)
            self._place()
        except Exception as e:
            logging.error(f"[设备切换] 刷新列表失败: {e}", exc_info=True)

    def _render(self, online_devices):
        """按「在线 / 离线与历史」分组渲染（纯 Canvas 绘制）"""
        try:
            c = self._canvas
            c.delete('all')
            self._rows = []
            self._hover_index = -1

            t = self.theme
            bg = t.color('bg_elev')
            fg = t.color('fg')
            dim = t.color('fg_dim')
            accent = t.color('accent')
            success = t.color('success')
            line = t.color('line')

            current = self.app.get_ip_address()
            # ⚠️ 当前目标可能是「10.1.246.185:5555」（带端口），
            #    而设备列表里也是带端口的 —— 但 get_ip_address() 有时返回
            #    去掉端口的形式。**两边都要归一化再比**，
            #    否则「当前设备」永远认不出来（截图里 10.1.246.185
            #    明明是当前目标，却显示成「切换到」）。
            current_norm = self._normalize(current) if current else None
            online_norm = set()
            for d in online_devices:
                online_norm.add(self._normalize(d))

            y = 4
            width = POPUP_WIDTH - 12

            # ── 在线设备分组 ──────────────────────────────
            y = self._draw_group(c, "在线设备", y, width, dim)
            if online_devices:
                for device in online_devices:
                    y = self._draw_row(
                        c, device, y, width,
                        online=True,
                        is_current=(current_norm is not None
                                    and self._normalize(device) == current_norm),
                        bg=bg, fg=fg, dim=dim, accent=accent,
                        success=success)
            else:
                c.create_text(10, y + 8, text="当前没有在线设备",
                              anchor=tk.NW, font=(FONT_UI, FS_SM), fill=dim)
                y += 24

            # ── 离线与历史分组 ────────────────────────────
            history = [d for d in self.app.ip_history
                       if self._normalize(d) not in online_norm]
            if history:
                # 分隔线
                c.create_line(6, y + 4, width - 6, y + 4, fill=line)
                y += 8
                y = self._draw_group(c, "离线与历史", y, width, dim)
                for device in history[:MAX_HISTORY_ROWS]:
                    y = self._draw_row(
                        c, device, y, width,
                        online=False,
                        is_current=(current_norm is not None
                                    and self._normalize(device) == current_norm),
                        bg=bg, fg=fg, dim=dim, accent=accent,
                        success=success)
                if len(history) > MAX_HISTORY_ROWS:
                    c.create_text(10, y + 4,
                                  text=f"还有 {len(history) - MAX_HISTORY_ROWS} 条历史记录…",
                                  anchor=tk.NW, font=(FONT_UI, FS_XS), fill=dim)
                    y += 20

            # 内容总高度 → 滚动区域
            self._content_height = y + 6
            c.configure(scrollregion=(0, 0, width, self._content_height))
            # ⚠️ 视口高度 = min(内容高, 上限)
            #    canvas 的 height 决定可视区；浮层总高 = 视口 + chrome。
            #    两者必须用同一个值，否则底部要么露白、要么被裁断。
            max_view = POPUP_MAX_HEIGHT - CHROME_HEIGHT
            view_h = max(60, min(self._content_height, max_view))
            c.configure(height=view_h)
            # 记录视口高度，_place() 用它算浮层总高
            self._view_height = view_h

            # 更新标题右侧的计数
            if hasattr(self, '_count_label') and self._count_label.winfo_exists():
                n = len(online_devices)
                self._count_label.config(text=f"在线 {n} 台")
        except Exception as e:
            logging.error(f"[设备切换] 渲染失败: {e}", exc_info=True)

    def _draw_group(self, c, text, y, width, dim):
        """画分组小标题，返回新的 y"""
        c.create_text(8, y, text=text, anchor=tk.NW,
                      font=(FONT_UI, FS_XS), fill=dim)
        return y + GROUP_HEIGHT

    def _draw_row(self, c, device, y, width, online, is_current,
                  bg, fg, dim, accent, success):
        """画一行设备条目，返回新的 y

        ⚠️ **整行都是点击热区**（不是只有 IP 文字可点）——
           之前右侧写着「可切换」却点不动，用户完全不知道该点哪。
           现在：
           - 整行绑定点击
           - 悬停整行高亮（bg_hover 底色）
           - 右侧「可切换」画成**带边框的胶囊按钮**，视觉上明确是按钮
        """
        idx = len(self._rows)
        top = y
        bottom = y + ROW_HEIGHT

        # 悬停高亮背景（默认隐藏，鼠标移入时显示）
        hover_bg = self.theme.color('bg_hover')
        tag = f'row{idx}'
        c.create_rectangle(2, top, width - 2, bottom,
                           fill=hover_bg, outline='', tags=(tag, 'hover'))
        c.tag_lower('hover')

        # 状态点：●（在线）/ ○（离线）
        dot_color = success if online else dim
        c.create_text(14, top + ROW_HEIGHT / 2,
                      text="●" if online else "○",
                      font=(FONT_UI, FS_SM), fill=dot_color,
                      anchor=tk.CENTER)

        # 设备标识（主行）
        c.create_text(28, top + 13, text=self._display_id(device),
                      anchor=tk.W, font=(FONT_MONO, FS_MD), fill=fg)

        # 型号 · 版本（副行）
        c.create_text(28, top + 31, text=self._meta_text(device, online),
                      anchor=tk.W, font=(FONT_UI, FS_XS), fill=dim)

        # 右侧标记
        if is_current:
            # 当前设备：实心主色胶囊 + 文字
            label = "当前"
            tw = 46
            c.create_rectangle(width - 12 - tw, top + 12, width - 12,
                               top + 12 + 18, fill=accent, outline='')
            c.create_text(width - 12 - tw / 2, top + 21, text=label,
                          font=(FONT_UI, FS_XS), fill=self.theme.color('accent_fg'))
        elif online:
            # 可切换：**描边胶囊**，一眼看出是个可点的按钮
            label = "切换到"
            tw = 52
            c.create_rectangle(width - 12 - tw, top + 12, width - 12,
                               top + 12 + 18, fill='', outline=success,
                               width=1)
            c.create_text(width - 12 - tw / 2, top + 21, text=label,
                          font=(FONT_UI, FS_XS), fill=success)

        self._rows.append((device, top, bottom))
        return bottom + 2

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _row_at(self, y):
        """找到 y 坐标落在哪一行"""
        for i, (device, top, bottom) in enumerate(self._rows):
            if top <= y <= bottom:
                return i
        return -1

    def _on_click(self, event):
        """点击某一行 → 切换到该设备"""
        try:
            idx = self._row_at(self._canvas.canvasy(event.y))
            if idx < 0:
                return
            device = self._rows[idx][0]
            self.hide()
            self.app.select_device(device)
        except Exception as e:
            logging.error(f"[设备切换] 选中设备失败: {e}", exc_info=True)

    def _on_motion(self, event):
        """鼠标移动 → 高亮所在行"""
        try:
            idx = self._row_at(self._canvas.canvasy(event.y))
            if idx == self._hover_index:
                return
            # 取消旧高亮
            if 0 <= self._hover_index < len(self._rows):
                self._canvas.itemconfigure(
                    f'row{self._hover_index}', fill=self.theme.color('bg_elev'))
            self._hover_index = idx
            # 高亮新行
            if idx >= 0:
                self._canvas.itemconfigure(
                    f'row{idx}', fill=self.theme.color('bg_hover'))
            self._canvas.configure(cursor='hand2' if idx >= 0 else '')
        except Exception:
            pass

    def _on_leave(self, event=None):
        """鼠标移出 → 取消高亮"""
        try:
            if 0 <= self._hover_index < len(self._rows):
                self._canvas.itemconfigure(
                    f'row{self._hover_index}', fill=self.theme.color('bg_elev'))
            self._hover_index = -1
            self._canvas.configure(cursor='')
        except Exception:
            pass

    def _on_mousewheel(self, event):
        """滚轮滚动"""
        try:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        except Exception:
            pass

    def _on_root_click(self, event):
        """点击主窗口其它地方 → 关闭浮层"""
        try:
            if not self.is_open():
                return
            widget = self.app.root.winfo_containing(event.x_root, event.y_root)
            if widget is None:
                self.hide()
                return
            # 在浮层内则不关
            w = str(widget)
            if w.startswith(str(self.win)):
                return
            self.hide()
        except Exception:
            pass

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

    def _load_meta_async(self, device):
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
            parts = [p for p in (meta.get('model'), meta.get('version')) if p]
            if not parts:
                return
            # 找到该行对应的副标题 item 并更新文字
            for i, (d, top, bottom) in enumerate(self._rows):
                if d == device:
                    # 副标题在 create_text 时是第 4 个 item（背景/点/主行/副行）
                    items = self._canvas.find_overlapping(
                        28, top + 26, 28 + 200, top + 36)
                    for it in items:
                        if self._canvas.type(it) == 'text':
                            self._canvas.itemconfigure(it, text=' · '.join(parts))
                            break
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
        output, ok = run_adb_command(
            "adb shell getprop", retries=1, timeout=8, target_device=device)
        if not ok or not output:
            return {}
        props = parse_getprop_all(output)
        return {
            'model': props.get('ro.product.model', ''),
            'version': props.get('ro.build.version.release', ''),
        }
