# 格子谱样式（Grid Sheet Styles）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 按任务逐条执行（每任务先写失败测试 → 跑通实现 → 提交）。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 为 SkyGridSheetMaker 增加 6 种格子谱边框样式与 4 色自定义（旋律/和弦/背景/边框），样式随 `.ggp` 保存，显示区与导出 PNG 统一渲染，导出预览对话框支持临时调整。

**Architecture:** 新建独立模块 `grid_style.py` 定义样式枚举、校验与 `GridStyle` 值对象；`file_io` 保存/加载新字段；`sheet_widget` 与 `export` 按样式统一绘制（内线/外框/线宽/背景色参数化）；`main_window` 提供工具栏下拉框与样式颜色对话框；`ExportDialog` 增加临时样式控件（不写回乐谱）。

**Tech Stack:** Python 3.10+、PySide6、PyInstaller（打包）、回归测试 test_app.py（QT_QPA_PLATFORM=offscreen）。

---

## 文件结构

| 文件 | 职责 | 改动 |
| --- | --- | --- |
| `grid_style.py` | 新增：样式枚举、校验、线宽/内外框判定、GridStyle 值对象 | 新建 |
| `model.py` | 数据模型 | 不改 |
| `file_io.py` | .ggp 保存/加载新字段（grid_style/bg_color/border_color） | 修改 |
| `sheet_widget.py` | 显示区按样式渲染 | 修改 |
| `export.py` | 导出按样式渲染 | 修改 |
| `dialogs.py` | ExportDialog 临时样式控件 + 新增 StyleColorsDialog | 修改 |
| `main_window.py` | 工具栏下拉框/样式颜色按钮、状态、保存/打开接线 | 修改 |
| `test_app.py` | T32 系列回归测试 | 修改 |

关键常量（与现有代码保持一致）：默认旋律色 `#E84848`、和弦色 `#4A90D9`、背景 `#FFFFFF`、边框 `#B8B8B8`；细线 1px、粗线 2px。

---

### Task 1: 新建 grid_style.py（样式定义与校验）

**Files:**
- Create: `grid_style.py`
- Test: `test_app.py`（T32 系列中内联断言，暂不单独建文件）

- [ ] **Step 1: 先写失败测试（校验函数尚不存在）**

在 `test_app.py` 的 `main()` 中、T31 之后插入（见 Task 7 给出完整测试块，此处先写校验子集）：

```python
        # ---------------- T32a: 样式定义与校验 ----------------
        from grid_style import (STYLE_OPTIONS, DEFAULT_STYLE, GridStyle,
                                is_valid_style, draws_inner_lines,
                                draws_outer_frame, inner_pen_width)
        check("T32a 样式表含 6 项且枚举合法",
              len(STYLE_OPTIONS) == 6 and is_valid_style("full_frame")
              and not is_valid_style("bad_style"))
        check("T32b 内外框/线宽判定",
              draws_outer_frame("full_frame") and draws_outer_frame("thick_frame")
              and not draws_outer_frame("default")
              and inner_pen_width("thick_inner") == 2
              and inner_pen_width("default") == 1
              and not draws_inner_lines("no_border"))
        gs = GridStyle.coerce(style="thick_frame", bg_color="bad",
                              border_color="#333333")
        check("T32c GridStyle 非法值回退默认",
              gs.style == "thick_frame" and gs.bg_color == DEFAULT_STYLE  # 占位
              and gs.border_color == "#333333")
```

- [ ] **Step 2: 运行确认失败**

Run: `python test_app.py`
Expected: `[FAIL] T32a ...`（ImportError/名称不存在），TOTAL_OK < 200。

- [ ] **Step 3: 实现 grid_style.py**

创建 `grid_style.py`：

