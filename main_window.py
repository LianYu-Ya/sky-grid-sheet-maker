# -*- coding: utf-8 -*-
"""主窗口：四区布局（工具栏 / 格子谱显示区 / 键位面板 / 状态栏）。"""

import os

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDockWidget,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from model import DEFAULT_CHORD_COLOR, DEFAULT_MARK_COLOR, NoteGrid
from grid_style import (DEFAULT_BORDER_COLOR, DEFAULT_BG_COLOR, DEFAULT_STYLE,
                        STYLE_OPTIONS, GridStyle, is_valid_style)
from file_io import default_data_dir, default_output_dir, load_ggp, save_ggp
from dialogs import BrowseSheetsDialog, ExportDialog, StyleColorsDialog, prompt_title
from sheet_widget import LINE_GAP, MARGIN_Y, SheetWidget
from key_panel import (
    KeyPanel, MODE_BLANK, MODE_KEY, MODE_LETTER, MODE_TONE,
)
from export import export_pages


class MainWindow(QMainWindow):
    """光遇格子谱制作器主窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("光遇格子谱制作器")
        self.resize(1000, 720)

        self._model = NoteGrid()
        self._dirty = False
        self._current_path: str | None = None
        self._mark_color: str | None = None    # None=使用默认旋律色
        self._chord_color: str | None = None   # None=使用默认和弦色
        self._style: str = DEFAULT_STYLE                 # 格子样式
        self._bg_color: str | None = None                # None=默认背景色
        self._border_color: str | None = None            # None=默认边框色

        # ---------- 顶部工具栏 ----------
        self.toolbar = QToolBar("工具栏", self)
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("输入乐谱标题")
        self.title_edit.setMaximumWidth(220)
        self.toolbar.addWidget(self.title_edit)

        self.toolbar.addWidget(QLabel("每横排"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(4, 16)
        self.cols_spin.setValue(4)
        self.cols_spin.setToolTip("每横排节拍块数（4–16）")
        self.toolbar.addWidget(self.cols_spin)

        mark_color_btn = QPushButton("旋律颜色")
        mark_color_btn.clicked.connect(self.choose_mark_color)
        self.toolbar.addWidget(mark_color_btn)

        chord_color_btn = QPushButton("和弦颜色")
        chord_color_btn.clicked.connect(self.choose_chord_color)
        self.toolbar.addWidget(chord_color_btn)

        self.toolbar.addWidget(QLabel("格子样式"))
        self.style_combo = QComboBox()
        self.style_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)   # 始终完全展开显示当前样式
        for value, label in STYLE_OPTIONS:
            self.style_combo.addItem(label, value)
        self.style_combo.setToolTip("格子谱样式：边框形态（默认/完整内外边框/无外边框/无边框纯色块/粗内线/粗内线+外框）")
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.toolbar.addWidget(self.style_combo)

        style_colors_btn = QPushButton("样式颜色")
        style_colors_btn.setToolTip("自定义旋律/和弦/背景/边框颜色（随乐谱保存）")
        style_colors_btn.clicked.connect(self.open_style_colors)
        self.toolbar.addWidget(style_colors_btn)

        self.toolbar.addSeparator()

        # R13 自动跳转：开启后键盘/键位面板按节奏自动换拍（阈值内归同拍）
        self.auto_advance_check = QCheckBox("自动跳转")
        self.auto_advance_check.setToolTip(
            "开启后：键盘输入与键位面板点击按节奏自动换拍——\n"
            "从本拍第一个键按下开始计时，间隔内的按键归本拍；\n"
            "超过间隔后的下一次按键自动跳到下一节拍")
        self.toolbar.addWidget(self.auto_advance_check)

        self.advance_spin = QSpinBox()
        self.advance_spin.setRange(100, 5000)
        self.advance_spin.setSingleStep(50)
        self.advance_spin.setValue(800)
        self.advance_spin.setSuffix(" ms")
        self.advance_spin.setToolTip("同拍合并时间窗：从本拍第一个键开始计时，超过后下一键换拍")
        self.advance_spin.setEnabled(False)   # 开关未开启时阈值置灰
        self.toolbar.addWidget(self.advance_spin)

        new_btn = QPushButton("新建")
        new_btn.clicked.connect(self.new_sheet)
        self.toolbar.addWidget(new_btn)

        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_sheet)
        self.toolbar.addWidget(save_btn)

        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_sheets)
        self.toolbar.addWidget(browse_btn)

        export_btn = QPushButton("导出 PNG")
        export_btn.clicked.connect(self.export_png)
        self.toolbar.addWidget(export_btn)

        out_folder_btn = QPushButton("输出文件夹")
        out_folder_btn.setToolTip("打开默认导出目录（应用目录下的 outputs）")
        out_folder_btn.clicked.connect(self.open_output_folder)
        self.toolbar.addWidget(out_folder_btn)

        # 按键区菜单按钮：打开设置侧边栏（键面显示模式 / 显隐）
        self.key_panel_btn = QPushButton("按键区")
        self.key_panel_btn.setToolTip("打开按键区设置（键面显示：字母/按键/音调/空白、显隐）")
        self.key_panel_btn.clicked.connect(self._toggle_key_dock)
        self.toolbar.addWidget(self.key_panel_btn)

        # ---------- 中央：QSplitter（上部格子谱滚动区 / 下部键位面板） ----------
        self.sheet = SheetWidget(self._model, self.cols_spin.value())
        self.sheet.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sheet.setMinimumWidth(300)

        self.scroll = QScrollArea()
        # 不用 widgetResizable(True)：它会把 Expanding 策略的 SheetWidget 高度
        # 钳制在可视区高度，内容多行时下方被截断且滚动条不出现。
        # 改为关闭自动缩放，由 _sync_scroll_size() 手动把 widget 设成
        # max(sizeHint, 可视区) —— 内容高时出现滚动条、矮时铺满可视区垂直居中。
        self.scroll.setWidgetResizable(False)
        self.scroll.setWidget(self.sheet)
        # R14：滚动条美化——细窄圆角滑块、无上下箭头、滑道透明，悬停加深
        self.scroll.setStyleSheet(
            "QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }"
            "QScrollBar::handle:vertical { background: #C9C9C9; border-radius: 5px;"
            " min-height: 30px; margin: 2px; }"
            "QScrollBar::handle:vertical:hover { background: #A6A6A6; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
            "QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }"
            "QScrollBar::handle:horizontal { background: #C9C9C9; border-radius: 5px;"
            " min-width: 30px; margin: 2px; }"
            "QScrollBar::handle:horizontal:hover { background: #A6A6A6; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }")
        # 滚动区与可视区都装事件过滤器：窗口缩放/分割条拖动/滚动条出现消失
        # 都会改变可视区宽度，任意一处变化都要重新同步格子谱宽度
        self.scroll.installEventFilter(self)
        self.scroll.viewport().installEventFilter(self)

        self.key_panel = KeyPanel(self)
        self.key_panel.setMinimumHeight(160)    # 键位面板最小高度（避免太小点不到键）
        self.key_panel.setMaximumHeight(520)    # 键位面板最大高度（避免拉得过大浪费空间）

        self.scroll.setMinimumHeight(160)       # 格子谱区最小高度

        self.splitter = QSplitter(Qt.Vertical, self)
        self.splitter.setChildrenCollapsible(False)   # 禁止把任一区拖到 0 隐藏
        self.splitter.addWidget(self.scroll)
        self.splitter.addWidget(self.key_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setSizes([520, 240])
        self.setCentralWidget(self.splitter)

        # ---------- 按键区设置侧边栏（菜单打开）：显隐 + 键面显示模式 ----------
        self.key_dock = QDockWidget("按键区设置", self)
        self.key_dock.setObjectName("key_settings_dock")
        dock_widget = QWidget()
        dock_layout = QVBoxLayout(dock_widget)
        dock_layout.setContentsMargins(8, 8, 8, 8)

        self.show_panel_check = QCheckBox("显示按键区")
        self.show_panel_check.setChecked(True)
        self.show_panel_check.toggled.connect(self._toggle_key_panel)
        dock_layout.addWidget(self.show_panel_check)
        dock_layout.addSpacing(10)

        dock_layout.addWidget(QLabel("键面显示"))
        self.mode_group = QButtonGroup(self)
        for mode, label in ((MODE_LETTER, "字母"), (MODE_KEY, "按键"),
                            (MODE_TONE, "音调"), (MODE_BLANK, "空白")):
            rb = QRadioButton(label)
            self.mode_group.addButton(rb)
            rb.setProperty("mode", mode)
            rb.toggled.connect(self._on_mode_radio)
            if mode == MODE_LETTER:
                rb.setChecked(True)
            dock_layout.addWidget(rb)
        dock_layout.addStretch(1)
        self.key_dock.setWidget(dock_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.key_dock)
        self.key_dock.setFloating(True)   # 悬浮样式：不挤占主窗口布局
        self.key_dock.hide()

        # ---------- 状态栏 ----------
        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label)
        hint = QLabel("左键主旋律切换 · 右键和弦切换 · 中键切光标 · 键盘输入 YUIOPHJKL;NM,./ · Backspace 删除高亮节拍")
        hint.setStyleSheet("color: #888888;")
        self.statusBar().addPermanentWidget(hint)

        # ---------- 接线 ----------
        # 键位面板点击 → 在当前光标节拍放置、不前进光标（左键=主旋律、右键=和弦）
        self.key_panel.keyPressed.connect(self.sheet.place_at_cursor)
        self.sheet.keySelected.connect(self.key_panel.set_current_key)
        self.sheet.modelChanged.connect(self._on_model_changed)
        self.sheet.cursorMoved.connect(self._on_cursor_moved)   # 光标移动 → 仅刷新状态栏，不清脏
        # 追加连接（不覆盖上面 modelChanged 的已有连接）：光标节拍标记同步到键位面板
        self.sheet.cursorMoved.connect(self._refresh_beat_marks)
        self.sheet.modelChanged.connect(self._refresh_beat_marks)
        self.sheet.keySelected.connect(self._refresh_beat_marks)
        # R5：内容变化 / 光标移动 → 自动滚动到光标所在节拍块可见
        self.sheet.modelChanged.connect(self._scroll_to_cursor)
        self.sheet.cursorMoved.connect(self._scroll_to_cursor)
        self.cols_spin.valueChanged.connect(self._on_columns_changed)
        self.title_edit.textChanged.connect(self._mark_dirty)
        # R13 自动跳转：开关→SheetWidget、阈值→SheetWidget、开关联动阈值置灰
        self.auto_advance_check.toggled.connect(self.sheet.set_auto_advance)
        self.advance_spin.valueChanged.connect(self.sheet.set_advance_threshold)
        self.auto_advance_check.toggled.connect(self.advance_spin.setEnabled)

        self._refresh_beat_marks()
        self._refresh_status()

    # ---------- 状态与脏标记 ----------

    def _refresh_status(self):
        """刷新状态栏：列数 | 光标 | 每横排。"""
        self.status_label.setText(
            f"列数 {self._model.num_columns()} | 光标 {self.sheet.cursor()} | "
            f"每横排 {self.sheet.columns_per_line()}")

    def _refresh_beat_marks(self, *_):
        """把光标所在节拍被标记的键同步到键位面板（仅显示，不影响数据）。"""
        beat = self.sheet.cursor()
        self.key_panel.set_beat_marks(
            self.sheet.model().melody_keys(beat),
            self.sheet.model().chord_keys(beat),
            self.sheet.mark_color(),
            self.sheet.chord_color(),
        )

    def _sync_scroll_size(self):
        """手动同步格子谱 widget 尺寸 = max(sizeHint, 滚动区可视区)。

        内容（多行节拍块）高于可视区 → widget 高=sizeHint 高，出现垂直滚动条
        且可滚到底（内部 _offset_y 为 0，顶部对齐）；
        内容矮于可视区 → widget 高=可视区高，内部 _offset_y 垂直居中。
        """
        if self.scroll.widget() is not self.sheet:
            return
        vp = self.scroll.viewport()
        hint = self.sheet.sizeHint()
        w = max(hint.width(), vp.width())
        h = max(hint.height(), vp.height())
        if (self.sheet.width(), self.sheet.height()) != (w, h):
            self.sheet.resize(w, h)
            # 本次尺寸变化可能连锁引发滚动条出现/消失 → 可视区宽度再变，
            # 下一轮事件循环再同步一次，直到完全收敛（初始布局尤其需要）。
            QTimer.singleShot(0, self._sync_scroll_size)

    def showEvent(self, event):
        """窗口显示后再同步一次格子谱宽度（此时滚动区可视区才最终定型）。

        初始布局时滚动区的 Resize 发生在 viewport 宽度确定之前，
        导致 sheet 宽度停在中间值（如 700）而非可视区宽（如 984），
        首次交互触发 _sync_scroll_size 时宽度跳变 → 整格重排、点击位置错位。
        用 singleShot(0) 在本轮事件循环结束后同步一次即可根治。
        """
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_scroll_size)

    def eventFilter(self, obj, event):
        """滚动区 / 可视区尺寸变化（窗口缩放 / 分割条拖动 / 滚动条出现）时同步格子谱尺寸。"""
        if event.type() == QEvent.Resize and \
                (obj is self.scroll or obj is self.scroll.viewport()):
            self._sync_scroll_size()
        return super().eventFilter(obj, event)

    def _mark_dirty(self, *_):
        """置脏并更新窗口标题星号。"""
        if not self._dirty:
            self._dirty = True
            self._update_title()
        self._refresh_status()

    def _update_title(self):
        base = "光遇格子谱制作器"
        if self._dirty:
            base += " *"
        self.setWindowTitle(base)

    def _set_sheet_model(self, model):
        """替换格子谱显示区内部的 model（兼容后续实现的 set_model 方法）。"""
        setter = getattr(self.sheet, "set_model", None)
        if callable(setter):
            setter(model)
        else:
            self.sheet._model = model
        self.sheet.update()

    def _on_model_changed(self):
        self._sync_scroll_size()
        self._refresh_status()
        self._mark_dirty()

    def _on_cursor_moved(self, *_):
        """光标移动：仅刷新状态栏光标显示与滚动区尺寸，不置脏。"""
        self._sync_scroll_size()
        self._refresh_status()

    # ---------- 自动滚动（R5） ----------

    def _scroll_to_cursor(self, *_):
        """自动滚动：确保光标所在节拍块完整露出（块顶对齐视口顶部留边距）。

        ensureVisible 依赖滚动条范围，而追加节拍时 widget 尺寸刚变、范围要等
        下一轮事件循环才刷新，直接滚动会差一点导致块底被裁。因此：
        1) 先手动同步尺寸；2) 用 setValue 直接定位块顶（超出时被 clamp 到
        底部，恰好让末尾块完整露出）；3) 下一轮事件循环再定位一次收敛。
        """
        if self.scroll.widget() is not self.sheet:
            return
        if getattr(self.sheet, "_suppress_scroll", False):
            return    # 鼠标点击格子谱期间不自动滚动（防视图乱跳）
        self._sync_scroll_size()
        cpl = max(1, self.sheet.columns_per_line())
        block_h = self.sheet._block_h()
        line = self.sheet.cursor() // cpl
        y0 = MARGIN_Y + line * (block_h + LINE_GAP)
        bar = self.scroll.verticalScrollBar()
        bar.setValue(y0 - MARGIN_Y)
        QTimer.singleShot(0, lambda: bar.setValue(y0 - MARGIN_Y))

    def _scroll_to_bottom(self):
        """打开 / 新建乐谱后滚动到底部（内容最下方）。

        尺寸同步在下一轮事件循环还会二次收敛（滚动条出现/消失会再次改变
        可视区高度），因此同步后先滚一次，下一轮再滚一次确保真正到底。
        """
        if self.scroll.widget() is not self.sheet:
            return
        self._sync_scroll_size()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        QTimer.singleShot(0, self._scroll_to_bottom_once)

    def _scroll_to_bottom_once(self):
        """布局收敛后的补充滚动：确保内容底部完全露出（不被挡住）。"""
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_columns_changed(self):
        self.sheet.set_columns_per_line(self.cols_spin.value())
        self._sync_scroll_size()
        self._refresh_status()

    def _toggle_key_panel(self, visible: bool):
        """显示/隐藏键位面板；隐藏时格子谱区占满，布局自动重同步。"""
        self.key_panel.setVisible(visible)
        self._sync_scroll_size()
        self.statusBar().showMessage(
            "键位面板已隐藏" if not visible else "键位面板已显示", 3000)

    def _toggle_key_dock(self):
        """菜单按钮：打开/收起按键区设置侧边栏。"""
        self.key_dock.setVisible(not self.key_dock.isVisible())

    def open_output_folder(self):
        """打开默认导出目录（应用目录下的 outputs），不存在则先创建。"""
        out_dir = str(default_output_dir())
        QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        self.statusBar().showMessage(f"已打开输出文件夹：{out_dir}", 3000)

    def _on_mode_radio(self, checked: bool):
        """侧边栏键面显示模式单选 → 同步到键位面板。"""
        if not checked:
            return
        btn = self.sender()
        if isinstance(btn, QRadioButton):
            self.key_panel.set_display_mode(btn.property("mode"))

    # ---------- 动作：新建 ----------

    def new_sheet(self):
        """新建：脏时确认；确认后清空标题与网格，光标归零，每横排不变。"""
        if self._dirty:
            ret = QMessageBox.question(
                self, "新建乐谱", "当前乐谱有未保存的修改，是否放弃？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.No)
            if ret != QMessageBox.Yes:
                return

        self.title_edit.blockSignals(True)
        self.title_edit.clear()
        self.title_edit.blockSignals(False)
        self._model = NoteGrid()
        self._set_sheet_model(self._model)
        self.sheet.set_cursor(0)
        self._current_path = None
        self._dirty = False
        self._update_title()
        self._refresh_status()
        self._refresh_beat_marks()
        self._scroll_to_bottom()   # R5：新建后滚动到底部（空谱即顶部）

    # ---------- 动作：保存 ----------

    def save_sheet(self):
        """保存：标题为空先输入；路径 = 数据目录/标题.ggp；重名确认覆盖。"""
        title = self.title_edit.text().strip()
        if not title:
            title = prompt_title(self)
            if not title:
                return
            self.title_edit.blockSignals(True)
            self.title_edit.setText(title)
            self.title_edit.blockSignals(False)

        data_dir = default_data_dir()
        path = os.path.join(str(data_dir), title + ".ggp")

        if os.path.exists(path) and self._current_path != path:
            ret = QMessageBox.question(
                self, "文件已存在",
                f"「{title}」已存在，是否覆盖？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return

        save_ggp(path, title, self.sheet.columns_per_line(), self._model,
                 mark_color=self._mark_color, chord_color=self._chord_color,
                 style=self._style, bg_color=self._bg_color,
                 border_color=self._border_color)
        self._current_path = path
        self._dirty = False
        self._update_title()
        self.statusBar().showMessage(f"已保存：{title}", 3000)

    # ---------- 动作：浏览 ----------

    def browse_sheets(self):
        """浏览历史乐谱并打开选中项（脏时确认放弃）。"""
        dlg = BrowseSheetsDialog(default_data_dir(), self)
        if dlg.exec() != QDialog.Accepted:
            return
        path = dlg.selected_path()
        if not path:
            return

        if self._dirty:
            ret = QMessageBox.question(
                self, "打开乐谱", "当前乐谱有未保存的修改，是否放弃？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return

        try:
            data = load_ggp(path)
        except (OSError, ValueError):
            QMessageBox.warning(self, "打开失败", f"无法读取文件：\n{path}")
            return

        # 恢复网格内容（同一 model 实例）
        self._model.from_list(data["note_grid"])
        self.sheet.update()

        # 恢复每横排列数（QSpinBox 自动夹取到 4–16）
        cpl = data["columns_per_line"]
        self.cols_spin.setValue(cpl)

        # 恢复标题
        self.title_edit.blockSignals(True)
        self.title_edit.setText(data["title"])
        self.title_edit.blockSignals(False)

        # 恢复旋律颜色与和弦颜色（文件带字段时）
        if data.get("mark_color"):
            self._mark_color = data["mark_color"]
            self.sheet.set_mark_color(QColor(data["mark_color"]))
        if data.get("chord_color"):
            self._chord_color = data["chord_color"]
            self.sheet.set_chord_color(QColor(data["chord_color"]))

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

        self.sheet.set_cursor(0)
        self._current_path = path
        self._dirty = False
        self._update_title()
        self._refresh_status()
        self._refresh_beat_marks()
        self._scroll_to_bottom()   # R5：打开后滚动到底部
        self.statusBar().showMessage(f"已打开：{data['title'] or path}", 3000)

    # ---------- 动作：旋律 / 和弦颜色 ----------

    def choose_mark_color(self):
        """弹出颜色选择器设置自定义旋律标记颜色（不置脏，仅状态栏提示）。"""
        color = QColorDialog.getColor(self.sheet.mark_color(), self, "选择旋律颜色")
        if not color.isValid():
            return
        self._mark_color = color.name()
        self.sheet.set_mark_color(color)
        self.statusBar().showMessage(f"旋律颜色已更换：{self._mark_color}", 3000)

    def choose_chord_color(self):
        """弹出颜色选择器设置自定义和弦标记颜色（不置脏，仅状态栏提示）。"""
        color = QColorDialog.getColor(self.sheet.chord_color(), self, "选择和弦颜色")
        if not color.isValid():
            return
        self._chord_color = color.name()
        self.sheet.set_chord_color(color)
        self.statusBar().showMessage(f"和弦颜色已更换：{self._chord_color}", 3000)

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

    # ---------- 动作：导出 PNG ----------

    def export_png(self):
        """导出 PNG：预览对话框内设置输出目录（默认 outputs）、分层/平铺模式、
        行列与颜色等，确认后分页导出（多页文件名自动追加 _1/_2…）。"""
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
        if dlg.exec() != QDialog.Accepted:
            return
        path_base = dlg.output_path_base()
        ok, pages = export_pages(
            path_base, self._model, dlg.columns_per_line(), dlg.rows_per_page(),
            mark_color=dlg.mark_color(), chord_color=dlg.chord_color(),
            style=dlg.style(), bg_color=dlg.bg_color(),
            border_color=dlg.border_color(),
            title=dlg.display_name(), draw_title=dlg.draw_title())
        if ok:
            if pages > 1:
                QMessageBox.information(
                    self, "导出完成",
                    f"已导出 {pages} 张 PNG：\n{path_base}_1.png … {path_base}_{pages}.png")
            else:
                QMessageBox.information(self, "导出完成", f"已导出：\n{path_base}.png")
        else:
            QMessageBox.warning(self, "导出失败", f"部分图片保存失败：\n{path_base}_*.png")

    # ---------- 关闭 ----------

    def closeEvent(self, event):
        """关闭窗口：脏时确认是否放弃。"""
        if self._dirty:
            ret = QMessageBox.question(
                self, "退出", "当前乐谱有未保存的修改，是否放弃？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()
