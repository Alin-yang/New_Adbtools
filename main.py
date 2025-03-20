from app import ADBToolApp
import tkinter as tk
import argparse
from gui import layout_en
from gui import layout_zh


# 解析命令行参数
parser = argparse.ArgumentParser()
# 打包exe文件时，需修改default参数为zh或en
parser.add_argument("--lang", choices=["en", "zh"], default="en", help="选择语言: en (英文) 或 zh (中文)")
args = parser.parse_args()


# 根据参数加载对应语言布局
if args.lang == "zh":
    layout = layout_zh
else: # 确保这个模块存在
    layout = layout_en


if __name__ == "__main__":
    root = tk.Tk()
    app = ADBToolApp(root, layout_module=layout)
    root.mainloop()