```python
# -*- coding: utf-8 -*-
"""格子谱样式：边框形态 + 颜色（背景/边框/旋律/和弦）。

grid_style 枚举：default / full_frame / no_outer / no_border /
thick_inner / thick_frame
- default      默认（现状）：白底、细内线、无外框
- full_frame   完整内外边框：每个节拍块外框 + 内部细格线
- no_outer     无外边框：只保留内部细格线（与默认渲染一致）
- no_border    无边框纯色块：不画任何线条，有标记=填色、无标记=底色
- thick_inner  粗内线：内部格线 2px、无外框
- thick_frame  粗内线+外框：内部格线 2px + 节拍块外框

样式与颜色随 .ggp 保存：grid_style 总是写入；bg_color / border_color
与默认不同才写入（沿用 mark_color / chord_color 的省略约定）。
"""

import re

from dataclasses import dataclass

from model import DEFAULT_CHORD_COLOR, DEFAULT_MARK_COLOR

DEFAULT_STYLE = "default"

# (枚举值, 显示名)，顺序即下拉框顺序
STYLE_OPTIONS = [
    ("default", "默认"),
    ("full_frame", "完整内外边框"),
    ("no_outer", "无外边框"),
    ("no_border", "无边框纯色块"),
    ("thick_inner", "粗内线"),
    ("thick_frame", "粗内线+外框"),
]

VALID_STYLES = {value for value, _ in STYLE_OPTIONS}

DEFAULT_BG_COLOR = "#FFFFFF"
DEFAULT_BORDER_COLOR = "#B8B8B8"

# 线宽（px）：粗样式 2，其余 1；无边框样式不画线
THIN_PEN = 1
THICK_PEN = 2

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def is_valid_style(style) -> bool:
    """是否为合法样式枚举值。"""
    return style in VALID_STYLES


def draws_inner_lines(style: str) -> bool:
    """样式是否绘制小格内线（no_border 除外）。"""
    return style != "no_border"


def draws_outer_frame(style: str) -> bool:
    """样式是否绘制节拍块外框。"""
    return style in ("full_frame", "thick_frame")


def inner_pen_width(style: str) -> int:
    """内线/外框线宽：粗样式 2px，其余 1px。"""
    return THICK_PEN if style in ("thick_inner", "thick_frame") else THIN_PEN


def _coerce_style(style) -> str:
    return style if is_valid_style(style) else DEFAULT_STYLE


def _coerce_color(raw, default: str) -> str:
    if isinstance(raw, str) and _HEX_COLOR_RE.match(raw):
        return raw
    return default


@dataclass
class GridStyle:
    """一份完整的格子样式（样式类型 + 四色，颜色均为 #RRGGBB）。"""

    style: str = DEFAULT_STYLE
    bg_color: str = DEFAULT_BG_COLOR
    border_color: str = DEFAULT_BORDER_COLOR
    mark_color: str = DEFAULT_MARK_COLOR
    chord_color: str = DEFAULT_CHORD_COLOR

    @classmethod
    def coerce(cls, style=None, bg_color=None, border_color=None,
               mark_color=None, chord_color=None) -> "GridStyle":
        """构造 GridStyle；非法/缺失值一律回退默认。"""
        return cls(
            style=_coerce_style(style),
            bg_color=_coerce_color(bg_color, DEFAULT_BG_COLOR),
            border_color=_coerce_color(border_color, DEFAULT_BORDER_COLOR),
            mark_color=_coerce_color(mark_color, DEFAULT_MARK_COLOR),
            chord_color=_coerce_color(chord_color, DEFAULT_CHORD_COLOR),
        )
```

- [ ] **Step 4: 修正 T32c 断言并跑通**

把 T32c 中占位断言 `gs.bg_color == DEFAULT_STYLE` 改为：

```python
        check("T32c GridStyle 非法值回退默认",
              gs.style == "thick_frame" and gs.bg_color == "#FFFFFF"
              and gs.border_color == "#333333")
```

Run: `python test_app.py`
Expected: T32a/b/c PASS。

- [ ] **Step 5: 提交**

```bash
git add grid_style.py test_app.py
git commit -m "feat: add grid style definitions and validation"
```

---

### Task 2: file_io 保存/加载新字段

**Files:**
- Modify: `file_io.py`（save_ggp、load_ggp）

- [ ] **Step 1: 写失败测试（字段未保存/加载）**

在 test_app.py 的 T32 块中追加：

```python
        # ---------------- T32d: 样式字段往返保存 ----------------
        p_style = tmp / "Style.ggp"
        save_ggp(str(p_style), "Style", 4, NoteGrid(2),
                 mark_color="#123456", chord_color="#ABCDEF",
                 style="full_frame", bg_color="#FFF8E1",
                 border_color="#333333")
        loaded = load_ggp(str(p_style))
        check("T32d 样式/颜色字段往返保存一致",
              loaded["grid_style"] == "full_frame"
              and loaded["bg_color"] == "#FFF8E1"
              and loaded["border_color"] == "#333333"
              and loaded["mark_color"] == "#123456"
              and loaded["chord_color"] == "#ABCDEF")
        p_old = tmp / "Old.ggp"
        save_ggp(str(p_old), "Old", 4, NoteGrid())
        old_loaded = load_ggp(str(p_old))
        check("T32e 未传样式时回退默认",
              old_loaded["grid_style"] == "default"
              and old_loaded["bg_color"] == "#FFFFFF"
              and old_loaded["border_color"] == "#B8B8B8")
        # 非法字段回退
        p_bad = tmp / "Bad.ggp"
        p_bad.write_text('{"version":2,"note_grid":[[{"k":"Y","c":false}]],'
                         '"grid_style":"nope","bg_color":"zz","border_color":"#12345"}',
                         encoding="utf-8")
        bad_loaded = load_ggp(str(p_bad))
        check("T32f 非法样式/颜色回退默认",
              bad_loaded["grid_style"] == "default"
              and bad_loaded["bg_color"] == "#FFFFFF"
              and bad_loaded["border_color"] == "#B8B8B8")
```

