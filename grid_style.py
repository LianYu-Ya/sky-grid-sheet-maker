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
