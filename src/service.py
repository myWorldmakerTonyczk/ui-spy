# -*- coding: utf-8 -*-
"""业务层：控件操作（锁定、详情、搜索）。"""
import uiautomation as auto
import util


def lock_control(x, y, top_only=False, mode="hit"):
    """锁定鼠标 (x,y) 处的控件。
    mode: "hit"=命中测试（普通应用）；"walk"=全树遍历（微信 DirectUI）。
    top_only=True 直接锁定顶层窗口。
    """
    if top_only:
        import win32gui
        hwnd = win32gui.WindowFromPoint((int(x), int(y)))
        return auto.ControlFromHandle(hwnd) if hwnd else auto.ControlFromPoint(x, y)
    if mode in ("walk", "全树遍历"):
        return util.deepest_at_point(x, y)
    return util.hit_test_at_point(x, y)


def matches_name(c, query):
    """控件名称是否包含 query（忽略大小写）。"""
    q = query.lower()
    name = ''
    try:
        name = c.Name or ''
    except Exception:
        pass
    return q in name.lower()


def search_matches(root, query, max_nodes=2000):
    """从 root 往下遍历子树，产出名称含 query 的控件（忽略大小写）。"""
    count = [0]

    def walk(c):
        count[0] += 1
        if count[0] > max_nodes:
            return
        if matches_name(c, query):
            yield c
        try:
            kids = c.GetChildren()
        except Exception:
            kids = []
        for k in kids:
            yield from walk(k)

    yield from walk(root)


def control_details(c):
    """返回控件的详情项列表 [(标签, 值), ...]。"""
    def s(attr):
        try:
            return getattr(c, attr) or ''
        except Exception:
            return ''

    r = c.BoundingRectangle
    hwnd, thread, pid = util.window_info(c)
    return [
        ("类型", c.ControlTypeName),
        ("名称", repr(s('Name'))),
        ("类名", repr(s('ClassName'))),
        ("AutomationId", repr(s('AutomationId'))),
        ("句柄", f"{hex(hwnd) if hwnd else '0'}  线程:{thread}  进程:{pid}"),
        ("矩形", f"({r.left},{r.top},{r.right},{r.bottom})  {r.width()}x{r.height()}"),
    ]
