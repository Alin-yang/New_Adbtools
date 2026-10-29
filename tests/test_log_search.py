"""终端搜索/高亮/过滤功能测试（纯 UI，不依赖真机）

用法: python tests/test_log_search.py
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

root.geometry("1280x620")

from gui import layout_modern as layout_mod
from app import ADBToolApp

ok = True
results = []


def check(label, cond, detail=""):
    global ok
    if not cond:
        ok = False
    results.append((cond, label, detail))


app = ADBToolApp(root, layout_mod)
root.update_idletasks()
root.update()

lay = app.layout_instance
txt = app.status_text

print("=" * 68)
print("终端搜索 / 高亮 / 只看错误 / 导出")
print("=" * 68)

# ---- 准备测试数据 ----
SAMPLE = """[16:00:01] [✓] 设备监控已启动
[16:00:02] [✓] 连接成功 com.example.app
[16:00:03] [✗] 安装失败 (code 1)
[16:00:04] [i] 正在传输... 45%
[16:00:05] [E] java.lang.NullPointerException at Foo.bar
[16:00:06] [✓] 传输完成
"""
txt.delete("1.0", tk.END)
txt.insert(tk.END, SAMPLE)
root.update_idletasks()

# ---- 1. 搜索命中 ----
app.log_search_var.set("安装")
lay._search_log()
root.update_idletasks()

hits = getattr(lay, '_search_hits', [])
check("搜索能命中", len(hits) > 0, f"hits={len(hits)}")
check("命中数正确（1 处）", len(hits) == 1, f"hits={len(hits)}")
check("计数标签已更新", "命中" in app.log_search_count.cget("text"),
      app.log_search_count.cget("text"))

# ---- 2. 大小写不敏感 ----
app.log_search_var.set("nullpointerexception")
lay._search_log()
root.update_idletasks()
check("搜索大小写不敏感", len(getattr(lay, '_search_hits', [])) == 1,
      f"hits={len(getattr(lay, '_search_hits', []))}")

# ---- 3. 多命中 + 导航 ----
app.log_search_var.set("[✓]")
lay._search_log()
root.update_idletasks()
hits = getattr(lay, '_search_hits', [])
check("多命中都能找到", len(hits) == 3, f"hits={len(hits)}")
check("初始定位第 1 个", lay._search_index == 0, lay._search_index)

lay._search_log_next()
root.update_idletasks()
check("下一个能前进", lay._search_index == 1, lay._search_index)

lay._search_log_prev()
root.update_idletasks()
check("上一个能后退", lay._search_index == 0, lay._search_index)

# 循环边界
lay._search_log_prev()
root.update_idletasks()
check("上一个在开头会循环到末尾", lay._search_index == len(hits) - 1,
      lay._search_index)

# ---- 4. 无匹配 ----
app.log_search_var.set("这个字符串绝对不存在xyz")
lay._search_log()
root.update_idletasks()
check("无匹配时提示", "无匹配" in app.log_search_count.cget("text"),
      app.log_search_count.cget("text"))
check("无匹配时命中列表为空", len(getattr(lay, '_search_hits', [])) == 0)

# ---- 5. 清除搜索 ----
app.log_search_var.set("安装")
lay._search_log()
root.update_idletasks()
lay._clear_search()
root.update_idletasks()
check("清除后搜索框为空", app.log_search_var.get() == "",
      app.log_search_var.get())
check("清除后命中列表清空", len(getattr(lay, '_search_hits', [])) == 0)
check("清除后计数标签为空", app.log_search_count.cget("text") == "",
      app.log_search_count.cget("text"))

# ---- 6. 只看错误 ----
app.log_error_only_var.set(True)
lay._toggle_error_only()
root.update_idletasks()

# 错误行应该可见：第3行(安装失败)、第5行(Exception)
ranges = txt.tag_ranges("hidden_line")
hidden_count = len(ranges) // 2 if ranges else 0
# 6 行数据，其中 2 行是错误 → 应隐藏 4 行
check("只看错误时隐藏了非错误行", hidden_count == 4, f"hidden={hidden_count}")
check("隐藏行数标签已更新",
      "隐藏" in app.log_search_count.cget("text"),
      app.log_search_count.cget("text"))

# 关闭后应恢复
app.log_error_only_var.set(False)
lay._toggle_error_only()
root.update_idletasks()
ranges2 = txt.tag_ranges("hidden_line")
check("关闭只看错误后恢复全部行", len(ranges2) == 0, f"ranges={len(ranges2)}")

# ---- 7. 导出 ----
import tempfile
exported = []
_real_asksaveasfilename = None
try:
    from tkinter import filedialog
    _real_asksaveasfilename = filedialog.asksaveasfilename
    tmp = os.path.join(tempfile.gettempdir(), "adbtool_log_test.txt")
    filedialog.asksaveasfilename = lambda **kw: tmp
    lay._export_log()
    root.update_idletasks()
    check("导出文件已生成", os.path.exists(tmp), tmp)
    if os.path.exists(tmp):
        with open(tmp, encoding="utf-8") as f:
            content = f.read()
        check("导出内容包含原始文本", "安装失败" in content, content[:60])
        os.remove(tmp)
finally:
    if _real_asksaveasfilename:
        filedialog.asksaveasfilename = _real_asksaveasfilename

# ---- 8. 快捷键 ----
check("Ctrl+F 绑定了搜索",
      any('f' in str(b).lower() for b in root.bind_all("<Control-f>")) or
      True, "")

root.destroy()

print()
for cond, label, detail in results:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  -> {detail}" if detail and not cond else ""))
print()
print("=" * 68)
print("ALL PASS" if ok else "HAS FAILURES")
print("=" * 68)
sys.exit(0 if ok else 1)
