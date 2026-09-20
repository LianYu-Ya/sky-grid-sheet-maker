# -*- coding: utf-8 -*-
"""导出 PNG 长图（块状样式，与格子谱显示区一致，version 2）。

将整份乐谱渲染为白色背景的 PNG 长图：
- 只渲染块状乐谱网格（R9：不再绘制顶部 3×5 键位图例）：每块 = 3×5 键位小网格，
  主旋律格填 mark_color（默认红 #E84848）、和弦格填 chord_color（默认蓝 #4A90D9），
  空格白底加深灰边框；不画字母、不画光标，超出按每横排块数换行
- 可选在图片顶部绘制乐谱名（title 非空时）：大号深灰粗体居中，网格整体下移
- 使用固定小格尺寸渲染（MINI=36，R10 加大更清晰），网格关闭抗锯齿使边框锐利无糊边
- 小格边框色与显示区统一加深为 #B8B8B8（R10）
"""

import math

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QImage, QColor, QPainter, QPen

from model import (
    DEFAULT_CHORD_COLOR, DEFAULT_MARK_COLOR, KEYS, ROWS, NoteGrid,
)
from grid_style import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR,
    draws_inner_lines, draws_outer_frame, inner_pen_width,
    uses_continuous_lines,
)

# ---- 视觉配色（与格子谱显示区统一） ----
COLOR_BG = QColor("#FFFFFF")           # 背景纯白
COLOR_CELL_BORDER = QColor("#B8B8B8")  # 小格边框（R10 加深，更清晰）
COLOR_TITLE = QColor("#333333")        # 乐谱名文字：深灰

# ---- 布局参数（固定小格尺寸渲染） ----
MINI = 36                          # 小格边长（固定，R10 加大更清晰）
MINI_GAP = 2                       # 小格间距
BLOCK_W = 5 * MINI + 4 * MINI_GAP  # 3×5 节拍块宽度
BLOCK_H = 3 * MINI + 2 * MINI_GAP  # 3×5 节拍块高度
BLOCK_GAP = 12                     # 块间距
LINE_GAP = 24                      # 横排（行）与行之间的空隙
MARGIN = 24                        # 四周留白
TITLE_H = 56                       # 顶部乐谱名区域高度（无标题时为 0）
TITLE_FONT_PX = 30                 # 乐谱名字号


def _num_lines(num_columns: int, columns_per_line: int) -> int:
    """乐谱网格的横排块数量；空乐谱（0 列）也渲染 1 行空网格。"""
    cols = max(1, columns_per_line)
    return max(1, math.ceil(num_columns / cols))


def _valid_qcolor(color, default: str) -> QColor:
    """构造合法 QColor：空或非法时回退默认色。"""
    qcolor = QColor(color) if color else QColor(default)
    if not qcolor.isValid():
        qcolor = QColor(default)
    return qcolor


def _draw_title(painter: QPainter, title: str, width: int):
    """在图片顶部绘制居中乐谱名（大号深灰粗体）。"""
    font = QFont()
    font.setPixelSize(TITLE_FONT_PX)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(COLOR_TITLE)
    painter.drawText(QRect(0, MARGIN, width, TITLE_H - MARGIN),
                     Qt.AlignCenter, title)


def render_sheet_image(grid: NoteGrid, columns_per_line: int,
                       mark_color: str | None = None,
                       chord_color: str | None = None,
                       title: str | None = None,
                       style: str | None = None,
                       bg_color: str | None = None,
                       border_color: str | None = None) -> QImage:
    """渲染整份乐谱为白色背景 QImage（长图），返回 QImage。

    等价于"每页 = 全部行"的单页渲染；mark_color / chord_color 为 #RRGGBB
    颜色字符串，None 或非法时分别使用默认红 / 默认蓝；title 非空（strip 后）
    时在图片顶部绘制乐谱名，否则不绘制且不增加图片高度。
    """
    cols_per_line = max(1, int(columns_per_line))
    total_lines = _num_lines(grid.num_columns(), cols_per_line)
    return render_page_image(grid, cols_per_line, total_lines, 0,
                             mark_color, chord_color, title,
                             style, bg_color, border_color)


def num_pages(num_columns: int, columns_per_line: int, rows_per_page: int) -> int:
    """分页总页数：每页 rows_per_page 行 × columns_per_line 列块，至少 1 页。"""
    cols = max(1, int(columns_per_line))
    rows = max(1, int(rows_per_page))
    total_lines = _num_lines(num_columns, cols)
    return max(1, math.ceil(total_lines / rows))


def render_page_image(grid: NoteGrid, columns_per_line: int, rows_per_page: int,
                      page_index: int,
                      mark_color: str | None = None,
                      chord_color: str | None = None,
                      title: str | None = None,
                      style: str | None = None,
                      bg_color: str | None = None,
                      border_color: str | None = None) -> QImage:
    """渲染第 page_index 页（每页 rows_per_page 行 × columns_per_line 列块）。

    页码越界时渲染空页（1 行空网格）保证图片高度有效；
    title 非空（strip 后）时绘制在页面顶部，否则不绘制。
    """
    title = (title or "").strip()
    cols_per_line = max(1, int(columns_per_line))
    rows_per_page = max(1, int(rows_per_page))
    num_columns = grid.num_columns()
    total_lines = _num_lines(num_columns, cols_per_line)
    first_line = max(0, int(page_index)) * rows_per_page
    num_lines = min(rows_per_page, max(0, total_lines - first_line))
    lines = max(1, num_lines)   # 空页也渲染 1 行空网格

    mark_qcolor = _valid_qcolor(mark_color, DEFAULT_MARK_COLOR)
    chord_qcolor = _valid_qcolor(chord_color, DEFAULT_CHORD_COLOR)
    bg_qcolor = _valid_qcolor(bg_color, DEFAULT_BG_COLOR)
    border_qcolor = _valid_qcolor(border_color, DEFAULT_BORDER_COLOR)

    title_h = TITLE_H if title else 0
    width = MARGIN * 2 + cols_per_line * BLOCK_W + (cols_per_line - 1) * BLOCK_GAP
    height = MARGIN * 2 + title_h + lines * BLOCK_H + (lines - 1) * LINE_GAP

    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(bg_qcolor)

    painter = QPainter(image)
    if title:
        painter.setRenderHint(QPainter.Antialiasing, True)
        _draw_title(painter, title, width)
        painter.setRenderHint(QPainter.Antialiasing, False)
    _draw_sheet(painter, grid, cols_per_line, first_line, lines,
                mark_qcolor, chord_qcolor, title_h,
                style, bg_qcolor, border_qcolor)
    painter.end()
    return image


