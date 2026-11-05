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

    # 4e. 设备信息（型号）必须能显示 —— v5.4.2 的核心功能
    # ⚠️ 这条必须守护：v5.4.1 重构时漏掉了 _load_meta_async 的调用，
    #    副标题永远显示「在线/已离线」，浮层退化成纯 IP 列表。
    #    打包后如果 utils.load_device_info_cache 之类没被收进去，
    #    也会在这里暴露。
    _loaded = []
    _orig_meta = picker._load_meta_async

    def _meta_spy(device):
        _loaded.append(device)
        return _orig_meta(device)

    picker._load_meta_async = _meta_spy
    # ⚠️ 浮层此刻是**打开**状态（步骤 3 打开的），toggle() 会把它**关闭**，
    #    不会触发重渲染 → 拿不到任何加载调用。
    #    必须先 hide 再 toggle，让它真正重新渲染一次。
    picker.hide()
    lay._toggle_device_picker()
    for _ in range(3):
        root.update_idletasks()
        root.update()
    check("渲染时会为在线设备拉取型号",
          len(_loaded) > 0, _loaded)
    # 副标题文本：注入一条缓存，验证能拼出「型号 · 版本」
    if picker._rows:
        _dev = picker._rows[0][0]
        _key = picker._normalize(_dev)
        picker._meta_cache[_key] = {'model': 'TestModel X',
                                    'version': '13.0'}
        _txt = picker._meta_text(_dev, True)
        check("副标题能显示型号与系统版本",
              'TestModel X' in _txt and '13.0' in _txt, _txt)
        # 离线设备必须额外标出「已离线」
        _txt_off = picker._meta_text(_dev, False)
        check("离线设备的副标题标出「已离线」",
              '已离线' in _txt_off, _txt_off)
    else:
        _out("       (无设备行，跳过型号显示测试)")

    # 4f. 滚动条（内容超出视口时必须有提示）
    # ⚠️ v5.4.3 新增：内容 570px / 视口 278px 时底部半截条目
    #    会让用户以为渲染坏了，且不知道下面还有设备。
    _orig_hist = app.ip_history
    _orig_online = app.get_online_devices
    app.ip_history = ['192.168.0.3', '192.168.0.8', '192.168.1.7',
                      '192.168.1.20', '192.168.2.3', '192.168.2.44',
                      '192.168.3.9', '10.1.246.77']
    app.get_online_devices = lambda: ['10.1.246.185:5555', '192.168.1.99:5555']
    picker.hide()
    root.update()
    picker._render(app.get_online_devices())
    for _ in range(3):
        root.update_idletasks()
        root.update()
    check("内容超出视口时显示滚动条",
          picker._sb_thumb is not None, picker._sb_thumb)
    check("滚动条宽度够看得见",
          picker._sbar.winfo_width() >= 4, picker._sbar.winfo_width())
    check("滚动条高度与列表视口一致",
          picker._sbar.winfo_height() == picker._canvas.winfo_height(),
          "sbar=%s canvas=%s" % (picker._sbar.winfo_height(),
                                picker._canvas.winfo_height()))
    check("底部提示提到可滚动",
          '滚动' in picker._hint_label.cget('text'),
          picker._hint_label.cget('text'))
    # 内容放得下时不应有滚动条
    app.ip_history = ['192.168.0.3']
    picker._render(['10.1.246.185:5555'])
    for _ in range(2):
        root.update_idletasks()
        root.update()
    check("内容能全放下时不显示滚动条",
          picker._sb_thumb is None, picker._sb_thumb)
    app.ip_history = _orig_hist
    app.get_online_devices = _orig_online

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
