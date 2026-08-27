# -*- coding: utf-8 -*-
"""UI 层：控件查询工具界面（Tkinter）。

点住🔍拖到目标控件上松开 → 锁定；控件树状展示（按类型配色、折叠重复层）；
↑父 / ⤒顶 累积控制线路；搜索框高亮匹配；详情含句柄/线程/进程。
业务逻辑见 service.py，底层函数见 util.py。
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

import util
import service

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
BORDER_MS = 500
BORDER_COLOR = '#ffd000'
BORDER_THICK = 4
MAG_COLOR = '#00c853'
ROUTE_COLOR = '#ffe0b2'   # 路径/折叠节点颜色（浅橙）
MATCH_COLOR = '#c8e6c9'   # 搜索命中色（绿）

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


class SpyApp:
    def __init__(self):
        self.targeting = False
        self.border_wins = []
        self.controls = {}       # iid -> control
        self.item_type = {}      # iid -> ControlTypeName
        self.hl_path = []        # 上溯累积的控制线路（来源+各级父）
        self._border_after = None
        self._collapse_runs = {}   # 折叠节点 iid -> (start, count)
        self._dup_buttons = []     # 折叠节点文字右侧的 + 按钮
        self._dup_shown = set()
        self._dup_children = {}
        self.root_control = None
        self.route_only = False
        self._cur_path = []
        self._cur_source = None
        self._cur_groups = []

        self.root = tk.Tk()
        self.root.title("控件查询")
        self.root.attributes('-topmost', True)
        self.root.geometry("660x620")
        self.root.minsize(660, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.screen_h = self.root.winfo_screenheight()

        # ---------- 顶部搜索框 ----------
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

        # ---------- 控件树 ----------
        self.tree_frame = tk.Frame(self.root)
        self.tree_frame.pack(fill='both', expand=True, padx=8, pady=(8, 4))
        self.tree = ttk.Treeview(self.tree_frame, show='tree', selectmode='browse')
        self.tree.heading('#0', text='控件')
        self.tree.column('#0', width=490, anchor='w')
        for ct, color in TYPE_COLORS.items():
            self.tree.tag_configure(ct, foreground=color)
        self.tree.tag_configure('route', background=ROUTE_COLOR, foreground='#000000')
        self.tree.tag_configure('match', background=MATCH_COLOR, foreground='#1b5e20')
        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(self.tree_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewOpen>>', self._on_tree_open)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<MouseWheel>', lambda e: self._refresh_fold_buttons())

        # ---------- 详情 ----------
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
        mode_frame = tk.Frame(bottom)
        mode_frame.grid(row=0, column=0, sticky='w')
        self.top_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(mode_frame, text="锁定顶层窗口", variable=self.top_only_var).pack(side='left')
        tk.Label(mode_frame, text=" 匹配:", font=('Microsoft YaHei', 9)).pack(side='left')
        self.mode_var = tk.StringVar(value="自动")
        ttk.Combobox(mode_frame, textvariable=self.mode_var, state='readonly',
                     values=("自动", "命中测试", "全树遍历"), width=8,
                     font=('Microsoft YaHei', 9)).pack(side='left')
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

    # ---------- 放大镜 / 点击穿透 ----------
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
            c = service.lock_control(x, y, self.top_only_var.get(), self.mode_var.get())
            self.root_control = c
            self.hl_path = [c]       # 控制线路起点 = 来源控件
            self._build_tree(c)
            self._show_details(c)
            self._show_border(c.BoundingRectangle)
            self.root.after(BORDER_MS, self.hide_border)
        except Exception as e:
            log(f"取控件失败: {type(e).__name__}: {e}")
            self.details.configure(state='normal')
            self.details.delete('1.0', 'end')
            self.details.insert('end', f"锁定失败: {e}", 'lbl')
            self.details.configure(state='disabled')

    # ---------- 树 ----------
    def _build_tree(self, c):
        self.tree.delete(*self.tree.get_children())
        self.controls = {}
        self.item_type = {}
        self.hl_path = []
        self.root_control = c
        self._insert_node('', c)
        try:
            self.tree.item(self.tree.get_children()[0], open=True)
        except Exception:
            pass
        self._autosize()

    def _visible_count(self, iids):
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
        rows = self._visible_count(self.tree.get_children())
        h = rows * 20 + 300
        h = max(620, min(h, self.screen_h - 120))
        self.root.geometry(f"660x{h}")
        self.root.update_idletasks()

    def _insert_node(self, parent_iid, c):
        iid = f'c{id(c)}'
        ct = c.ControlTypeName
        self.tree.insert(parent_iid, 'end', iid=iid, text=util.label_text(c), tags=(ct,))
        self.controls[iid] = c
        self.item_type[iid] = ct
        try:
            if c.GetChildren():
                self.tree.insert(iid, 'end', iid=f'{iid}_ph', text='')
        except Exception:
            pass
        return iid

    def _open_node(self, iid):
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

    # ---------- 折叠节点 + 按钮 ----------
    def _place_fold_buttons(self):
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
        for btn, iid in self._dup_buttons:
            try:
                bbox = self.tree.bbox(iid)
            except Exception:
                continue
            if bbox:
                btn.place(x=bbox[0] + bbox[2] + 2, y=bbox[1],
                          width=16, height=max(bbox[3], 16))

    def _toggle_duplicates(self, iid):
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
            for idx in range(s + cnt - 1, s - 1, -1):
                miid = self._ins_node(cur_parent, path[idx], True)
                if top_iid is None:
                    top_iid = miid
                cur_parent = miid
            self.tree.move(top_iid, iid, 0)
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

    # ---------- 控制线路渲染 ----------
    def _render_route(self):
        path = self.hl_path
        if not path:
            return
        self._cur_path = path
        self._cur_source = path[0]
        self._cur_groups = util.collapse_groups(path)
        self._collapse_runs = {}
        self._dup_buttons = []
        self._dup_shown = set()
        self._dup_children = {}
        groups = self._cur_groups
        self.tree.delete(*self.tree.get_children())
        self.controls = {}
        self.item_type = {}

        # 顶层组（不高亮）
        self.root_control = path[groups[-1][0] + groups[-1][1] - 1]
        root_iid = self._ins_node('', self.root_control, False)
        if groups[-1][1] > 1:
            self.tree.item(root_iid, text=util.label_text(self.root_control) + f'  ×{groups[-1][1]}')
        self.tree.item(root_iid, open=True)
        self._render_level(root_iid, path[groups[-1][0]], len(groups) - 2)
        self._autosize()
        self._place_fold_buttons()

    def _ins_node(self, parent_iid, c, mark):
        iid = f'c{id(c)}'
        tags = ('route',) if mark else (c.ControlTypeName,)
        self.tree.insert(parent_iid, 'end', iid=iid,
                         text=util.label_text(c), tags=tags)
        self.controls[iid] = c
        self.item_type[iid] = c.ControlTypeName
        return iid

    def _ins_lazy(self, parent_iid, c):
        iid = self._ins_node(parent_iid, c, False)
        try:
            if c.GetChildren():
                self.tree.insert(iid, 'end', iid=f'{iid}_ph', text='')
        except Exception:
            pass

    def _render_level(self, parent_iid, c, gi):
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
            path_child = util.find_path_child(kids, source)
        for k in kids:
            if path_child is not None and k is path_child:
                s, cnt = groups[gi]
                iid = self._ins_node(parent_iid, k, True)
                if cnt > 1:
                    # 只折叠重复层（×N），路径延续自动可见；右侧 + 按钮展开重复项
                    self.tree.item(iid, text=util.label_text(k) + f'  ×{cnt}')
                    self._collapse_runs[iid] = (s, cnt)
                    self.tree.item(iid, open=True)
                    self._render_level(iid, path[s], gi - 1)
                else:
                    self.tree.item(iid, open=True)
                    self._render_level(iid, path[s], gi - 1)
            else:
                if not self.route_only:
                    self._ins_lazy(parent_iid, k)   # 兄弟分支：仅完整模式显示

    def go_parent(self):
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
        current = self._current_control()
        if current is None:
            return
        self.hl_path = util.path_to_top(current)   # [来源, ..., 顶层窗口]
        self._render_route()
        self._show_details(current)

    def toggle_route(self):
        self.route_only = not self.route_only
        self.route_btn.config(text='全树' if self.route_only else '线路')
        self._render_route()

    # ---------- 详情 / 复制 ----------
    def _show_details(self, c):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        for lbl, val in service.control_details(c):
            self.details.insert('end', f"{lbl}: ", 'lbl')
            self.details.insert('end', f"{val}\n", 'val')
        self.details.configure(state='disabled')

    def copy_info(self):
        txt = self.details.get('1.0', 'end').strip()
        tree_txt = "\n".join(self._tree_text())
        full = txt + "\n\n--- 树状结构 ---\n" + tree_txt
        if full:
            self.root.clipboard_clear()
            self.root.clipboard_append(full)

    def _tree_text(self):
        lines = []

        def walk(parent, prefix):
            children = self.tree.get_children(parent)
            for i, iid in enumerate(children):
                if iid.endswith('_ph'):
                    continue
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

    # ---------- 搜索 ----------
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
        root = self.root_control
        if root is None:
            return
        self._search_count = 0
        self.tree.delete(*self.tree.get_children())
        self.controls = {}
        self.item_type = {}
        self._collapse_runs = {}
        self._dup_buttons = []
        self._dup_shown = set()
        self._dup_children = {}
        self._render_search_node('', root, query, 0)
        self._autosize()

    def _ins_search_node(self, parent_iid, c, matched):
        iid = f'c{id(c)}'
        tags = ('match',) if matched else (c.ControlTypeName,)
        self.tree.insert(parent_iid, 'end', iid=iid,
                         text=util.label_text(c), tags=tags)
        self.controls[iid] = c
        self.item_type[iid] = c.ControlTypeName
        return iid

    def _render_search_node(self, parent_iid, c, q, depth):
        self._search_count += 1
        if self._search_count > 2000:   # 防爆
            return None, False
        matched = service.matches_name(c, q)
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
