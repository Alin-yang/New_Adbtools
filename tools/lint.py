"""零依赖代码质量检查（lint）

不依赖 ruff/flake8，只用 Python 标准库 —— 团队里每个人的 Python 路径都不一样，
引入外部工具反而跑不起来。

检查项：
  1. 死代码：定义后从未被引用的函数/类/方法（会反射调用的除外）
  2. 未使用的 import
  3. 危险模式：shell 管道过滤、裸 except、后台线程里的 root.after
  4. 超大文件（拆分提示）

用法:
    D:\\tool\\python\\python.exe tools\\lint.py            # 报告
    D:\\tool\\python\\python.exe tools\\lint.py --strict   # 有 error 就返回非 0
"""
import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只扫描这些文件
TARGETS = [
    'app.py', 'utils.py', 'config.py', 'decorators.py', 'device_monitor.py',
    'cache_manager.py', 'adaptive_cache.py', 'main.py',
    'gui/layout_modern.py', 'modules/performance_monitor.py', 'modules/screen_mirror.py',
]

# 反射调用白名单：这些名字是靠 getattr(app, "名字") 绑定的
REFLECT_PREFIX = ('_create_', 'create_', 'on_', 'handle_', 'do_')

errors, warnings = [], []

# ---------------------------------------------------------------- 基线
# 当前已知的存量问题记录在基线文件里，不重复报警；
# 只报"新增"的问题，这样门禁立刻可用又能防止继续劣化。
# 清理完某条后，把基线里对应行删掉即可。
BASELINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lint_baseline.txt')


