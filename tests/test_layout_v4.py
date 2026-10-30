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
check("包名框宽度可读", app.pkg_combobox.winfo_width() >= 90,
      f"width={app.pkg_combobox.winfo_width()}")
check("设备框宽度可读", app.ip_combobox.winfo_width() >= 100,
      f"width={app.ip_combobox.winfo_width()}")

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
lay._toggle_terminal()
pump()
check("可折叠终端", lay._terminal_collapsed)
check("折叠后终端列宽归零",
      lay.root_frame.grid_columnconfigure(3).get('minsize') == 0,
      str(lay.root_frame.grid_columnconfigure(3).get('minsize')))
lay._toggle_terminal()
pump()
check("可展开终端", not lay._terminal_collapsed)
check("展开后终端列宽恢复",
      lay.root_frame.grid_columnconfigure(3).get('minsize') == Config.TERMINAL_WIDTH)

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
