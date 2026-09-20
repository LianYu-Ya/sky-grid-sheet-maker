# -*- coding: utf-8 -*-
"""格子谱显示区（块状样式，经典光遇格子谱风格，version 2）。

整份谱子 = N 个节拍块（每块 = 一个 3×5 键位小网格），块按"每横排 X 个"
从左到右排列，排满 X 个后换到下一行继续：
- 每个 3×5 块内，主旋律键对应小格填"旋律颜色"、和弦键对应小格填"和弦颜色"，
  无文字；空格白底浅灰边框；
- 块大小随窗口宽度自动缩放（小格边长约 18–44px），保证每横排 X 个块铺满，
  格子谱整体水平居中；内容高于可视区时可上下滚动（配合外部 QScrollArea），
  矮于可视区时垂直居中；
- 光标所在节拍块的整块外框用 2px 强调色描边；
- 点击：左键切换该格对应键的主旋律标记、右键切换该格对应键的和弦标记、
  中键只切换光标（不更改任何标记），点在最后一列之后的块 → 自动扩展节拍；
- 键盘：YUIOPHJKL;NM,./ 输入（普通按键切换主旋律标记且不前进光标、
  Shift+按键切换和弦标记也不前进；按键按 event.key() 做基础字符映射，
  Shift 修饰下 `; , . /`（event.text() 会变成 `: < > ?`，event.key() 为
  Key_Colon/Key_Less/Key_Greater/Key_Question）仍能正确输入）、
  Backspace 清空光标所在（高亮）节拍的全部音符（保留空拍位置、不连带删空拍）、
  Del 删除光标所在（高亮）节拍（整拍移除、后续节拍左移）、
  左右方向键移动光标（右移到末尾自动追加空白节拍）；
- 自动跳转（R13，可选开关）：开启后"键盘输入 + 键位面板点击"按节奏自动换拍——
  从本拍第一个键按下开始计时，阈值（可调，默认 800ms）内的按键全部归本拍；
  超过阈值后的下一次按键先自动前进到下一节拍（末尾自动追加空白拍）再放置。

绘制与点击的坐标换算完全一致：每个标记格只填自己约 30px 级的小格矩形
（修复历史版本中"点一个键整块/整行变色"的渲染 bug）。
点击换算前先 _sync_mini() 同步小格边长、偏移量取整（R1/R10）——
保证点击与绘制永远使用同一套 _mini 与偏移，杜绝"标记偏一格"。
"""

import time

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from model import (
    DEFAULT_CHORD_COLOR, DEFAULT_MARK_COLOR, KEYS, KEY_ROWS, ROWS, NoteGrid,
)
from grid_style import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_STYLE,
    draws_inner_lines, draws_outer_frame, inner_pen_width, is_valid_style,
    uses_continuous_lines,
)

# ---------- 简约白色主题配色 ----------
COLOR_BG = QColor("#FFFFFF")          # 背景纯白
COLOR_CELL_BORDER = QColor("#B8B8B8")  # 小格边框（R10 加深，更清晰）
COLOR_ACCENT = QColor("#4A90D9")      # 光标块外框强调色

# ---------- 布局常量（像素） ----------
MINI_DEFAULT = 30        # 小格边长默认值
MINI_MIN = 18            # 小格边长下限（缩放 clamp）
MINI_MAX = 44            # 小格边长上限（缩放 clamp）
MINI_GAP = 2             # 小格间距
BLOCK_GAP = 12           # 块间距
LINE_GAP = 24            # 横排（行）与行之间的空隙
MARGIN_X = 16            # 左右边距
MARGIN_Y = 12            # 上下边距