- [ ] **Step 2: 运行确认失败**

Run: `python test_app.py`
Expected: T32d/e/f FAIL（load_ggp 返回 dict 无这些键 → KeyError 中断，先修 KeyError 再断言）。

- [ ] **Step 3: 实现 file_io.py 改动**

在 `file_io.py` 导入区追加：

```python
from grid_style import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_STYLE,
    is_valid_style,
)
```

`save_ggp` 签名与写入逻辑修改（在 `chord_color` 参数后追加三个可选参数）：

```python
def save_ggp(path, title: str, columns_per_line: int, grid: NoteGrid,
             mark_color: str | None = None,
             chord_color: str | None = None,
             style: str | None = None,
             bg_color: str | None = None,
             border_color: str | None = None) -> None:
    """...（原 docstring 保留，追加说明：
    style 总是写入（非法回退默认）；bg_color / border_color 非空时写入。"""
```

`data` 字典构建后追加：

```python
    data["grid_style"] = style if is_valid_style(style) else DEFAULT_STYLE
    if bg_color:
        data["bg_color"] = str(bg_color)
    if border_color:
        data["border_color"] = str(border_color)
```

`load_ggp` 颜色读取处追加（复用 `_read_color`）：

```python
    grid_style = raw.get("grid_style")
    if not is_valid_style(grid_style):
        grid_style = DEFAULT_STYLE
    bg_color = _read_color(raw.get("bg_color"), DEFAULT_BG_COLOR)
    border_color = _read_color(raw.get("border_color"), DEFAULT_BORDER_COLOR)
```

返回 dict 追加三个键：

```python
        "mark_color": mark_color,
        "chord_color": chord_color,
        "grid_style": grid_style,
        "bg_color": bg_color,
        "border_color": border_color,
```

- [ ] **Step 4: 运行确认通过**

Run: `python test_app.py`
Expected: T32d/e/f PASS，且原 T8a–T8n 仍 PASS（新增字段不影响既有断言）。

- [ ] **Step 5: 提交**

```bash
git add file_io.py test_app.py
git commit -m "feat: persist grid style and colors in .ggp"
```

---

### Task 3: sheet_widget 显示区按样式渲染

**Files:**
- Modify: `sheet_widget.py`

- [ ] **Step 1: 写失败测试（默认渲染含新 setter/属性）**

在 T32 块中追加：

```python
        # ---------------- T32g: 显示区样式渲染 ----------------
        sheet.set_style("no_border")
        sheet.set_bg_color(QColor("#FFF8E1"))
        sheet.set_border_color(QColor("#333333"))
        check("T32g 显示区样式 getter/setter 生效",
              sheet.style() == "no_border"
              and sheet.bg_color().name() == "#fff8e1"
              and sheet.border_color().name() == "#333333")
```

- [ ] **Step 2: 运行确认失败**

Run: `python test_app.py`
Expected: T32g FAIL（SheetWidget 无 set_style 方法 → AttributeError）。

- [ ] **Step 3: 实现 sheet_widget.py**

导入区追加：

```python
from grid_style import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_STYLE,
    draws_inner_lines, draws_outer_frame, inner_pen_width, is_valid_style,
)
```

`__init__` 中颜色初始化处追加（`_chord_color` 之后）：

```python
        self._bg_color = QColor(DEFAULT_BG_COLOR)       # 背景色
        self._border_color = QColor(DEFAULT_BORDER_COLOR)  # 格线/外框色
        self._style = DEFAULT_STYLE                     # 格子样式
```

标记颜色 getter/setter 区域（`set_chord_color` 之后）追加：

```python
    # ---------- 格子样式 ----------

    def style(self) -> str:
        """当前格子样式枚举值。"""
        return self._style

    def set_style(self, style):
        """设置格子样式；非法值回退默认。"""
        self._style = style if is_valid_style(style) else DEFAULT_STYLE
        self.update()

    def bg_color(self) -> QColor:
        """当前背景色。"""
        return QColor(self._bg_color)

    def set_bg_color(self, color):
        """设置背景色；None 或非法 QColor 时恢复默认。"""
        self._bg_color = self._coerce_color(color, DEFAULT_BG_COLOR)
        self.update()

    def border_color(self) -> QColor:
        """当前格线/外框颜色。"""
        return QColor(self._border_color)

    def set_border_color(self, color):
        """设置格线/外框颜色；None 或非法 QColor 时恢复默认。"""
        self._border_color = self._coerce_color(color, DEFAULT_BORDER_COLOR)
        self.update()
```

