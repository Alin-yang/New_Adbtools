#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ADB工具界面分析脚本
分析当前界面布局和按钮分布情况
"""

def analyze_button_layout():
    """分析按钮布局情况"""
    
    # 从布局配置中获取按钮信息
    button_configs = [
        ("连接 ADB", 4, 0, "connect_adb"),
        ("断开所有ADB连接", 4, 1, "disconnect_adb"),
        ("查看已连接设备", 4, 2, "show_device_info"),
        ("强制安装apk", 5, 0, "force_install"),
        ("卸载当前包名应用", 5, 1, "uninstall"),
        ("获取已安装应用包名列表", 5, 2, "package_list"),
        ("清除应用缓存", 6, 0, "clear_cache"),
        ("获取Root权限", 6, 1, "root_device"),
        ("导出ANR文件", 6, 2, "pull_anr_file"),
        ("重新挂载分区", 7, 0, "remount"),
        ("获取当前包名版本号", 7, 1, "get_version"),
        ("重启设备", 7, 2, "reboot"),
        ("获取Android版本号", 8, 0, "get_android_version"),
        ("启动日志捕获", 8, 1, "start_logcat"),
        ("停止日志捕获", 8, 2, "stop_logcat"),
        ("终止当前包名所有进程", 9, 0, "kill_app_process"),
        ("清除日志缓存", 9, 1, "log_clear"),
        ("获取当前打开应用包名", 9, 2, "get_package_name"),
        ("获取当前包名应用安装路径", 10, 0, "get_package_path"),
        ("开始屏幕录制", 10, 1, "start_recording"),
        ("停止屏幕录制", 10, 2, "stop_recording"),
        ("截取当前屏幕", 0, 2, "screencap"),
        ("获取设备串号", 1, 2, "get_serial_number"),
        ("功能按键原始执行命令", 11, 0, "show_all_adb_commands"),
        ("打开工厂菜单", 11, 2, "open_factory_menu"),
    ]
    
    print("=" * 50)
    print("ADB工具界面分析报告")
    print("=" * 50)
    
    # 1. 基本统计
    total_buttons = len(button_configs)
    print(f"📊 总按钮数量: {total_buttons}个")
    
    # 2. 功能分类分析
    categories = {
        '设备管理': [],
        '应用管理': [],
        '日志调试': [],
        '系统操作': [],
        '设备信息': [],
        '其他功能': []
    }
    
    for text, row, col, method_name in button_configs:
        if '连接' in text or '断开' in text or '设备' in text or '查看' in text:
            categories['设备管理'].append((text, row, col))
        elif '安装' in text or '卸载' in text or '包名' in text or '缓存' in text or '进程' in text:
            categories['应用管理'].append((text, row, col))
        elif '日志' in text or 'ANR' in text or '捕获' in text:
            categories['日志调试'].append((text, row, col))
        elif '权限' in text or '挂载' in text or '重启' in text:
            categories['系统操作'].append((text, row, col))
        elif '截取' in text or '录制' in text or '串号' in text or '版本' in text:
            categories['设备信息'].append((text, row, col))
        else:
            categories['其他功能'].append((text, row, col))
    
    print("\n📋 功能分类详情:")
    print("-" * 30)
    for category, buttons in categories.items():
        if buttons:
            print(f"{category}: {len(buttons)}个按钮")
            for text, row, col in buttons:
                print(f"  ├─ {text} (第{row}行, 第{col}列)")
    
    # 3. 布局分析
    print("\n📐 布局分析:")
    print("-" * 30)
    
    # 统计每行按钮数量
    rows = {}
    for text, row, col, method_name in button_configs:
        if row not in rows:
            rows[row] = []
        rows[row].append((text, col))
    
    print("按钮行分布:")
    for row_num in sorted(rows.keys()):
        buttons_in_row = len(rows[row_num])
        print(f"  第{row_num}行: {buttons_in_row}个按钮")
        if buttons_in_row > 3:
            print(f"    ⚠️  警告: 该行按钮过多，可能影响界面美观")
    
    # 4. 用户体验评估
    print("\n🎯 用户体验评估:")
    print("-" * 30)
    
    issues = []
    suggestions = []
    
    if total_buttons > 20:
        issues.append(f"按钮总数较多({total_buttons}个)，可能导致界面拥挤")
        suggestions.append("建议使用Tab页或折叠面板进行功能分组")
    
    # 检查是否有行按钮过多
    crowded_rows = [row for row, buttons in rows.items() if len(buttons) > 3]
    if crowded_rows:
        issues.append(f"第{', '.join(map(str, crowded_rows))}行按钮过多")
        suggestions.append("建议重新排列按钮布局，每行不超过3个按钮")
    
    # 输出评估结果
    if issues:
        print("❌ 发现的问题:")
        for issue in issues:
            print(f"  • {issue}")
        
        print("\n💡 改进建议:")
        for suggestion in suggestions:
            print(f"  • {suggestion}")
    else:
        print("✅ 界面布局较为合理")
    
    # 5. 优化方案建议
    print("\n🔧 优化方案建议:")
    print("-" * 30)
    print("方案一: Tab页面分类")
    print("  • 设备管理Tab: 连接、断开、查看设备等")
    print("  • 应用管理Tab: 安装、卸载、包名操作等")
    print("  • 日志调试Tab: 日志捕获、ANR导出等")
    print("  • 系统信息Tab: 截屏、录制、设备信息等")
    
    print("\n方案二: 折叠面板")
    print("  • 将相关功能按钮放入可展开/收缩的面板中")
    print("  • 默认展开常用功能，折叠高级功能")
    
    print("\n方案三: 搜索+快捷按钮")
    print("  • 保留最常用的5-8个按钮在主界面")
    print("  • 其他功能通过搜索框快速查找")
    print("  • 提供功能分类导航")

if __name__ == "__main__":
    analyze_button_layout()