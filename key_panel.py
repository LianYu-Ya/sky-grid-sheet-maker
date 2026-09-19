# -*- coding: utf-8 -*-
"""3×5 键位面板（完整实现，自适应版）。

绘制 YUIOP / HJKL; / NM,./ 三行五列键位：
- 键内图标按用户标注图分三种：菱形中带圆 ◈（Y K /）、纯菱形 ◇（U O J L M .）、
  纯圆形 ○（其余）；图标放大占满键
- 键面文字显示在图形内部居中，显示模式可切换（set_display_mode）：
  letter=键字母（默认）、key=键位编号 1..7（按 KEY_NUMBERS，第二/三轮
  数字上方加 1/2 个高音点）、tone=音调名 C D E F G A B…（按 KEY_TONES）、
  blank=只显示图形不显示文字
- 当前选中键：浅蓝填充 + 2px 强调色边框
- 光标节拍标记键：旋律色/和弦色淡填充 + 同色细边框 + 右上角同色小圆点
点击键位发 keyPressed(key, is_chord) 信号（左键=主旋律、右键=和弦，均不前进光标）；
高亮状态由外部 set_current_key 同步，本面板不自行修改选中态。

自适应：resizeEvent 时按面板实际宽高重算键宽/键高
（保证 5 列 + 边距 + 间距铺满宽度，高度按比例），
绘制与点击命中检测使用同一套坐标换算，整体水平居中。
图形放满键、文字居中于图形内，键拉大/缩小时均不会被裁剪。
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from model import (
    DEFAULT_CHORD_COLOR, DEFAULT_MARK_COLOR, KEYS, KEY_NUMBERS, KEY_TONES,
    MAIN_KEYS, ROWS, SHAPE_CIRCLE, SHAPE_DIAMOND, SHAPE_DIAMOND_CIRCLE,
)

# ---------- 键面显示模式 ----------
MODE_LETTER = "letter"   # 显示键字母（Y U I …）
MODE_KEY = "key"         # 显示键位编号（1..7，参考用户标注图）
MODE_TONE = "tone"       # 显示音调名（C D E F G A B …）
MODE_BLANK = "blank"     # 只显示图形，不显示文字
DISPLAY_MODES = (MODE_LETTER, MODE_KEY, MODE_TONE, MODE_BLANK)

# ---------- 视觉常量（简约白色，统一用色） ----------
COLOR_BG = QColor("#FFFFFF")             # 面板背景：白
COLOR_MAIN_BG = QColor("#FFFFFF")        # 主音键底：白
COLOR_MAIN_BORDER = QColor("#C8C8C8")    # 主音键边框：细灰
COLOR_MAIN_SHAPE = QColor("#B0B0B0")     # 主音菱形描边
COLOR_SHARP_BG = QColor("#F2F2F2")       # 变化音键底：浅灰
COLOR_SHARP_BORDER = QColor("#D9D9D9")   # 变化音键边框
COLOR_SHARP_SHAPE = QColor("#9E9E9E")    # 变化音圆形描边
COLOR_TEXT = QColor("#333333")           # 键字母：深灰
COLOR_CURRENT_BG = QColor("#E8F1FB")     # 选中键填充：浅蓝
COLOR_CURRENT_BORDER = QColor("#4A90D9")  # 选中键边框：强调色

# ---------- 基准尺寸（sizeHint 依据，随面板缩放） ----------
KEY_W = 68        # 基准键宽
KEY_H = 60        # 基准键高
GAP = 8           # 键间距
MARGIN = 16       # 面板边距
RADIUS = 8        # 键圆角半径
FONT_PX = 18      # 键字母基准字号
KEY_W_MIN = 30    # 键宽下限（防止面板过窄时键不可点）

COLS = len(KEYS) // ROWS                 # 每行 5 个键（由 model 推导，不硬编码）

CONTENT_W = COLS * KEY_W + (COLS - 1) * GAP   # 基准内容区总宽
CONTENT_H = ROWS * KEY_H + (ROWS - 1) * GAP   # 基准内容区总高


class KeyPanel(QWidget):
    """3×5 键位面板：绘制精美键位，点击发 keyPressed(key, is_chord) 信号。"""

    keyPressed = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_key = "J"
        # 键面显示模式（默认显示键字母）
        self._display_mode = MODE_LETTER
        # 光标节拍标记（仅显示用）：被标记的键集合 + 标记颜色
        self._melody_marks: set[str] = set()
        self._chord_marks: set[str] = set()
        self._melody_mark_color = QColor(DEFAULT_MARK_COLOR)
        self._chord_mark_color = QColor(DEFAULT_CHORD_COLOR)
        # 自适应键宽/键高：初始用基准尺寸，resizeEvent 后按实际面板缩放
        self._key_w = KEY_W
        self._key_h = KEY_H
        self.setMinimumWidth(COLS * KEY_W_MIN + (COLS - 1) * GAP + 2 * MARGIN)
        # 鼠标悬停显示手型光标，便于触达
        self.setCursor(Qt.PointingHandCursor)

        # 键字母字体：粗体（字号随缩放）
        self._font = QFont()
        self._font.setPixelSize(FONT_PX)
        self._font.setBold(True)

    # ---------- 公共接口 ----------

    def set_current_key(self, key: str):
        """记录当前选中键并重绘高亮（key 非法时忽略）。"""
        if key in KEYS and key != self._current_key:
            self._current_key = key
            self.update()

    def current_key(self) -> str:
        return self._current_key

    def set_display_mode(self, mode: str):
        """设置键面显示模式（letter/key/tone/blank），非法值忽略。"""
        if mode in DISPLAY_MODES and mode != self._display_mode:
            self._display_mode = mode
            self.update()

    def display_mode(self) -> str:
        return self._display_mode

    def set_beat_marks(self, melody_keys, chord_keys, melody_color, chord_color):
        """记录光标所在节拍被标记的键并重绘（仅影响显示，不改变数据）。

        melody_keys / chord_keys：可迭代的键字母集合；melody_color / chord_color：
        旋律色与和弦色（QColor 或 '#RRGGBB' 字符串，非法时回退默认色）。
        """
        self._melody_marks = set(melody_keys or ())
        self._chord_marks = set(chord_keys or ())
        self._melody_mark_color = self._coerce_color(melody_color, DEFAULT_MARK_COLOR)
        self._chord_mark_color = self._coerce_color(chord_color, DEFAULT_CHORD_COLOR)
        self.update()

    @staticmethod
    def _coerce_color(color, default: str) -> QColor:
        if color is None:
            return QColor(default)
        if isinstance(color, QColor):
            return QColor(color) if color.isValid() else QColor(default)
        qc = QColor(color) if isinstance(color, str) else QColor(default)
        return qc if qc.isValid() else QColor(default)

    def sizeHint(self) -> QSize:
        """返回基准尺寸（内容区 + 边距），供 QSplitter 初始布局。"""
        return QSize(CONTENT_W + 2 * MARGIN, CONTENT_H + 2 * MARGIN)

    # ---------- 自适应 ----------

    def _recompute(self):
        """按面板实际宽高重算键宽/键高。

        宽度充裕时让 5 列 + 边距 + 间距铺满宽度；若按此比例算出的高度
        超出面板高度，则改按高度限制缩放（此时整体水平居中）。
        """
        w, h = self.width(), self.height()
        avail_w = w - 2 * MARGIN
        avail_h = h - 2 * MARGIN
        if avail_w <= 0 or avail_h <= 0:
            self._key_w, self._key_h = KEY_W, KEY_H
            return
        key_w = (avail_w - (COLS - 1) * GAP) / COLS
        key_h = key_w * (KEY_H / KEY_W)
        max_key_h = (avail_h - (ROWS - 1) * GAP) / ROWS
        if key_h > max_key_h:
            # 高度受限：按高度缩放，宽度留白居中
            key_h = max_key_h
            key_w = key_h * (KEY_W / KEY_H)
        self._key_w = key_w
        self._key_h = key_h

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recompute()
        self.update()

    def _content_w(self) -> float:
        return COLS * self._key_w + (COLS - 1) * GAP

    def _content_h(self) -> float:
        return ROWS * self._key_h + (ROWS - 1) * GAP

    # ---------- 鼠标点击 ----------

    def mousePressEvent(self, event):
        """左键=在当前光标节拍增加该键主旋律，右键=增加该键和弦，中键忽略（R8）。

        键位面板自身不前进光标，由主窗口 place_at_cursor 处理；Shift 不再参与区分。
        """
        button = event.button()
        if button not in (Qt.LeftButton, Qt.RightButton):
            return
        key = self._key_at(event.position().x(), event.position().y())
        if key:
            # 左键=主旋律（is_chord=False），右键=和弦（is_chord=True）
            self.keyPressed.emit(key, button == Qt.RightButton)
            event.accept()

    def _key_at(self, x: float, y: float) -> str | None:
        """根据坐标返回命中的键字母（与绘制使用同一套换算），未命中返回 None。"""
        ox = (self.width() - self._content_w()) / 2.0
        oy = (self.height() - self._content_h()) / 2.0
        for row in range(ROWS):
            for col in range(COLS):
                idx = row * COLS + col
                if idx >= len(KEYS):
                    break
                kx = ox + col * (self._key_w + GAP)
                ky = oy + row * (self._key_h + GAP)
                if kx <= x <= kx + self._key_w and ky <= y <= ky + self._key_h:
                    return KEYS[idx]
        return None

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), COLOR_BG)

        # 内容区水平/垂直居中偏移
        ox = (self.width() - self._content_w()) / 2.0
        oy = (self.height() - self._content_h()) / 2.0

        for row in range(ROWS):
            for col in range(COLS):
                idx = row * COLS + col
                if idx >= len(KEYS):
                    break
                key = KEYS[idx]
                x = ox + col * (self._key_w + GAP)
                y = oy + row * (self._key_h + GAP)
                self._draw_key(painter, key, x, y)

    def _draw_key(self, painter: QPainter, key: str, x: float, y: float):
        """绘制单个键：圆角矩形底 + 放满键的图形（菱形/圆形）+ 图形内居中文字。

        文字按显示模式取（字母/编号/音调/空白），文字位于图形内部居中，
        键被拉大/缩小时图形与文字同步缩放，不会出现裁剪。
        """
        rect = QRectF(x, y, self._key_w, self._key_h)
        is_main = key in MAIN_KEYS
        is_current = key == self._current_key
        is_melody_mark = key in self._melody_marks
        is_chord_mark = key in self._chord_marks
        is_marked = is_melody_mark or is_chord_mark
        mark_color = self._melody_mark_color if is_melody_mark else self._chord_mark_color

        # 随缩放的视觉参数
        scale = self._key_w / KEY_W
        radius = max(4, RADIUS * scale)

        # 圆角矩形底与边框（优先级：当前选中键 > 光标节拍标记 > 默认）
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        if is_current:
            # 选中键：仅底色变化（浅蓝填充），边框用默认细灰，不画蓝色选择框
            painter.fillPath(path, COLOR_CURRENT_BG)
            painter.setPen(QPen(COLOR_MAIN_BORDER if is_main else COLOR_SHARP_BORDER, 1))
        elif is_marked:
            painter.fillPath(path, mark_color.lighter(175))   # 标记色淡填充
            painter.setPen(QPen(mark_color, 1.5))             # 标记色细边框
        else:
            painter.fillPath(path, COLOR_MAIN_BG if is_main else COLOR_SHARP_BG)
            painter.setPen(QPen(COLOR_MAIN_BORDER if is_main else COLOR_SHARP_BORDER, 1))
        # 关键：上一键若画了角标圆点会残留 mark_color 画笔，
        # 这里必须先置空画笔，否则 drawPath 会用残留画笔把本键整键填充
        # （这正是"标记落在旁边一格"的根因：被标记键右侧的下一键被纯标记色填充）。
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        cx = x + self._key_w / 2.0       # 键水平中心
        cy = y + self._key_h / 2.0       # 键垂直中心

        # 图标：按用户标注图分三种（菱形中带圆 / 菱形 / 圆形）。
        # 菱形内圆 = 菱形的内切圆（例图比例）；单独圆形 = 与菱形内圆同尺寸
        shape_r = max(8, min(self._key_w, self._key_h) * 0.42)   # 菱形 / 菱形带圆
        inner_r = shape_r * 0.707                                 # 菱形内切圆半径（例图）
        circle_r = inner_r                                        # 单独圆形：与内圆一致
        pen_w = max(2.0, 2.0 * scale)
        if key in SHAPE_DIAMOND_CIRCLE:
            # 菱形中带圆 ◈：菱形 + 内切圆
            painter.setPen(QPen(COLOR_MAIN_SHAPE, pen_w))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(QPolygonF([
                QPointF(cx, cy - shape_r),
                QPointF(cx + shape_r, cy),
                QPointF(cx, cy + shape_r),
                QPointF(cx - shape_r, cy),
            ]))
            painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)
        elif key in SHAPE_DIAMOND:
            # 纯菱形 ◇
            painter.setPen(QPen(COLOR_MAIN_SHAPE, pen_w))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(QPolygonF([
                QPointF(cx, cy - shape_r),
                QPointF(cx + shape_r, cy),
                QPointF(cx, cy + shape_r),
                QPointF(cx - shape_r, cy),
            ]))
        else:
            # 纯圆形 ○（SHAPE_CIRCLE）：最初版正常大小
            painter.setPen(QPen(COLOR_SHARP_SHAPE, pen_w))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(cx, cy), circle_r, circle_r)

        # 键面文字：居中绘制在图形内部（按显示模式取内容），字号偏小不拥挤
        text = self._key_label(key)
        if text:
            font = QFont(self._font)
            font.setPixelSize(max(10, int(min(self._key_w, self._key_h) * 0.26)))
            painter.setFont(font)
            painter.setPen(COLOR_TEXT)
            painter.drawText(QRectF(x, y, self._key_w, self._key_h),
                             Qt.AlignCenter, text)
            # 按键模式：编号 1..7 循环，第二/三轮在数字上方加高音点（1 点/2 点）
            if self._display_mode == MODE_KEY:
                self._draw_octave_dots(painter, key, cx, cy,
                                       max(10, int(min(self._key_w, self._key_h) * 0.26)))

        # 光标节拍标记角标：右上角小圆点（即使叠加"当前选中键"浅蓝填充仍可区分）
        if is_marked:
            dot_r = max(3, 5 * scale)
            dot_cx = x + self._key_w - dot_r - max(3, 4 * scale)
            dot_cy = y + dot_r + max(3, 4 * scale)
            painter.setPen(Qt.NoPen)
            painter.setBrush(mark_color)
            painter.drawEllipse(QPointF(dot_cx, dot_cy), dot_r, dot_r)
            # 恢复空画笔：否则 mark_color 画笔会泄漏到下一键的 drawPath，
            # 把被标记键右侧一格整键填充成纯标记色（用户所见"标记偏一格"的根源）。
            painter.setBrush(Qt.NoBrush)

    def _draw_octave_dots(self, painter: QPainter, key: str,
                          cx: float, cy: float, font_px: int):
        """在键面数字上方绘制高音点：第二轮 1 点、第三轮 2 点（垂直堆叠）。"""
        octave = self._key_octave(key)
        if octave <= 0:
            return
        dot_r = max(2.0, font_px * 0.08)      # 高音点：小号圆点
        gap = max(1.5, dot_r * 0.5)
        y0 = cy - font_px * 0.55 - dot_r          # 数字顶上方第一个点中心
        painter.setPen(Qt.NoPen)
        painter.setBrush(COLOR_TEXT)
        for i in range(octave):
            painter.drawEllipse(QPointF(cx, y0 - i * (dot_r * 2 + gap)),
                                dot_r, dot_r)
        painter.setBrush(Qt.NoBrush)

    def _key_octave(self, key: str) -> int:
        """按键（数字）模式的八度轮次：按 1..7 循环，0=中音 1=高音 2=更高音。"""
        return KEYS.index(key) // 7

    def _key_label(self, key: str) -> str:
        """按当前显示模式返回键面文字（blank 模式返回空串）。"""
        if self._display_mode == MODE_BLANK:
            return ""
        if self._display_mode == MODE_KEY:
            return str(KEY_NUMBERS[KEYS.index(key)])
        if self._display_mode == MODE_TONE:
            return KEY_TONES[key]
        return key

    def _shape_type(self, key: str) -> str:
        """返回键位图标类型：dc=菱形中带圆、diamond=菱形、circle=圆形。"""
        if key in SHAPE_DIAMOND_CIRCLE:
            return "dc"
        if key in SHAPE_DIAMOND:
            return "diamond"
        return "circle"