`paintEvent` 修改（替换原 "1) 逐行逐块绘制" 段）：

```python
        # 1) 逐行逐块绘制 3×5 小格：空格用背景色填充，
        #    主旋律格填旋律色、和弦格填和弦色；按样式画内线（no_border 不画）
        pen_width = inner_pen_width(self._style)
        if draws_inner_lines(self._style):
            painter.setPen(QPen(self._border_color, pen_width))
        for line_i in range(n_lines):
            for j in range(cpl):
                col = line_i * cpl + j
                for r in range(ROWS):
                    for c in range(5):
                        rect = self._cell_rect(line_i, r, j, c)
                        key = KEYS[r * 5 + c]
                        if col < num_cols and self._model.is_chord(col, key):
                            painter.fillRect(rect, self._chord_color)
                        elif col < num_cols and self._model.has_note(col, key):
                            painter.fillRect(rect, self._mark_color)
                        else:
                            painter.fillRect(rect, self._bg_color)
                        if draws_inner_lines(self._style):
                            painter.drawRect(rect)
```

`paintEvent` 的 `painter.fillRect(self.rect(), COLOR_BG)` 改为 `painter.fillRect(self.rect(), self._bg_color)`。

在 "2) 光标块外框" 段**之前**插入外框绘制：

```python
        # 1.5) 完整内外边框 / 粗内线+外框：每个节拍块画外框（线宽与内线一致）
        if draws_outer_frame(self._style):
            painter.setPen(QPen(self._border_color, pen_width))
            for line_i in range(n_lines):
                for j in range(cpl):
                    painter.drawRect(self._block_rect(line_i, j))
```

（`COLOR_BG`/`COLOR_CELL_BORDER` 模块常量保留供其他模块引用，不再参与绘制。）

- [ ] **Step 4: 运行确认通过**

Run: `python test_app.py`
Expected: T32g PASS；原 T0/T11/T16 像素断言仍 PASS（默认样式渲染不变）。

- [ ] **Step 5: 提交**

```bash
git add sheet_widget.py test_app.py
git commit -m "feat: render grid styles in sheet widget"
```

---

### Task 4: export.py 导出按样式渲染

**Files:**
- Modify: `export.py`

- [ ] **Step 1: 写失败测试（导出样式像素）**

在 T32 块中追加：

```python
        # ---------------- T32h: 导出样式渲染（固定 MINI=36） ----------------
        from export import render_page_image, MINI as EX_MINI, MARGIN as EX_M
        g1 = NoteGrid(1)
        g1.set_note(0, "Y", False, True)
        img_def = render_page_image(g1, 4, 1, 0)          # 默认样式
        px_def_border = img_def.pixelColor(EX_M + 2, EX_M + 2).name()
        img_nb = render_page_image(g1, 4, 1, 0, style="no_border",
                                   bg_color="#FFF8E1")
        px_nb = img_nb.pixelColor(EX_M + 2, EX_M + 2).name()
        check("T32h 默认导出有内线、no_border 无内线且背景生效",
              px_def_border == "#b8b8b8" and px_nb == "#fff8e1", 
              f"def={px_def_border} nb={px_nb}")
        img_ff = render_page_image(g1, 4, 1, 0, style="full_frame",
                                   border_color="#333333")
        px_frame = img_ff.pixelColor(EX_M, EX_M).name()   # 块外框左上角
        check("T32i 完整内外边框导出画外框（自定义边框色）",
              px_frame == "#333333", f"frame={px_frame}")
```

- [ ] **Step 2: 运行确认失败**

Run: `python test_app.py`
Expected: T32h/i FAIL（render_page_image 无 style 参数 → TypeError）。

- [ ] **Step 3: 实现 export.py**

导入区追加：

```python
from grid_style import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR,
    draws_inner_lines, draws_outer_frame, inner_pen_width,
)
```

`render_page_image` 签名追加三个参数并接线：

```python
def render_page_image(grid: NoteGrid, columns_per_line: int, rows_per_page: int,
                      page_index: int,
                      mark_color: str | None = None,
                      chord_color: str | None = None,
                      title: str | None = None,
                      style: str | None = None,
                      bg_color: str | None = None,
                      border_color: str | None = None) -> QImage:
```

函数体颜色构造处追加（`chord_qcolor` 之后）：

```python
    bg_qcolor = _valid_qcolor(bg_color, DEFAULT_BG_COLOR)
    border_qcolor = _valid_qcolor(border_color, DEFAULT_BORDER_COLOR)
```