def _baseline_keys():
    keys = set()
    if os.path.exists(BASELINE_FILE):
        with io.open(BASELINE_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    keys.add(line)
    return keys


def _key(path, lineno, msg):
    # ⚠️ 不能带行号：代码一改行号就漂移，基线会失效、存量问题重复报警
    return f"{rel(path)}:{msg}"


def report(bucket, path, lineno, msg):
    """记录一条问题（基线里的跳过）"""
    if _key(path, lineno, msg) in _baseline_keys():
        return
    bucket.append((path, lineno, msg))


def rel(path):
    return os.path.relpath(path, ROOT).replace('\\', '/')


def collect_defs(tree, path, src):
    """收集所有函数/类定义及其位置"""
    defs = []

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            defs.append((node.name, node.lineno, 'func'))
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            defs.append((node.name, node.lineno, 'func'))
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            defs.append((node.name, node.lineno, 'class'))
            self.generic_visit(node)

    V().visit(tree)
    return defs


def check_dead_code(path, src, tree):
    """死代码检测"""
    defs = collect_defs(tree, path, src)
    all_src = "\n".join(
        io.open(os.path.join(ROOT, f), encoding='utf-8').read()
        for f in TARGETS if os.path.exists(os.path.join(ROOT, f))
    )

    for name, lineno, kind in defs:
        if name.startswith('__') or name in ('main', 'setup_gui'):
            continue
        # 文本出现次数（减去定义处本身）
        occurrences = len(re.findall(r'\b' + re.escape(name) + r'\b', all_src))
        definitions = len(re.findall(r'^\s*(?:def|class)\s+' + re.escape(name) + r'\b',
                                     all_src, re.M))
        # 字符串反射引用（getattr(app, "xxx") / "xxx" 传给回调）
        quoted = all_src.count(f'"{name}"') + all_src.count(f"'{name}'")
        if occurrences <= definitions and quoted == 0:
            report(errors, path, lineno, f"死代码：{kind} '{name}' 定义后从未被引用")


def check_unused_imports(path, src, tree):
    """未使用的 import"""
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                name = a.asname or a.name.split('.')[0]
                imported[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == '*':
                    continue
                name = a.asname or a.name
                imported[name] = node.lineno

    # 用正则统计出现次数（能识别字符串里的类型注解、反射等），
    # ast.Name 检测不到 "Optional[str]" 这种字符串注解，会误报。
    for name, lineno in imported.items():
        occurrences = len(re.findall(r'\b' + re.escape(name) + r'\b', src))
        if occurrences > 1:      # >1 = 除 import 行外还有引用
            continue
        report(warnings, path, lineno, f"未使用的 import: {name}")


def check_dangerous(path, src, tree):
    """危险模式"""
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        # shell 管道过滤（管道由本机 cmd 解析，用户环境可能没有 grep）
        # ⚠️ 排除"给用户看的命令参考表"和文档示例 —— 那些是展示文本，不是实际执行的命令
        if re.search(r'adb [a-z ]*\| (grep|findstr)', line):
            if any(k in line for k in ('不能写', '改为', 'Python 侧', 'dumpsys window | findstr',
                                      '"adb shell dumpsys', "('获取当前打开应用包名'",
                                      '`adb shell xxx | grep yyy`')):
                continue
            if stripped.startswith('(') or stripped.startswith('"'):
                continue
            report(errors, path, i, "命令里用了 shell 管道过滤（用户环境可能没有 grep），改用 utils.filter_lines")
        # 裸 except
        if re.match(r'^\s*except\s*:', line):
            report(errors, path, i, "裸 except（会吞掉 KeyboardInterrupt）")
        # 2>/dev/null
        if '2>/dev/null' in line and '不能' not in line and '注意' not in line \
                and '|`adb shell' not in line and not stripped.startswith('#'):
            report(errors, path, i, "命令里用了 2>/dev/null（本机 cmd 会解析成重定向）")


def check_background_after(path, src, tree):
    """后台线程里调 root.after（应改用 app._run_in_ui）"""
    funcs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, ast.FunctionDef):
                    funcs[f.name] = f

    bg = set(n for n in funcs if n.endswith('_async'))
    for f in funcs.values():
        for node in ast.walk(f):
            if isinstance(node, ast.Call):
                for a in list(node.args) + [k.value for k in node.keywords]:
                    if isinstance(a, ast.Name) and a.id in funcs:
                        bg.add(a.id)
                    if isinstance(a, ast.Attribute) and a.attr in funcs:
                        bg.add(a.attr)

    for name in sorted(bg):
        f = funcs.get(name)
        if not f:
            continue
        for c in ast.walk(f):
            if not isinstance(c, ast.Call) or not isinstance(c.func, ast.Attribute):
                continue
            if c.func.attr not in ('after', 'after_idle'):
                continue
            v = c.func.value
            is_root = (isinstance(v, ast.Name) and v.id == 'root') or \
                      (isinstance(v, ast.Attribute) and v.attr == 'root')
            if is_root and c.args and isinstance(c.args[0], ast.Constant) \
                    and c.args[0].value == 0:
                report(errors, path, c.lineno,
                       f"后台线程 {name}() 里调 root.after(0,...)："
                       f"主线程忙时会抛 'main thread is not in main loop'，改用 app._run_in_ui()")


def write_baseline(all_findings):
    """把当前所有问题写成基线（用于 --update-baseline）"""
    with io.open(BASELINE_FILE, 'w', encoding='utf-8', newline='\n') as f:
        f.write("# 存量问题基线 —— 由 tools/lint.py --update-baseline 生成\n")
        f.write("# 清理完某条后删掉对应行，下次 lint 就会开始报警\n")
        for p, ln, msg in sorted(all_findings, key=lambda x: (x[0], x[1], x[2])):
            f.write(f"{_key(p, ln, msg)}\n")
    print(f"基线已更新：{BASELINE_FILE}（{len(all_findings)} 条）")


def main():
    strict = '--strict' in sys.argv
    update_baseline = '--update-baseline' in sys.argv
    print("=" * 74)
    print("  代码质量检查（零依赖）")
    print("=" * 74)

    for f in TARGETS:
        path = os.path.join(ROOT, f)
        if not os.path.exists(path):
            continue
        src = io.open(path, encoding='utf-8').read()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            report(errors, path, e.lineno or 0, f"语法错误: {e}")
            continue

        check_dead_code(path, src, tree)
        check_unused_imports(path, src, tree)
        check_dangerous(path, src, tree)
        check_background_after(path, src, tree)

        # 文件过大提示
        n = len(src.splitlines())
        if n > 3000:
            report(warnings, path, 0, f"文件 {n} 行，建议拆分")

    if update_baseline:
        write_baseline(errors + warnings)
        return 0

    if errors:
        print(f"\n❌ 错误 {len(errors)} 处：")
        for p, ln, msg in sorted(errors, key=lambda x: (x[0], x[1])):
            print(f"   {rel(p)}:{ln}  {msg}")
    else:
        print("\n✅ 没有错误")

    if warnings:
        print(f"\n⚠️  警告 {len(warnings)} 处：")
        for p, ln, msg in sorted(warnings, key=lambda x: (x[0], x[1])):
            print(f"   {rel(p)}:{ln}  {msg}")
    else:
        print("✅ 没有警告")

    print()
    if strict and errors:
        print("strict 模式：有错误，返回码 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
