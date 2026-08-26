# ui-spy · Windows 控件查询工具

一个用于 UI 自动化调试的控件定位工具：拖拽锁定目标控件，树状展示控件层级，方便找控件类型 / 名称 / 句柄 / 线程等。

## 功能

- **拖拽锁定**：按住 🔍 拖到任意窗口的控件上松开，锁定该控件
- **树状展示**：锁定后展示控件层级树（按类型配色），支持展开子控件
- **↑父 / ⤒顶**：逐级上溯父控件（累积成控制线路），或一键跳到控件自己的顶层窗口
- **折叠重复层**：路径上连续相同的单子链层折叠成 `×N`，`+` 按钮可展开重复项
- **路径标记**：控制线路上的节点用橙色标记
- **搜索**：从树根往下搜索，命中节点绿色高亮
- **详情**：类型 / 名称 / 类名 / AutomationId / 窗口句柄 / 线程 / 进程 / 矩形
- **边框预览**：点树中节点，对应控件边框亮 1 秒；锁定显示黄色边框
- **复制**：复制详情 + 树状结构文本

## 使用

```bash
# 源码运行（需 Python 3.10+，安装 uiautomation）
python ui_spy.py

# 或直接运行打包好的 exe
ui-spy.exe
```

## 技术要点

- 基于 `uiautomation`（UI Automation）
- 微信等 DirectUI 的 `ElementFromPoint` 不可靠，改用「从窗口句柄往下全树遍历找矩形包含该点的最深控件」
- 窗口句柄/线程/进程：`win32gui.WindowFromPoint` + `win32process.GetWindowThreadProcessId`
- 折叠功能用「矩形完整包含来源控件且面积最小」的子确定性定位路径

## 打包

```bash
pip install pyinstaller uiautomation
pyinstaller --onefile --windowed --name ui-spy ui_spy.py
```
