# -*- coding: utf-8 -*-
"""控件查询工具：点住🔍拖到目标控件上松开 → 锁定；控件单列树状展示（按类型配色、层级缩进清晰）；
↑父 上溯并展开父的全部子+高亮来源子；⤒顶 一键跳到顶层窗口，逐级展开、每层高亮路径上的那个；
可选"锁定顶层窗口"模式；详情含句柄/线程/进程；锁定显示黄色边框 0.5 秒。
用法:  .venv/Scripts/python.exe ui_spy.py   (或打包成 exe)
"""
import ctypes
import os
import sys
import io
from tkinter import ttk
# windowed 打包时没有控制台，sys.stdout 是 None，直接包 TextIOWrapper 会崩
if sys.stdout is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import tkinter as tk

LOG_PATH = os.path.join(os.path.dirname(sys.executable), 'spy_error.log')


def log(msg):
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(msg + "\n")
    except Exception:
        pass


log("=== spy 启动 ===")
try:
    import uiautomation as auto
    log("uiautomation import OK")
except Exception:
    import traceback
    log("uiautomation import 失败: " + traceback.format_exc())
    raise

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
VK_LBUTTON = 0x01
GA_ROOT = 2
BORDER_MS = 500
BORDER_COLOR = '#ffd000'
BORDER_THICK = 4
MAG_COLOR = '#00c853'
ROUTE_COLOR = '#ffe0b2'   # 路径/折叠节点颜色（浅橙）

TYPE_COLORS = {
    'WindowControl': '#c62828',
    'ButtonControl': '#1565c0',
    'EditControl': '#00897b',
    'ListItemControl': '#6a1b9a',
    'ListControl': '#6a1b9a',
    'TextControl': '#e65100',
    'PaneControl': '#757575',
    'MenuControl': '#ad1457',
    'TreeItemControl': '#2e7d32',
    'ImageControl': '#ff8f00',
}
DEFAULT_COLOR = '#37474f'


