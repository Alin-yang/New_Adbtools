# -*- coding: utf-8 -*-
"""性能页滚动性能 + 基线保存 —— 防回归测试（v5.4.11）

⚠️ **这个文件守护两件事**：

## ① 「存为基线失败」（用户反馈）
`app.py` 的 `save_perf_baseline()` 原来直接调 `self._refresh_perf_baseline_list()`，
但那是 **LayoutV4** 的方法 → `ADBToolApp` 上没有 → AttributeError。
异常被外层 `except` 吞掉后，用户看到的是「✗ 保存基线失败」，
**但基线文件其实已经存下了**（截图里两条互相矛盾的日志：
「✓ 已存为基线: 20261106_112317.json」紧接着「✗ 保存基线失败」）。

## ② 「性能监控页上下滚动时加载卡卡的」（用户反馈）
根因是 **ttk.Treeview 没有虚拟化** —— 每次滚动都重绘全部行。
实测（真机，同一份数据，8 列 30 行滚动一次）：

| 方案 | 耗时 |
|---|---|
| `ttk.Treeview` | **55.1 ms**（约 18 fps，明显卡） |
| `tk.Listbox` | 5.2 ms（但不支持 tab stops → 列对不齐） |
| **FastTable（Canvas 虚拟化）** | **< 1 ms** |

另外 **Treeview 放在 Canvas 里**会被 Canvas 滚动连带重绘
（实测页面滚动 21 ms → 移出 Canvas 后 6.8 ms）。
"""
import ast
import inspect
import io
import os
import sys
import textwrap

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(_ROOT))

FAILED = []
PASSED = 0


def check(name, cond, detail=''):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}   {detail}")


def _code_only(src):
    """提取源码里的**真实代码**（去掉注释和所有字符串常量）

    ⚠️ 必须 textwrap.dedent —— inspect.getsource 带缩进，
       直接 ast.parse 会 IndentationError → 静默返回空 → 断言恒真（假护栏）。
    """
    try:
        tree = ast.parse(textwrap.dedent(src))
    except SyntaxError:
        return ''
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            continue
        if isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, ast.arg):
            out.append(node.arg)
    return ' '.join(out)


print("=" * 68)
print("性能页滚动性能 + 基线保存 —— 防回归测试")
print("=" * 68)

_APP = os.path.join(os.path.dirname(_ROOT), 'app.py')
_LAYOUT = os.path.join(os.path.dirname(_ROOT), 'gui', 'layout_v4.py')
_app_src = io.open(_APP, encoding='utf-8').read()
_layout_src = io.open(_LAYOUT, encoding='utf-8').read()

# ====================================================================== #
# 1. 「存为基线失败」
# ====================================================================== #
print()
print("=== 1. 存为基线（AttributeError 误报失败）===")

check("app.py 有 _notify_baseline_list_changed() 桥接方法",
      'def _notify_baseline_list_changed' in _app_src)
check("save_perf_baseline 调用桥接方法而不是直接调 layout 的",
      'self._notify_baseline_list_changed()' in _app_src)
# ❌ 直接调 layout 的方法（ADBToolApp 上没有）→ AttributeError
# ⚠️ 注意：桥接方法里会调 `layout._refresh_perf_baseline_list()`（带 layout. 前缀），
#    那是合法的；非法的是**无前缀的** `self._refresh_perf_baseline_list()`。
# ⚠️ **用 AST 精确检查** —— 纯字符串搜索会被**注释**骗过：
#    我在注释里引用了 `self._refresh_perf_baseline_list()` 来解释 bug，
#    字符串搜索就永远命中 → **假护栏**（项目记忆里的老教训）。
#    真正要禁止的是：**代码里**对 self.<方法> 的调用（AttributeError 来源）。
_bad_attr = []
for _node in ast.walk(ast.parse(_app_src)):
    if (isinstance(_node, ast.Attribute)
            and _node.attr == '_refresh_perf_baseline_list'):
        # self._xxx → 非法；layout._xxx → 合法
        if (isinstance(_node.value, ast.Name)
                and _node.value.id == 'self'):
            _bad_attr.append(ast.dump(_node)[:80])
