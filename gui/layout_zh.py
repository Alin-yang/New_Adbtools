import tkinter as tk
from tkinter import ttk
from .layout_base import LayoutBase, get_button_configs


def setup_gui(app):
    """构建中文界面布局"""
    layout = LayoutBase(app)
    
    # 设置主容器
    layout.setup_main_container()
    
    # 创建左右分栏
    layout.create_panels(left_weight=50, right_weight=40)
    
    # 创建输入区域
    layout.create_input_section()
    
    # 创建功能按钮
    button_configs = get_button_configs()
    button_list = []
    for text, row, col, method_name in button_configs:
        if hasattr(app, method_name):
            button_list.append((text, row, col, getattr(app, method_name)))
    
    layout.create_buttons(button_list)
    
    # 创建输出区域
    layout.create_output_section()
    
    # 设置快捷键
    layout.setup_keyboard_shortcuts()