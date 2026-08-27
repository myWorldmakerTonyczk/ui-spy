# -*- coding: utf-8 -*-
"""工具层：uiautomation / win32 底层函数。"""
import uiautomation as auto


def label_text(c, max_len=40):
    """控件标签：类型 + 名称（截断）。"""
    nm = ''
    try:
        nm = c.Name or ''
    except Exception:
        pass
    if len(nm) > max_len:
        nm = nm[:max_len] + '…'
    return c.ControlTypeName + (f"  '{nm}'" if nm else '')


def ctrl_key(c):
    """控件的稳定身份 key。RuntimeId 在此版本不存在，改用 矩形+类型+名称
    （同元素不同方式获取，几何信息一致，可稳定匹配）。"""
    try:
        r = c.BoundingRectangle
        return ('geo', c.ControlTypeName, c.Name or '',
                r.left, r.top, r.width(), r.height())
    except Exception:
        return ('id', id(c))


def same_wrapper(a, b):
    """类型/名称/类名 是否都相同。"""
    try:
        return (a.ControlTypeName == b.ControlTypeName
                and (a.Name or '') == (b.Name or '')
                and (a.ClassName or '') == (b.ClassName or ''))
    except Exception:
        return False


def single_child_chain(child, parent):
    """child 是否是 parent 的唯一子控件。"""
    try:
        return len(parent.GetChildren()) == 1
    except Exception:
        return False


def collapse_groups(path):
    """折叠路径上连续"类型/名称/类名相同 且 单子链"的层。返回 [(start_idx, count)]。"""
    if not path:
        return []
    groups = []
    n = len(path)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and same_wrapper(path[j], path[j + 1]) \
                and single_child_chain(path[j], path[j + 1]):
            j += 1
        groups.append((i, j - i + 1))
        i = j + 1
    return groups


def find_path_child(kids, source):
    """在给定子控件列表里，找"矩形完整包含来源控件且面积最小"的那个（路径向下的一层）。"""
    best = None
    best_area = None
    try:
        sr = source.BoundingRectangle
    except Exception:
        return None
    for k in kids:
        try:
            r = k.BoundingRectangle
        except Exception:
            continue
        if r.width() <= 0 or r.height() <= 0:
            continue
        if r.left <= sr.left and r.right >= sr.right \
                and r.top <= sr.top and r.bottom >= sr.bottom:
            area = r.width() * r.height()
            if best_area is None or area < best_area:
                best, best_area = k, area
    return best


def hit_test_at_point(x, y):
    """命中测试模式（普通应用）：用 UIA 自带的 ElementFromPoint，provider 直接回答该点是什么。"""
    try:
        return auto.ControlFromPoint(x, y)
    except Exception:
        import win32gui
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        if hwnd:
            try:
                return auto.ControlFromHandle(hwnd)
            except Exception:
                pass
        return auto.ControlFromPoint(x, y)


def _is_top_level(c):
    """控件是否是顶层窗口（即它自己就是那棵树的根）。"""
    if c is None:
        return True
    try:
        top = c.GetTopLevelControl()
        return getattr(c, 'NativeWindowHandle', 0) == getattr(top, 'NativeWindowHandle', 0)
    except Exception:
        return False


def auto_at_point(x, y):
    """自动模式：先命中测试；若只命中顶层窗口（provider 失效或子控件不在这条路上），
    再试全树遍历，取能下钻的那个结果。"""
    hit = None
    try:
        hit = auto.ControlFromPoint(x, y)
    except Exception:
        hit = None
    if hit is not None and not _is_top_level(hit):
        return hit                       # 命中测试直接命中具体控件 → 用它
    walk = deepest_at_point(x, y)        # 命中测试失效 → 全树遍历兜底
    if not _is_top_level(walk):
        return walk
    return hit if hit is not None else walk


def deepest_at_point(x, y):
    """全树遍历模式（微信 DirectUI）：WindowFromPoint 拿窗口 → 从句柄全树遍历，
    自己用 BoundingRectangle 判断"矩形包含该点"的最深控件（不依赖 provider 的命中回答）。"""
    import win32gui
    hwnd = win32gui.WindowFromPoint((int(x), int(y)))
    if not hwnd:
        return auto.ControlFromPoint(x, y)
    try:
        w = auto.ControlFromHandle(hwnd)
    except Exception:
        return auto.ControlFromPoint(x, y)
    best, bd = w, -1
    try:
        for c, depth in auto.WalkControl(w, maxDepth=40):
            try:
                r = c.BoundingRectangle
            except Exception:
                continue
            if r.width() > 0 and r.height() > 0 and \
                    r.left <= x <= r.right and r.top <= y <= r.bottom:
                if depth > bd:
                    best, bd = c, depth
    except Exception:
        pass
    return best


def path_to_top(c):
    """返回控件到其顶层窗口的链 [c, ..., 顶层窗口]（在顶层窗口处停）。"""
    chain = []
    while c is not None:
        chain.append(c)
        try:
            if c.NativeWindowHandle:
                break
        except Exception:
            pass
        try:
            c = c.GetParentControl()
        except Exception:
            break
    return chain


def window_info(c):
    """取控件所在顶层窗口的 句柄/线程/进程。"""
    import win32gui
    import win32process
    hwnd, thread, pid = 0, 0, 0
    try:
        r = c.BoundingRectangle
        if r.width() > 0 and r.height() > 0:
            x = r.left + r.width() // 2
            y = r.top + r.height() // 2
            h = win32gui.WindowFromPoint((int(x), int(y)))
            if h:
                h = win32gui.GetAncestor(h, 2)   # GA_ROOT
                hwnd = h
                thread, pid = win32process.GetWindowThreadProcessId(h)
    except Exception:
        pass
    return hwnd, thread, pid