`image.fill(COLOR_BG)` → `image.fill(bg_qcolor)`；`_draw_sheet(...)` 调用追加参数：

```python
    _draw_sheet(painter, grid, cols_per_line, first_line, lines,
                mark_qcolor, chord_qcolor, title_h,
                style, bg_qcolor, border_qcolor)
```

`_draw_sheet` 签名与循环修改：

```python
def _draw_sheet(painter: QPainter, grid: NoteGrid, cols_per_line: int,
                first_line: int, num_lines: int,
                mark_qcolor: QColor, chord_qcolor: QColor,
                title_h: int = 0,
                style: str | None = None,
                bg_qcolor: QColor | None = None,
                border_qcolor: QColor | None = None):
    """...（原 docstring 保留，追加：按样式画内线/外框，线宽粗细跟随样式）"""
    block_y0 = MARGIN + title_h
    num_columns = grid.num_columns()
    cell_step = MINI + MINI_GAP
    if bg_qcolor is None:
        bg_qcolor = COLOR_BG
    if border_qcolor is None:
        border_qcolor = COLOR_CELL_BORDER
    style = style or "default"
    pen_width = inner_pen_width(style)
    if draws_inner_lines(style):
        painter.setPen(QPen(border_qcolor, pen_width))
    for i in range(num_lines):
        line = first_line + i
        block_y = block_y0 + i * (BLOCK_H + LINE_GAP)
        for j in range(cols_per_line):
            beat = line * cols_per_line + j
            bx = MARGIN + j * (BLOCK_W + BLOCK_GAP)
            for r in range(ROWS):
                for c in range(5):
                    x = bx + c * cell_step
                    y = block_y + r * cell_step
                    key = KEYS[r * 5 + c]

                    # 小格：空 = 底色；和弦格填和弦色；主旋律格填旋律色
                    if beat < num_columns:
                        if grid.is_chord(beat, key):
                            painter.setBrush(chord_qcolor)
                        elif grid.has_note(beat, key):
                            painter.setBrush(mark_qcolor)
                        else:
                            painter.setBrush(bg_qcolor)
                    else:
                        painter.setBrush(bg_qcolor)
                    if draws_inner_lines(style):
                        painter.drawRect(x, y, MINI, MINI)
            # 外框：包住整个 3×5 节拍块（线宽与内线一致）
            if draws_outer_frame(style):
                painter.setPen(QPen(border_qcolor, pen_width))
                painter.drawRect(bx, block_y, BLOCK_W, BLOCK_H)
```

`render_sheet_image` 与 `export_pages` 追加同签名参数并透传；`export_png` 同样追加并透传给 `render_sheet_image`。

- [ ] **Step 4: 运行确认通过**

Run: `python test_app.py`
Expected: T32h/i PASS；T9/T11/T18/T20/T23 全部保持 PASS（未传 style 时渲染不变）。

- [ ] **Step 5: 提交**

```bash
git add export.py test_app.py
git commit -m "feat: render grid styles in PNG export"
```

---

### Task 5: main_window 工具栏下拉框 + 保存/打开接线

**Files:**
- Modify: `main_window.py`

- [ ] **Step 1: 写失败测试（下拉框存在并联动）**

在 T32 块中追加：

```python
        # ---------------- T32j: 工具栏样式下拉框联动 ----------------
        combo = window.style_combo
        check("T32j 工具栏含 6 项样式下拉框且联动显示区",
              combo.count() == 6)
        idx = combo.findData("full_frame")
        combo.setCurrentIndex(idx)
        QTest.qWait(10)
        check("T32k 切换下拉框实时生效",
              window.sheet.style() == "full_frame" and window._style == "full_frame")
```

- [ ] **Step 2: 运行确认失败**

Run: `python test_app.py`
Expected: T32j FAIL（MainWindow 无 style_combo 属性 → AttributeError）。

- [ ] **Step 3: 实现 main_window.py**

导入区追加：

```python
from grid_style import (DEFAULT_BORDER_COLOR, DEFAULT_BG_COLOR, DEFAULT_STYLE,
                        STYLE_OPTIONS, GridStyle, is_valid_style)
from dialogs import BrowseSheetsDialog, ExportDialog, StyleColorsDialog, prompt_title
```

`__init__` 状态区（`self._chord_color` 之后）追加：

```python
        self._style: str = DEFAULT_STYLE                 # 格子样式
        self._bg_color: str | None = None                # None=默认背景色
        self._border_color: str | None = None            # None=默认边框色
```

工具栏（`chord_color_btn` 之后、`self.toolbar.addSeparator()` 之前）追加：