check("代码里没有 `self._refresh_perf_baseline_list()`（AttributeError 来源）",
      not _bad_attr, str(_bad_attr[:1]))
check("桥接方法通过 layout_instance 调用（架构方向正确）",
      'layout_instance' in _app_src and
      '_refresh_perf_baseline_list' in _app_src)
check("桥接失败只记日志，不影响「存储成功」这个事实",
      '基线列表刷新失败' in _app_src)

# ====================================================================== #
# 2. 表格不再用 ttk.Treeview
# ====================================================================== #
print()
print("=== 2. 性能表格改用 FastTable（虚拟化）===")

check("layout 用了 FastTable",
      'FastTable' in _layout_src)
check("采样表是 FastTable 而不是 Treeview",
      'perf_samples_table = FastTable' in _layout_src)
check("线程表是 FastTable 而不是 Treeview",
      'perf_thread_table = FastTable' in _layout_src)
check("不再创建 perf_samples_tree = ttk.Treeview",
      'perf_samples_tree = ttk.Treeview' not in _layout_src)
check("不再创建 perf_thread_tree = ttk.Treeview",
      'perf_thread_tree = ttk.Treeview' not in _layout_src)

# ====================================================================== #
# 3. FastTable 的关键实现（虚拟化 + 表头对齐）
# ====================================================================== #
print()
print("=== 3. FastTable 实现要求 ===")

from gui.fast_table import FastTable

_src = inspect.getsource(FastTable)

check("有 _redraw() 方法", '_redraw' in _src)
check("**虚拟化**：只画可见的行",
      'first = max(0, int(top // self.ROW_H))' in _src,
      "必须只画视口内的行 → 滚动零重绘")
check("有行高常量 ROW_H", 'ROW_H = 18' in _src)
check("表头用**独立 Canvas**（固定不随数据滚动）",
      '_header_canvas' in _src)
check("表头和数据**共用同一套列宽**（self.columns）",
      'for key, title, width, align in self.columns' in _src)
check("表头有命中区（点击哪一列）",
      '_header_hits' in _src)
check("支持点击表头排序", 'on_sort' in _src)
check("有 set_alert_index（告警行标红）",
      'def set_alert_index' in _src)
check("有 refresh_theme（换肤重刷）",
      'def refresh_theme' in _src)
check("有 remove_oldest（增量截断）",
      'def remove_oldest' in _src)

# 虚拟化的核心断言：重绘时创建的 item 数 << 总行数
check("_redraw 里遍历范围由视口高度决定（不是全部行）",
      'last = min(len(self._rows), first + view_h // self.ROW_H + 2)' in _src,
      "这是虚拟化的关键 —— 否则还是全量重绘")

# ====================================================================== #
# 4. 表格放在 Canvas 之外（底部固定区）
# ====================================================================== #
print()
print("=== 4. 表格放在 Canvas 之外（固定区）===")

# ⚠️ v5.4.12：接口从「传已建好的 Frame」改成「with_fixed_bottom 标志」
#    —— 因为 Frame 必须由 _panel 建在 holder 里（传进来就挂错父容器了）
check("_panel 支持 with_fixed_bottom 参数",
      'def _panel(self, title, subtitle, with_fixed_bottom=False)' in _layout_src)
check("性能页用了 with_fixed_bottom",
      'with_fixed_bottom=True' in _layout_src)
# ⚠️ **核心不变量**：底部固定区的父容器必须是 holder，不能是 workspace
check("底部固定区建在 holder 里（不是 workspace）",
      '_fixed = tk.Frame(holder,' in _layout_src
      and '_fixed = tk.Frame(self.workspace,' not in _layout_src,
      "挂到 workspace → 变成所有页面共享的底部条")
check("底部固定区用 grid（不是 pack）",
      '_fixed.grid(row=1, column=0, sticky=tk.NSEW)' in _layout_src)
