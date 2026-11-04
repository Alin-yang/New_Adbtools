"""打包产物自检 —— 独立入口，实跑打包后的真实链路

⚠️ 为什么需要这个（MEMORY 里记的教训）：
   静态检查 PYZ 里有没有某个模块，只是「文件在不在」；
   运行时才会暴露「导入路径不对」「控件没建出来」「后台线程没投递」这类问题。
   所以这里真跑一遍：建 App → 建浮层 → 渲染设备列表 → 点选切换 → 徽标三态。

⚠️ 打包后 stdout 是 GBK —— print 非 ASCII 字符（如「▾」U+25BE）
   会抛 UnicodeEncodeError 直接崩掉整个进程。
   所以所有输出都要走 _out() 兜底。

用法：
   源码目录：python tools/selftest_device_picker.py
   打包后：  用 ADBTool_selftest.spec 打一个独立 exe，跑它
"""
import sys
import os

# ⚠️ 源码目录直接跑时，项目根不在 sys.path 里（脚本在 tools/ 下），
#    `from gui import layout_v4` 会 ModuleNotFoundError。
#    打包后 sys.path 由 PyInstaller 处理，这行自然不生效。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.isdir(os.path.join(_ROOT, 'gui')):
    sys.path.insert(0, _ROOT)

# ⚠️ 打包后 stdout 是 GBK，print 非 ASCII 可能抛 UnicodeEncodeError
#    （「▾」= U+25BE 在 GBK 里就没有 → 直接崩）
def _out(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode('gbk', 'replace').decode('gbk'))
        except Exception:
            print('(output encode failed)')

ok = True


def check(name, cond, extra=""):
    global ok
    _out(("  PASS  " if cond else "  FAIL  ") + name
         + (("  -> " + str(extra)) if extra else ""))
    if not cond:
        ok = False


def main():
    import tkinter as tk
    from gui import layout_v4 as layout_mod
    from app import ADBToolApp

    _out("=" * 60)
    _out("打包产物自检：设备切换器")
    _out("=" * 60)

    root = tk.Tk()
    app = ADBToolApp(root, layout_mod)
    for _ in range(4):
        root.update_idletasks()
        root.update()

    lay = app.layout_instance

    # 1. 顶栏有「设备」切换按钮
    check("顶栏有设备切换按钮", hasattr(app, 'btn_device_picker'))
    if hasattr(app, 'btn_device_picker'):
        _out("       按钮文案: " + str(app.btn_device_picker.cget('text')))

    # 2. 浮层实例存在（验证 gui.device_picker 被正确导入）
    check("有设备切换浮层实例", hasattr(lay, 'device_picker'))

    # 3. 打开浮层
    lay._toggle_device_picker()
    for _ in range(4):
        root.update_idletasks()
        root.update()
    picker = lay.device_picker
    check("浮层能打开", picker.is_open(),
          picker.win.place_info() if picker.win else '')

    # 4. 渲染了内容（渲染路径涉及 Canvas/主题注册）
    _out("       渲染条目数: " + str(len(picker._rows)))

    # 4b. 浮层必须挂在主窗口内部（跟随移动，不是独立 Toplevel）
    check("浮层是主窗口的子孙（跟随主窗口移动）",
          str(picker.win).startswith(str(root)), str(picker.win))

    # 4c. 整行都是点击热区（用户反馈「以为要点『可切换』」）
    if picker._rows:
        _dev0, _top0, _bot0 = picker._rows[0]
        _hits = []
        for _frac in (0.05, 0.5, 0.95):
            _hits.append(picker._row_at(_top0 + (_bot0 - _top0) * _frac))
        check("行内任意位置都命中同一行", all(h == 0 for h in _hits), _hits)

    # 4d. 滚动性能（纯 Canvas，不能卡）
    import time as _time
    _t0 = _time.perf_counter()
    for _ in range(30):
        picker._canvas.yview_scroll(-1, 'units')
        root.update()
    _elapsed = (_time.perf_counter() - _t0) * 1000
    check("30 次滚动耗时 < 200ms（纯 Canvas 不卡）", _elapsed < 200,
          "%.1fms" % _elapsed)

    # 5. 点选切换
    picked = []
    _orig_select = app.select_device

    def _spy(device, announce=True, devices=None):
        picked.append(device)
        return _orig_select(device, announce=announce, devices=devices)

    app.select_device = _spy
    if picker._rows:
        _ev = type('E', (), {'y': picker._rows[0][1] + 5})()
        picker._on_click(_ev)
        check("点选条目触发切换", len(picked) == 1, picked)
    else:
        _out("       (无在线设备，跳过点选测试)")

    # 6. 徽标三态
    app.update_connection_status(ip_address='192.168.0.3',
                                 devices=['192.168.0.3:5555'])
    root.update_idletasks()
    _out("       徽标(在线): " + app.connection_status_label.cget('text'))
    check("徽标能显示「已连接」",
          "已连接" in app.connection_status_label.cget('text'),
          app.connection_status_label.cget('text'))

    app.update_connection_status(ip_address='192.168.0.3', devices=[])
    root.update_idletasks()
    _out("       徽标(无设备): " + app.connection_status_label.cget('text'))
    check("徽标能显示「无设备」",
          "无设备" in app.connection_status_label.cget('text'),
          app.connection_status_label.cget('text'))

    # 7. 顶栏宽度没被挤爆
    bar = lay.topbar
    bar.update_idletasks()
    total_req = sum(c.winfo_reqwidth() for c in bar.winfo_children())
    avail = bar.winfo_width()
    check("顶栏宽度未超", total_req <= avail,
          "需求=%s 可用=%s" % (total_req, avail))
    check("包名框宽度可读", app.pkg_combobox.winfo_width() >= 170,
          "width=%s" % app.pkg_combobox.winfo_width())

    # 8. 浮层宽度（用 place_info —— 浮层是 place 定位的，不是独立窗口）
    # ⚠️ 必须在浮层**打开时**查：place_forget 后 place_info() 拿不到尺寸。
    lay._toggle_device_picker()
    for _ in range(3):
        root.update_idletasks()
        root.update()
    _info = picker.win.place_info()
    _width = int(_info.get('width') or 0)
    check("浮层宽度为 360px", _width == 360, _info.get('width'))

    root.destroy()

    _out("")
    _out("=" * 60)
    _out("SELFTEST PASS" if ok else "SELFTEST FAILED")
    _out("=" * 60)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
