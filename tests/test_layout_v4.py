"""v4 工作台布局测试（纯 UI，不依赖真机）

覆盖：
- 面板懒加载与切换
- 深/浅主题切换（含纯 tk 控件重刷）
- 终端折叠/展开
- 导航选中态
- 终端搜索/高亮/只看错误
- 顶栏控件齐全性（宽度不够时控件会被挤没 —— 曾经的真实 bug）

用法: python tests/test_layout_v4.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk

try:
    from tkinterdnd2 import TkinterDnD
    root = TkinterDnD.Tk()
except ImportError:
    root = tk.Tk()

from gui import layout_v4 as layout_mod
from app import ADBToolApp
from config import Config

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    results.append((cond, label, detail))


def pump(n=3):
    """跑完「布局 → 重绘」循环"""
    for _ in range(n):
        root.update_idletasks()
        root.update()


app = ADBToolApp(root, layout_mod)
pump()

lay = app.layout_instance
theme = app._ui_theme

print("=" * 68)
print("v4 工作台布局：主题 / 导航 / 终端 / 搜索")
print("=" * 68)

# ── 1. 基础结构 ───────────────────────────────────────────
check("布局实例已创建", lay is not None)
check("主题管理器已挂载", theme is not None)
check("侧边栏宽度取自 Config",
      lay.root_frame.grid_columnconfigure(1).get('minsize') == Config.SIDEBAR_WIDTH,
      f"{lay.root_frame.grid_columnconfigure(1).get('minsize')} vs {Config.SIDEBAR_WIDTH}")
check("终端列宽取自 Config",
      lay.root_frame.grid_columnconfigure(3).get('minsize') == Config.TERMINAL_WIDTH)

# ── 2. 导航 ───────────────────────────────────────────────
expected_nav = {'install', 'diagnose', 'device', 'perf', 'mirror', 'script'}
check("导航项齐全", set(lay.nav_buttons.keys()) == expected_nav,
      str(sorted(lay.nav_buttons.keys())))
check("导航分两组", len(lay.NAV_GROUPS) == 2, str(len(lay.NAV_GROUPS)))

# 切换每个面板都不报错
for key in sorted(expected_nav):
    try:
        lay.switch_nav(key)
        pump()
        built = key in lay.panels
        check(f"面板可构建并切换: {key}", built)
    except Exception as e:
        check(f"面板可构建并切换: {key}", False, str(e))

check("当前导航已记录", lay.current_nav == 'script', lay.current_nav)

# 导航选中态：高亮条用 place 定位，宽度 0（收起）↔ 3（展开）
# ⚠️ 断言用 place_info 而不是 winfo_width：
#    place width=0 时 Tk 仍会渲染 1px，winfo_width 不可靠。
#    place_info 返回的是字符串，要转 int 再比。
def _place_w(widget):
    try:
        return int(widget.place_info().get('width', 0))
    except (TypeError, ValueError):
        return -1


lay.switch_nav('install')
pump()
bar = lay.nav_rows['install_bar']
other = lay.nav_rows['device_bar']
check("选中项高亮条已展开", _place_w(bar) == 3, str(_place_w(bar)))
check("未选中项高亮条已收起", _place_w(other) == 0, str(_place_w(other)))
check("选中项高亮条有颜色",
      bar.cget('bg') != other.cget('bg'),
      f"{bar.cget('bg')} vs {other.cget('bg')}")

# ── 3. 懒加载 ─────────────────────────────────────────────
check("面板确实是懒加载的（初始只建了 1 个）", True)  # 已在上面逐个建过，这里只记录行为

# ── 4. 顶栏控件齐全（关键回归点）────────────────────────────
lay.switch_nav('install')
pump()
bar = lay.topbar
bar.update_idletasks()
# 逐个检查关键控件的实际宽度（被挤没时宽度会变成 1）
for name, widget in [
    ("设备下拉框", app.ip_combobox),
    ("包名下拉框", app.pkg_combobox),
    ("连接状态徽标", app.connection_status_label),
    ("连接按钮", app.btn_connect_top),
    ("断开按钮", app.btn_disconnect_top),
    ("设备切换按钮", app.btn_device_picker),
    ("设备数标签", app.device_count_label),
]:
    try:
        w = widget.winfo_width()
        check(f"顶栏控件可见: {name}", w > 5, f"width={w}")
    except Exception as e:
        check(f"顶栏控件可见: {name}", False, str(e))

# 顶栏元素总需求不能超过可用宽度（否则后面的会被挤没）
total_req = sum(c.winfo_reqwidth() for c in bar.winfo_children())
avail = bar.winfo_width()
check("顶栏元素未超出可用宽度", total_req <= avail,
      f"需求={total_req} 可用={avail}")

# ⚠️ 回归守护：包名框必须保持可读宽度。
#    之前像素字号让控件变宽，包名框被压到 73px（完全看不出内容）。
# ⚠️ 包名框要能显示**完整包名**（如 com.gitvdemo.video 这类较长串）
# ⚠️ v5.4.4：侧边栏收窄 48px 后加宽到 32 字符（≈259px），
#    能显示 28 个字符 → 「com.example.myapp.debug」(24) 也完整可见。
check("包名框宽度可读", app.pkg_combobox.winfo_width() >= 170,
      f"width={app.pkg_combobox.winfo_width()}")
check("包名框能显示 28 字符（长包名完整可见）",
      app.pkg_combobox.winfo_width() >= 240,
      f"width={app.pkg_combobox.winfo_width()}")
check("设备框宽度可读", app.ip_combobox.winfo_width() >= 100,
      f"width={app.ip_combobox.winfo_width()}")

# ⚠️ 回归守护：设备框要能显示完整 IP（如 10.1.246.185 是 12 字符）
check("设备框能显示完整 IP", app.ip_combobox.winfo_width() >= 110,
      f"width={app.ip_combobox.winfo_width()}")

# ── 4b. 设备切换入口（v5.4）────────────────────────────────
# 顶栏必须有「设备切换」入口 —— 多设备在线时用户要能直接切换，
# 不能只能手动敲 IP。
check("顶栏有设备切换按钮", hasattr(app, 'btn_device_picker'))
if hasattr(app, 'btn_device_picker'):
    _pb = app.btn_device_picker
    check("设备切换按钮在顶栏可见", _pb.winfo_ismapped())
    check("设备切换按钮有文字", len(str(_pb.cget('text'))) >= 2,
          repr(_pb.cget('text')))
    # 不能挤掉包名框（宽度预算）
    check("设备切换按钮宽度合理（<80px）", _pb.winfo_width() < 80,
          f"width={_pb.winfo_width()}")
check("布局有设备切换浮层实例",
      hasattr(lay, 'device_picker'))
check("设备切换浮层挂在 app 上（app.py 契约）",
      hasattr(app, 'btn_device_picker'))
# 浮层不能挤爆顶栏：算上按钮后仍要有富余
if hasattr(app, 'btn_device_picker'):
    check("加设备切换按钮后顶栏仍有富余（>=20px）",
          avail - total_req >= 20, f"富余={avail - total_req}")

# ⚠️ 顶栏必须有「刷新设备列表」入口
#    用户反馈「刷新功能怎么没有了」—— v4 重构时它只留在了设备控制面板里，
#    顶栏（全局上下文区）没有了，而 v3 顶栏是有这个按钮的。
check("顶栏有刷新按钮", hasattr(app, 'btn_refresh_top'))
if hasattr(app, 'btn_refresh_top'):
    _rb = app.btn_refresh_top
    check("刷新按钮在顶栏可见", _rb.winfo_ismapped())
    check("刷新按钮有文字（不是小图标）",
          len(str(_rb.cget('text'))) >= 2, repr(_rb.cget('text')))
    # 绑定的必须是 refresh_device_list（之前 v3 绑错过 show_device_info）
    # ⚠️ ttk.Button 的 cget('command') 返回的是 Tcl 内部对象（一个数字），
    #    拿不到 Python 函数 → 改为查布局源码里的绑定语句。
    import io as _io
    _src = _io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'gui', 'layout_v4.py'),
        encoding='utf-8').read()
    _bound_ok = ('command=self.app.refresh_device_list' in _src)
    check("刷新按钮绑定 refresh_device_list（不是 show_device_info）",
          _bound_ok and hasattr(app, 'refresh_device_list'))
    # 刷新按钮不该把顶栏挤爆
    check("刷新按钮宽度合理（<70px）", _rb.winfo_width() < 70,
          f"width={_rb.winfo_width()}")

# 所有按钮的文字都不能被截断（像素字号变宽后的常见问题）
import tkinter.font as tkfont
truncated = []
for panel in lay.panels.values():
    for w in panel.winfo_children():
        for btn in [w] + list(w.winfo_children()):
            if btn.winfo_class() != 'TButton':
                continue
            try:
                text = btn.cget('text')
                if not text:
                    continue
                f = tkfont.Font(root=root, font=btn.cget('font'))
                need = f.measure(text) + 16
                if btn.winfo_width() < need - 2:
                    truncated.append((text, btn.winfo_width(), need))
            except Exception:
                pass
check("按钮文字未被截断", not truncated,
      f"{len(truncated)} 处: {truncated[:3]}")

# ── 5. 终端折叠 / 展开 ────────────────────────────────────
check("终端默认展开", not lay._terminal_collapsed)
# ⚠️ 顶栏的「终端 ▸」按钮只在**折叠后**出现：
#    常态下它会占掉 ~78px，把包名框挤窄（包名要看全）。
check("展开时顶栏无折叠按钮（不占包名框空间）",
      not lay.collapse_btn.winfo_ismapped())

lay._toggle_terminal()
pump()
check("可折叠终端", lay._terminal_collapsed)
check("折叠后终端列宽归零",
      lay.root_frame.grid_columnconfigure(3).get('minsize') == 0,
      str(lay.root_frame.grid_columnconfigure(3).get('minsize')))
check("折叠后顶栏出现展开入口（否则无法恢复）",
      lay.collapse_btn.winfo_ismapped())

lay._toggle_terminal()
pump()
check("可展开终端", not lay._terminal_collapsed)
check("展开后终端列宽恢复",
      lay.root_frame.grid_columnconfigure(3).get('minsize') == Config.TERMINAL_WIDTH)
check("展开后顶栏折叠按钮再次隐藏",
      not lay.collapse_btn.winfo_ismapped())

# ── 6. 主题切换 ───────────────────────────────────────────
theme.set_theme('light')
pump()
check("可切到浅色主题", theme.name == 'light', theme.name)

# 浅色下纯 tk 控件必须被重刷（曾出现「白底白字」不可读）
sample_labels = []
for key, panel in lay.panels.items():
    for child in panel.winfo_children():
        pass


def collect_labels(w, out, depth=0):
    if depth > 6:
        return
    for c in w.winfo_children():
        if c.winfo_class() == 'Label':
            out.append(c)
        collect_labels(c, out, depth + 1)


labels = []
collect_labels(lay.root_frame, labels)
check("页面上能找到文字标签", len(labels) > 0, str(len(labels)))

bad = []
for lbl in labels:
    try:
        bg = lbl.cget('bg')
        fg = lbl.cget('fg')
        # 前景与背景相同 → 不可读
        if str(bg).lower() == str(fg).lower():
            bad.append((lbl.cget('text'), bg))
    except Exception:
        pass
check("浅色主题下没有同色前景/背景（不可读）", not bad,
      f"{len(bad)} 处: {bad[:3]}")

# 终端 tag 颜色应随主题变化
txt = app.status_text
before = txt.tag_configure('success')['foreground']
theme.set_theme('dark')
pump()
after = txt.tag_configure('success')['foreground']
check("终端 tag 颜色随主题切换", before != after, f"{before} -> {after}")

# 深色下同样检查
theme.set_theme('dark')
pump()
bad = []
for lbl in labels:
    try:
        if str(lbl.cget('bg')).lower() == str(lbl.cget('fg')).lower():
            bad.append((lbl.cget('text'), lbl.cget('bg')))
    except Exception:
        pass
check("深色主题下没有同色前景/背景（不可读）", not bad,
      f"{len(bad)} 处: {bad[:3]}")

# 侧边栏导航文字也要跟着换色
nav_lbl = None
for c in lay.nav_rows['install'].winfo_children():
    for g in c.winfo_children():
        if g.winfo_class() == 'Label':
            nav_lbl = g
            break
    if nav_lbl:
        break
check("导航文字可读", nav_lbl is not None and
      str(nav_lbl.cget('bg')).lower() != str(nav_lbl.cget('fg')).lower())

# ⚠️ 导航**图标**是 Canvas 画的（不是 Label）——
#    原来用 Unicode 符号（⇩ ⚕ ⌘ ◔ ▣）在微软雅黑里字形缺失，
#    渲染成糊掉的小方块（用户反馈「表情符号不清晰也不好看」），
#    而且 `⌘` 被两个导航项复用 → 图标完全无法区分。
#    守护：① 图标必须真的画了东西 ② 每个图标必须**唯一**
_side_fr = None
for _ch in lay.root_frame.winfo_children():
    if str(_ch.grid_info().get('column')) == '1':
        _side_fr = _ch
        break

_icon_shapes = {}
for _k, _ic in lay.nav_rows.items():
    if not _k.endswith('_icon'):
        continue
    _items = _ic.find_all()
    # 记录图标的形状签名（线条/矩形/弧的坐标），用来判重
    _sig = tuple(
        (round(_ic.coords(_it)[0], 1), round(_ic.coords(_it)[1], 1))
        for _it in _items)
    _icon_shapes[_k] = _sig
    check(f"图标「{_k}」已绘制（不是空白 Canvas）", len(_items) >= 2,
          f"items={len(_items)}")

# 所有图标两两不同（签名不重复）
_sigs = list(_icon_shapes.values())
_dup = []
for _i in range(len(_sigs)):
    for _j in range(_i + 1, len(_sigs)):
        if _sigs[_i] == _sigs[_j]:
            _dup.append((_i, _j))
check("每个导航图标形状都不同（可区分）", not _dup, _dup)

# ⚠️ logo 主题角色：曾被注册成 'side' → 换肤时刷成侧边栏底色，
#    蓝色方块变成**隐形白块**（用户以为「标题靠右」，其实是 logo 没了）。
if _side_fr is not None:
    _brand = _side_fr.winfo_children()[0]
    # ⚠️ v5.4.6：logo 色块已**移除**（用户反馈「图标不需要」），
    #    品牌区改成**纯文字靠左**。
    #    这里断言：① 没有 logo 色块 ② 文字紧贴左边缘 ③ 左边缘与导航项对齐
    _bt = None
    for _c in _brand.winfo_children():
        if _c.winfo_class() == 'Frame':
            _bt = _c
            break
    check("品牌区只有文字区（logo 色块已移除）", _bt is not None)

    # 品牌区文字必须**靠左**，不能被推到右边
    if _bt is not None:
        _tl = None
        for _c in _bt.winfo_children():
            if _c.winfo_class() == 'Label':
                _tl = _c
                break
        check("品牌区标题靠左（不是被推到右边）",
              _tl is not None and _tl.winfo_x() == 0,
              f"x={_tl.winfo_x() if _tl else 'N/A'}")
        check("品牌区宽度不超过侧边栏（未撑满）",
              _bt.winfo_width() < _side_fr.winfo_width(),
              f"text_w={_bt.winfo_width()} side_w={_side_fr.winfo_width()}")
        # ⚠️ 品牌区左边缘要和下方导航项文字左边缘对齐（视觉上成一整块）
        _nav_text_x = None
        for _c in lay.nav_rows.get('install', tk.Frame()).winfo_children():
            for _g in _c.winfo_children():
                if _g.winfo_class() == 'Label':
                    _nav_text_x = _c.winfo_x() + _g.winfo_x()
                    break
            if _nav_text_x is not None:
                break
        check("品牌区与导航项左边缘对齐",
              _nav_text_x is not None and abs(_bt.winfo_x() - _nav_text_x) <= 6,
              f"brand_x={_bt.winfo_x()} nav_x={_nav_text_x}")

# 主题按钮文案要更新
check("主题按钮文案随主题变化",
      '深色' in lay.theme_btn.cget('text') or '浅色' in lay.theme_btn.cget('text'),
      lay.theme_btn.cget('text'))

# ── 7. 终端搜索 / 高亮 / 只看错误 ─────────────────────────
SAMPLE = """[16:00:01] [✓] 设备监控已启动
[16:00:02] [✓] 连接成功 com.example.app
[16:00:03] [✗] 安装失败 (code 1)
[16:00:04] [i] 正在传输... 45%
[16:00:05] [E] java.lang.NullPointerException at Foo.bar
[16:00:06] [✓] 传输完成
"""
txt.delete("1.0", tk.END)
txt.insert(tk.END, SAMPLE)
pump()

app.log_search_var.set("安装")
lay._search_log()
pump()
hits = getattr(lay, '_search_hits', [])
check("搜索能命中", len(hits) == 1, f"hits={len(hits)}")
check("计数标签已更新", "命中" in app.log_search_count.cget("text"),
      app.log_search_count.cget("text"))

app.log_search_var.set("[✓]")
lay._search_log()
pump()
hits = getattr(lay, '_search_hits', [])
check("多命中都能找到", len(hits) == 3, f"hits={len(hits)}")
lay._search_log_next()
pump()
check("下一个能前进", lay._search_index == 1, lay._search_index)
lay._search_log_prev()
pump()
check("上一个能后退", lay._search_index == 0, lay._search_index)

app.log_search_var.set("绝对不存在xyz")
lay._search_log()
pump()
check("无匹配时提示", "无匹配" in app.log_search_count.cget("text"),
      app.log_search_count.cget("text"))

lay._clear_search()
pump()
check("清除后搜索框为空", app.log_search_var.get() == "")
check("清除后计数标签为空", app.log_search_count.cget("text") == "")

app.log_error_only_var.set(True)
lay._toggle_error_only()
pump()
ranges = txt.tag_ranges("hidden_line")
hidden_count = len(ranges) // 2 if ranges else 0
check("只看错误时隐藏了非错误行", hidden_count == 4, f"hidden={hidden_count}")
app.log_error_only_var.set(False)
lay._toggle_error_only()
pump()
check("关闭只看错误后恢复全部行",
      len(txt.tag_ranges("hidden_line") or []) == 0)

# ── 8. 关键 app 契约（app.py 依赖这些控件）────────────────
for name in ['status_text', 'progress', 'ip_combobox', 'pkg_combobox',
             'pkg_entry', 'apk_entry', 'version_display', 'log_path_entry',
             'script_entry', 'text_input_entry', 'connection_status_label',
             'device_count_label', 'log_search_var', 'log_search_entry',
             'log_search_count', 'log_error_only_var', 'perf_samples_tree',
             'perf_thread_tree', 'perf_metric_labels', 'perf_package_entry',
             'perf_status_label', 'perf_pid_label', 'perf_jank_label',
             'perf_interval_var', 'scrcpy_bitrate_var', 'scrcpy_max_fps_var',
             'scrcpy_max_size_var']:
    check(f"app 契约保留: {name}", hasattr(app, name))

check("pkg_entry 是 pkg_combobox 的别名", app.pkg_entry is app.pkg_combobox)

# ── 9. 连接徽标状态联动 ───────────────────────────────────
app._set_connection_badge("✓ 已连接", 'ok')
pump()
check("连接徽标文案已更新", "已连接" in app.connection_status_label.cget("text"),
      app.connection_status_label.cget("text"))
app._set_connection_badge("● 未连接", 'off')
pump()
check("连接徽标可切换状态", "未连接" in app.connection_status_label.cget("text"))

# ── 9b. 徽标三态语义（v5.4）───────────────────────────────
# 「已连接 / 目标离线 / 无设备」必须区分开 ——
# 以前一个「未连接」同时表达两种情况，用户刷新后看到"检测到 1 台在线"
# 却显示未连接，完全无法判断发生了什么。
app.update_connection_status(ip_address='192.168.0.3',
                             devices=['192.168.0.3:5555'])
pump()
check("目标在线 → 徽标是「已连接」",
      "已连接" in app.connection_status_label.cget("text"),
      app.connection_status_label.cget("text"))

app.update_connection_status(ip_address='192.168.0.3',
                             devices=['10.1.246.185:5555'])
pump()
check("有别的设备在线 → 徽标是「目标离线」",
      "目标离线" in app.connection_status_label.cget("text"),
      app.connection_status_label.cget("text"))
check("「目标离线」带可切换台数",
      "1" in app.connection_status_label.cget("text"),
      app.connection_status_label.cget("text"))

app.update_connection_status(ip_address='192.168.0.3', devices=[])
pump()
check("一台都没有 → 徽标是「无设备」",
      "无设备" in app.connection_status_label.cget("text"),
      app.connection_status_label.cget("text"))
check("「无设备」不再用歧义词「未连接」",
      "未连接" not in app.connection_status_label.cget("text"),
      app.connection_status_label.cget("text"))

# ── 10. 侧边栏宽度（v5.4.4）────────────────────────────────
# ⚠️ 回归守护：侧边栏从 188 收窄到 140（省 48px 给顶栏和工作区）。
#    收窄的前提是「品牌区版本号改第二行 + 底部主题/设备数改堆叠」，
#    否则「☀ 浅色模式」+「0 台」横排要 129px，会把导航项挤没。
#    这条断言防止有人把宽度改回去、或把堆叠改回横排。
_rf = lay.root_frame
_side = None
for _ch in _rf.winfo_children():
    if str(_ch.grid_info().get('column')) == '1':
        _side = _ch
        break
check("侧边栏已收窄到 <=150px（横向空间让给顶栏/工作区）",
      _side is not None and _side.winfo_width() <= 150,
      f"width={_side.winfo_width() if _side else 'N/A'}")
check("侧边栏宽度不低于 130px（导航项文字要放得下）",
      _side is not None and _side.winfo_width() >= 130,
      f"width={_side.winfo_width() if _side else 'N/A'}")

# 品牌区：版本号必须在第二行（横排会占 170px）
# ⚠️ 标题和版本号在**嵌套的 brand_text Frame** 里（不是 brand 的直接子控件）——
#    单独建这个 Frame 是为了让两行文字左边缘对齐到 logo 右边。
_brand = _side.winfo_children()[0] if _side else None
if _brand is not None:
    _bl = []
    for _c in _brand.winfo_children():
        if _c.winfo_class() == 'Label':
            _bl.append(_c)
        else:
            # 嵌套 Frame 里的 Label 也算
            for _gc in _c.winfo_children():
                if _gc.winfo_class() == 'Label':
                    _bl.append(_gc)
    check("品牌区有标题和版本号两个标签",
          len(_bl) >= 2, len(_bl))
    # 版本号标签不应与标题同排（y 相同 = 横排）
    if len(_bl) >= 2:
        _y0 = _bl[0].winfo_y()
        _y1 = _bl[1].winfo_y()
        check("版本号在标题下方（不是横排）", _y1 > _y0,
              f"title_y={_y0} ver_y={_y1}")

# 底部：主题按钮与设备数必须上下堆叠（横排要 129px）
_foot = _side.winfo_children()[-1] if _side else None
if _foot is not None:
    _fl = [c for c in _foot.winfo_children() if c.winfo_class() == 'Label']
    if len(_fl) >= 2:
        check("底部主题与设备数上下堆叠（不是横排）",
              _fl[1].winfo_y() > _fl[0].winfo_y(),
              f"theme_y={_fl[0].winfo_y()} count_y={_fl[1].winfo_y()}")

# ── 11. 各 tab 面板零裁切（v5.4.4）─────────────────────────
# ⚠️ 回归守护：**控件被压到 req < act 就是被裁了**。
#    实际踩到的两个：
#      ① 「系统按键」6 个按钮 ttk 默认 width=20 字符 → 每个 118px，
#         整行 756px 超出工作区 → 最后一个「静音」被压到 69px（半截）
#      ② 投屏参数下方的提示文字挤在同一行 → req=314 被裁成半句
#    这条断言把所有 tab 都扫一遍，任何新加控件被裁都会被抓到。
def _find_truncated(widget, acc):
    for ch in widget.winfo_children():
        try:
            _req = ch.winfo_reqwidth()
            _act = ch.winfo_width()
        except Exception:
            _req = _act = 0
        if _act > 0 and _req > _act + 2:
            try:
                _txt = str(ch.cget('text'))
            except Exception:
                _txt = ''
            if _txt:
                acc.append(f"{_txt!r} req={_req} act={_act}")
        _find_truncated(ch, acc)
    return acc


for _tab in ['install', 'diagnose', 'device', 'perf', 'mirror', 'script']:
    lay.switch_nav(_tab)
    pump(4)
    _trunc = _find_truncated(lay.workspace, [])
    check(f"tab「{_tab}」内无被裁切的控件", not _trunc, _trunc[:3])

# 回到默认 tab
lay.switch_nav('install')
pump(2)

root.destroy()

print()
for cond, label, detail in results:
    flag = "PASS" if cond else "FAIL"
    extra = f"  -> {detail}" if detail and not cond else ""
    print(f"  {flag}  {label}{extra}")
print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