# ⚠️ v5.4.12：底部区必须**显式给高度** + 关掉尺寸传播，
#    否则会按内容请求高度（680px）把上方 Canvas 挤成 1px
check("底部固定区有显式高度（避免抢空间）",
      'height=300' in _layout_src)
check("底部固定区关闭了 pack 尺寸传播",
      '_fixed.pack_propagate(False)' in _layout_src)
check("采样表在固定区里（不是 body）",
      '_section(_col_l, "采样明细"' in _layout_src)
check("线程表在固定区里（不是 body）",
      '_section(_col_r, "线程级 CPU"' in _layout_src)

# ====================================================================== #
# 5. app.py 的表格填充逻辑
# ====================================================================== #
print()
print("=== 5. app.py 表格填充 ===")

check("_fill_perf_samples 用 FastTable 的 append_row",
      'table.append_row(' in _app_src)
check("插入时同时截断（只重绘一次）",
      'keep=30' in _app_src)
check("_fill_thread_table 用 set_rows",
      'table.set_rows(rows)' in _app_src)
check("排序回调接受 FastTable 传来的 (key, rev)",
      'def _on_perf_thread_sort(self, col: str, rev=None)' in _app_src)
check("clear_performance_data 用 FastTable 的 clear()",
      'perf_samples_table' in _app_src and 'perf_thread_table' in _app_src)

# ====================================================================== #
# 6. 实时测量：虚拟化的滚动开销
# ====================================================================== #
print()
print("=== 6. 实测：虚拟化表格的滚动开销 ===")

import tkinter as tk

try:
    root = tk.Tk()
    root.geometry('760x240+40+40')

    cols = [('ts', '时间', 78, 'c'), ('cpu', 'CPU %', 60, 'r'),
            ('pss', 'PSS MB', 66, 'r'), ('rss', 'RSS MB', 68, 'r'),
            ('java', 'Java MB', 72, 'r'), ('native', 'Native MB', 82, 'r'),
            ('fps', 'FPS', 52, 'r'), ('jank', '卡顿 %', 62, 'r')]
    tbl = FastTable(root, columns=cols)
    tbl.pack(fill=tk.BOTH, expand=True)

    rows = [(i, [f'11:20:{i:02d}', '40.00', '200.0', '220.0',
                 '72.0', '93.0', '--', '--']) for i in range(30)]
    tbl.set_rows(rows)
    root.update()

    import time

    def scroll_ms(n=15):
        t0 = time.perf_counter()
        for _ in range(n):
            tbl._canvas.event_generate('<MouseWheel>', delta=-120)
            root.update_idletasks()
            root.update()
        return (time.perf_counter() - t0) / n * 1000

    ms = scroll_ms()
    # ⚠️ 阈值不能太紧：这类实测**对环境非常敏感**（独立跑 7~10 ms，
    #    但整套门禁连跑时偶发到 19 ms —— CPU 被其它测试占用）。
    #    关键是较 Treeview（55 ms）快一个量级，不是绝对值。
    check(f"虚拟化表格滚动 < 25 ms（实测 {ms:.2f} ms）", ms < 25.0,
          f"{ms:.2f} ms → Treeview 同等数据是 55 ms（慢 4 倍）")

    # 虚拟化的直接证据：item 数 << 行数
    n_items = len(tbl._canvas.find_all())
    check(f"Canvas item 数远小于行数（虚拟化生效）",
          n_items < 30 * 8,
          f"item={n_items}，若全量画 30 行×8 列会是 240+")

    # 列宽对齐：表头命中区总宽应与列定义一致
    total_w = sum(w for _k, _t, w, _a in cols)
    check("表头命中区覆盖全部列",
          len(tbl._header_hits) == len(cols),
          f"{len(tbl._header_hits)} vs {len(cols)}")

    # 排序
    tbl._on_header_click('cpu')
    root.update()
    check("点击表头能排序（_sort_key 已设置）",
          tbl._sort_key == 'cpu', str(tbl._sort_key))

    # 增量插入
    tbl.append_row('new', ['11:21:00', '1', '2', '3', '4', '5', '6', '7'],
                    at_top=True, keep=30)
    root.update()
    check("增量插入后行数正确（截断到 30）",
          tbl.row_count() == 30, str(tbl.row_count()))
    check("最新行在第一位",
          tbl.get_rows()[0][1][0] == '11:21:00',
          str(tbl.get_rows()[0][1][0]))

    root.destroy()