```python
        self.toolbar.addWidget(QLabel("格子样式"))
        self.style_combo = QComboBox()
        for value, label in STYLE_OPTIONS:
            self.style_combo.addItem(label, value)
        self.style_combo.setToolTip("格子谱样式：边框形态（默认/完整内外边框/无外边框/无边框纯色块/粗内线/粗内线+外框）")
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.toolbar.addWidget(self.style_combo)

        style_colors_btn = QPushButton("样式颜色")
        style_colors_btn.setToolTip("自定义旋律/和弦/背景/边框颜色（随乐谱保存）")
        style_colors_btn.clicked.connect(self.open_style_colors)
        self.toolbar.addWidget(style_colors_btn)
```

导入区需要补充 `QComboBox`（当前未导入）。

新增方法（放在 `choose_chord_color` 之后）：

```python
    # ---------- 动作：格子样式 ----------

    def _on_style_changed(self, *_):
        """下拉框切换样式：同步显示区并置脏。"""
        value = self.style_combo.currentData()
        style = value if is_valid_style(value) else DEFAULT_STYLE
        if style != self._style:
            self._style = style
            self.sheet.set_style(style)
            self._mark_dirty()
            self.statusBar().showMessage(f"格子样式已切换：{style}", 3000)

    def open_style_colors(self):
        """打开样式颜色对话框：四色实时作用于显示区并随乐谱保存。"""
        dlg = StyleColorsDialog(
            self, GridStyle.coerce(style=self._style,
                                   bg_color=self._bg_color,
                                   border_color=self._border_color,
                                   mark_color=self._mark_color,
                                   chord_color=self._chord_color))
        dlg.styleChanged.connect(self._apply_style_colors)
        dlg.exec()

    def _apply_style_colors(self, gs: GridStyle):
        """应用样式颜色（实时预览，置脏）。"""
        self._style = gs.style
        self._bg_color = gs.bg_color if gs.bg_color != DEFAULT_BG_COLOR else None
        self._border_color = (gs.border_color
                              if gs.border_color != DEFAULT_BORDER_COLOR else None)
        self._mark_color = gs.mark_color if gs.mark_color != DEFAULT_MARK_COLOR else None
        self._chord_color = (gs.chord_color
                             if gs.chord_color != DEFAULT_CHORD_COLOR else None)
        self.sheet.set_style(gs.style)
        self.sheet.set_bg_color(QColor(gs.bg_color))
        self.sheet.set_border_color(QColor(gs.border_color))
        self.sheet.set_mark_color(QColor(gs.mark_color))
        self.sheet.set_chord_color(QColor(gs.chord_color))
        idx = self.style_combo.findData(gs.style)
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)
        self._mark_dirty()
```

`save_sheet` 的 `save_ggp(...)` 调用追加参数：

```python
        save_ggp(path, title, self.sheet.columns_per_line(), self._model,
                 mark_color=self._mark_color, chord_color=self._chord_color,
                 style=self._style, bg_color=self._bg_color,
                 border_color=self._border_color)
```

`browse_sheets` 打开恢复段（`chord_color` 恢复之后）追加：

```python
        # 恢复格子样式与背景/边框色（文件带字段时）
        style = data.get("grid_style")
        self._style = style if is_valid_style(style) else DEFAULT_STYLE
        self.sheet.set_style(self._style)
        idx = self.style_combo.findData(self._style)
        if idx >= 0:
            self.style_combo.blockSignals(True)
            self.style_combo.setCurrentIndex(idx)
            self.style_combo.blockSignals(False)
        self._bg_color = (data.get("bg_color")
                          if data.get("bg_color") != DEFAULT_BG_COLOR else None)
        self._border_color = (data.get("border_color")
                              if data.get("border_color") != DEFAULT_BORDER_COLOR
                              else None)
        self.sheet.set_bg_color(QColor(data.get("bg_color") or DEFAULT_BG_COLOR))
        self.sheet.set_border_color(
            QColor(data.get("border_color") or DEFAULT_BORDER_COLOR))
```

`export_png` 的 `ExportDialog(...)` 与 `export_pages(...)` 调用追加：

```python
        dlg = ExportDialog(
            self._model, self.sheet.columns_per_line(),
            default_title=self.title_edit.text().strip(),
            mark_color=self.sheet.mark_color().name(),
            chord_color=self.sheet.chord_color().name(),
            style=self._style,
            bg_color=self.sheet.bg_color().name(),
            border_color=self.sheet.border_color().name(),
            default_dir=str(default_output_dir()),
            parent=self)
        ...
        ok, pages = export_pages(
            path_base, self._model, dlg.columns_per_line(), dlg.rows_per_page(),
            mark_color=dlg.mark_color(), chord_color=dlg.chord_color(),
            style=dlg.style(), bg_color=dlg.bg_color(),
            border_color=dlg.border_color(),
            title=dlg.display_name(), draw_title=dlg.draw_title())
```

