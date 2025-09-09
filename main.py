from app import ADBToolApp
import tkinter as tk
from gui import layout_zh as layout
import sys
import traceback

# 全局变量控制拖拽功能
use_dnd = False
TkinterDnD = None

# 尝试导入tkinterdnd2
try:
    from tkinterdnd2 import TkinterDnD
    use_dnd = True
    print("✅ tkinterdnd2 库加载成功，拖拽功能可用")
except ImportError as e:
    print(f"⚠️ tkinterdnd2 库导入失败: {e}")
    print("💡 拖拽功能不可用，将使用普通模式")
    use_dnd = False
except Exception as e:
    print(f"❌ tkinterdnd2 库加载时发生未知错误: {e}")
    print("💡 回退到普通模式")
    use_dnd = False


def create_root_window():
    """创建根窗口，处理拖拽功能的兼容性"""
    global use_dnd, TkinterDnD
    
    if use_dnd and TkinterDnD:
        try:
            # 尝试创建支持拖拽的根窗口
            root = TkinterDnD.Tk()
            print("✅ 拖拽功能已启用")
            return root
        except Exception as e:
            print(f"❌ 创建拖拽窗口失败: {e}")
            print("🔄 回退到普通窗口模式")
            # 如果创建拖拽窗口失败，标记为不可用并创建普通窗口
            use_dnd = False
    
    # 创建普通的Tkinter窗口
    root = tk.Tk()
    print("ℹ️ 使用普通窗口模式（无拖拽功能）")
    return root


if __name__ == "__main__":
    try:
        # 创建根窗口
        root = create_root_window()
        
        # 创建应用实例
        app = ADBToolApp(root, layout_module=layout)
        
        # 启动主循环
        root.mainloop()
        
    except Exception as e:
        # 处理任何启动错误
        error_msg = f"程序启动失败: {str(e)}\n\n详细错误信息:\n{traceback.format_exc()}"
        print(error_msg)
        
        # 尝试显示错误对话框
        try:
            import tkinter.messagebox as messagebox
            messagebox.showerror("启动错误", error_msg)
        except:
            # 如果连对话框都无法显示，则打印到控制台
            print("无法显示错误对话框")
        
        sys.exit(1)