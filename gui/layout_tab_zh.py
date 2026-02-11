import tkinter as tk
from tkinter import ttk
from .layout_tab import TabLayout, get_tab_button_configs


def setup_gui(app):
    """构建基于Tab页的中文界面布局"""
    layout = TabLayout(app)
    
    # 设置主容器
    layout.setup_main_container()
    
    # 创建左右分栏
    layout.create_panels(left_weight=50, right_weight=40)
    
    # 创建输入区域（IP、包名、APK、日志路径）
    layout.create_input_section()
    
    # 创建Tab页面
    layout.create_tab_pages()
    
    # 创建输出区域
    layout.create_output_section()
    
    # 设置快捷键
    layout.setup_keyboard_shortcuts()