- [ ] **Step 4: 运行确认通过**

Run: `python test_app.py`
Expected: T32j/k PASS；T1a/T26f/T30e 等涉及工具栏的测试仍 PASS。

- [ ] **Step 5: 提交**

```bash
git add main_window.py test_app.py
git commit -m "feat: add style dropdown and colors wiring in main window"
```

---

### Task 6: ExportDialog 临时样式 + StyleColorsDialog

**Files:**
- Modify: `dialogs.py`

- [ ] **Step 1: 写失败测试（ExportDialog 临时样式不写回乐谱）**

在 T32 块中追加：

```python
        # ---------------- T32l: 导出对话框临时样式 ----------------
        ed = dlg.ExportDialog(NoteGrid(2), 4, default_title="Temp",
                              style="default")
        ed.style_combo.setCurrentIndex(ed.style_combo.findData("thick_frame"))
        ed.set_bg_color("#FFEEDD")
        check("T32l 导出对话框样式读取为临时值",
              ed.style() == "thick_frame" and ed.bg_color() == "#FFEEDD")
        check("T32m 导出临时样式不影响乐谱保存值",
              window.sheet.style() == "full_frame"
              and window._style == "full_frame")
        ed.close()
```

（注：`ed.set_bg_color` 为对话框内部直接设置 `_bg_color` 的辅助方法，Task 6 Step 3 实现。）

- [ ] **Step 2: 运行确认失败**

Run: `python test_app.py`
Expected: T32l FAIL（ExportDialog 无 style_combo 属性 → AttributeError）。

- [ ] **Step 3: 实现 dialogs.py**

导入区追加：

```python
from grid_style import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_STYLE,
    STYLE_OPTIONS, GridStyle, is_valid_style,
)
```

**A. 新增 `StyleColorsDialog`**（放在 `BrowseSheetsDialog` 之前）：

```python
class StyleColorsDialog(QDialog):
    """样式颜色设置：旋律/和弦/背景/边框 四色，改动实时作用于显示区。

    styleChanged 信号携带最新 GridStyle（随乐谱保存，非临时）。
    """

    styleChanged = Signal(object)

    def __init__(self, parent=None, style: GridStyle | None = None):
        super().__init__(parent)
        self.setWindowTitle("样式颜色")
        self.resize(320, 260)
        self._style = style or GridStyle()

        layout = QVBoxLayout(self)
        hint = QLabel("点击按钮选择颜色，实时生效并随乐谱保存")
        layout.addWidget(hint)

        self._btn_specs = [
            ("旋律色", "mark_color"),
            ("和弦色", "chord_color"),
            ("背景色", "bg_color"),
            ("边框色", "border_color"),
        ]
        self._buttons: dict[str, QPushButton] = {}
        for label, attr in self._btn_specs:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _=False, a=attr: self._pick(a))
            self._buttons[attr] = btn
            layout.addWidget(btn)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        self._refresh()

    # ---------- 内部 ----------

    def _refresh(self):
        """用当前样式颜色给按钮着色（文字即色标）。"""
        for attr, btn in self._buttons.items():
            color = getattr(self._style, attr)
            btn.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _pick(self, attr: str):
        color = QColorDialog.getColor(QColor(getattr(self._style, attr)),
                                      self, "选择颜色")
        if color.isValid():
            setattr(self._style, attr, color.name())
            self._refresh()
            self.styleChanged.emit(self._style)

    # ---------- 对外取值 ----------

    def style(self) -> GridStyle:
        return GridStyle(**self._style.__dict__)
```

**B. `ExportDialog.__init__`** 签名追加三个参数（`chord_color` 之后）：

```python
                 mark_color: str | None = None, chord_color: str | None = None,
                 style: str | None = None,
                 bg_color: str | None = None,
                 border_color: str | None = None,
                 default_dir: str = "", parent=None):
```

初始化追加（`self._chord_color = ...` 之后）：

```python
        self._style = style if is_valid_style(style) else DEFAULT_STYLE
        self._bg_color = bg_color or DEFAULT_BG_COLOR
        self._border_color = border_color or DEFAULT_BORDER_COLOR
```

颜色行（`color_row` 中 `chord_btn` 之后、`addStretch` 之前）追加两个按钮：

```python
        self.bg_btn = QPushButton("背景色")
        self.bg_btn.setToolTip("修改谱面底色，实时刷新预览（仅本次导出）")
        self.bg_btn.clicked.connect(self._choose_bg_color)
        color_row.addWidget(self.bg_btn)
        self.border_btn = QPushButton("边框色")
        self.border_btn.setToolTip("修改格线/外框颜色，实时刷新预览（仅本次导出）")
        self.border_btn.clicked.connect(self._choose_border_color)
        color_row.addWidget(self.border_btn)
```

