# -*- coding: utf-8 -*-
"""浏览历史乐谱弹窗、标题输入对话框与导出预览对话框。"""

import os
import subprocess

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)

from export import num_pages, render_page_image
from grid_style import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_STYLE,
    STYLE_OPTIONS, GridStyle, is_valid_style,
)
from file_io import copy_sheet, delete_sheet, list_sheets, rename_sheet


def prompt_title(parent, initial: str = "") -> str:
    """弹出标题输入框，返回输入文本；用户取消返回 ""。"""
    text, ok = QInputDialog.getText(parent, "输入标题", "乐谱标题：", text=initial)
    if ok:
        return text.strip()
    return ""


def _contrast_text_color(hex_color: str) -> str:
    """按背景色亮度返回可读文字色：浅底深字、深底白字。"""
    c = QColor(hex_color)
    lum = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0
    return "#333333" if lum > 0.55 else "#FFFFFF"


def _color_button_style(hex_color: str) -> str:
    """颜色按钮样式：颜色作底色、文字取自动对比色、加细边框保证浅色可见。"""
    return (f"background-color: {hex_color}; color: {_contrast_text_color(hex_color)};"
            f" border: 1px solid #B0B0B0; border-radius: 4px; font-weight: bold;")


class StickyComboBox(QComboBox):
    """粘滞下拉框：点击展开后保持展开。

    选择选项 / 鼠标移开 / 点击其他位置都不会收起（便于反复对比效果）；
    再次点击下拉框本身才会收起。API 与 QComboBox 完全兼容。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stick = False

    def showPopup(self):
        """首次点击展开：置粘滞标志，保持展开。"""
        self._stick = True
        super().showPopup()

    def hidePopup(self):
        """拦截自动收起：粘滞期间（选择项/外部点击）保持展开。"""
        if self._stick and self.view().isVisible():
            return
        self._stick = False
        super().hidePopup()

    def mousePressEvent(self, event):
        """再次点击已展开的下拉框 → 真正收起；否则走正常展开逻辑。"""
        if self._stick and self.view().isVisible():
            self._stick = False
            self.hidePopup()
            return
        super().mousePressEvent(event)


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
        """用当前颜色作按钮底色，文字取自动对比色（浅底深字、深底白字）。"""
        for attr, btn in self._buttons.items():
            btn.setStyleSheet(_color_button_style(getattr(self._style, attr)))

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


class BrowseSheetsDialog(QDialog):
    """列出数据目录下的历史乐谱（.ggp）。

    每行显示乐谱名，行内提供"复制 / 重命名 / 删除"三个操作按钮；
    底部"打开文件所在位置"可在资源管理器中定位选中乐谱；
    双击或点"打开"返回选中路径。
    """

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("浏览乐谱")
        self.resize(560, 460)
        self._path: str | None = None
        self._data_dir = data_dir

        layout = QVBoxLayout(self)

        hint = QLabel("双击或选中后点“打开”载入乐谱；行内按钮可复制 / 重命名 / 删除；“打开文件所在位置”可在资源管理器中定位文件")
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_open)
        # 选中项：仅底色变化（去掉蓝色选择框）
        self._list.setStyleSheet(
            "QListWidget::item { border: none; }"
            "QListWidget::item:selected { background: #E8F1FB; color: #333333; }"
            "QListWidget::item:selected:active { background: #E8F1FB; }"
            "QListWidget::item:hover { background: #F5FAFF; }")
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        locate_btn = QPushButton("打开文件所在位置")
        locate_btn.setToolTip("在资源管理器中定位当前选中的乐谱文件")
        locate_btn.clicked.connect(self._open_location)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        open_btn = QPushButton("打开")
        open_btn.setDefault(True)
        open_btn.clicked.connect(self._on_open)
        btn_row.addWidget(locate_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

        self._reload(data_dir)

    # ---------- 内部 ----------

    def _reload(self, data_dir):
        """加载乐谱列表：每项 = 乐谱名 + 复制/重命名/删除 按钮。"""
        self._list.clear()
        sheets = list_sheets(data_dir)
        if not sheets:
            empty_item = QListWidgetItem("（暂无乐谱，请先保存）")
            empty_item.setFlags(empty_item.flags() & ~Qt.ItemIsEnabled)
            self._list.addItem(empty_item)
            return
        for sheet in sheets:
            item = QListWidgetItem()
            item.setData(0, sheet["path"])
            item.setSizeHint(QSize(0, 44))   # 行高，保证行内按钮文字完整显示

            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(8, 4, 8, 4)
            name = QLabel(f"{sheet['title']}  ({sheet['mtime_text']})")
            name.setToolTip(sheet["path"])
            lay.addWidget(name, 1)

            copy_btn = QPushButton("复制")
            copy_btn.setFixedWidth(64)
            copy_btn.clicked.connect(
                lambda _=False, p=sheet["path"]: self._copy_sheet(p))
            rename_btn = QPushButton("重命名")
            rename_btn.setFixedWidth(72)
            rename_btn.clicked.connect(
                lambda _=False, p=sheet["path"], t=sheet["title"]: self._rename_sheet(p, t))
            del_btn = QPushButton("删除")
            del_btn.setFixedWidth(64)
            del_btn.clicked.connect(
                lambda _=False, p=sheet["path"], t=sheet["title"]: self._delete_sheet(p, t))
            lay.addWidget(copy_btn)
            lay.addWidget(rename_btn)
            lay.addWidget(del_btn)

            self._list.addItem(item)
            self._list.setItemWidget(item, row)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _copy_sheet(self, path):
        """复制乐谱并刷新列表。"""
        copy_sheet(path)
        self._reload(self._data_dir)

    def _rename_sheet(self, path, old_title: str):
        """弹窗输入新标题 → 重命名乐谱并刷新列表。"""
        title = prompt_title(self, initial=old_title)
        if not title:
            return
        rename_sheet(path, title)
        self._reload(self._data_dir)

    def _delete_sheet(self, path, title: str):
        """确认后删除乐谱并刷新列表。"""
        ret = QMessageBox.question(
            self, "删除乐谱", f"确定删除乐谱「{title}」吗？\n删除后无法恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        delete_sheet(path)
        self._reload(self._data_dir)

    def _open_location(self):
        """在资源管理器中打开当前选中乐谱所在的文件夹并定位该文件。"""
        item = self._list.currentItem()
        if item is None:
            return
        path = item.data(0)
        if not path:
            return
        if os.name == "nt":
            # /select, 后跟路径，定位并选中文件
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])

    def _on_open(self):
        """打开当前选中项：记录路径并 accept。"""
        item = self._list.currentItem()
        if item is None:
            return
        path = item.data(0)
        if not path:
            return
        self._path = path
        self.accept()

    # ---------- 对外 ----------

    def selected_path(self) -> str | None:
        """返回选中的乐谱路径；取消则返回 None。"""
        return self._path


class ExportDialog(QDialog):
    """导出预览对话框：预览分页效果，调整每页行列后分页导出 PNG。

    - 预览区实时渲染当前页，可调每页行数 / 列数并翻页查看每一页；
    - 文件名（不含扩展名，分页自动追加 _1/_2…）与显示名（绘制在图片顶部）
      相互独立，两者留空均默认使用乐谱名；
    - "每页绘制显示名"控制是否把显示名画在每页顶部；
    - 输出目录默认 outputs（可手动更改），分层模式每谱一个子文件夹（默认），
      平铺模式直接放入输出目录；可在导出界面修改旋律/和弦颜色。
    """

    def __init__(self, grid, columns_per_line: int, default_title: str = "",
                 mark_color: str | None = None, chord_color: str | None = None,
                 style: str | None = None,
                 bg_color: str | None = None,
                 border_color: str | None = None,
                 default_dir: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出预览")
        self.resize(780, 700)
        self._grid = grid
        self._mark_color = mark_color or "#E84848"
        self._chord_color = chord_color or "#4A90D9"
        self._style = style if is_valid_style(style) else DEFAULT_STYLE
        self._bg_color = bg_color or DEFAULT_BG_COLOR
        self._border_color = border_color or DEFAULT_BORDER_COLOR
        self._default_dir = default_dir or os.getcwd()
        self._default_title = (default_title or "").strip()

        layout = QVBoxLayout(self)

        # 文件名（与显示名分离，留空默认用乐谱名）
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("文件名"))
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText(self._default_title or "留空默认用乐谱名")
        self.file_edit.setToolTip("保存的文件名（不含扩展名），分页自动追加 _1/_2…；留空默认用乐谱名")
        file_row.addWidget(self.file_edit, 1)
        layout.addLayout(file_row)

        # 显示名 + 是否绘制开关
        disp_row = QHBoxLayout()
        disp_row.addWidget(QLabel("显示名"))
        self.display_edit = QLineEdit()
        self.display_edit.setPlaceholderText(self._default_title or "留空默认用乐谱名")
        self.display_edit.setToolTip("绘制在图片顶部的乐谱名，与文件名相互独立；留空默认用乐谱名")
        disp_row.addWidget(self.display_edit, 1)
        self.draw_title_check = QCheckBox("每页绘制显示名")
        self.draw_title_check.setChecked(True)
        disp_row.addWidget(self.draw_title_check)
        layout.addLayout(disp_row)

        # 输出目录（默认 outputs，可手动更改）
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("输出目录"))
        self.dir_edit = QLineEdit(self._default_dir)
        self.dir_edit.setToolTip("PNG 导出目录；默认应用目录下的 outputs")
        dir_row.addWidget(self.dir_edit, 1)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        # 导出模式：分层（默认）/ 平铺
        mode_row = QHBoxLayout()
        self.layered_radio = QRadioButton("分层（每谱一个文件夹）")
        self.layered_radio.setChecked(True)
        self.layered_radio.setToolTip("每个乐谱导出到 输出目录/乐谱名/ 子文件夹下")
        self.flat_radio = QRadioButton("平铺（直接放入输出目录）")
        self.flat_radio.setToolTip("所有乐谱直接导出到输出目录，不建子文件夹")
        mode_row.addWidget(self.layered_radio)
        mode_row.addWidget(self.flat_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        # 旋律 / 和弦颜色修改
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("标记颜色"))
        self.mark_btn = QPushButton("旋律颜色")
        self.mark_btn.setToolTip("修改主旋律标记颜色，实时刷新预览")
        self.mark_btn.clicked.connect(self._choose_mark_color)
        color_row.addWidget(self.mark_btn)
        self.chord_btn = QPushButton("和弦颜色")
        self.chord_btn.setToolTip("修改和弦标记颜色，实时刷新预览")
        self.chord_btn.clicked.connect(self._choose_chord_color)
        color_row.addWidget(self.chord_btn)
        self.bg_btn = QPushButton("背景色")
        self.bg_btn.setToolTip("修改谱面底色，实时刷新预览（仅本次导出）")
        self.bg_btn.clicked.connect(self._choose_bg_color)
        color_row.addWidget(self.bg_btn)
        self.border_btn = QPushButton("边框色")
        self.border_btn.setToolTip("修改格线/外框颜色，实时刷新预览（仅本次导出）")
        self.border_btn.clicked.connect(self._choose_border_color)
        color_row.addWidget(self.border_btn)
        color_row.addStretch(1)
        layout.addLayout(color_row)
        self._sync_color_buttons()

        # 格子样式（仅本次导出生效）
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("格子样式"))
        self.style_combo = StickyComboBox()
        self.style_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)   # 始终完全展开显示当前样式
        for value, label in STYLE_OPTIONS:
            self.style_combo.addItem(label, value)
        self.style_combo.setCurrentIndex(
            max(0, self.style_combo.findData(self._style)))
        self.style_combo.currentIndexChanged.connect(self._refresh)
        style_row.addWidget(self.style_combo)
        style_row.addWidget(QLabel("（仅本次导出生效）"))
        style_row.addStretch(1)
        layout.addLayout(style_row)

        # 每页行列数
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("每页行数"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 20)
        self.rows_spin.setValue(3)
        page_row.addWidget(self.rows_spin)
        page_row.addSpacing(16)
        page_row.addWidget(QLabel("每页列数"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(4, 30)
        self.cols_spin.setValue(max(4, min(30, int(columns_per_line))))
        page_row.addWidget(self.cols_spin)
        page_row.addStretch(1)
        page_row.addWidget(QLabel("第"))
        self.page_spin = QSpinBox()      # 当前预览页（1..总页数）
        self.page_spin.setRange(1, 1)
        self.page_spin.setValue(1)
        self.page_spin.setToolTip("预览当前页，可切换查看每一页")
        page_row.addWidget(self.page_spin)
        page_row.addWidget(QLabel("页"))
        self.pages_label = QLabel(" / 共 1 页")
        page_row.addWidget(self.pages_label)
        layout.addLayout(page_row)

        # 预览区：按视口等比缩放显示（窗口/行列变化时自适应），大图不裁剪可看全貌
        self._full_pixmap: QPixmap | None = None
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(200, 160)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setWidget(self.preview_label)
        self.preview_scroll.viewport().installEventFilter(self)
        layout.addWidget(self.preview_scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        export_btn = QPushButton("导出")
        export_btn.setDefault(True)
        export_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

        self.rows_spin.valueChanged.connect(self._refresh)
        self.cols_spin.valueChanged.connect(self._refresh)
        self.page_spin.valueChanged.connect(self._refresh)
        self.display_edit.textChanged.connect(self._refresh)
        self.draw_title_check.toggled.connect(self._refresh)
        self._refresh()

    # ---------- 预览刷新 ----------

    def _refresh(self):
        """按当前行列 / 显示名刷新预览原图与页数提示（页码自动夹取到有效范围）。"""
        rows = self.rows_spin.value()
        cols = self.cols_spin.value()
        pages = num_pages(self._grid.num_columns(), cols, rows)
        # 行列变化后总页数可能变小，页码自动夹取到有效范围（防信号回流）
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, max(1, pages))
        self.page_spin.setValue(max(1, min(self.page_spin.value(), pages)))
        self.page_spin.blockSignals(False)
        self.pages_label.setText(f" / 共 {pages} 页")
        title = self.display_name() if self.draw_title_check.isChecked() else None
        img = render_page_image(self._grid, cols, rows,
                                self.page_spin.value() - 1,
                                self._mark_color, self._chord_color, title,
                                style=self.style(), bg_color=self._bg_color,
                                border_color=self._border_color)
        self._full_pixmap = QPixmap.fromImage(img)
        self._apply_preview_scale()

    def _apply_preview_scale(self):
        """把预览原图等比缩放到视口大小（保持宽高比、平滑缩放），随窗口自适应。"""
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return
        vp = self.preview_scroll.viewport()
        avail = QSize(max(10, vp.width()), max(10, vp.height()))
        scaled = self._full_pixmap.scaled(
            avail, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)

    def eventFilter(self, obj, event):
        """预览视口尺寸变化（窗口缩放/分割）→ 重新等比缩放预览。"""
        if obj is self.preview_scroll.viewport() and event.type() == QEvent.Resize:
            self._apply_preview_scale()
        return super().eventFilter(obj, event)

    # ---------- 输出目录 / 颜色 ----------

    def _browse_dir(self):
        """弹出目录选择框，选中后填入输出目录输入框。"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择输出目录", self.dir_edit.text() or self._default_dir)
        if dir_path:
            self.dir_edit.setText(dir_path)

    def _choose_mark_color(self):
        """选择旋律颜色并刷新预览。"""
        color = QColorDialog.getColor(QColor(self._mark_color), self, "选择旋律颜色")
        if color.isValid():
            self._mark_color = color.name()
            self._sync_color_buttons()
            self._refresh()

    def _choose_chord_color(self):
        """选择和弦颜色并刷新预览。"""
        color = QColorDialog.getColor(QColor(self._chord_color), self, "选择和弦颜色")
        if color.isValid():
            self._chord_color = color.name()
            self._sync_color_buttons()
            self._refresh()

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

    def _sync_color_buttons(self):
        """用当前颜色作按钮底色，文字取自动对比色（浅底深字、深底白字）。"""
        for btn, color in ((self.mark_btn, self._mark_color),
                           (self.chord_btn, self._chord_color),
                           (self.bg_btn, self._bg_color),
                           (self.border_btn, self._border_color)):
            btn.setStyleSheet(_color_button_style(color))

    # ---------- 对外取值 ----------

    def file_name(self) -> str:
        """导出文件名（不含扩展名）；留空用乐谱名。"""
        return self.file_edit.text().strip() or self._default_title

    def display_name(self) -> str:
        """绘制在图片顶部的显示名；留空用乐谱名。"""
        return self.display_edit.text().strip() or self._default_title

    def draw_title(self) -> bool:
        return self.draw_title_check.isChecked()

    def rows_per_page(self) -> int:
        return self.rows_spin.value()

    def columns_per_line(self) -> int:
        return self.cols_spin.value()

    def mark_color(self) -> str:
        """当前旋律标记颜色（#RRGGBB，导出用）。"""
        return self._mark_color

    def chord_color(self) -> str:
        """当前和弦标记颜色（#RRGGBB，导出用）。"""
        return self._chord_color

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

    def layered(self) -> bool:
        """True=分层（每谱一个子文件夹），False=平铺。"""
        return self.layered_radio.isChecked()

    def output_path_base(self) -> str:
        """创建输出目录并返回导出基础路径（不含扩展名）。

        分层：<输出目录>/<文件名>/<文件名>；平铺：<输出目录>/<文件名>。
        """
        name = self.file_name() or "乐谱"
        out_dir = self.dir_edit.text().strip() or self._default_dir
        if self.layered_radio.isChecked():
            sub = os.path.join(out_dir, name)
            os.makedirs(sub, exist_ok=True)
            return os.path.join(sub, name)
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, name)