class SheetWidget(QWidget):
    """块状 3×5 格子谱显示区（完整实现，version 2）。"""

    keySelected = Signal(str)     # 键盘或 apply_key 产生键字母时发出（同步键位面板高亮）
    modelChanged = Signal()       # 网格内容变化时发出（主窗口刷新状态栏/置脏）
    cursorMoved = Signal(int)     # 光标位置变化时发出（主窗口刷新光标显示，不清脏）

    def __init__(self, model: NoteGrid, columns_per_line: int = 4, parent=None):
        super().__init__(parent)
        self._model = model
        self._columns_per_line = int(columns_per_line)
        self._cursor_col = 0          # 当前光标节拍（全局列号）
        self._current_key = "J"       # 当前选中键（键位面板同步）
        self._mark_color = QColor(DEFAULT_MARK_COLOR)    # 主旋律标记颜色
        self._chord_color = QColor(DEFAULT_CHORD_COLOR)  # 和弦标记颜色
        self._bg_color = QColor(DEFAULT_BG_COLOR)       # 背景色
        self._border_color = QColor(DEFAULT_BORDER_COLOR)  # 格线/外框色
        self._style = DEFAULT_STYLE                     # 格子样式
        self._mini = MINI_DEFAULT     # 当前小格边长（随宽度自适应）
        self._last_width = -1         # 上次处理过的宽度（防 resize 死循环）
        # R13 自动跳转：开关默认关；阈值默认 800ms；本拍第一个键的时间戳
        self._auto_advance = False
        self._advance_threshold_ms = 800
        self._beat_start_time: float | None = None
        # 鼠标点击期间抑制自动滚动（避免点击格子谱时视图乱跳）
        self._suppress_scroll = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(140)

    # ---------- 对外 API（契约） ----------

    def model(self) -> NoteGrid:
        return self._model

    def set_model(self, model: NoteGrid):
        """更换内部 model（供主窗口新建/打开时使用）。"""
        self._model = model
        self.set_cursor(self._cursor_col)   # 将光标夹取到新模型范围
        self.updateGeometry()
        self.update()

    # ---------- R13 自动跳转 ----------

    def set_auto_advance(self, enabled: bool):
        """开关自动跳转：关闭时重置计时起点（避免残留计时造成误跳）。"""
        self._auto_advance = bool(enabled)
        if not self._auto_advance:
            self._beat_start_time = None

    def auto_advance_enabled(self) -> bool:
        return self._auto_advance

    def set_advance_threshold(self, ms: int):
        """设置同拍合并时间窗（毫秒，>=0；0 表示立即换拍）。"""
        self._advance_threshold_ms = max(0, int(ms))

    def advance_threshold_ms(self) -> int:
        return self._advance_threshold_ms

    def _auto_advance_before_input(self):
        """自动跳转判定：距本拍第一个键超过阈值 → 先前进到下一拍。

        只在本拍已开始计时（即本拍已有按键）时判定；本次按键总会把
        计时起点重置为当前时刻，成为"新拍"的第一个键。
        """
        if not self._auto_advance:
            return
        now = time.monotonic()
        if self._beat_start_time is not None and \
                now - self._beat_start_time >= self._advance_threshold_ms / 1000.0:
            self.move_cursor(1)   # 末尾自动追加空白拍（R2），中途前进一格
        self._beat_start_time = now


    def apply_key(self, key: str):
        """切换 key 主旋律标记到光标节拍（R3：不前进光标、不发 cursorMoved）。

        已标记则取消、未标记则添加（与键位面板点击、格子谱点击语义一致）。
        """
        if key not in KEY_ROWS:
            return
        self._auto_advance_before_input()   # R13：超阈值先前进到下一拍
        self._model.toggle_note(self._cursor_col, key, chord=False)
        self._current_key = key
        self.keySelected.emit(key)
        self.modelChanged.emit()
        self.updateGeometry()   # 列数可能增加，刷新滚动区尺寸
        self.update()

    def place_at_cursor(self, key: str, chord: bool = False):
        """在当前光标节拍放置音符，不前进光标（键位面板点击入口）。

        chord=False → 主旋律：用 toggle_note(chord=False) 切换主旋律标记
        （已标记则取消，未标记则添加）；
        chord=True  → 和弦：用 toggle_note(chord=True) 切换和弦标记。
        """
        if key not in KEY_ROWS:
            return
        self._auto_advance_before_input()   # R13：超阈值先前进到下一拍
        self._model.toggle_note(self._cursor_col, key, chord=chord)
        self._current_key = key
        self.keySelected.emit(key)
        self.modelChanged.emit()
        self.updateGeometry()
        self.update()

    def backspace(self):
        """Backspace：删除（清空）光标所在（高亮）节拍的全部音符。

        只清空该拍内容、保留空拍位置——不做 trim，中间/尾部空拍结构原样保留，
        避免"连着空拍一并删除"；光标保持原位，不发 cursorMoved。
        """
        self._model.clear_beat(self._cursor_col)
        self.modelChanged.emit()
        self.updateGeometry()
        self.update()

    def delete_beat(self):
        """Del：删除光标所在（高亮）节拍（整拍移除，后续节拍整体左移）。

        只删除目标节拍这一列，绝不连带删除其前后的空拍；谱子至少保留 1 列。
        光标夹取回有效范围（若删的是最后一拍，光标停在新的末尾）。
        """
        self._model.delete_column(self._cursor_col)
        self._cursor_col = max(0, min(self._cursor_col, self._model.num_columns() - 1))
        self.modelChanged.emit()
        self.updateGeometry()
        self.update()

    def move_cursor(self, delta: int):
        """光标左右移动（负为左，R2）。

        右移到最后一拍之后再右移 → 自动追加一个空白节拍并移入；
        左移到 0 后不再移动；移动仍发 cursorMoved（由 set_cursor 发出）。
        """
        new = self._cursor_col + int(delta)
        if new < 0:
            return
        if new >= self._model.num_columns():
            # 移到已有节拍之外：追加空白节拍
            self._model.ensure_columns(new + 1)
            self.updateGeometry()
        self.set_cursor(new)

    def set_cursor(self, col: int):
        """设置光标节拍（夹在 [0, max(num_columns, 0)] 之间）。

        光标移动时重置 R13 计时起点，避免手动移拍后残留计时造成误跳。
        """
        col = max(0, min(int(col), max(self._model.num_columns(), 0)))
        self._beat_start_time = None
        if col != self._cursor_col:
            self._cursor_col = col
            self.cursorMoved.emit(col)
            self.update()

    def cursor(self) -> int:
        return self._cursor_col

    def set_columns_per_line(self, n: int):
        """设置每横排节拍块数并重新布局（夹取到 4–16）。

        关键：先重置 _last_width 再重算 _mini——否则"宽度未变"的守卫
        （_recompute_mini 的 `if width == self._last_width: return`）会挡住
        小格边长随每横排数的即时重算，导致改动必须等窗口 resize 才生效。
        """
        n = int(n)
        if n < 4 or n > 16:
            n = max(4, min(16, n))
        if n == self._columns_per_line:
            return
        self._columns_per_line = n
        self._last_width = -1          # 解除宽度守卫，强制按当前宽度重算小格边长
        self._recompute_mini(self.width())
        self.updateGeometry()
        self.update()

    def columns_per_line(self) -> int:
        return self._columns_per_line

    def current_key(self) -> str:
        return self._current_key

    # ---------- 标记颜色 ----------

    def mark_color(self) -> QColor:
        """当前主旋律标记颜色。"""
        return QColor(self._mark_color)

    def set_mark_color(self, color):
        """设置主旋律标记颜色；传入 None 或非法 QColor 时恢复默认色。"""
        self._mark_color = self._coerce_color(color, DEFAULT_MARK_COLOR)
        self.update()

    def chord_color(self) -> QColor:
        """当前和弦标记颜色。"""
        return QColor(self._chord_color)

    def set_chord_color(self, color):
        """设置和弦标记颜色；传入 None 或非法 QColor 时恢复默认色。"""
        self._chord_color = self._coerce_color(color, DEFAULT_CHORD_COLOR)
        self.update()

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

    @staticmethod
    def _coerce_color(color, default: str) -> QColor:
        if color is None:
            return QColor(default)
        if isinstance(color, QColor) and color.isValid():
            return QColor(color)
        return QColor(default)

    # ---------- 缩放与布局 ----------

    def _block_w(self) -> int:
        """当前节拍块宽度（随小格边长缩放）。"""
        return 5 * self._mini + 4 * MINI_GAP

    def _block_h(self) -> int:
        """当前节拍块高度（随小格边长缩放）。"""
        return 3 * self._mini + 2 * MINI_GAP

    def _compute_mini(self, width: int) -> int:
        """根据可用宽度计算小格边长：X 个块 + 块间距刚好铺满（clamp 18–44）。"""
        cpl = max(1, self._columns_per_line)
        avail = width - 2 * MARGIN_X
        # X 个块并排：每块 = 5*mini + 4*MINI_GAP，块间 (X-1)*BLOCK_GAP
        numerator = avail - (cpl - 1) * BLOCK_GAP - cpl * 4 * MINI_GAP
        mini = int(numerator // (cpl * 5)) if cpl > 0 and numerator > 0 else MINI_DEFAULT
        return max(MINI_MIN, min(MINI_MAX, mini))

    def _recompute_mini(self, width: int):
        """宽度变化时重算小格边长（记录上次宽度防死循环）。"""
        if width == self._last_width:
            return
        self._last_width = width
        self._mini = self._compute_mini(width)

    def _sync_mini(self):
        """确保 _mini 与当前宽度一致（resizeEvent 与绘制兜底共用）。

        resizeEvent 在窗口尺寸变化时触发；独立 widget（未显示）绘制前
        也调用一次，保证小格边长始终与宽度匹配。
        """
        w = self.width()
        if w != self._last_width:
            self._last_width = w
            self._mini = self._compute_mini(w)

    def resizeEvent(self, event):
        """宽度变化时自适应缩放小格边长并刷新几何尺寸。"""
        super().resizeEvent(event)
        self._sync_mini()
        self.updateGeometry()
        self.update()

    def _offset_x(self) -> int:
        """水平居中偏移（取整，避免半像素模糊）：宽度富余时内容居中，否则 0（可滚动）。"""
        return int((self.width() - self.sizeHint().width()) / 2.0)

    def _offset_y(self) -> int:
        """垂直偏移（取整）：内容高于视图时顶部对齐（滚动），矮于视图时垂直居中。"""
        return int((self.height() - self.sizeHint().height()) / 2.0)

    # ---------- 换行逻辑 ----------

    def _lines(self) -> list[range]:
        """按每横排 columns_per_line 块把 [0, num_columns) 切成多段（供绘制与点击换算共用）。"""
        n = self._model.num_columns()
        if n <= 0:
            return [range(0, 0)]
        step = max(1, self._columns_per_line)
        return [range(start, min(start + step, n)) for start in range(0, n, step)]

    # ---------- 布局辅助 ----------

    def _block_rect(self, line: int, col_in_line: int) -> QRect:
        """第 line 横排、第 col_in_line 个节拍块的外框矩形（内容坐标，不含居中偏移）。"""
        x = MARGIN_X + col_in_line * (self._block_w() + BLOCK_GAP)
        y = MARGIN_Y + line * (self._block_h() + LINE_GAP)
        return QRect(x, y, self._block_w(), self._block_h())

    def _cell_rect(self, line: int, row: int, col_in_line: int, c: int) -> QRect:
        """某节拍块内小格 (row, c) 的矩形区域（内容坐标，不含居中偏移）。

        关键：每个标记格只使用自己的小格坐标与尺寸（约 _mini 见方），
        绝不使用块/行/列的坐标或尺寸，避免"点一个键整块/整行变色"。
        """
        x = (MARGIN_X + col_in_line * (self._block_w() + BLOCK_GAP)
             + c * (self._mini + MINI_GAP))
        y = (MARGIN_Y + line * (self._block_h() + LINE_GAP)
             + row * (self._mini + MINI_GAP))
        return QRect(x, y, self._mini, self._mini)

    def sizeHint(self) -> QSize:
        """宽度=每横排块数铺满，高度随换行行数增长（默认至少两横排），供外部 QScrollArea 正确滚动。"""
        n_lines = max(2, len(self._lines()))   # 默认显示两横排（不足时第二行为空网格）
        cpl = max(1, self._columns_per_line)
        width = 2 * MARGIN_X + cpl * self._block_w() + (cpl - 1) * BLOCK_GAP
        height = 2 * MARGIN_Y + n_lines * self._block_h() + (n_lines - 1) * LINE_GAP
        return QSize(width, height)

    # ---------- 键盘事件 ----------

    def keyPressEvent(self, event):
        # 基础字符映射：按 event.key()（而非 event.text()）构造基础键字母，
        # 使 Shift+`; , . /`（此时 event.text() 为 `: < > ?`）仍能正确输入和弦
        key_code = event.key()
        if Qt.Key_A <= key_code <= Qt.Key_Z:
            base = chr(key_code)
        elif key_code == Qt.Key_Semicolon:
            base = ";"
        elif key_code == Qt.Key_Comma:
            base = ","
        elif key_code == Qt.Key_Period:
            base = "."
        elif key_code == Qt.Key_Slash:
            base = "/"
        elif key_code == Qt.Key_Colon:       # R6：Shift+;（event.key() 的另一种键码）
            base = ";"
        elif key_code == Qt.Key_Less:        # R6：Shift+,
            base = ","
        elif key_code == Qt.Key_Greater:     # R6：Shift+.
            base = "."
        elif key_code == Qt.Key_Question:    # R6：Shift+/
            base = "/"
        else:
            base = ""
        if base in KEY_ROWS:
            if event.modifiers() & Qt.ShiftModifier:
                # Shift+按键：在当前光标节拍切换该键的和弦标记，不前进光标
                self._model.toggle_note(self._cursor_col, base, chord=True)
                self._current_key = base
                self.modelChanged.emit()
                self.updateGeometry()
                self.update()
            else:
                # 普通按键：放置主旋律标记并前进光标
                self.apply_key(base)
            event.accept()
            return
        key = event.key()
        if key == Qt.Key_Backspace:
            self.backspace()
            event.accept()
            return
        if key == Qt.Key_Delete:
            self.delete_beat()
            event.accept()
            return
        if key == Qt.Key_Left:
            self.move_cursor(-1)
            event.accept()
            return
        if key == Qt.Key_Right:
            self.move_cursor(1)
            event.accept()
            return
        super().keyPressEvent(event)

    # ---------- 鼠标事件 ----------

    def mousePressEvent(self, event):
        button = event.button()
        if button not in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            return
        # R1：点击换算前先同步小格边长——保证与绘制（paintEvent 也先 _sync_mini）
        # 使用同一套 _mini，杜绝宽度变化后"点击换算用旧值、绘制用新值"的偏格
        self._sync_mini()
        pos = event.position()
        x = pos.x() - self._offset_x()
        y = pos.y() - self._offset_y()
        cpl = max(1, self._columns_per_line)

        # 换算点击位置所在横排（line）与块内行号（row）
        rel_y = y - MARGIN_Y
        if rel_y < 0:
            return
        unit_y = self._block_h() + LINE_GAP
        line = int(rel_y // unit_y)
        rem_y = rel_y - line * unit_y
        if rem_y >= self._block_h():
            return    # 落在行与行之间的空隙
        row = int(rem_y // (self._mini + MINI_GAP))
        if row >= ROWS:
            return    # 落在块内行间距

        # 换算块内列号（col_in_line）与小格列号（c）
        rel_x = x - MARGIN_X
        if rel_x < 0:
            return
        unit_x = self._block_w() + BLOCK_GAP
        col_in_line = int(rel_x // unit_x)
        if col_in_line >= cpl:
            return
        rem_x = rel_x - col_in_line * unit_x
        if rem_x >= self._block_w():
            return    # 落在块与块之间的空隙
        c = int(rem_x // (self._mini + MINI_GAP))
        if c >= 5:
            return    # 落在块内列间距

        beat = line * cpl + col_in_line
        key = KEYS[row * 5 + c]   # 目标键：该小格对应的键字母

        # 显示出来的节拍块位（含未创建的空白块，渲染画满每横排）均可点击添加；
        # 只有完全空白区域（行/列间隙、格子外）在坐标换算时已被忽略，不创建。
        # 鼠标点击期间抑制自动滚动（防点击格子谱时视图乱跳）
        self._suppress_scroll = True
        try:
            if button == Qt.MiddleButton:
                # 中键：只切换光标到该节拍，不更改任何标记（R7）
                self._current_key = key
                self.keySelected.emit(key)
                self.set_cursor(beat)
                event.accept()
                return

            # 左键=切换主旋律标记；右键=切换和弦标记（R7，不再用 Shift 区分）
            self._model.toggle_note(beat, key, button == Qt.RightButton)
            self._current_key = key
            self.keySelected.emit(key)
            self.set_cursor(beat)
            self.modelChanged.emit()
            self.updateGeometry()
            self.update()
            event.accept()
        finally:
            self._suppress_scroll = False

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg_color)

        # 绘制前兜底同步小格边长（独立/未显示 widget 也保证与宽度一致）
        self._sync_mini()

        # 水平居中（宽度富余时）/ 垂直居中或顶部对齐后平移坐标系
        painter.translate(self._offset_x(), self._offset_y())

        cpl = max(1, self._columns_per_line)
        num_cols = self._model.num_columns()
        lines = self._lines()
        n_lines = max(2, len(lines))   # 默认至少绘制两横排（第二行不足时为空网格）

        # 1) 逐行逐块绘制 3×5 小格：空格用背景色填充，
        #    主旋律格填旋律色、和弦格填和弦色
        pen_width = inner_pen_width(self._style)
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
                if not draws_inner_lines(self._style):
                    continue
                painter.setPen(QPen(self._border_color, pen_width))
                if uses_continuous_lines(self._style):
                    # 非默认样式：行间/列间格线画成完整线段（线宽均匀、交点不叠加）
                    bx = MARGIN_X + j * (self._block_w() + BLOCK_GAP)
                    by = MARGIN_Y + line_i * (self._block_h() + LINE_GAP)
                    step = self._mini + MINI_GAP
                    bw = self._block_w()
                    bh = self._block_h()
                    for k in range(1, ROWS):       # 行间水平线
                        painter.drawLine(bx, by + k * step, bx + bw, by + k * step)
                    for k in range(1, 5):          # 列间竖直线
                        painter.drawLine(bx + k * step, by, bx + k * step, by + bh)
                else:
                    # 默认样式：逐格边框（维持原视觉）
                    for r in range(ROWS):
                        for c in range(5):
                            painter.drawRect(self._cell_rect(line_i, r, j, c))

        # 1.5) 完整内外边框 / 粗内线+外框：每个节拍块画外框（线宽与内线一致）
        if draws_outer_frame(self._style):
            painter.setPen(QPen(self._border_color, pen_width))
            for line_i in range(n_lines):
                for j in range(cpl):
                    painter.drawRect(self._block_rect(line_i, j))

        # 2) 光标所在节拍块：整块外框 2px 强调色描边（画在块外围）
        cursor_line = self._cursor_col // cpl
        cursor_j = self._cursor_col % cpl
        if cursor_line < n_lines:
            block_rect = self._block_rect(cursor_line, cursor_j)
            painter.setPen(QPen(COLOR_ACCENT, 2))
            painter.drawRect(block_rect.adjusted(-1, -1, 1, 1))