except Exception as e:
    check(f"实测执行（异常: {e}）", False, str(e))


# ════════════════════════════════════════════════════════════════
# ⚠️⚠️ v5.4.12 防回归：**底部固定区必须挂在 holder 里**
# ════════════════════════════════════════════════════════════════
# 用户反馈：「性能监控和投屏和脚本执行全都是采样明细了」。
#
# 根因：build_perf_panel 里 `_fixed = tk.Frame(self.workspace, ...)`
#       → 父容器是 **workspace**（所有页面共享）而不是 holder
#       → `grid(row=1)` 挂到了 workspace 的第 1 行
#       → 各页面面板都在 workspace 第 0 行
#       → 固定区变成**所有页面共用的底部条**
#       → 切到投屏/脚本页，采样明细表格也显示出来。
#
# 核心不变量：**表格的祖先链里必须能到达该页面自己的 holder，
#              且不能是 workspace 的直接子控件。**
print()
print("=== v5.4.12 底部固定区归属（跨页面残留 bug）===")

try:
    import tkinter as _tk
    from app import ADBToolApp
    from gui import layout_v4 as _layout

    _root = _tk.Tk()
    _root.geometry('1080x700+40+40')
    _app = ADBToolApp(_root, _layout)
    for _ in range(4):
        _root.update_idletasks(); _root.update()
    _lay = _app.layout_instance

    # 先访问性能页（触发表格构建）
    _lay.switch_nav('perf')
    for _ in range(8):
        _root.update_idletasks(); _root.update()

    _tbl = getattr(_app, 'perf_samples_table', None)
    check("性能页构建出了采样表", _tbl is not None)

    if _tbl is not None:
        # ① 表格的祖先链（holder 本身是 workspace 的子控件，
        #    所以链上必然有 workspace —— 要查的是
        #    **workspace 与表格之间夹了几层**）
        _chain = []
        _p = _tbl.master
        while _p is not None and _p is not _root:
            _chain.append(_p)
            _p = _p.master
        # 表格 → ... → holder → workspace
        # 正确的结构里，holder 和 workspace 之间是**直接父子**
        # （holder 是 workspace 的 grid 子控件），
        # 表格挂在 holder 的**子树**里（不是 workspace 的直接子控件）。
        _tbl_is_ws_direct = bool(_chain) and _chain[0] is _lay.workspace
        check("表格不是 workspace 的直接子控件（否则跨页残留）",
              not _tbl_is_ws_direct,
              "表格直接挂在 workspace 上 → 变成所有页面共享的底部条")

        # ② 表格必须在 perf 面板 holder 的子树里
        _perf_holder = _lay.panels.get('perf')
        check("表格在性能页 holder 的子树内",
              _perf_holder is not None and _perf_holder in _chain,
              "表格不在 perf holder 里 → 切页时归属错乱")

        # ③ **直接证据**：workspace 的直接子控件里，
        #    除了各页面 holder，不该有独立的固定区 Frame
        #    （holder 都是 grid 在 row=0 col=0）
        _ws_kids = list(_lay.workspace.winfo_children())
        _bad_rows = []
        for _c in _ws_kids:
            _gi = _c.grid_info()
            if not _gi.get('row'):
                continue
            # row 非 0 → 说明有东西被挂到了 workspace 的其他行
            _bad_rows.append((_gi.get('row'), _gi.get('column')))
        check("workspace 里没有挂在非 0 行的独立子控件",
              not _bad_rows,
              f"发现 {_bad_rows} → 共享底部条（就是本 bug）")

        # ④ 切换到投屏/脚本页后，表格所属页面仍是 perf
        for _key in ('mirror', 'script'):
            _lay.switch_nav(_key)
            for _ in range(6):
                _root.update_idletasks(); _root.update()
            # ⚠️ 表格在 holder 的**深层子树**里
            #    （holder → _fixed → _tables → _col → section → card → table）
            #    所以要递归找，不能只看直接子控件。
            def _contains(_w, _target, _depth=0):
                if _depth > 12:
                    return False
                for _c in _w.winfo_children():
                    if _c is _target:
                        return True
                    if _contains(_c, _target, _depth + 1):
                        return True
                return False

            _owner = None
            for _pk, _pv in _lay.panels.items():
                if _contains(_pv, _tbl):
                    _owner = _pk
                    break
            check(f"切到 {_key} 页后表格仍属于 perf 面板",
                  _owner == 'perf', f"实际属于 {_owner}")

    # ⑤ 性能页上方内容区必须有可用高度（不能被底部区挤成 1px）
    _perf_holder = _lay.panels.get('perf')
    if _perf_holder is not None:
        _cvs = _perf_holder.grid_slaves(row=0, column=0)
        _h = _cvs[0].winfo_height() if _cvs else 0
        check(f"性能页滚动区高度正常（>150px，实测 {_h}px）",
              _h > 150, f"只有 {_h}px → 上方内容被底部区挤没了")

    _root.destroy()