def export_pages(path_base: str, grid: NoteGrid, columns_per_line: int,
                 rows_per_page: int,
                 mark_color: str | None = None,
                 chord_color: str | None = None,
                 title: str | None = None,
                 draw_title: bool = True,
                 style: str | None = None,
                 bg_color: str | None = None,
                 border_color: str | None = None) -> tuple[bool, int]:
    """分页导出 PNG：多页文件名 path_base_1.png / path_base_2.png…，单页 path_base.png。

    draw_title=False 时不绘制乐谱名；title 仅作显示名（与文件名分离）。
    返回 (是否全部成功, 实际页数)。
    """
    pages = num_pages(grid.num_columns(), columns_per_line, rows_per_page)
    ok_all = True
    for p in range(pages):
        path = f"{path_base}_{p + 1}.png" if pages > 1 else path_base + ".png"
        try:
            img = render_page_image(grid, columns_per_line, rows_per_page, p,
                                    mark_color, chord_color,
                                    title if draw_title else None,
                                    style, bg_color, border_color)
            ok_all = img.save(path, "PNG") and ok_all
        except Exception:
            ok_all = False
    return ok_all, pages


def _draw_sheet(painter: QPainter, grid: NoteGrid, cols_per_line: int,
                first_line: int, num_lines: int,
                mark_qcolor: QColor, chord_qcolor: QColor,
                title_h: int = 0,
                style: str | None = None,
                bg_qcolor: QColor | None = None,
                border_qcolor: QColor | None = None):
    """绘制乐谱网格中从 first_line 起的 num_lines 行：每行 cols_per_line 个 3×5 块，
    主旋律/和弦格分别填色（不画字母、不画光标）。
    按样式画内线/外框，线宽粗细跟随样式。"""
    if bg_qcolor is None:
        bg_qcolor = COLOR_BG
    if border_qcolor is None:
        border_qcolor = COLOR_CELL_BORDER
    style = style or "default"
    pen_width = inner_pen_width(style)
    block_y0 = MARGIN + title_h
    num_columns = grid.num_columns()
    cell_step = MINI + MINI_GAP

    for i in range(num_lines):
        line = first_line + i
        block_y = block_y0 + i * (BLOCK_H + LINE_GAP)
        for j in range(cols_per_line):
            beat = line * cols_per_line + j
            bx = MARGIN + j * (BLOCK_W + BLOCK_GAP)

            # 小格填充：空 = 底色；和弦格填和弦色；主旋律格填旋律色
            for r in range(ROWS):
                for c in range(5):
                    x = bx + c * cell_step
                    y = block_y + r * cell_step
                    key = KEYS[r * 5 + c]
                    if beat < num_columns:
                        if grid.is_chord(beat, key):
                            painter.fillRect(x, y, MINI, MINI, chord_qcolor)
                        elif grid.has_note(beat, key):
                            painter.fillRect(x, y, MINI, MINI, mark_qcolor)
                        else:
                            painter.fillRect(x, y, MINI, MINI, bg_qcolor)
                    else:
                        painter.fillRect(x, y, MINI, MINI, bg_qcolor)

            if not draws_inner_lines(style):
                continue
            painter.setPen(QPen(border_qcolor, pen_width))
            if uses_continuous_lines(style):
                # 非默认样式：行间/列间格线画成完整线段（线宽均匀、交点不叠加）
                for k in range(1, ROWS):
                    painter.drawLine(bx, block_y + k * cell_step,
                                     bx + BLOCK_W, block_y + k * cell_step)
                for k in range(1, 5):
                    painter.drawLine(bx + k * cell_step, block_y,
                                     bx + k * cell_step, block_y + BLOCK_H)
            else:
                # 默认样式：逐格边框（维持原视觉）
                for r in range(ROWS):
                    for c in range(5):
                        painter.drawRect(bx + c * cell_step, block_y + r * cell_step,
                                         MINI, MINI)

            # 外框：包住整个 3×5 节拍块（线宽与内线一致）
            if draws_outer_frame(style):
                painter.setPen(QPen(border_qcolor, pen_width))
                painter.drawRect(bx, block_y, BLOCK_W, BLOCK_H)


def export_png(path: str, grid: NoteGrid, columns_per_line: int,
               mark_color: str | None = None,
               chord_color: str | None = None,
               title: str | None = None,
               style: str | None = None,
               bg_color: str | None = None,
               border_color: str | None = None) -> bool:
    """调 render_sheet_image 并保存为 PNG；成功返回 True，异常/失败返回 False。"""
    try:
        image = render_sheet_image(grid, columns_per_line,
                                   mark_color, chord_color, title,
                                   style, bg_color, border_color)
        return image.save(path, "PNG")
    except Exception:
        return False