class SpyApp:
    def __init__(self):
        self.targeting = False
        self.border_wins = []
        self.controls = {}       # iid -> control
        self.ctrl_key_to_iid = {}  # RuntimeId -> iid
        self.item_type = {}      # iid -> ControlTypeName
        self._hl_iids = []
        self.hl_path = []        # 上溯累积的控制线路（来源+各级父）
        self._border_after = None
        self._collapse_runs = {}   # 折叠节点 iid -> (start, count)
        self._dup_buttons = []     # 折叠节点文字右侧的 + 按钮
        self._dup_shown = set()
        self._dup_children = {}
        self.root_control = None

        self.root = tk.Tk()
        self.root.title("控件查询")
        self.root.attributes('-topmost', True)
        self.root.geometry("520x620")
        self.root.minsize(520, 620)   # 最小窗口，最大不限制
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.screen_h = self.root.winfo_screenheight()

        # ---------- 顶部搜索框（从树根往下搜，高亮匹配） ----------
        self.search_var = tk.StringVar()
        search_frame = tk.Frame(self.root)
        search_frame.pack(fill='x', padx=8, pady=(8, 0))
        tk.Label(search_frame, text="🔍 搜索:", font=('Microsoft YaHei', 10)).pack(side='left')
        search_entry = tk.Entry(search_frame, textvariable=self.search_var,
                                font=('Microsoft YaHei', 10), relief='sunken')
        search_entry.pack(side='left', fill='x', expand=True, padx=(4, 0))
        search_entry.bind('<KeyRelease>', self._on_search)
        tk.Button(search_frame, text="清空", width=4, font=('Microsoft YaHei', 9),
                  command=self._clear_search).pack(side='left', padx=(4, 0))
        self.route_only = False   # 是否只显示主线路

        # ---------- 控件树（单列，层级缩进清晰） ----------
        self.tree_frame = tk.Frame(self.root)
        self.tree_frame.pack(fill='both', expand=True, padx=8, pady=(8, 4))
        self.tree = ttk.Treeview(self.tree_frame, show='tree', selectmode='browse')
        self.tree.heading('#0', text='控件')
        self.tree.column('#0', width=490, anchor='w')
        for ct, color in TYPE_COLORS.items():
            self.tree.tag_configure(ct, foreground=color)
        self.tree.tag_configure('route', background=ROUTE_COLOR, foreground='#000000')  # 路径/折叠节点色
        self.tree.tag_configure('match', background='#c8e6c9', foreground='#1b5e20')    # 搜索命中色（绿）
        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(self.tree_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewOpen>>', self._on_tree_open)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<MouseWheel>', lambda e: self._refresh_fold_buttons())

        # ---------- 详情（标签粗体、值正常，字号加大） ----------
        self.details = tk.Text(self.root, height=8, bg='#f5f5f5', relief='sunken',
                               font=('Microsoft YaHei', 11), padx=6, pady=4)
        self.details.pack(fill='x', padx=8, pady=2)
        self.details.tag_configure('lbl', font=('Microsoft YaHei', 11, 'bold'),
                                   foreground='#7b7b7b')
        self.details.tag_configure('val', font=('Microsoft YaHei', 12),
                                   foreground='#111')
        self.details.insert('end', "拖到目标控件上，或点🔍开始", 'lbl')
        self.details.configure(state='disabled')

        # ---------- 底部 ----------
        bottom = tk.Frame(self.root)
        bottom.pack(fill='x', padx=8, pady=(4, 8))
        bottom.columnconfigure(0, weight=1)
        self.top_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bottom, text="锁定顶层窗口", variable=self.top_only_var).grid(row=0, column=0, sticky='w')
        self.target_btn = tk.Button(bottom, text="🔍", font=('Segoe UI Emoji', 11),
                                    width=3, cursor='hand2')
        self.target_btn.grid(row=0, column=1, padx=2)
        self.target_btn.bind('<ButtonPress-1>', lambda e: self.start_targeting())
        tk.Button(bottom, text="复制", command=self.copy_info, width=6).grid(row=0, column=2, padx=2)
        tk.Button(bottom, text="↑父", command=self.go_parent, width=4).grid(row=0, column=3, padx=2)
        tk.Button(bottom, text="⤒顶", command=self.go_top, width=4).grid(row=0, column=4, padx=2)
        self.route_btn = tk.Button(bottom, text="线路", command=self.toggle_route, width=4)
        self.route_btn.grid(row=0, column=5, padx=2)

        # 拖动时跟随的放大镜小图窗口
        self.mag = tk.Toplevel(self.root)
        self.mag.overrideredirect(True)
        self.mag.attributes('-topmost', True)
        self.mag.geometry("40x40")
        self.mag_canvas = tk.Canvas(self.mag, bg='#f8f8f8', highlightthickness=0)
        self.mag_canvas.pack(fill='both', expand=True)
        self._draw_mag(self.mag_canvas)
        self._make_click_through(self.mag)
        self.mag.withdraw()

        self.root.mainloop()

    def _draw_mag(self, cv):
        cv.create_oval(5, 5, 28, 28, outline=MAG_COLOR, width=3)
        cv.create_line(26, 26, 37, 37, fill=MAG_COLOR, width=5)

    def _make_click_through(self, w):
        try:
            h = w.winfo_id()
            user32 = ctypes.windll.user32
            ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
            user32.SetWindowLongW(h, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT)
        except Exception:
            pass

    # ---------- 拖动目标锁定 ----------
    def start_targeting(self):
        self.targeting = True
        ctypes.windll.user32.ShowCursor(False)
        self.mag.deiconify()
        self.root.after(30, self.poll_targeting)

    def poll_targeting(self):
        if not self.targeting:
            return
        x, y = self.root.winfo_pointerx(), self.root.winfo_pointery()
        self.mag.geometry(f"40x40+{x - 20}+{y - 20}")
        self.mag.lift()
        if not (ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
            self.on_target_release(x, y)
            return
        self.root.after(30, self.poll_targeting)

    def on_target_release(self, x, y):
        self.targeting = False
        self.mag.withdraw()
        ctypes.windll.user32.ShowCursor(True)
        try:
            if self.top_only_var.get():
                import win32gui
                hwnd = win32gui.WindowFromPoint((int(x), int(y)))
                c = auto.ControlFromHandle(hwnd) if hwnd else auto.ControlFromPoint(x, y)
            else:
                c = self._deepest_at_point(x, y)
            self.root_control = c
            self.hl_path = [c]       # 控制线路起点 = 来源控件
            self._build_tree(c)
            self._show_details(c)
            self._show_border(c.BoundingRectangle)
            self.root.after(BORDER_MS, self.hide_border)
        except Exception as e:
            log(f"取控件失败: {type(e).__name__}: {e}")
            self.details_var.set(f"锁定失败: {e}")

    def _deepest_at_point(self, x, y):
        """全树遍历找"矩形包含 (x,y)"的最深控件（微信 DirectUI 命中测试/中间层矩形不可靠）。"""
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

    # ---------- 树 ----------
    def _ctrl_key(self, c):
        """控件的稳定身份 key。RuntimeId 在此版本不存在，改用 矩形+类型+名称
        （同元素不同方式获取，几何信息一致，可稳定匹配）。"""
        try:
            r = c.BoundingRectangle
            return ('geo', c.ControlTypeName, c.Name or '',
                    r.left, r.top, r.width(), r.height())
        except Exception:
            return ('id', id(c))

    def _iid_of(self, c):
        return self.ctrl_key_to_iid.get(self._ctrl_key(c))

    def _build_tree(self, c):
        self.tree.delete(*self.tree.get_children())
        self.controls = {}
        self.ctrl_key_to_iid = {}
        self.item_type = {}
        self._hl_iids = []
        self.hl_path = []
        self.root_control = c
        self._insert_node('', c)
        try:
            root_item = self.tree.get_children()[0]
            self.tree.item(root_item, open=True)
        except Exception:
            pass
        self._autosize()

    def _visible_count(self, iids):
        """统计树里可见（含展开的）行数。"""
        n = 0
        for i in iids:
            n += 1
            try:
                if self.tree.item(i, 'open'):
                    n += self._visible_count(self.tree.get_children(i))
            except Exception:
                pass
        return n

    def _autosize(self):
        """窗口高度自适应树内容：内容高就拉长，超屏交给滚动条；最小不低于 620（保证图标完整）。"""
        rows = self._visible_count(self.tree.get_children())
        h = rows * 20 + 300   # 树区 + 详情/按钮/边距
        h = max(620, min(h, self.screen_h - 120))
        self.root.geometry(f"520x{h}")
        self.root.update_idletasks()

    def _insert_node(self, parent_iid, c):
        iid = f'c{id(c)}'
        ct = c.ControlTypeName
        nm = ''
        try:
            nm = c.Name or ''
        except Exception:
            pass
        if len(nm) > 40:
            nm = nm[:40] + '…'
        label = ct + (f"  '{nm}'" if nm else '')
        self.tree.insert(parent_iid, 'end', iid=iid, text=label, tags=(ct,))
        self.controls[iid] = c
        self.ctrl_key_to_iid[self._ctrl_key(c)] = iid
        self.item_type[iid] = ct
        try:
            if c.GetChildren():
                self.tree.insert(iid, 'end', iid=f'{iid}_ph', text='')
        except Exception:
            pass
        return iid

    def _open_node(self, iid):
        """加载并展开该节点的所有直接子控件（已加载过则跳过）。"""
        c = self.controls.get(iid)
        if c is None:
            return
        kids = self.tree.get_children(iid)
        if any(not k.endswith('_ph') for k in kids):
            self.tree.item(iid, open=True)
            return
        for ch in kids:
            if ch.endswith('_ph'):
                self.tree.delete(ch)
        try:
            for k in c.GetChildren():
                self._insert_node(iid, k)
        except Exception:
            pass
        self.tree.item(iid, open=True)

    def _on_tree_open(self, event):
        iid = self.tree.focus()
        c = self.controls.get(iid)
        if c is None:
            return
        kids = self.tree.get_children(iid)
        if any(not k.endswith('_ph') for k in kids):
            return
        self._open_node(iid)

    def _place_fold_buttons(self):
        """为每个折叠节点在文字右侧放一个 + 按钮（挨着文字，非行最右）。"""
        for b, _ in self._dup_buttons:
            try:
                b.destroy()
            except Exception:
                pass
        self._dup_buttons = []
        for iid in self._collapse_runs:
            try:
                bbox = self.tree.bbox(iid)
            except Exception:
                continue
            if not bbox:
                continue
            btn = tk.Button(self.tree_frame, text='+', font=('Consolas', 8),
                            relief='ridge', bd=1, width=1, cursor='hand2',
                            command=lambda i=iid: self._toggle_duplicates(i))
            btn.place(x=bbox[0] + bbox[2] + 2, y=bbox[1],
                      width=16, height=max(bbox[3], 16))
            self._dup_buttons.append((btn, iid))

    def _refresh_fold_buttons(self):
        """树滚动/缩放后把 + 按钮挪到文字右边。"""
        for btn, iid in self._dup_buttons:
            try:
                bbox = self.tree.bbox(iid)
            except Exception:
                continue
            if bbox:
                btn.place(x=bbox[0] + bbox[2] + 2, y=bbox[1],
                          width=16, height=max(bbox[3], 16))

    def _toggle_duplicates(self, iid):
        """点 + 按钮：在折叠节点下切换展开/收起重复层。"""
        info = self._collapse_runs.get(iid)
        if not info:
            return
        s, cnt = info
        path = self._cur_path
        if iid in self._dup_shown:
            for ch in self._dup_children.get(iid, []):
                try:
                    self.tree.delete(ch)
                except Exception:
                    pass
            self._dup_children[iid] = []
            self._dup_shown.discard(iid)
            for b, bi in self._dup_buttons:
                if bi == iid:
                    b.config(text='+')
        else:
            top_iid = None
            cur_parent = iid
            for idx in range(s + cnt - 1, s - 1, -1):   # 顶部→底部 逐个嵌套
                miid = self._ins_node(cur_parent, path[idx], True)
                if top_iid is None:
                    top_iid = miid
                cur_parent = miid
            self.tree.move(top_iid, iid, 0)   # 移到最前面，续在延续节点上方
            self._dup_children[iid] = [top_iid]
            self._dup_shown.add(iid)
            for b, bi in self._dup_buttons:
                if bi == iid:
                    b.config(text='−')
            self.tree.item(iid, open=True)

    def _on_tree_select(self, event):
        iid = self.tree.focus()
        c = self.controls.get(iid)
        if c is not None:
            self._show_details(c)
            # 点哪个节点，哪个控件边框亮 1 秒
            try:
                r = c.BoundingRectangle
                if r.width() > 0 and r.height() > 0:
                    if self._border_after:
                        self.root.after_cancel(self._border_after)
                    self._show_border(r)
                    self._border_after = self.root.after(1000, self.hide_border)
            except Exception:
                pass

    def _current_control(self):
        iid = self.tree.focus()
        c = self.controls.get(iid)
        return c if c is not None else self.root_control

    def _highlight(self, controls):
        """清除旧高亮；给指定控件打上黄底黑字高亮 tag（与类型配色区分开）。"""
        for iid in self._hl_iids:
            try:
                self.tree.item(iid, tags=(self.item_type.get(iid, ''),))
            except Exception:
                pass
        self._hl_iids = []
        for c in controls:
            iid = self._iid_of(c)
            if iid:
                try:
                    self.tree.item(iid, tags=('hl',))
                    self._hl_iids.append(iid)
                    self.tree.see(iid)
                except Exception:
                    pass

    def _label_text(self, c):
        nm = ''
        try:
            nm = c.Name or ''
        except Exception:
            pass
        if len(nm) > 40:
            nm = nm[:40] + '…'
        return c.ControlTypeName + (f"  '{nm}'" if nm else '')

    def _same_wrapper(self, a, b):
        """类型/名称/类名 是否都相同。"""
        try:
            return (a.ControlTypeName == b.ControlTypeName
                    and (a.Name or '') == (b.Name or '')
                    and (a.ClassName or '') == (b.ClassName or ''))
        except Exception:
            return False

    def _single_child_chain(self, child, parent):
        """child 是否是 parent 的唯一子控件。"""
        try:
            return len(parent.GetChildren()) == 1
        except Exception:
            return False

    def _collapse_groups(self, path):
        """折叠路径上连续"类型/名称/类名相同 且 单子链"的层。返回 [(start_idx, count)]。"""
        if not path:
            return []
        groups = []
        n = len(path)
        i = 0
        while i < n:
            j = i
            while j + 1 < n and self._same_wrapper(path[j], path[j + 1]) \
                    and self._single_child_chain(path[j], path[j + 1]):
                j += 1
            groups.append((i, j - i + 1))
            i = j + 1
        return groups

    def _open_children_route(self, iid):
        """加载并展开该节点（即其"子控件来源"）的全部直接子控件。"""
        c = self.controls.get(iid)
        if c is None:
            return
        for ch in self.tree.get_children(iid):
            if ch.endswith('_ph'):
                self.tree.delete(ch)
        try:
            for k in c.GetChildren():
                self._insert_node(iid, k)
        except Exception:
            pass
        self.tree.item(iid, open=True)

    def _render_route(self):
        """按 hl_path 渲染完整树：路径节点橙色标记 + 折叠相同单子链（×N），
        折叠节点可点击展开显示重复项；每层兄弟分支照常显示。顶层窗口不高亮。"""
        path = self.hl_path
        if not path:
            return
        self._cur_path = path
        self._cur_source = path[0]
        self._cur_groups = self._collapse_groups(path)
        self._collapse_runs = {}
        self._dup_buttons = []
        self._dup_shown = set()
        self._dup_children = {}
        groups = self._cur_groups
        self.tree.delete(*self.tree.get_children())
        self.controls = {}
        self.ctrl_key_to_iid = {}
        self.item_type = {}
        self._hl_iids = []

        # 顶层组（不高亮）
        self.root_control = path[groups[-1][0] + groups[-1][1] - 1]
        root_iid = self._ins_node('', self.root_control, False)
        if groups[-1][1] > 1:
            self.tree.item(root_iid, text=self._label_text(self.root_control) + f'  ×{groups[-1][1]}')
        self.tree.item(root_iid, open=True)
        self._render_level(root_iid, path[groups[-1][0]], len(groups) - 2)
        self._autosize()
        self._place_fold_buttons()

    def _ins_node(self, parent_iid, c, mark):
        """插入一个节点；mark=True 用路径色（橙），否则用类型色。"""
        iid = f'c{id(c)}'
        tags = ('route',) if mark else (c.ControlTypeName,)
        self.tree.insert(parent_iid, 'end', iid=iid,
                         text=self._label_text(c), tags=tags)
        self.controls[iid] = c
        self.item_type[iid] = c.ControlTypeName
        return iid

    def _ins_lazy(self, parent_iid, c):
        """插入一个可见节点，子控件懒加载（占位）。"""
        iid = self._ins_node(parent_iid, c, False)
        try:
            if c.GetChildren():
                self.tree.insert(iid, 'end', iid=f'{iid}_ph', text='')
        except Exception:
            pass

    def _render_level(self, parent_iid, c, gi):
        """渲染控件 c 的所有子。gi = 下一组（路径）的索引；-1 表示不再有路径层。"""
        path = self._cur_path
        source = self._cur_source
        groups = self._cur_groups
        try:
            kids = c.GetChildren()
        except Exception:
            return
        if not kids:
            return
        path_child = None
        if gi >= 0:
            path_child = self._find_path_child(kids, source)
        for k in kids:
            if path_child is not None and k is path_child:
                s, cnt = groups[gi]
                iid = self._ins_node(parent_iid, k, True)   # 路径节点：橙色
                if cnt > 1:
                    # 只折叠重复层（×N），下面路径延续照常展开显示；右侧 + 按钮展开重复项
                    self.tree.item(iid, text=self._label_text(k) + f'  ×{cnt}')
                    self._collapse_runs[iid] = (s, cnt)
                    self.tree.item(iid, open=True)
                    self._render_level(iid, path[s], gi - 1)  # 路径延续自动可见
                else:
                    self.tree.item(iid, open=True)
                    self._render_level(iid, path[s], gi - 1)
            else:
                if not self.route_only:
                    self._ins_lazy(parent_iid, k)           # 兄弟分支：仅完整模式显示


    def _find_path_child(self, kids, source):
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

    def go_parent(self):
        """上溯一级：父加入控制线路并重新渲染（折叠相同单子链层）。"""
        old_root = self.root_control
        if old_root is None:
            return
        try:
            if old_root.NativeWindowHandle:
                return   # 已是顶层窗口
        except Exception:
            pass
        try:
            p = old_root.GetParentControl()
        except Exception:
            p = None
        if p is None:
            return
        if not self.hl_path:
            self.hl_path = [old_root]
        self.hl_path.append(p)
        self._render_route()
        self._show_details(old_root)

    def go_top(self):
        """一键跳到控件自己的顶层窗口，整条控制线路折叠渲染。"""
        current = self._current_control()
        if current is None:
            return
        chain = []
        c = current
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
        self.hl_path = list(chain)   # [来源, ..., 顶层窗口]
        self._render_route()
        self._show_details(current)

    # ---------- 详情 ----------
    def _window_info(self, c):
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
                    h = win32gui.GetAncestor(h, GA_ROOT)
                    hwnd = h
                    thread, pid = win32process.GetWindowThreadProcessId(h)
        except Exception:
            pass
        return hwnd, thread, pid

    def _show_details(self, c):
        def s(attr):
            try:
                return getattr(c, attr) or ''
            except Exception:
                return ''

        r = c.BoundingRectangle
        hwnd, thread, pid = self._window_info(c)
        items = [
            ("类型", c.ControlTypeName),
            ("名称", repr(s('Name'))),
            ("类名", repr(s('ClassName'))),
            ("AutomationId", repr(s('AutomationId'))),
            ("句柄", f"{hex(hwnd) if hwnd else '0'}  线程:{thread}  进程:{pid}"),
            ("矩形", f"({r.left},{r.top},{r.right},{r.bottom})  {r.width()}x{r.height()}"),
        ]
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        for lbl, val in items:
            self.details.insert('end', f"{lbl}: ", 'lbl')   # 标签粗体灰
            self.details.insert('end', f"{val}\n", 'val')    # 值正常黑
        self.details.configure(state='disabled')

    def copy_info(self):
        """复制：详情 + 当前树状结构。"""
        txt = self.details.get('1.0', 'end').strip()
        tree_txt = "\n".join(self._tree_text())
        full = txt + "\n\n--- 树状结构 ---\n" + tree_txt
        if full:
            self.root.clipboard_clear()
            self.root.clipboard_append(full)

    def _tree_text(self):
        """把当前树渲染成带连线的文本结构（完整名称，跳过懒加载占位）。"""
        lines = []

        def walk(parent, prefix):
            children = self.tree.get_children(parent)
            for i, iid in enumerate(children):
                if iid.endswith('_ph'):
                    continue                      # 跳过懒加载占位
                c = self.controls.get(iid)
                if c is not None:
                    nm = ''
                    try:
                        nm = c.Name or ''
                    except Exception:
                        pass
                    label = c.ControlTypeName + (f" '{nm}'" if nm else '')
                    if iid in self._collapse_runs:
                        label += f'  ×{self._collapse_runs[iid][1]}'
                else:
                    label = self.tree.item(iid, 'text')
                    if not label:
                        continue
                is_last = (i == len(children) - 1)
                connector = '└─ ' if is_last else '├─ '
                lines.append(prefix + connector + label)
                walk(iid, prefix + ('   ' if is_last else '│  '))

        walk('', '')
        return lines

    def toggle_route(self):
        """切换：只显示主线路 / 完整树。"""
        self.route_only = not self.route_only
        self.route_btn.config(text='全树' if self.route_only else '线路')
        self._render_route()

    # ---------- 搜索（从树根往下，高亮匹配） ----------
    def _on_search(self, event):
        query = self.search_var.get()
        if query.strip():
            self._render_search(query.strip())
        else:
            self._render_route()

    def _clear_search(self):
        self.search_var.set('')
        self._render_route()

    def _render_search(self, query):
        q = query.lower()
        root = self.root_control
        if root is None:
            return
        self._search_count = 0
        self.tree.delete(*self.tree.get_children())
        self.controls = {}
        self.ctrl_key_to_iid = {}
        self.item_type = {}
        self._hl_iids = []
        self._collapse_runs = {}
        self._dup_buttons = []
        self._dup_shown = set()
        self._dup_children = {}
        self._render_search_node('', root, q, 0)
        self._autosize()

    def _ins_search_node(self, parent_iid, c, matched):
        iid = f'c{id(c)}'
        tags = ('match',) if matched else (c.ControlTypeName,)
        self.tree.insert(parent_iid, 'end', iid=iid,
                         text=self._label_text(c), tags=tags)
        self.controls[iid] = c
        self.item_type[iid] = c.ControlTypeName
        return iid

    def _render_search_node(self, parent_iid, c, q, depth):
        self._search_count += 1
        if self._search_count > 2000:   # 防爆
            return None, False
        name = ''
        try:
            name = c.Name or ''
        except Exception:
            pass
        matched = q in name.lower()
        iid = self._ins_search_node(parent_iid, c, matched)
        if depth >= 14:
            return iid, matched
        try:
            kids = c.GetChildren()
        except Exception:
            kids = []
        has = matched
        for k in kids:
            kiid, kh = self._render_search_node(iid, k, q, depth + 1)
            if kh:
                has = True
            else:
                if kiid:
                    try:
                        self.tree.delete(kiid)
                    except Exception:
                        pass
                    self._ins_lazy(iid, k)   # 无命中分支收成懒加载
        if has:
            self.tree.item(iid, open=True)
        return iid, has

    # ---------- 边框 ----------
    def _show_border(self, r):
        self.hide_border()
        th = BORDER_THICK
        specs = [
            (r.left, r.top, r.width(), th),
            (r.left, r.bottom - th, r.width(), th),
            (r.left, r.top, th, r.height()),
            (r.right - th, r.top, th, r.height()),
        ]
        for x, y, w, h in specs:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.geometry(f"{w}x{h}+{x}+{y}")
            tk.Frame(win, bg=BORDER_COLOR).pack(fill='both', expand=True)
            self._make_click_through(win)
            self.border_wins.append(win)

    def hide_border(self):
        self._border_after = None
        for w in self.border_wins:
            try:
                w.destroy()
            except Exception:
                pass
        self.border_wins = []

    def on_close(self):
        self.hide_border()
        if self.targeting:
            ctypes.windll.user32.ShowCursor(True)
        self.root.destroy()


if __name__ == "__main__":
    SpyApp()