except Exception as _e:
    check(f"固定区归属实测（异常: {_e}）", False, str(_e))


# ════════════════════════════════════════════════════════════════
# 源码级守护：底部区不能自己 new Frame 挂到 workspace 上
# ════════════════════════════════════════════════════════════════
print()
print("=== 源码级守护 ===")
# ⚠️ _ROOT 是 tests 目录 → 项目根要退一级
_PROJ = os.path.dirname(_ROOT)
_src = io.open(os.path.join(_PROJ, 'gui', 'layout_v4.py'),
               encoding='utf-8').read()

# 用 AST 找 build_perf_panel 里所有 tk.Frame(...) 的第一个参数
try:
    _tree = ast.parse(_src)
    _cls = [n for n in _tree.body if isinstance(n, ast.ClassDef)][0]
    _fn = [n for n in _cls.body
           if isinstance(n, ast.FunctionDef)
           and n.name == 'build_perf_panel'][0]
    _ws_frames = []
    for _node in ast.walk(_fn):
        if (isinstance(_node, ast.Call)
                and isinstance(_node.func, ast.Attribute)
                and _node.func.attr == 'Frame'
                and _node.args):
            _a0 = _node.args[0]
            if isinstance(_a0, ast.Attribute) \
                    and _a0.attr == 'workspace':
                _ws_frames.append(_node.lineno)
    check("build_perf_panel 里没有把 Frame 挂到 self.workspace",
          not _ws_frames, f"行 {_ws_frames} → 会变成共享底部条")

    # _panel 必须有 with_fixed_bottom 参数
    _panel = [n for n in _cls.body
              if isinstance(n, ast.FunctionDef) and n.name == '_panel'][0]
    _args = [a.arg for a in _panel.args.args]
    check("_panel 有 with_fixed_bottom 参数",
          'with_fixed_bottom' in _args, str(_args))
    check("_panel 不再有 fixed_bottom 参数（旧接口已废弃）",
          'fixed_bottom' not in _args, str(_args))
except Exception as _e:
    check(f"源码守护（异常: {_e}）", False, str(_e))

print()
print("=" * 68)
if FAILED:
    print(f"HAS FAILURES —— {len(FAILED)} 项失败：")
    for f in FAILED:
        print(f"  - {f}")
    print("=" * 68)
    sys.exit(1)
else:
    print(f"ALL PASS （{PASSED} 项）")
    print("=" * 68)