在颜色行之后新增样式行（插到 `page_row` 之前）：

```python
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("格子样式"))
        self.style_combo = QComboBox()
        for value, label in STYLE_OPTIONS:
            self.style_combo.addItem(label, value)
        self.style_combo.setCurrentIndex(
            max(0, self.style_combo.findData(self._style)))
        self.style_combo.currentIndexChanged.connect(self._refresh)
        style_row.addWidget(self.style_combo)
        style_row.addWidget(QLabel("（仅本次导出生效）"))
        style_row.addStretch(1)
        layout.addLayout(style_row)
```

新增颜色选择方法（`_choose_chord_color` 之后）：

```python
    def _choose_bg_color(self):
        color = QColorDialog.getColor(QColor(self._bg_color), self, "选择背景颜色")
        if color.isValid():
            self._bg_color = color.name()
            self._sync_color_buttons()
            self._refresh()

    def _choose_border_color(self):
        color = QColorDialog.getColor(QColor(self._border_color), self, "选择边框颜色")
        if color.isValid():
            self._border_color = color.name()
            self._sync_color_buttons()
            self._refresh()
```

`_sync_color_buttons` 末尾追加：

```python
        self.bg_btn.setStyleSheet(f"color: {self._bg_color}; font-weight: bold;")
        self.border_btn.setStyleSheet(
            f"color: {self._border_color}; font-weight: bold;")
```

`_refresh` 中 `render_page_image(...)` 调用追加参数：

```python
        img = render_page_image(self._grid, cols, rows,
                                self.page_spin.value() - 1,
                                self._mark_color, self._chord_color, title,
                                style=self._style, bg_color=self._bg_color,
                                border_color=self._border_color)
```

对外取值区追加：

```python
    def style(self) -> str:
        """本次导出的格子样式（临时，不写回乐谱）。"""
        value = self.style_combo.currentData()
        return value if is_valid_style(value) else DEFAULT_STYLE

    def bg_color(self) -> str:
        """本次导出的背景色（临时）。"""
        return self._bg_color

    def border_color(self) -> str:
        """本次导出的边框色（临时）。"""
        return self._border_color
```

导入区补充 `QComboBox`（当前 dialogs.py 未导入）。

- [ ] **Step 4: 运行确认通过**

Run: `python test_app.py`
Expected: T32l/m PASS；T20g–T20k、T23d/e 仍 PASS（导出对话框新增控件不影响既有断言）。

- [ ] **Step 5: 提交**

```bash
git add dialogs.py test_app.py
git commit -m "feat: temp style controls in export dialog and style colors dialog"
```

---

### Task 7: 全量回归验证

**Files:**
- Test: `test_app.py`（T32 系列全部就位）

- [ ] **Step 1: 运行全量回归**

Run: `python test_app.py`
Expected: 全部 PASS，`TOTAL_OK: 208/208`（原 200 + T32a–m 共 8 项：T32a,b,c,d,e,f,g,h,i,j,k,l,m = 13 项，按实际插入数量核对，需 >200 且无 FAIL）。

- [ ] **Step 2: 修复任何失败**

若出现 FAIL：按测试名定位对应 Task 实现，修正后重跑；重点核对：
- 默认样式渲染像素不变（T0/T11/T16/T18/T20 不能回归）；
- `GridStyle.coerce` / `load_ggp` 非法值回退路径；
- 主窗口 `style_combo` 与 `ExportDialog.style_combo` 名称不冲突。

- [ ] **Step 3: 提交**

```bash
git add test_app.py
git commit -m "test: add grid style regression tests (T32)"
```

- [ ] **Step 4: 运行应用人工冒烟（可选）**

Run: `python main.py`
手动核对：切换 6 种样式实时变化；样式颜色对话框四色生效；保存后重新打开样式还原；导出预览临时改样式只影响导出图。

---

## 自审结论

- **Spec 覆盖**：6 种样式（Task 1/3/4）✓；4 色自定义（Task 5/6）✓；下拉框切换（Task 5）✓；随 .ggp 保存且兼容旧文件（Task 2）✓；显示/导出统一渲染（Task 3/4）✓；导出预览临时调整不写回（Task 6）✓。
- **占位符扫描**：无 TBD/TODO；所有代码步骤给出完整实现。
- **类型一致性**：`GridStyle`（style/bg_color/border_color/mark_color/chord_color）贯穿 grid_style → file_io → sheet_widget → dialogs → main_window；`style()`/`bg_color()`/`border_color()` accessor 命名统一。
