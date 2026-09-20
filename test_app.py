# -*- coding: utf-8 -*-
"""光遇格子谱制作器 —— 端到端冒烟测试（version 2 集成验证）。

运行方式（Windows PowerShell，cwd=项目根目录）：
    $env:QT_QPA_PLATFORM='offscreen'
    python test_app.py

覆盖：
  0. V0 偏格回归：逐格点击 / 键盘放置后像素采样，断言标记恰好落于所点格
     （含滚动到底与手动尺寸同步后仍精确）
  1. 主窗口四区 + QSplitter 存在 + QSpinBox(4–16) 存在 + 滚动区手动尺寸同步
  2. 键盘输入 Y/J/N（含小写）→ 主旋律放置、光标不前进；右箭头追加空白节拍并移入
  3. Shift+按键 → 该键以和弦存到当前节拍且光标不前进；与主旋律同节拍共存；
     Shift+`; , . /` 与 `: < > ?`（两种 event.key() 键码）均以和弦输入、
     普通 `;` 输入主旋律
  4. 每节拍多键：同一节拍通过点击放多个不同键；点击键位面板 → 当前节拍放置
     且不前进光标（左键=增加主旋律、右键=增加和弦、中键忽略）
  5. 格子谱三键：左键=主旋律切换、右键=和弦切换、中键=只切光标不改标记；
     已和弦格左键更新为主旋律；Shift 不再参与主/和弦区分
  6. Backspace → 删除光标所在（高亮）节拍全部音符且光标不动；
     方向键右移在末尾追加空白节拍、左移到 0 不动
  7. 每横排 QSpinBox 改值 → 内容不丢；小格边长/sizeHint 立即重算（不依赖 resize）
  8. 保存/加载往返：内容、columns_per_line、mark_color、chord_color 一致；
     v1 旧格式文件（单字母 note_grid）能加载并转换为全部主旋律
  9. 导出 PNG：默认色与自定义色均成功、非空
  10. 状态栏：列数/光标/每横排正确；cursorMoved 不清脏；内容变化置脏
  11. 像素级回归：无图例（R9）、单格填充、边框 #b8b8b8、无抗锯齿糊边（R10）
  12. 自适应：resize SheetWidget 到不同宽度，断言小格边长缩放限幅、
      sizeHint 高度随行数变化、绘制不抛异常
  13. 滚动：40 节拍 cpl=4（10 横排）→ 垂直滚动条出现、滚到底最后一块可见；
      空谱不出现滚动条且垂直居中
  14. 键位面板标记（set_beat_marks）：随光标移动/内容变化同步、重绘不抛异常
  15. 自动滚动（R5）：内容/光标变化后自动滚到光标节拍块可见、新建复位到底

测试全部使用 tempfile 临时目录，并通过注入（mock patch）替换对话框与
default_data_dir，避免触碰真实 %APPDATA%/SkyGridSheet 与真实弹窗。
"""

import json
import os
import pathlib
import sys
import tempfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialog, QMessageBox, QPushButton, QSpinBox, QSplitter,
)

import main_window as mw
import dialogs as dlg
from main_window import MainWindow
from model import (
    DEFAULT_CHORD_COLOR, DEFAULT_MARK_COLOR, KEYS, KEY_COLS, KEY_ROWS, ROWS,
    NoteGrid,
)
from sheet_widget import SheetWidget
from key_panel import KeyPanel
from file_io import save_ggp, load_ggp
from export import (export_png, render_sheet_image,
                    num_pages, render_page_image, export_pages)

# 布局常量（与各模块保持一致，供点击坐标换算）
from sheet_widget import (MARGIN_X, MARGIN_Y, MINI_GAP, BLOCK_GAP, LINE_GAP,
                          MINI_MIN, MINI_MAX)
from key_panel import (KEYS as PANEL_KEYS, COLS as PANEL_COLS, ROWS as PANEL_ROWS,
                       KEY_W, KEY_H, GAP as PANEL_GAP,
                       COLOR_CURRENT_BG, COLOR_SHARP_BG)
from export import (MARGIN as EXPORT_MARGIN, MINI as EXPORT_MINI,
                    MINI_GAP as EXPORT_MINI_GAP,
                    BLOCK_W as EXPORT_BLOCK_W, BLOCK_H as EXPORT_BLOCK_H,
                    BLOCK_GAP as EXPORT_BLOCK_GAP,
                    LINE_GAP as EXPORT_LINE_GAP,
                    TITLE_H as EXPORT_TITLE_H)
from export import MINI as EX_MINI, MARGIN as EX_M

RESULTS: list[tuple[str, bool]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    """登记一条断言结果并打印 PASS/FAIL。"""
    RESULTS.append((name, bool(cond)))
    line = f"[{'PASS' if cond else 'FAIL'}] {name}"
    if not cond and detail:
        line += f"  (detail: {detail})"
    print(line)
    return cond


def panel_key_center(panel: KeyPanel, key: str) -> QPoint:
    """计算键位面板中某键的中心像素坐标（基于面板实际自适应键尺寸）。"""
    idx = PANEL_KEYS.index(key)
    row = idx // PANEL_COLS
    col = idx % PANEL_COLS
    kw, kh = panel._key_w, panel._key_h
    cw = PANEL_COLS * kw + (PANEL_COLS - 1) * PANEL_GAP
    ch = PANEL_ROWS * kh + (PANEL_ROWS - 1) * PANEL_GAP
    ox = (panel.width() - cw) / 2.0
    oy = (panel.height() - ch) / 2.0
    x = ox + col * (kw + PANEL_GAP) + kw / 2.0
    y = oy + row * (kh + PANEL_GAP) + kh / 2.0
    return QPoint(int(x), int(y))


def sheet_cell_center(sheet: SheetWidget, r: int, c: int,
                      block: int = 0, line: int = 0) -> QPoint:
    """计算格子谱显示区某节拍块内小格 (r,c) 的中心像素坐标（含居中偏移与自适应尺寸）。"""
    mini = sheet._mini
    bw = sheet._block_w()
    bh = sheet._block_h()
    x = (sheet._offset_x() + MARGIN_X + block * (bw + BLOCK_GAP)
         + c * (mini + MINI_GAP) + mini / 2.0)
    y = (sheet._offset_y() + MARGIN_Y + line * (bh + LINE_GAP)
         + r * (mini + MINI_GAP) + mini / 2.0)
    return QPoint(int(x), int(y))


def settle_layout(window: MainWindow):
    """等待窗口布局稳定（初始布局/滚动条出现需多轮事件处理，防止点击坐标过期）。"""
    sheet = window.sheet
    for _ in range(30):
        w_before = sheet.width()
        h_before = sheet.height()
        QApplication.processEvents()
        QTest.qWait(10)
        if (sheet.width(), sheet.height()) == (w_before, h_before) \
                and sheet._last_width == sheet.width():
            break


def panel_pixels(panel: KeyPanel) -> dict:
    """统计键位面板每个键矩形内的主色（面积最大颜色）→ {key: color_name}。

    键底/标记填充色面积最大；文字、形状标记、角标、边框面积都小，
    用众数可稳定取到键底色（避开中心形状与字母的抗锯齿混色）。
    若某键被画笔泄漏整键填充（旧 bug），泄漏色面积最大 → 断言即可捕获。
    """
    img = panel.grab().toImage()
    out = {}
    for key in PANEL_KEYS:
        idx = PANEL_KEYS.index(key)
        row, col = idx // PANEL_COLS, idx % PANEL_COLS
        kw, kh = panel._key_w, panel._key_h
        ox = (panel.width() - PANEL_COLS * kw - (PANEL_COLS - 1) * PANEL_GAP) / 2.0
        oy = (panel.height() - PANEL_ROWS * kh - (PANEL_ROWS - 1) * PANEL_GAP) / 2.0
        x0 = int(ox + col * (kw + PANEL_GAP))
        y0 = int(oy + row * (kh + PANEL_GAP))
        x1 = min(img.width(), int(ox + col * (kw + PANEL_GAP) + kw))
        y1 = min(img.height(), int(oy + row * (kh + PANEL_GAP) + kh))
        hist: dict[str, int] = {}
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                c = img.pixelColor(xx, yy).name()
                hist[c] = hist.get(c, 0) + 1
        out[key] = max(hist.items(), key=lambda kv: kv[1])[0]
    return out


def main() -> int:
    app = QApplication.instance() or QApplication([])

    # 临时目录：全部文件操作均在此，不污染项目与用户数据目录
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ggp_smoke_"))

    with (
        mock.patch.object(mw.QMessageBox, "question", return_value=QMessageBox.Yes),
        mock.patch.object(mw.QMessageBox, "information"),
        mock.patch.object(mw.QMessageBox, "warning"),
        mock.patch.object(dlg.ExportDialog, "exec", return_value=QDialog.Accepted),
        mock.patch.object(mw, "default_data_dir", return_value=tmp),
        mock.patch.object(mw, "default_output_dir", return_value=tmp / "outputs"),  # 默认导出目录 → tmp/outputs
        mock.patch.object(mw.QDesktopServices, "openUrl"),
    ):
        window = MainWindow()
        window.show()
        QTest.qWait(30)
        sheet = window.sheet
        panel = window.key_panel

        # ---------------- T1: 主窗口四区 + QSplitter + QSpinBox ----------------
        check("T1a 工具栏存在", isinstance(window.toolbar, mw.QToolBar))
        check("T1b 中央为 QSplitter 且上部滚动区承载 SheetWidget",
              isinstance(window.centralWidget(), QSplitter)
              and window.centralWidget().widget(0) is window.scroll
              and window.scroll.widget() is sheet)
        check("T1c 下部键位面板 KeyPanel 存在",
              window.centralWidget().widget(1) is panel
              and isinstance(panel, KeyPanel))
        check("T1d 状态栏存在且含状态标签",
              window.statusBar() is not None and window.status_label is not None)
        check("T1e 每横排为 QSpinBox 范围4-16默认4",
              isinstance(window.cols_spin, QSpinBox)
              and window.cols_spin.minimum() == 4 and window.cols_spin.maximum() == 16
              and window.cols_spin.value() == 4,
              f"value={window.cols_spin.value()}")
        check("T1f 滚动区关闭自动缩放（widget 尺寸手动同步）",
              window.scroll.widgetResizable() is False)
        settle_layout(window)

        # ---------------- T0: V0 复现——点击/输入与标记渲染位置一致（防"偏一格"） ----------------
        # A) 块 0 每个小格中心左键点击 → model 恰好得到 KEYS[r*5+c]，无偏格
        window.new_sheet()
        model = window._model
        click_ok = True
        for r in range(3):
            for c in range(5):
                key = KEYS[r * 5 + c]
                pos = sheet_cell_center(sheet, r, c)
                QTest.mouseClick(sheet, Qt.LeftButton, pos=pos)
                notes = model.notes(0)
                if notes != [(key, False)] or sheet.cursor() != 0:
                    click_ok = False
                    print(f"      [V0] 格({r},{c}) 期望 {key} 实际 {notes} cursor={sheet.cursor()}")
                QTest.mouseClick(sheet, Qt.LeftButton, pos=pos)   # 再点取消，复位
        check("T0a 逐格点击 → 标记恰好落在所点格（无偏格）", click_ok)

        # B) apply_key/place_at_cursor 放置后 grab() 像素采样：标记落于该键小格中心、相邻格仍白
        pix_ok = True
        for key in KEYS:
            window.new_sheet()
            sheet.apply_key(key)
            img = sheet.grab().toImage()
            r = KEY_ROWS[key]
            c = KEY_COLS[key]
            mini = sheet._mini
            cx = int(sheet._offset_x() + MARGIN_X + c * (mini + MINI_GAP) + mini / 2.0)
            cy = int(sheet._offset_y() + MARGIN_Y + r * (mini + MINI_GAP) + mini / 2.0)
            px = img.pixelColor(cx, cy)
            c2 = c + 1 if c < 4 else c - 1
            cx2 = int(sheet._offset_x() + MARGIN_X + c2 * (mini + MINI_GAP) + mini / 2.0)
            px2 = img.pixelColor(cx2, cy)
            mark = sheet.mark_color().name()
            if px.name() != mark or px2.name() != "#ffffff":
                pix_ok = False
                print(f"      [V0] key={key} 格({r},{c}) px={px.name()} 期望{mark} 相邻格={px2.name()}")
        check("T0b apply_key 放置后标记落于该键小格中心、相邻格仍白", pix_ok)

        # C) 手动尺寸同步场景：宽度改变 → _mini 重算、内容重绘 → 点击/像素仍精确无位移
        s2 = SheetWidget(NoteGrid(0), 4)
        s2.resize(460, 300)
        s2.show()
        QTest.qWait(10)
        mini_1 = s2._mini
        QTest.mouseClick(s2, Qt.LeftButton, pos=sheet_cell_center(s2, 1, 1))   # (1,1) → J
        m2 = s2.model()
        ok_c1 = (m2.melody_keys(0) == ["J"])
        s2.resize(900, 300)                                                     # 模拟 _sync_scroll_size
        QTest.qWait(10)
        mini_2 = s2._mini
        QTest.mouseClick(s2, Qt.LeftButton, pos=sheet_cell_center(s2, 2, 3))   # (2,3) → '.'
        ok_c2 = (m2.melody_keys(0) == ["J", "."])
        img2 = s2.grab().toImage()
        mini = s2._mini
        mark2 = s2.mark_color().name()
        cxJ = int(s2._offset_x() + MARGIN_X + 1 * (mini + MINI_GAP) + mini / 2.0)
        cyJ = int(s2._offset_y() + MARGIN_Y + 1 * (mini + MINI_GAP) + mini / 2.0)
        pxJ = img2.pixelColor(cxJ, cyJ)
        cxD = int(s2._offset_x() + MARGIN_X + 3 * (mini + MINI_GAP) + mini / 2.0)
        cyD = int(s2._offset_y() + MARGIN_Y + 2 * (mini + MINI_GAP) + mini / 2.0)
        pxD = img2.pixelColor(cxD, cyD)
        check("T0c 宽度改变 mini 重算后点击换算与像素仍精确",
              mini_2 != mini_1 and ok_c1 and ok_c2
              and pxJ.name() == mark2 and pxD.name() == mark2,
              f"mini {mini_1}->{mini_2} click1={ok_c1} click2={ok_c2} "
              f"pxJ={pxJ.name()} pxDot={pxD.name()} 期望{mark2}")

        # D) 滚动区滚到底后点击最底行小格 → 坐标换算仍精确（无滚动偏移）
        window.new_sheet()
        model = window._model
        for i in range(40):
            sheet.apply_key("Y")
            if i < 39:
                QTest.keyClick(sheet, Qt.Key_Right)
        QTest.qWait(30)
        sb = window.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        QTest.qWait(30)
        QTest.mouseClick(sheet, Qt.LeftButton,
                         pos=sheet_cell_center(sheet, 2, 2, block=3, line=9))   # beat=39 的 (2,2) → ','
        ok_d = (model.has_note(39, ",") and sheet.cursor() == 39)
        img4 = sheet.grab().toImage()
        mini = sheet._mini
        cx = int(sheet._offset_x() + MARGIN_X + 3 * (sheet._block_w() + BLOCK_GAP)
                 + 2 * (mini + MINI_GAP) + mini / 2.0)
        cy = int(sheet._offset_y() + MARGIN_Y + 9 * (sheet._block_h() + LINE_GAP)
                 + 2 * (mini + MINI_GAP) + mini / 2.0)
        pxK = img4.pixelColor(cx, cy)
        check("T0d 滚到底后点击最底行小格仍精确且像素为标记色",
              ok_d and pxK.name() == sheet.mark_color().name(),
              f"notes39={model.notes(39)} cursor={sheet.cursor()} pxK={pxK.name()}")

        # ---------------- T2: 键盘输入 Y/J/N（含小写）→ 主旋律放置、光标不前进、自动扩展 ----------------
        window.new_sheet()   # 重置为干净状态
        model = window._model   # new_sheet 之后捕获（model 实例被替换）
        QTest.keyClick(sheet, "Y")                    # 大写字符串
        check("T2a Y 放入节拍0主旋律", model.cell(0, 0) == "Y",
              f"cell={model.cell(0, 0)!r}")
        check("T2b 普通按键不再前进光标", sheet.cursor() == 0, f"cursor={sheet.cursor()}")
        QTest.keyClick(sheet, Qt.Key_Right)           # 右箭头 → 追加空白节拍并移入（R2）
        check("T2c 右箭头光标到1", sheet.cursor() == 1, f"cursor={sheet.cursor()}")
        QTest.keyClick(sheet, Qt.Key_J)               # 无 Shift 修饰，text 为小写 'j'
        check("T2d 小写 j 放入节拍1主旋律", model.cell(1, 1) == "J",
              f"cell={model.cell(1, 1)!r}")
        QTest.keyClick(sheet, Qt.Key_Right)
        QTest.keyClick(sheet, "n")                    # 小写字符串
        check("T2e 小写 n 放入节拍2主旋律", model.cell(2, 2) == "N",
              f"cell={model.cell(2, 2)!r}")
        QTest.keyClick(sheet, Qt.Key_Right)
        QTest.keyClick(sheet, "i")                    # 小写字符串
        check("T2f 小写 i 放入节拍3主旋律", model.cell(0, 3) == "I",
              f"cell={model.cell(0, 3)!r}")
        check("T2g 键盘输入不前进光标（停在3）", sheet.cursor() == 3, f"cursor={sheet.cursor()}")
        check("T2h 网格自动扩展至至少4节拍", model.num_columns() >= 4,
              f"num_columns={model.num_columns()}")

        # ---------------- T3: Shift+按键 → 和弦且光标不前进；与主旋律共存 ----------------
        QTest.keyClick(sheet, "Y", Qt.ShiftModifier)   # 节拍3 放 Y 和弦
        check("T3a Shift+Y 以和弦存入节拍3", model.chord_keys(3) == ["Y"],
              f"chord={model.chord_keys(3)}")
        check("T3b 和弦不前进光标", sheet.cursor() == 3, f"cursor={sheet.cursor()}")
        QTest.keyClick(sheet, "u")                    # 普通按键 → 节拍3 放 U 主旋律（不前进）
        check("T3c 普通 U 放入节拍3主旋律", "U" in model.melody_keys(3),
              f"melody={model.melody_keys(3)}")
        check("T3d 主旋律与和弦同节拍共存",
              "U" in model.melody_keys(3) and model.chord_keys(3) == ["Y"],
              f"melody={model.melody_keys(3)} chord={model.chord_keys(3)}")
        check("T3e 普通按键不前进光标", sheet.cursor() == 3, f"cursor={sheet.cursor()}")

        # Shift+符号键，键码形式一：Key_Semicolon / Key_Comma / Key_Period / Key_Slash（R6）
        QTest.keyClick(sheet, Qt.Key_Semicolon, Qt.ShiftModifier)   # 节拍3 放 ';' 和弦
        QTest.keyClick(sheet, Qt.Key_Comma, Qt.ShiftModifier)
        QTest.keyClick(sheet, Qt.Key_Period, Qt.ShiftModifier)
        QTest.keyClick(sheet, Qt.Key_Slash, Qt.ShiftModifier)
        check("T3f Shift+; , . /（Key_Semicolon 等）全部以和弦输入且不前进",
              sorted(model.chord_keys(3)) == [",", ".", "/", ";", "Y"] and sheet.cursor() == 3,
              f"chord={model.chord_keys(3)} cursor={sheet.cursor()}")
        # 键码形式二：Shift 下 event.key() 为 Key_Colon / Key_Less / Key_Greater / Key_Question（R6）
        QTest.keyClick(sheet, Qt.Key_Right)                        # 光标 → 4（追加空白节拍）
        QTest.keyClick(sheet, Qt.Key_Colon, Qt.ShiftModifier)
        QTest.keyClick(sheet, Qt.Key_Less, Qt.ShiftModifier)
        QTest.keyClick(sheet, Qt.Key_Greater, Qt.ShiftModifier)
        QTest.keyClick(sheet, Qt.Key_Question, Qt.ShiftModifier)
        check("T3g Shift+: < > ?（Key_Colon 等）也能以和弦输入",
              sorted(model.chord_keys(4)) == [",", ".", "/", ";"] and sheet.cursor() == 4,
              f"chord={model.chord_keys(4)} cursor={sheet.cursor()}")
        QTest.keyClick(sheet, Qt.Key_Semicolon)                     # 普通 ; → 主旋律（不前进）
        check("T3h 普通 ; 输入主旋律且不前进",
              model.melody_keys(4).count(";") == 1 and sheet.cursor() == 4,
              f"notes4={model.notes(4)} cursor={sheet.cursor()}")

        # ---------------- T4: 每节拍多键（点击放多个不同键） ----------------
        window.new_sheet()
        model = window._model
        QTest.mouseClick(sheet, Qt.LeftButton, pos=sheet_cell_center(sheet, 0, 0))  # beat0 → Y
        QTest.mouseClick(sheet, Qt.LeftButton, pos=sheet_cell_center(sheet, 0, 1))  # beat0 → U
        check("T4a 同一节拍两个主旋律键", len(model.notes(0)) == 2,
              f"notes={model.notes(0)}")
        check("T4b 键分别为 Y 与 U",
              sorted(model.melody_keys(0)) == ["U", "Y"],
              str(sorted(model.melody_keys(0))))
        check("T4c 点击不前进节拍之外", model.num_columns() >= 1)

        # 键位面板点击 → place_at_cursor：当前节拍放置、不前进光标（R8）
        QTest.mouseClick(panel, Qt.LeftButton, pos=panel_key_center(panel, "O"))
        check("T4d 左键点击键位面板 → 当前节拍0 增加主旋律且不前进光标",
              model.melody_keys(0).count("O") == 1 and sheet.cursor() == 0,
              f"notes={model.notes(0)} cursor={sheet.cursor()}")
        QTest.mouseClick(panel, Qt.RightButton, pos=panel_key_center(panel, "P"))
        check("T4e 右键点击键位面板 → 当前节拍增加和弦且不前进光标",
              model.is_chord(0, "P") and sheet.cursor() == 0,
              f"notes={model.notes(0)} cursor={sheet.cursor()}")

        # ---------------- T5: 三键点击（左=主旋律切换、右=和弦切换、中=只切光标） ----------------
        QTest.mouseClick(sheet, Qt.LeftButton, pos=sheet_cell_center(sheet, 1, 0))  # beat0 → H 主旋律
        check("T5a 左键点空格放置主旋律 H", model.melody_keys(0).count("H") == 1,
              f"notes={model.notes(0)}")
        QTest.mouseClick(sheet, Qt.LeftButton, pos=sheet_cell_center(sheet, 1, 0))
        check("T5b 左键再点同格取消主旋律", model.has_note(0, "H") is False,
              f"notes={model.notes(0)}")
        QTest.mouseClick(sheet, Qt.RightButton, pos=sheet_cell_center(sheet, 1, 1))  # beat0 → J 和弦
        check("T5c 右键放和弦 J", model.is_chord(0, "J") is True,
              f"notes={model.notes(0)}")
        QTest.mouseClick(sheet, Qt.RightButton, pos=sheet_cell_center(sheet, 1, 1))
        check("T5d 右键再点同格取消和弦", model.has_note(0, "J") is False,
              f"notes={model.notes(0)}")
        # 已有和弦的格：左键点击 → 类型更新为主旋律（不取消）
        QTest.mouseClick(sheet, Qt.RightButton, pos=sheet_cell_center(sheet, 1, 2))  # beat0 → K 和弦
        QTest.mouseClick(sheet, Qt.LeftButton, pos=sheet_cell_center(sheet, 1, 2))   # 左键 → 变主旋律
        check("T5e 左键点击已和弦格→更新为主旋律",
              model.is_chord(0, "K") is False and model.has_note(0, "K") is True,
              f"notes={model.notes(0)}")
        # 右键已存在的主旋律格：不删除（R7 右键只切换和弦标记）
        QTest.mouseClick(sheet, Qt.RightButton, pos=sheet_cell_center(sheet, 1, 0))  # 右键 H（主旋律）
        check("T5f 右键已存在主旋律格不删除", model.has_note(0, "H") is True,
              f"notes={model.notes(0)}")
        # Shift 不再参与主/和弦区分：Shift+左键仍按主旋律切换
        QTest.mouseClick(sheet, Qt.LeftButton, Qt.ShiftModifier,
                         pos=sheet_cell_center(sheet, 1, 4))   # beat0 → ; 主旋律
        check("T5g Shift+左键仍按主旋律切换（不再切和弦）",
              model.is_chord(0, ";") is False and model.melody_keys(0).count(";") == 1,
              f"notes={model.notes(0)}")
        # 中键：只切换光标，不更改任何标记
        QTest.mouseClick(sheet, Qt.MiddleButton,
                         pos=sheet_cell_center(sheet, 2, 3, block=1))   # beat1 (2,3) → '.'
        check("T5h 中键只切光标不改标记",
              sheet.cursor() == 1 and model.has_note(1, ".") is False,
              f"cursor={sheet.cursor()} notes1={model.notes(1)}")
        # 三键点击后均更新当前选中键并同步键位面板高亮
        check("T5i 中键后当前键同步", sheet.current_key() == ".",
              f"key={sheet.current_key()}")

        # ---------------- T6: Backspace 删除光标所在节拍且光标不动；方向键移动/追加 ----------------
        window.new_sheet()
        model = window._model
        QTest.keyClick(sheet, "Y")                            # 节拍0 Y 主旋律（R3 不前进）
        QTest.keyClick(sheet, Qt.Key_Right)                   # 光标 → 1
        QTest.keyClick(sheet, "U")                            # 节拍1 U 主旋律
        QTest.keyClick(sheet, "I", Qt.ShiftModifier)          # 节拍1 和弦 I，光标不动
        check("T6a 前置状态：节拍0 Y、节拍1 U+I 和弦、光标1",
              model.notes(0) == [("Y", False)]
              and model.notes(1) == [("U", False), ("I", True)]
              and sheet.cursor() == 1,
              f"notes0={model.notes(0)} notes1={model.notes(1)} cursor={sheet.cursor()}")
        QTest.keyClick(sheet, Qt.Key_Backspace)               # Backspace：清空高亮拍（节拍1）全部音符，保留空拍位置
        check("T6b Backspace 清空高亮拍（节拍1）全部音符且光标不动",
              model.notes(1) == [] and sheet.cursor() == 1,
              f"notes1={model.notes(1)} cursor={sheet.cursor()}")
        QTest.keyClick(sheet, Qt.Key_Left)                    # 光标移回0
        QTest.keyClick(sheet, Qt.Key_Backspace)               # Backspace：清空节拍0（Y），光标不动
        check("T6c Backspace 清空节拍0全部音符且光标不动",
              model.notes(0) == [] and sheet.cursor() == 0,
              f"notes0={model.notes(0)} cursor={sheet.cursor()}")
        QTest.keyClick(sheet, Qt.Key_Backspace)               # 空节拍再删不越界
        check("T6d 空节拍删除不越界", sheet.cursor() == 0, f"cursor={sheet.cursor()}")
        # R2：右箭头在末尾追加空白节拍并移入；左移到 0 后不再移动
        QTest.keyClick(sheet, Qt.Key_Right)                   # 末尾(0)右移 → 追加空白节拍1
        QTest.keyClick(sheet, Qt.Key_Right)                   # 再右移 → 追加空白节拍2
        check("T6e 末尾右箭头追加空白节拍并移入",
              sheet.cursor() == 2 and model.num_columns() == 3,
              f"cursor={sheet.cursor()} cols={model.num_columns()}")
        check("T6f 追加的节拍为空白", model.notes(2) == [], f"notes2={model.notes(2)}")
        QTest.keyClick(sheet, Qt.Key_Left)
        QTest.keyClick(sheet, Qt.Key_Left)
        QTest.keyClick(sheet, Qt.Key_Left)                    # 2 → 0
        check("T6g 左移可回到0", sheet.cursor() == 0, f"cursor={sheet.cursor()}")
        QTest.keyClick(sheet, Qt.Key_Left)                    # 0 处再左移不越界
        check("T6h 0 处左移不越界", sheet.cursor() == 0, f"cursor={sheet.cursor()}")

        # ---------------- T7: 每横排 QSpinBox 改值实时生效 / 内容不丢 ----------------
        before = model.to_list()
        before_h = sheet.sizeHint().height()
        window.cols_spin.setValue(8)
        check("T7a spin 切到每横排8", sheet.columns_per_line() == 8,
              f"cpl={sheet.columns_per_line()}")
        check("T7b 切换后内容不丢", model.to_list() == before)
        # R3：每横排改动必须立即重算小格边长（解除 _last_width 守卫），不等窗口 resize
        expect_mini = sheet._compute_mini(sheet.width())
        check("T7c 小格边长立即按当前宽度重算",
              sheet._mini == expect_mini and sheet._last_width == sheet.width(),
              f"mini={sheet._mini} expect={expect_mini} last={sheet._last_width} w={sheet.width()}")
        check("T7d sizeHint 高度随每横排立即变化", sheet.sizeHint().height() != before_h,
              f"{before_h} -> {sheet.sizeHint().height()}")
        pix_cpl = sheet.grab()
        check("T7e 改值后立即绘制不抛异常", not pix_cpl.isNull())
        sheet.set_columns_per_line(16)
        check("T7f set_columns_per_line(16) 生效", sheet.columns_per_line() == 16)
        sheet.set_columns_per_line(4)
        check("T7g set_columns_per_line(4) 生效", sheet.columns_per_line() == 4)
        check("T7h 切回后内容不丢", model.to_list() == before)

        # ---------------- T8: 保存/加载往返 + v1 旧格式兼容 ----------------
        window.new_sheet()
        model = window._model
        model.place_key("Y", 0)
        model.toggle_note(0, "I", True)       # 节拍0：Y 主旋律 + I 和弦
        model.place_key("U", 1)
        window.sheet.set_cursor(0)
        window.title_edit.setText("SmokeTitle")
        window._mark_color = "#112233"
        window._chord_color = "#445566"
        window.save_sheet()   # default_data_dir 已注入临时目录
        saved_path = tmp / "SmokeTitle.ggp"
        check("T8a 保存文件存在", saved_path.exists(), str(saved_path))
        data = load_ggp(saved_path)
        grid2 = NoteGrid()
        grid2.from_list(data["note_grid"])
        check("T8b 加载内容一致（含和弦）", grid2.to_list() == model.to_list(),
              f"{grid2.to_list()} != {model.to_list()}")
        check("T8c columns_per_line 一致",
              data["columns_per_line"] == sheet.columns_per_line(),
              f"file={data['columns_per_line']} sheet={sheet.columns_per_line()}")
        check("T8d 标题一致", data["title"] == "SmokeTitle", f"title={data['title']!r}")
        check("T8e mark_color 往返一致", data["mark_color"] == "#112233",
              data["mark_color"])
        check("T8f chord_color 往返一致", data["chord_color"] == "#445566",
              data["chord_color"])
        with open(saved_path, "r", encoding="utf-8") as f:
            raw_saved = json.load(f)
        check("T8g 保存为 version 2", raw_saved.get("version") == 2,
              f"version={raw_saved.get('version')}")
        check("T8h note_grid 为新结构[节拍][音符对象]",
              isinstance(raw_saved["note_grid"][0], list)
              and isinstance(raw_saved["note_grid"][0][0], dict)
              and raw_saved["note_grid"][0][0].get("k") == "Y"
              and raw_saved["note_grid"][0][0].get("c") is False,
              str(raw_saved["note_grid"]))

        # 字段省略：未传颜色时
        no_mark_path = tmp / "no_mark.ggp"
        save_ggp(no_mark_path, "NoMark", 4, model)
        with open(no_mark_path, "r", encoding="utf-8") as f:
            raw_no_mark = json.load(f)
        check("T8i 未传颜色时省略字段",
              "mark_color" not in raw_no_mark and "chord_color" not in raw_no_mark,
              str(list(raw_no_mark.keys())))
        check("T8j 缺失时回退默认色",
              load_ggp(no_mark_path)["mark_color"] == DEFAULT_MARK_COLOR
              and load_ggp(no_mark_path)["chord_color"] == DEFAULT_CHORD_COLOR,
              f"{load_ggp(no_mark_path)['mark_color']} {load_ggp(no_mark_path)['chord_color']}")
        # 非法颜色回退默认色
        bad_mark_path = tmp / "bad_mark.ggp"
        raw_no_mark["mark_color"] = "red"
        raw_no_mark["chord_color"] = "#ZZZZZZ"
        with open(bad_mark_path, "w", encoding="utf-8") as f:
            json.dump(raw_no_mark, f)
        bad = load_ggp(bad_mark_path)
        check("T8k 非法颜色回退默认色",
              bad["mark_color"] == DEFAULT_MARK_COLOR
              and bad["chord_color"] == DEFAULT_CHORD_COLOR,
              f"{bad['mark_color']} {bad['chord_color']}")

        # v1 旧格式：note_grid 为 [col][row] 单字母字符串
        v1_path = tmp / "old_v1.ggp"
        v1_data = {
            "version": 1,
            "title": "Old",
            "created_at": "2020-01-01T00:00:00",
            "updated_at": "2020-01-01T00:00:00",
            "columns_per_line": 12,
            "keys": KEYS,
            "rows": 3,
            "note_grid": [["Y", "H", ""], ["", "J", "N"], []],
        }
        with open(v1_path, "w", encoding="utf-8") as f:
            json.dump(v1_data, f)
        data_v1 = load_ggp(v1_path)
        check("T8l v1 version 透传原始值", data_v1["version"] == 1,
              f"version={data_v1['version']}")
        check("T8m v1 columns_per_line 透传", data_v1["columns_per_line"] == 12,
              f"cpl={data_v1['columns_per_line']}")
        gv1 = NoteGrid()
        gv1.from_list(data_v1["note_grid"])
        check("T8n v1 单字母转换为全部主旋律",
              gv1.notes(0) == [("Y", False), ("H", False)]
              and gv1.notes(1) == [("J", False), ("N", False)],
              f"n0={gv1.notes(0)} n1={gv1.notes(1)}")

        # ---------------- T9: 导出 PNG（默认色 / 自定义色） ----------------
        window.export_png()   # 预览对话框 exec 已注入通过，information 已静默
        # 默认分层模式：导出到 outputs/<乐谱名>/<乐谱名>.png
        export_path = tmp / "outputs" / "SmokeTitle" / "SmokeTitle.png"
        check("T9a 默认导出到 outputs/乐谱名 子文件夹（分层）",
              export_path.exists(), str(export_path))
        check("T9b 导出文件大于0字节", os.path.getsize(export_path) > 0,
              f"size={os.path.getsize(export_path)}")
        direct_png = tmp / "direct.png"
        ok = export_png(str(direct_png), model, sheet.columns_per_line())
        check("T9c 默认色导出成功且非空",
              ok and direct_png.exists() and os.path.getsize(direct_png) > 0)
        custom_png = tmp / "custom.png"
        ok2 = export_png(str(custom_png), model, sheet.columns_per_line(),
                         mark_color="#123456", chord_color="#654321")
        check("T9d 自定义色导出成功且非空",
              ok2 and custom_png.exists() and os.path.getsize(custom_png) > 0)

        # ---------------- T10: 状态栏 / cursorMoved 不清脏 / 内容变化置脏 ----------------
        status = window.status_label.text()
        check("T10a 状态栏含列数/光标/每横排",
              "列数" in status and "光标" in status and "每横排" in status, status)
        check("T10b 状态栏数字正确",
              f"列数 {model.num_columns()}" in status
              and f"每横排 {sheet.columns_per_line()}" in status, status)
        # cursorMoved 只刷新光标显示，不清脏（T8 保存后 dirty=False）
        check("T10c 保存后脏标记为 False", window._dirty is False,
              f"dirty={window._dirty}")
        window.sheet.set_cursor(1)
        check("T10d cursorMoved 更新状态栏光标显示",
              "光标 1" in window.status_label.text(), window.status_label.text())
        check("T10e cursorMoved 不影响脏标记", window._dirty is False,
              f"dirty={window._dirty}")
        # 反向：模型内容变化才置脏
        window.sheet.apply_key("Y")
        check("T10f 内容变化后置脏", window._dirty is True, f"dirty={window._dirty}")

        # ---------------- T11: 像素级回归（无图例 + 单格填充 + 边框锐利，R9/R10） ----------------
        g = NoteGrid(1)
        g.place_key("Y", 0)   # 节拍0 只有 (0,0) 一个主旋律键，其余为空
        img = render_sheet_image(g, 4, mark_color="#FF0000", chord_color="#0000FF")
        block_y0 = EXPORT_MARGIN     # R9：无图例，块直接从上边距开始
        cy = block_y0 + EXPORT_MINI // 2
        cx0 = EXPORT_MARGIN + EXPORT_MINI // 2                     # 格 (0,0) 中心
        px_melody = img.pixelColor(cx0, cy)
        check("T11a 标记格中心为旋律色", px_melody.name() == "#ff0000",
              f"px={px_melody.name()}")
        cx1 = EXPORT_MARGIN + (EXPORT_MINI + EXPORT_MINI_GAP) + EXPORT_MINI // 2  # 格 (0,1) 中心
        px_neighbor = img.pixelColor(cx1, cy)
        check("T11b 相邻空格中心仍为白色", px_neighbor.name() == "#ffffff",
              f"px={px_neighbor.name()}")
        # 整幅图其余空格保持白色：采样 (0,2)(0,3)(0,4) 与第2行所有格中心
        others_white = True
        for c in range(2, 5):
            xc = EXPORT_MARGIN + c * (EXPORT_MINI + EXPORT_MINI_GAP) + EXPORT_MINI // 2
            if img.pixelColor(xc, cy).name() != "#ffffff":
                others_white = False
        for r in range(1, 3):
            yc = block_y0 + r * (EXPORT_MINI + EXPORT_MINI_GAP) + EXPORT_MINI // 2
            for c in range(5):
                xc = EXPORT_MARGIN + c * (EXPORT_MINI + EXPORT_MINI_GAP) + EXPORT_MINI // 2
                if img.pixelColor(xc, yc).name() != "#ffffff":
                    others_white = False
        check("T11c 其余空格全部保持白色", others_white)
        # 和弦格：节拍0 放 U 和弦 → 格 (0,1) 中心应为和弦色
        g2 = NoteGrid(1)
        g2.place_key("U", 0, chord=True)
        img2 = render_sheet_image(g2, 4, mark_color="#FF0000", chord_color="#0000FF")
        px_chord = img2.pixelColor(cx1, cy)
        check("T11d 和弦格中心为和弦色", px_chord.name() == "#0000ff",
              f"px={px_chord.name()}")
        # 同节拍同格不能又是旋律色：采样 (0,0) 应为白（该格无音符）
        px_chord_other = img2.pixelColor(cx0, cy)
        check("T11e 未标记格不受相邻和弦影响", px_chord_other.name() == "#ffffff",
              f"px={px_chord_other.name()}")
        # R9：无图例 —— 顶部边距区域（块上方 MARGIN 内）全白、无按键图形
        legend_clean = True
        for x in range(EXPORT_MARGIN, img.width() - EXPORT_MARGIN, 2):
            for y in range(0, block_y0, 2):
                if img.pixelColor(x, y).name() != "#ffffff":
                    legend_clean = False
        check("T11f 导出无顶部键位图例（上边距区域全白）", legend_clean)
        # R9：图片高度 = 2*MARGIN + 行数*BLOCK_H + 行间隙（不含图例高度）
        expect_h = EXPORT_MARGIN * 2 + EXPORT_BLOCK_H
        check("T11g 导出高度不含图例", img.height() == expect_h,
              f"h={img.height()} expect={expect_h}")
        # R10：小格边框为 #b8b8b8，且边框外无抗锯齿糊边（仍白）
        border_px = img.pixelColor(EXPORT_MARGIN, cy)                  # 格(0,0)左边框像素
        outside_px = img.pixelColor(EXPORT_MARGIN - 1, cy)             # 边框外一格
        check("T11h 小格边框为 #b8b8b8", border_px.name() == "#b8b8b8",
              f"px={border_px.name()}")
        check("T11i 边框外无抗锯齿糊边（仍白）", outside_px.name() == "#ffffff",
              f"px={outside_px.name()}")

        # ---------------- T12: 自适应（小格缩放限幅 / sizeHint 高度 / 绘制不抛异常） ----------------
        sheet2 = SheetWidget(NoteGrid(4), 4)
        h1 = sheet2.sizeHint().height()
        sheet2.set_model(NoteGrid(9))     # 9 节拍 → ceil(9/4)=3 横排
        h2 = sheet2.sizeHint().height()
        check("T12a sizeHint 高度随行数增长", h2 > h1, f"h1={h1} h2={h2}")
        sheet2.resize(400, 300)
        pix = sheet2.grab()
        mini_a = sheet2._mini
        check("T12b 窄屏绘制不抛异常", not pix.isNull())
        sheet2.resize(900, 500)
        pix2 = sheet2.grab()
        mini_b = sheet2._mini
        check("T12c 宽屏绘制不抛异常", not pix2.isNull())
        check("T12d 小格边长随宽度缩放且限幅 18–44",
              MINI_MIN <= mini_a <= MINI_MAX and MINI_MIN <= mini_b <= MINI_MAX
              and mini_b > mini_a,
              f"mini_a={mini_a} mini_b={mini_b}")
        # 每横排变化后小格边长立即按当前宽度重算（R3：旧守卫会挡住重算，宽度不变是"铺满"设计）
        sheet2.set_columns_per_line(8)
        expect2 = sheet2._compute_mini(sheet2.width())
        check("T12e 每横排变化后小格边长立即重算",
              sheet2._mini == expect2 and sheet2._last_width == sheet2.width(),
              f"mini={sheet2._mini} expect={expect2} last={sheet2._last_width}")

        # ---------------- T13: 滚动（内容高于可视区 → 滚动条出现且可滚到底） ----------------
        window.new_sheet()
        model = window._model
        window.cols_spin.setValue(8)          # 触发每横排重算路径
        window.cols_spin.setValue(4)          # cpl=4 → 40 节拍 = 10 横排
        for i in range(40):
            window.sheet.apply_key("Y")       # 光标节拍放 Y（R3 不前进）
            if i < 39:
                QTest.keyClick(sheet, Qt.Key_Right)   # 右箭头推进到下一节拍
        check("T13a 40 节拍 cpl=4 → 10 横排",
              sheet.columns_per_line() == 4 and len(sheet._lines()) == 10,
              f"cpl={sheet.columns_per_line()} lines={len(sheet._lines())}")
        QTest.qWait(30)
        sb = window.scroll.verticalScrollBar()
        check("T13b 内容高于可视区时垂直滚动条出现", sb.maximum() > 0,
              f"max={sb.maximum()}")
        # 滚到底 → 最后一块（line=9, col=3）中心进入可视区
        sb.setValue(sb.maximum())
        QTest.qWait(30)
        vp = window.scroll.viewport()
        block_h = sheet._block_h()
        last_cy = MARGIN_Y + 9 * (block_h + LINE_GAP) + block_h / 2.0   # 内容坐标
        vis_top = sb.value()
        vis_bottom = vis_top + vp.height()
        check("T13c 滚到底后最后一块中心可见",
              vis_top <= last_cy <= vis_bottom,
              f"cy={last_cy} vis=[{vis_top},{vis_bottom}] max={sb.maximum()}")
        # 空谱：不出现垂直滚动条且内容垂直居中
        window.new_sheet()
        QTest.qWait(30)
        sb2 = window.scroll.verticalScrollBar()
        check("T13d 空谱不出现垂直滚动条", sb2.maximum() == 0, f"max={sb2.maximum()}")
        check("T13e 内容矮于可视区时垂直居中", sheet._offset_y() > 0,
              f"oy={sheet._offset_y()}")

        # ---------------- T14: 键位面板标记 set_beat_marks（R8） ----------------
        window.new_sheet()
        model = window._model
        model.place_key("Y", 0)
        model.toggle_note(0, "I", True)       # 节拍0：Y 主旋律 + I 和弦
        model.place_key("U", 1)
        # 内容变化（place_at_cursor → modelChanged）→ _refresh_beat_marks
        window.sheet.place_at_cursor("O", False)   # 光标当前 0，节拍0 加 O 主旋律
        check("T14a 内容变化后标记刷新",
              "Y" in panel._melody_marks and "O" in panel._melody_marks
              and "U" not in panel._melody_marks,
              f"m={panel._melody_marks}")
        check("T14b 和弦键同步到键位面板", "I" in panel._chord_marks,
              f"c={panel._chord_marks}")
        pix_panel = panel.grab()
        check("T14c 带标记重绘不抛异常", not pix_panel.isNull())
        # 光标移动 → _refresh_beat_marks → 标记跟随变化
        window.sheet.set_cursor(1)
        check("T14d 光标移动后标记跟随变化",
              panel._melody_marks == {"U"} and panel._chord_marks == set(),
              f"m={panel._melody_marks} c={panel._chord_marks}")
        # 独立面板直接调用 set_beat_marks（含与"当前选中键"J 叠加）重绘不异常
        panel2 = KeyPanel()
        panel2.resize(360, 200)
        panel2.set_beat_marks({"Y", "J"}, {"I", ","}, QColor("#FF0000"), QColor("#0000FF"))
        pix2 = panel2.grab()
        check("T14e 独立面板 set_beat_marks 后重绘不抛异常", not pix2.isNull())

        # ---------------- T15: 自动滚动（R5：内容/光标变化后滚动到光标块可见，新建复位） ----------------
        window.new_sheet()
        model = window._model
        window.cols_spin.setValue(8)
        window.cols_spin.setValue(4)          # cpl=4 → 40 节拍 = 10 横排
        for i in range(40):
            window.sheet.apply_key("Y")
            if i < 39:
                QTest.keyClick(sheet, Qt.Key_Right)
        QTest.qWait(50)
        sb = window.scroll.verticalScrollBar()
        vp = window.scroll.viewport()
        block_h = sheet._block_h()
        check("T15a 40 节拍后滚动条出现", sb.maximum() > 0, f"max={sb.maximum()}")
        # 光标在末尾（beat39, line9）→ cursorMoved/modelChanged 已自动滚动到底
        last_cy = MARGIN_Y + 9 * (block_h + LINE_GAP) + block_h / 2.0
        vis_top = sb.value()
        vis_bottom = vis_top + vp.height()
        check("T15b 光标移末尾后自动滚动到底（末块可见）",
              vis_top <= last_cy <= vis_bottom,
              f"cy={last_cy} vis=[{vis_top},{vis_bottom}] max={sb.maximum()}")
        # 光标回到顶部 → 自动滚回顶部
        window.sheet.set_cursor(0)
        QTest.qWait(50)
        check("T15c set_cursor(0) 后自动滚回顶部", sb.value() == 0,
              f"value={sb.value()}")
        # 光标移到中部某行 → 该行块可见
        window.sheet.set_cursor(20)           # line 5
        QTest.qWait(50)
        mid_cy = MARGIN_Y + 5 * (block_h + LINE_GAP) + block_h / 2.0
        vis_top = sb.value()
        vis_bottom = vis_top + vp.height()
        check("T15d set_cursor(20) 后中部行块可见",
              vis_top <= mid_cy <= vis_bottom,
              f"cy={mid_cy} vis=[{vis_top},{vis_bottom}]")
        # 新建 → 滚动条复位（空谱无滚动）
        window.new_sheet()
        QTest.qWait(30)
        check("T15e 新建后滚动条复位", sb.maximum() == 0 and sb.value() == 0,
              f"max={sb.maximum()} value={sb.value()}")

        # ---------------- T16: 标记错位根治回归（像素级四路输入 + 布局稳定性 + 面板一致性） ----------------
        # a) 布局稳定性：sheet 宽度必须等于滚动区可视区宽度（showEvent/自驱动同步修复后）
        window.new_sheet()
        settle_layout(window)
        check("T16a sheet 宽度等于滚动区可视区宽度（无初始缺口）",
              sheet.width() == window.scroll.viewport().width(),
              f"sheet.w={sheet.width()} vp={window.scroll.viewport().width()} "
              f"mini={sheet._mini}")

        # b/c) 四路输入各放单个 U 到节拍0：逐格像素断言（U→(0,1) 标记色、邻居白）
        #      + 输入前后宽度稳定（不再有首次交互跳变重排）
        def t16_place(label: str, fn, chord: bool = False):
            window.new_sheet()
            model = window._model
            fn(model)
            QTest.qWait(10)
            notes = model.notes(0)
            expect = (sheet.chord_color().name() if chord
                      else sheet.mark_color().name())
            img = sheet.grab().toImage()
            mini = sheet._mini

            def cxy(r: int, c: int):
                return (int(sheet._offset_x() + MARGIN_X
                            + c * (mini + MINI_GAP) + mini / 2.0),
                        int(sheet._offset_y() + MARGIN_Y
                            + r * (mini + MINI_GAP) + mini / 2.0))

            px = img.pixelColor(*cxy(0, 1)).name()
            nbr = (img.pixelColor(*cxy(0, 0)).name(),
                   img.pixelColor(*cxy(0, 2)).name(),
                   img.pixelColor(*cxy(1, 1)).name())
            check(f"T16b {label}：格(0,1) 为标记色且相邻格仍白",
                  notes == [("U", chord)] and px == expect
                  and nbr == ("#ffffff", "#ffffff", "#ffffff"),
                  f"notes={notes} px={px} 邻居={nbr} 期望={expect}")
            check(f"T16c {label}：输入后宽度稳定等于可视区",
                  sheet.width() == window.scroll.viewport().width(),
                  f"sheet.w={sheet.width()} vp={window.scroll.viewport().width()}")

        # A) 直接写 model（无信号）
        t16_place("A) model 直接写",
                  lambda m: (m.set_note(0, "U", False, True), sheet.update()))
        # B) place_at_cursor（首次触发同步的路径）
        t16_place("B) place_at_cursor",
                  lambda m: sheet.place_at_cursor("U", False))
        # C) 键位面板左键
        t16_place("C) 面板左键 U",
                  lambda m: QTest.mouseClick(panel, Qt.LeftButton,
                                             pos=panel_key_center(panel, "U")))
        # D) 键盘 U
        t16_place("D) 键盘 U",
                  lambda m: QTest.keyClick(sheet, Qt.Key_U))

        # d) 窗口 resize 后点击：命中 + 像素一致
        window.new_sheet()
        model = window._model
        window.resize(1100, 720)
        settle_layout(window)
        QTest.mouseClick(sheet, Qt.LeftButton,
                         pos=sheet_cell_center(sheet, 0, 2))
        QTest.qWait(10)
        img = sheet.grab().toImage()
        mini = sheet._mini
        cx = int(sheet._offset_x() + MARGIN_X + 2 * (mini + MINI_GAP) + mini / 2.0)
        cy = int(sheet._offset_y() + MARGIN_Y + 0 * (mini + MINI_GAP) + mini / 2.0)
        px = img.pixelColor(cx, cy).name()
        check("T16d resize 后点击格(0,2)：命中 I 且像素为标记色",
              model.notes(0) == [("I", False)] and px == sheet.mark_color().name(),
              f"notes={model.notes(0)} px={px}")

        # e) resize 后立即点击（未等布局稳定）：命中仍正确（点击前 _sync_mini 起效）
        window.new_sheet()
        model = window._model
        window.resize(900, 700)
        QTest.mouseClick(sheet, Qt.LeftButton,
                         pos=sheet_cell_center(sheet, 1, 1))
        QTest.qWait(30)
        check("T16e resize 后未settle立即点击格(1,1)：命中 J",
              model.notes(0) == [("J", False)],
              f"notes={model.notes(0)}")

        # f) 面板画笔泄漏回归（核心）：节拍0=U、当前键=Y →
        #    U 键淡红填充（标记键自身）、Y 键蓝底当前键、右侧 I 键无泄漏红填充
        window.new_sheet()
        model = window._model
        sheet.place_at_cursor("U", False)
        QTest.mouseClick(sheet, Qt.LeftButton,
                         pos=sheet_cell_center(sheet, 0, 0))   # 当前键 → Y（节拍0 增 Y）
        QTest.qWait(10)
        pp = panel_pixels(panel)
        mel_fill = QColor(sheet.mark_color()).lighter(175).name()
        check("T16f 面板：U 键淡红填充、Y 键蓝底当前键、I 键无泄漏红填充",
              pp["U"] == mel_fill and pp["Y"] == COLOR_CURRENT_BG.name()
              and pp["I"] == COLOR_SHARP_BG.name(),
              f"U={pp['U']} Y={pp['Y']} I={pp['I']} 期望U={mel_fill}")

        # g) 改每横排后点击不偏格
        window.new_sheet()
        model = window._model
        window.cols_spin.setValue(8)
        settle_layout(window)
        QTest.mouseClick(sheet, Qt.LeftButton,
                         pos=sheet_cell_center(sheet, 0, 2))
        check("T16g 改每横排8后点击格(0,2)：命中 I",
              model.notes(0) == [("I", False)],
              f"notes={model.notes(0)}")
        window.cols_spin.setValue(4)
        settle_layout(window)

        # h) 面板右键放和弦 U：块0 格(0,1) 和弦色；U 键淡蓝填充、I 键无泄漏蓝填充
        window.new_sheet()
        model = window._model
        QTest.mouseClick(panel, Qt.RightButton,
                         pos=panel_key_center(panel, "U"))
        QTest.qWait(10)
        img = sheet.grab().toImage()
        mini = sheet._mini
        cx = int(sheet._offset_x() + MARGIN_X + 1 * (mini + MINI_GAP) + mini / 2.0)
        cy = int(sheet._offset_y() + MARGIN_Y + 0 * (mini + MINI_GAP) + mini / 2.0)
        px = img.pixelColor(cx, cy).name()
        pp = panel_pixels(panel)
        check("T16h 面板右键 U：块0 格(0,1) 为和弦色",
              model.is_chord(0, "U") and px == sheet.chord_color().name(),
              f"notes={model.notes(0)} px={px}")
        # 右键面板 U → place_at_cursor 发 keySelected → U 成为当前键（蓝底），
        # 但标记靠右上角角标区分：断言 I 键无泄漏蓝填充、U 键右上角有和弦色角标
        check("T16i 面板：U 键当前键蓝底、I 键无泄漏蓝填充",
              pp["U"] == COLOR_CURRENT_BG.name() and pp["I"] == COLOR_SHARP_BG.name(),
              f"U={pp['U']} I={pp['I']} 期望U={COLOR_CURRENT_BG.name()}")
        img_p = panel.grab().toImage()
        idx_u = PANEL_KEYS.index("U")
        r_u, c_u = idx_u // PANEL_COLS, idx_u % PANEL_COLS
        kw, kh = panel._key_w, panel._key_h
        ox = (panel.width() - PANEL_COLS * kw - (PANEL_COLS - 1) * PANEL_GAP) / 2.0
        oy = (panel.height() - PANEL_ROWS * kh - (PANEL_ROWS - 1) * PANEL_GAP) / 2.0
        ux = int(ox + c_u * (kw + PANEL_GAP))
        uy = int(oy + r_u * (kh + PANEL_GAP))
        dot_color = QColor(sheet.chord_color()).name()
        dot_found = any(
            img_p.pixelColor(x, y).name() == dot_color
            for x in range(ux + int(kw) // 2, min(img_p.width(), ux + int(kw)))
            for y in range(uy, min(img_p.height(), uy + int(kh) // 3)))
        check("T16j 面板：U 键右上角有和弦色角标（当前键叠加标记仍可区分）", dot_found)

        # ---------------- T17: R13 自动跳转（距本拍首键计时） ----------------
        window.new_sheet()
        sheet = window.sheet
        panel = window.key_panel
        model = window._model

        # a) 默认关闭 → 连按不跳转（保持 R3 行为）
        sheet.apply_key("Y")
        sheet.apply_key("U")
        check("T17a 开关默认关：连续按键归同一拍不前进",
              model.num_columns() == 1
              and "Y" in model.melody_keys(0) and "U" in model.melody_keys(0),
              f"cols={model.num_columns()} notes0={model.notes(0)}")

        # b) 开启 + 大阈值：阈值内连按键归同一拍
        sheet.set_auto_advance(True)
        sheet.set_advance_threshold(5000)
        sheet.apply_key("I")
        sheet.apply_key("O")
        sheet.apply_key("P")
        check("T17b 开启+阈值内：连按键归同一拍不前进",
              sheet.cursor() == 0 and model.num_columns() == 1
              and "I" in model.melody_keys(0) and "O" in model.melody_keys(0)
              and "P" in model.melody_keys(0),
              f"cursor={sheet.cursor()} cols={model.num_columns()} notes0={model.notes(0)}")

        # c) 超阈值 → 自动前进到下一拍（末尾自动追加空白拍）
        sheet.set_advance_threshold(50)
        QTest.qWait(150)   # 距上一拍最后一次按键已超 50ms
        sheet.apply_key("H")
        QTest.qWait(150)
        sheet.apply_key("J")
        check("T17c 超阈值按键自动前进到下一拍（末尾追加空白拍）",
              model.num_columns() == 3 and sheet.cursor() == 2
              and "H" in model.melody_keys(1) and "J" in model.melody_keys(2),
              f"cols={model.num_columns()} cursor={sheet.cursor()} "
              f"n1={model.notes(1)} n2={model.notes(2)}")

        # d) 键位面板点击同样受自动跳转控制（阈值内归同拍、超阈值换拍）
        sheet.set_cursor(2)                 # 手动回拍2（重置计时起点）
        QTest.mouseClick(panel, Qt.LeftButton, pos=panel_key_center(panel, "K"))
        QTest.qWait(150)
        QTest.mouseClick(panel, Qt.LeftButton, pos=panel_key_center(panel, "L"))
        check("T17d 面板点击：阈值内归同拍、超阈值换拍",
              sheet.cursor() == 3 and "K" in model.melody_keys(2)
              and "L" in model.melody_keys(3),
              f"cursor={sheet.cursor()} n2={model.notes(2)} n3={model.notes(3)}")

        # e) 关闭开关重置计时起点（重开后不残留旧计时）
        sheet.set_auto_advance(False)
        check("T17e 关闭开关后计时起点重置", sheet._beat_start_time is None)

        # f) 手动移动光标也重置计时起点
        sheet.set_auto_advance(True)
        sheet.set_cursor(0)
        sheet.apply_key("Y")                 # beat0 已标记，起点已设
        started = sheet._beat_start_time
        sheet.set_cursor(1)
        check("T17f 手动移动光标后计时起点重置",
              started is not None and sheet._beat_start_time is None)
        sheet.set_auto_advance(False)

        # ---------------- T18: R14 清空整拍 + 导出标题 ----------------
        window.new_sheet()
        sheet = window.sheet
        model = window._model

        # a) Backspace 清空高亮拍全部音符，保留空拍位置（不 trim、不连带删空拍）
        sheet.apply_key("Y")
        sheet.apply_key("U")
        sheet.backspace()
        check("T18a Backspace 清空高亮拍全部音符（保留空拍位置）",
              model.notes(0) == [] and model.num_columns() == 1,
              f"notes0={model.notes(0)} cols={model.num_columns()}")

        # b) Backspace 清空高亮拍的和弦标记（与主旋律一并清空）
        sheet.place_at_cursor("P", True)     # 当前节拍 P 和弦
        check("T18b-前置 P 已作为和弦放置", model.is_chord(0, "P"))
        sheet.backspace()
        check("T18b Backspace 清空高亮拍全部音符（含和弦）",
              not model.has_note(0, "P") and model.notes(0) == [],
              f"notes0={model.notes(0)}")

        # c) 导出：有标题时图片更高且顶部出现乐谱名文字
        g = NoteGrid()
        g.toggle_note(0, "Y", False)
        img_none = render_sheet_image(g, 4)
        img_title = render_sheet_image(g, 4, title="测试乐谱")
        text_found = any(
            img_title.pixelColor(x, y).name() != "#ffffff"
            for x in range(0, img_title.width(), 8)
            for y in range(EXPORT_MARGIN, EXPORT_MARGIN + EXPORT_TITLE_H, 4))
        check("T18c 有标题导出：图片增高 TITLE_H 且顶部绘制乐谱名",
              img_title.height() == img_none.height() + EXPORT_TITLE_H and text_found,
              f"h_none={img_none.height()} h_title={img_title.height()}")

        # d) 导出：空白标题按无标题处理（高度不增加）
        img_blank = render_sheet_image(g, 4, title="   ")
        check("T18d 空白标题不增加图片高度",
              img_blank.height() == img_none.height(),
              f"h_none={img_none.height()} h_blank={img_blank.height()}")

        # ---------------- T19: Del 删除整拍（列移除，不连带空拍） ----------------
        window.new_sheet()
        sheet = window.sheet
        model = window._model

        # a) Del 删除高亮拍：后续节拍整体左移
        sheet.apply_key("Y")                       # beat0 Y，光标0
        QTest.keyClick(sheet, Qt.Key_Right)        # 光标1
        sheet.apply_key("U")                       # beat1 U
        QTest.keyClick(sheet, Qt.Key_Right)        # 光标2
        sheet.apply_key("I")                       # beat2 I
        sheet.set_cursor(1)
        QTest.keyClick(sheet, Qt.Key_Delete)       # 删除 beat1
        check("T19a Del 删除高亮拍：列移除、后续左移、光标停原位",
              model.notes(0) == [("Y", False)] and model.notes(1) == [("I", False)]
              and sheet.cursor() == 1,
              f"notes={[model.notes(i) for i in range(model.num_columns())]} "
              f"cursor={sheet.cursor()}")

        # b) Del 目标拍前面有空拍：空拍不受连带（只删目标列）
        window.new_sheet()
        model = window._model
        model.ensure_columns(2)                    # beat0 空、beat1 待填
        sheet.set_cursor(1)
        sheet.apply_key("Y")                       # beat1 Y，光标1
        QTest.keyClick(sheet, Qt.Key_Delete)       # 删除 beat1（其前 beat0 为空拍）
        check("T19b Del 删拍时前面的空拍不受连带",
              model.num_columns() == 1 and model.is_beat_empty(0)
              and sheet.cursor() == 0,
              f"cols={model.num_columns()} "
              f"notes={[model.notes(i) for i in range(model.num_columns())]} "
              f"cursor={sheet.cursor()}")

        # c) Backspace 清空后尾部空拍保留（不 trim）
        window.new_sheet()
        model = window._model
        sheet.apply_key("Y")                       # beat0 Y
        QTest.keyClick(sheet, Qt.Key_Right)        # 末尾右移 → 追加 beat1（空）
        sheet.set_cursor(0)
        sheet.backspace()                          # 清空 beat0
        check("T19c Backspace 清空后尾部空拍保留（不连带删空拍）",
              model.num_columns() == 2 and model.is_beat_empty(0)
              and model.is_beat_empty(1),
              f"cols={model.num_columns()} notes={[model.notes(i) for i in range(model.num_columns())]}")

        # d) 仅剩 1 列时 Del：清空内容保留 1 列，不越界
        window.new_sheet()
        model = window._model
        sheet.apply_key("Y")
        QTest.keyClick(sheet, Qt.Key_Delete)
        check("T19d 仅剩 1 列时 Del：清空内容保留 1 列",
              model.num_columns() == 1 and model.is_beat_empty(0)
              and sheet.cursor() == 0,
              f"cols={model.num_columns()} cursor={sheet.cursor()}")

        # ---------------- T20: 分页导出（预览行列 + 文件名/显示名分离） ----------------
        # a) 页数计算（13列→4行→每页3行→2页；25列→7行→3页）
        check("T20a 页数计算：0列/整除/有余数均正确",
              num_pages(0, 4, 3) == 1 and num_pages(4, 4, 3) == 1
              and num_pages(12, 4, 3) == 1 and num_pages(13, 4, 3) == 2
              and num_pages(16, 4, 3) == 2 and num_pages(25, 4, 3) == 3,
              f"pages={[num_pages(n, 4, 3) for n in (0, 4, 12, 13, 16, 25)]}")

        # b) 分页渲染内容隔离：5 列每列均 Y、每页 1 行×4 列 → 第0页含 beat0-3、第1页仅 beat4
        g5 = NoteGrid(5)
        for i in range(5):
            g5.toggle_note(i, "Y", False)
        img0 = render_page_image(g5, 4, 1, 0)
        img1 = render_page_image(g5, 4, 1, 1)
        mark_name = QColor(DEFAULT_MARK_COLOR).name()
        cy = EXPORT_MARGIN + EXPORT_MINI // 2
        b0 = EXPORT_MARGIN + EXPORT_MINI // 2                                  # 第0块 (0,0)
        b1 = EXPORT_MARGIN + (EXPORT_BLOCK_W + EXPORT_BLOCK_GAP) + EXPORT_MINI // 2   # 第1块 (0,0)
        check("T20b 分页渲染内容隔离（p0 含 beat0-3、p1 仅 beat4）",
              img0.pixelColor(b0, cy).name() == mark_name
              and img0.pixelColor(b1, cy).name() == mark_name
              and img1.pixelColor(b0, cy).name() == mark_name
              and img1.pixelColor(b1, cy).name() == "#ffffff",
              f"p0块0={img0.pixelColor(b0, cy).name()} "
              f"p0块1={img0.pixelColor(b1, cy).name()} "
              f"p1块0={img1.pixelColor(b0, cy).name()} "
              f"p1块1={img1.pixelColor(b1, cy).name()}")

        # c) 多页导出文件名 XXX_1 / XXX_2
        ok_c, pages_c = export_pages(str(tmp / "song_multi"), g5, 4, 1)
        check("T20c 多页导出 _1/_2 命名且全部成功",
              ok_c and pages_c == 2
              and (tmp / "song_multi_1.png").exists()
              and (tmp / "song_multi_2.png").exists(),
              f"ok={ok_c} pages={pages_c}")

        # d) 单页导出不带序号
        ok_d, pages_d = export_pages(str(tmp / "song_single"), g5, 4, 5)
        check("T20d 单页导出不带序号",
              ok_d and pages_d == 1
              and (tmp / "song_single.png").exists()
              and not (tmp / "song_single_1.png").exists(),
              f"ok={ok_d} pages={pages_d}")

        # e) 分页时显示名：draw_title=False 不绘制（高度不含标题区）
        base_h = EXPORT_MARGIN * 2 + 2 * EXPORT_BLOCK_H + (2 - 1) * EXPORT_LINE_GAP
        ok_e, _ = export_pages(str(tmp / "no_title"), g5, 4, 2,
                               title="SomeName", draw_title=False)
        img_e = QImage(str(tmp / "no_title.png"))
        ok_f, _ = export_pages(str(tmp / "with_title"), g5, 4, 2,
                               title="SomeName", draw_title=True)
        img_f = QImage(str(tmp / "with_title.png"))
        check("T20e 分页显示名：draw_title=False 不加标题",
              ok_e and img_e.height() == base_h,
              f"h={img_e.height()} expect={base_h}")
        check("T20f 分页显示名：draw_title=True 每页顶部绘制",
              ok_f and img_f.height() == base_h + EXPORT_TITLE_H,
              f"h={img_f.height()} expect={base_h + EXPORT_TITLE_H}")

        # g) 导出预览对话框：文件名/显示名分离、留空默认乐谱名、行列联动
        dlg_obj = dlg.ExportDialog(NoteGrid(5), 4, default_title="MySong")
        check("T20g 预览对话框：显示名留空默认乐谱名",
              dlg_obj.display_name() == "MySong" and dlg_obj.file_name() == "MySong")
        dlg_obj.file_edit.setText("CustomFile")
        check("T20h 文件名与显示名独立",
              dlg_obj.file_name() == "CustomFile" and dlg_obj.display_name() == "MySong")
        dlg_obj.display_edit.setText("DisplayName")
        check("T20i 显示名独立填写生效",
              dlg_obj.display_name() == "DisplayName" and dlg_obj.file_name() == "CustomFile")
        check("T20j 预览对话框默认每页 3 行 × 当前每横排列",
              dlg_obj.rows_per_page() == 3 and dlg_obj.columns_per_line() == 4)
        check("T20k 预览页数提示正确（5列→2行→1页）",
              "共 1 页" in dlg_obj.pages_label.text(), dlg_obj.pages_label.text())
        dlg_obj.close()

        # ---------------- T21: 导出预览自适应缩放 ----------------
        pdlg = dlg.ExportDialog(NoteGrid(9), 4, default_title="Pre")
        check("T21a 预览生成原图并按视口缩放显示",
              pdlg._full_pixmap is not None and not pdlg._full_pixmap.isNull()
              and pdlg.preview_label.pixmap() is not None
              and not pdlg.preview_label.pixmap().isNull())
        w0 = pdlg._full_pixmap.width()
        h0 = pdlg._full_pixmap.height()
        pdlg.rows_spin.setValue(1)     # 每页 3 行 → 1 行：预览原图变矮
        h1 = pdlg._full_pixmap.height()
        check("T21b 每页行数调小后预览原图变矮（自适应刷新）",
              h1 < h0 and pdlg._full_pixmap.width() == w0,
              f"h0={h0} h1={h1} w={pdlg._full_pixmap.width()}")
        pdlg.cols_spin.setValue(8)     # 每页 4 列 → 8 列：预览原图变宽
        w2 = pdlg._full_pixmap.width()
        check("T21c 每页列数调大后预览原图变宽（自适应刷新）",
              w2 > w0 and pdlg._full_pixmap.height() == h1,
              f"w0={w0} w2={w2} h={pdlg._full_pixmap.height()}")
        pdlg.resize(900, 700)          # 窗口缩放 → 视口变化 → 重新等比缩放
        QTest.qWait(20)
        check("T21d 窗口缩放后预览仍显示有效缩放图",
              pdlg.preview_label.pixmap() is not None
              and not pdlg.preview_label.pixmap().isNull())
        pdlg.close()

        # ---------------- T22: 每页预览（翻页）+ 行列放开 ----------------
        g25 = NoteGrid(25)
        for i in range(25):
            g25.toggle_note(i, "Y", False)
        pd2 = dlg.ExportDialog(g25, 4, default_title="Pages")
        check("T22a 行列限制放开（每页行 1-20、列 4-30）",
              pd2.rows_spin.maximum() == 20 and pd2.cols_spin.maximum() == 30)
        # 25 列、每页 3 行×4 列 → 7 行 → 3 页
        check("T22b 多页时页码范围=总页数（3页）",
              pd2.page_spin.maximum() == 3 and "共 3 页" in pd2.pages_label.text(),
              f"max={pd2.page_spin.maximum()} label={pd2.pages_label.text()}")
        pd2.page_spin.setValue(2)     # 翻到第 2 页
        check("T22c 翻页后预览刷新为下一页",
              pd2.page_spin.value() == 2
              and pd2._full_pixmap is not None and not pd2._full_pixmap.isNull())
        pd2.rows_spin.setValue(20)    # 7 行 ≤ 每页 20 行 → 合并为 1 页，页码夹回
        check("T22d 行列变化后页码自动夹取到有效范围",
              pd2.page_spin.maximum() == 1 and pd2.page_spin.value() == 1
              and "共 1 页" in pd2.pages_label.text(),
              f"max={pd2.page_spin.maximum()} val={pd2.page_spin.value()} "
              f"label={pd2.pages_label.text()}")
        pd2.close()

        # ---------------- T23: 输出目录（分层/平铺）+ 导出界面颜色 ----------------
        od = dlg.ExportDialog(NoteGrid(2), 4, default_title="SongX",
                              default_dir=str(tmp / "out"),
                              mark_color="#FF0000", chord_color="#0000FF")
        pb = od.output_path_base()
        check("T23a 默认分层：导出到 输出目录/乐谱名/ 子文件夹",
              od.layered() and pb == str(tmp / "out" / "SongX" / "SongX")
              and (tmp / "out" / "SongX").is_dir(),
              f"layered={od.layered()} pb={pb}")
        ok_t, pages_t = export_pages(pb, od._grid, 4, 1,
                                     mark_color=od.mark_color(),
                                     chord_color=od.chord_color())
        check("T23b 分层目录导出成功（单页文件在子文件夹内）",
              ok_t and pages_t == 1 and (tmp / "out" / "SongX" / "SongX.png").exists())
        od.flat_radio.setChecked(True)
        pb2 = od.output_path_base()
        ok_f, _ = export_pages(pb2, od._grid, 4, 1)
        check("T23c 平铺模式：直接导出到输出目录",
              not od.layered() and pb2 == str(tmp / "out" / "SongX")
              and (tmp / "out" / "SongX.png").exists(),
              f"pb2={pb2}")
        check("T23d 导出界面颜色传入与读取",
              od.mark_color() == "#FF0000" and od.chord_color() == "#0000FF")
        od._mark_color = "#123456"
        od._sync_color_buttons()
        check("T23e 修改颜色后按钮着色与取值同步",
              od.mark_color() == "#123456"
              and "#123456" in od.mark_btn.styleSheet(),
              od.mark_btn.styleSheet())
        od.close()

        # ---------------- T24: 分栏限制 + 按键区显隐 ----------------
        check("T24a 分栏不可拖到隐藏（childrenCollapsible=False）",
              window.splitter.childrenCollapsible() is False)
        check("T24b 键位面板高度限制（最小160、最大520）",
              window.key_panel.minimumHeight() == 160
              and window.key_panel.maximumHeight() == 520)
        check("T24c 格子谱区最小高度限制", window.scroll.minimumHeight() == 160)
        check("T24d 按键区默认显示（侧边栏勾选开）",
              window.show_panel_check.isChecked() and not window.key_panel.isHidden())
        window.show_panel_check.setChecked(False)
        QTest.qWait(20)
        check("T24e 关闭勾选隐藏键位面板",
              window.show_panel_check.isChecked() is False and window.key_panel.isHidden())
        window.show_panel_check.setChecked(True)
        QTest.qWait(20)
        check("T24f 重新勾选显示键位面板",
              window.show_panel_check.isChecked() and not window.key_panel.isHidden())

        # ---------------- T25: 显示出来的空块位可点击添加 + 完全空白不创建 + 点击不自动滚动 ----------------
        window.new_sheet()
        model = window._model
        model.toggle_note(0, "Y", False)
        model.toggle_note(1, "U", False)
        # a) 点击"显示出来"的空节拍块位（beat2 未创建）→ 直接添加标记并创建节拍
        pos_empty = sheet_cell_center(sheet, 0, 0, block=2, line=0)
        QTest.mouseClick(sheet, Qt.LeftButton, pos=pos_empty)
        check("T25a 点击显示出来的空节拍块可直接添加标记",
              model.num_columns() == 3 and model.has_note(2, "Y"),
              f"cols={model.num_columns()} notes2={model.notes(2)}")
        # b) 点击块与块之间的完全空白 → 不创建
        gap_x = int(sheet._offset_x() + MARGIN_X + sheet._block_w() + BLOCK_GAP / 2.0)
        gap_y = int(sheet._offset_y() + MARGIN_Y + sheet._mini)
        QTest.mouseClick(sheet, Qt.LeftButton, pos=QPoint(gap_x, gap_y))
        check("T25b 点击块间空隙不创建",
              model.num_columns() == 3, f"cols={model.num_columns()}")

        # c) 造 24 列（6 行）：点击视口外最后一行块，滚动条不应被自动移动
        window.new_sheet()
        model = window._model
        for i in range(24):
            model.toggle_note(i, "Y", False)
        settle_layout(window)
        bar = window.scroll.verticalScrollBar()
        bar.setValue(0)
        QTest.qWait(20)
        pos_last = sheet_cell_center(sheet, 0, 0, block=0, line=5)
        QTest.mouseClick(sheet, Qt.LeftButton, pos=pos_last)
        check("T25c 点击格子不自动滚动（视图不乱跳）",
              bar.value() == 0, f"bar={bar.value()}")

        # ---------------- T26: 键面显示模式（字母/按键/音调/空白）+ 菜单侧边栏 ----------------
        from key_panel import MODE_BLANK, MODE_KEY, MODE_LETTER, MODE_TONE
        from PySide6.QtWidgets import QRadioButton as _QRadioButton
        panel.set_display_mode(MODE_KEY)
        check("T26a 按键模式显示编号（Y=1,U=2,K=1,.=7,/ 循环到 1）",
              panel._key_label("Y") == "1" and panel._key_label("U") == "2"
              and panel._key_label("K") == "1" and panel._key_label(".") == "7"
              and panel._key_label("/") == "1")
        panel.set_display_mode(MODE_TONE)
        check("T26b 音调模式按数字映射（1→C、2→D、7→B）",
              panel._key_label("Y") == "C" and panel._key_label("U") == "D"
              and panel._key_label(".") == "B")
        panel.set_display_mode(MODE_BLANK)
        check("T26c 空白模式不显示文字", panel._key_label("Y") == "")
        panel.set_display_mode(MODE_LETTER)
        check("T26d 字母模式显示键字母", panel._key_label("Y") == "Y"
              and panel._key_label(";") == ";")
        # 拉大键位面板（独立实例，不受分栏布局约束）：文字/图形放满键居中不裁剪
        p2 = KeyPanel()
        p2.set_display_mode(MODE_LETTER)
        p2.resize(920, 340)
        p2.show()
        QTest.qWait(10)
        img = p2.grab().toImage()
        dark = any(
            img.pixelColor(x, y).name() == "#333333"
            for x in range(0, img.width(), 4)
            for y in range(0, img.height(), 4))
        check("T26e 拉大键位面板后文字完整显示在键内（不裁剪）", dark)
        p2.close()
        # 菜单：点按钮打开侧边栏，侧边栏切换显示模式
        window.key_panel_btn.click()
        QTest.qWait(10)
        check("T26f 按键区按钮打开设置侧边栏", window.key_dock.isVisible())
        tone_rb = next(rb for rb in window.key_dock.findChildren(_QRadioButton)
                       if rb.text() == "音调")
        tone_rb.setChecked(True)
        check("T26g 侧边栏切换音调模式并同步面板",
              panel.display_mode() == MODE_TONE
              and window.key_panel.display_mode() == MODE_TONE)
        letter_rb = next(rb for rb in window.key_dock.findChildren(_QRadioButton)
                         if rb.text() == "字母")
        letter_rb.setChecked(True)
        check("T26h 侧边栏切回字母模式",
              panel.display_mode() == MODE_LETTER)
        window.key_panel_btn.click()   # 再点收起
        QTest.qWait(10)
        check("T26i 再次点击收起侧边栏", not window.key_dock.isVisible())

        # ---------------- T27: 保存目录=应用文件夹/乐谱 + 打开输出文件夹 ----------------
        import file_io as fio_mod
        check("T27a 保存乐谱默认目录=应用文件夹下的 sheets 子目录",
              fio_mod.default_data_dir()
              == pathlib.Path(fio_mod.__file__).resolve().parent / "sheets")
        window.open_output_folder()
        check("T27b 打开输出文件夹调用系统打开",
              mw.QDesktopServices.openUrl.called)
        if mw.QDesktopServices.openUrl.called:
            url = mw.QDesktopServices.openUrl.call_args[0][0]
            local = url.toLocalFile().replace("\\", "/")
            check("T27c 打开的是应用目录下 outputs",
                  local.endswith("/outputs"), local)
        else:
            check("T27c 打开的是应用目录下 outputs", False, "openUrl 未调用")

        # ---------------- T28: 按键模式高音点（1..7 循环 + 八度轮次） ----------------
        panel.set_display_mode(MODE_KEY)
        check("T28a 八度轮次：第一轮 0、第二轮 1、第三轮 2",
              panel._key_octave("Y") == 0 and panel._key_octave("K") == 1
              and panel._key_octave(".") == 1 and panel._key_octave("/") == 2)
        check("T28b 编号 1..7 循环（第二轮 K=1、第三轮 /=1）",
              panel._key_label("K") == "1" and panel._key_label("/") == "1")
        p3 = KeyPanel()
        p3.set_display_mode(MODE_KEY)
        p3.resize(520, 220)
        p3.show()
        QTest.qWait(10)
        img3 = p3.grab().toImage()
        kw3, kh3 = p3._key_w, p3._key_h
        cw3 = PANEL_COLS * kw3 + (PANEL_COLS - 1) * PANEL_GAP
        ch3 = PANEL_ROWS * kh3 + (PANEL_ROWS - 1) * PANEL_GAP
        ox3 = (p3.width() - cw3) / 2.0
        oy3 = (p3.height() - ch3) / 2.0
        i_slash = PANEL_KEYS.index("/")
        rs, cs = i_slash // PANEL_COLS, i_slash % PANEL_COLS
        sx = int(ox3 + cs * (kw3 + PANEL_GAP) + kw3 / 2)
        sy = int(oy3 + rs * (kh3 + PANEL_GAP) + kh3 * 0.12)
        dots_slash = sum(
            1 for xx in range(sx - 8, sx + 9)
            for yy in range(sy - 10, sy + 10)
            if img3.pixelColor(xx, yy).name() == "#333333")
        i_y = PANEL_KEYS.index("Y")
        ry, cyy = i_y // PANEL_COLS, i_y % PANEL_COLS
        yx = int(ox3 + cyy * (kw3 + PANEL_GAP) + kw3 / 2)
        y_top = int(oy3 + ry * (kh3 + PANEL_GAP) + kh3 * 0.12)
        dots_y = sum(
            1 for xx in range(yx - 8, yx + 9)
            for yy in range(y_top - 10, y_top + 10)
            if img3.pixelColor(xx, yy).name() == "#333333")
        check("T28c 第三轮（/）数字上方有高音点、第一轮（Y）无高音点",
              dots_slash > 0 and dots_y == 0,
              f"dots_slash={dots_slash} dots_y={dots_y}")
        p3.close()
        panel.set_display_mode(MODE_LETTER)

        # ---------------- T29: 键位图标三种类型 + 音调 C 大调循环 ----------------
        from model import SHAPE_CIRCLE as M_SC, SHAPE_DIAMOND as M_SD, \
            SHAPE_DIAMOND_CIRCLE as M_SDC
        check("T29a 图标映射：菱形中带圆 = Y K /",
              M_SDC == {"Y", "K", "/"})
        check("T29b 图标映射：菱形 = U O J L M .",
              M_SD == {"U", "O", "J", "L", "M", "."})
        check("T29c 图标映射：圆形 = I P H ; N ,",
              M_SC == {"I", "P", "H", ";", "N", ","})
        check("T29d 面板图标类型判定",
              panel._shape_type("Y") == "dc" and panel._shape_type("U") == "diamond"
              and panel._shape_type("I") == "circle")
        panel.set_display_mode(MODE_TONE)
        check("T29e 音调按 C 大调循环（Y=K= /=C、H=A、.=B）",
              panel._key_label("Y") == "C" and panel._key_label("K") == "C"
              and panel._key_label("/") == "C" and panel._key_label("H") == "A"
              and panel._key_label(".") == "B")
        panel.set_display_mode(MODE_LETTER)

        # ---------------- T30: 乐谱子目录 + 复制/重命名/删除 + 悬浮侧边栏 ----------------
        src_p = tmp / "Origin.ggp"
        save_ggp(str(src_p), "Origin", 4, NoteGrid())
        copy_p = fio_mod.copy_sheet(str(src_p))
        check("T30a 复制乐谱为「副本」文件",
              pathlib.Path(copy_p).exists() and copy_p != str(src_p), copy_p)
        ren_p = fio_mod.rename_sheet(copy_p, "Renamed")
        check("T30b 重命名：文件改名且 JSON title 更新",
              pathlib.Path(ren_p).exists() and not pathlib.Path(copy_p).exists()
              and load_ggp(ren_p)["title"] == "Renamed",
              f"ren={ren_p}")
        fio_mod.delete_sheet(ren_p)
        check("T30c 删除乐谱文件", not pathlib.Path(ren_p).exists())
        bdlg = dlg.BrowseSheetsDialog(tmp)
        btns = [b.text() for b in bdlg.findChildren(QPushButton)]
        check("T30d 浏览界面每行提供 复制/重命名/删除 按钮",
              "复制" in btns and "重命名" in btns and "删除" in btns, str(btns))
        bdlg.close()
        check("T30e 按键区侧边栏为悬浮样式（不挤占主窗口）",
              window.key_dock.isFloating())

        # ---------------- T31: 默认显示两横排 ----------------
        window.new_sheet()
        model = window._model
        block_h = sheet._block_h()
        check("T31a 初始格子谱按两横排布局（高度含两行）",
              sheet.sizeHint().height()
              >= 2 * MARGIN_Y + 2 * block_h + LINE_GAP,
              f"h={sheet.sizeHint().height()}")
        # 第二横排第 1 块位（beat4，每横排 4）可点击直接添加
        pos_r2 = sheet_cell_center(sheet, 0, 0, block=0, line=1)
        QTest.mouseClick(sheet, Qt.LeftButton, pos=pos_r2)
        check("T31b 默认第二横排可点击直接添加标记",
              model.has_note(4, "Y") and model.num_columns() == 5,
              f"cols={model.num_columns()} notes4={model.notes(4)}")

        # ---------------- T32: 格子谱样式 ----------------
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
              gs.style == "thick_frame" and gs.bg_color == "#FFFFFF"
              and gs.border_color == "#333333")

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
        p_bad = tmp / "Bad.ggp"
        p_bad.write_text('{"version":2,"note_grid":[[{"k":"Y","c":false}]],'
                         '"grid_style":"nope","bg_color":"zz","border_color":"#12345"}',
                         encoding="utf-8")
        bad_loaded = load_ggp(str(p_bad))
        check("T32f 非法样式/颜色回退默认",
              bad_loaded["grid_style"] == "default"
              and bad_loaded["bg_color"] == "#FFFFFF"
              and bad_loaded["border_color"] == "#B8B8B8")

        # ---------------- T32g: 显示区样式渲染 ----------------
        sheet.set_style("no_border")
        sheet.set_bg_color(QColor("#FFF8E1"))
        sheet.set_border_color(QColor("#333333"))
        check("T32g 显示区样式 getter/setter 生效",
              sheet.style() == "no_border"
              and sheet.bg_color().name() == "#fff8e1"
              and sheet.border_color().name() == "#333333")

        # ---------------- T32h: 导出样式渲染（固定 MINI=36） ----------------
        g1 = NoteGrid(1)
        g1.set_note(0, "Y", False, True)
        img_def = render_page_image(g1, 4, 1, 0)          # 默认样式
        px_def_border = img_def.pixelColor(EX_M, EX_M + EX_MINI // 2).name()
        img_nb = render_page_image(g1, 4, 1, 0, style="no_border",
                                   bg_color="#FFF8E1")
        px_nb = img_nb.pixelColor(EX_M, EX_M + EX_MINI // 2).name()
        px_nb_bg = img_nb.pixelColor(
            EX_M + EX_MINI + EXPORT_MINI_GAP + EX_MINI // 2,
            EX_M + EX_MINI // 2).name()                    # 第2列空格内部
        check("T32h 默认导出有内线、no_border 无内线且背景生效",
              px_def_border == "#b8b8b8" and px_nb == "#e84848"
              and px_nb_bg == "#fff8e1",
              f"def={px_def_border} nb={px_nb} bg={px_nb_bg}")
        img_ff = render_page_image(g1, 4, 1, 0, style="full_frame",
                                   border_color="#333333")
        px_frame = img_ff.pixelColor(EX_M, EX_M).name()   # 块外框左上角
        check("T32i 完整内外边框导出画外框（自定义边框色）",
              px_frame == "#333333", f"frame={px_frame}")

        # ---------------- T32j: 工具栏样式下拉框联动 ----------------
        combo = window.style_combo
        check("T32j 工具栏含 6 项样式下拉框且联动显示区",
              combo.count() == 6)
        idx = combo.findData("full_frame")
        combo.setCurrentIndex(idx)
        QTest.qWait(10)
        check("T32k 切换下拉框实时生效",
              window.sheet.style() == "full_frame" and window._style == "full_frame")

        # ---------------- T32l: 导出对话框临时样式 ----------------
        ed = dlg.ExportDialog(NoteGrid(2), 4, default_title="Temp",
                              style="default")
        key0 = ed._full_pixmap.cacheKey()
        ed.style_combo.setCurrentIndex(ed.style_combo.findData("thick_frame"))
        key1 = ed._full_pixmap.cacheKey()
        ed._bg_color = "#FFEEDD"
        check("T32l 导出对话框样式读取为临时值",
              ed.style() == "thick_frame" and ed.bg_color() == "#FFEEDD")
        check("T32m 导出临时样式不影响乐谱保存值",
              window.sheet.style() == "full_frame"
              and window._style == "full_frame")
        check("T32p 导出预览切换样式实时刷新",
              key1 != key0, f"key0={key0} key1={key1}")
        check("T32q 颜色按钮文字自动对比色（浅色底深字、深色底白字）",
              "#333333" in ed.bg_btn.styleSheet()
              and "#FFFFFF" in ed.mark_btn.styleSheet(),
              ed.bg_btn.styleSheet())
        ed.close()

        # ---------------- T32n: 连续贯通格线（非默认样式） ----------------
        img_no = render_page_image(g1, 4, 1, 0, style="no_outer")
        x_mid = EX_M + EX_MINI + EXPORT_MINI_GAP + EX_MINI // 2   # 第2列空格内部
        px_top = img_no.pixelColor(x_mid, EX_M).name()            # 块顶边：无外框
        px_inner = img_no.pixelColor(
            x_mid, EX_M + EX_MINI + EXPORT_MINI_GAP).name()       # 行间内线
        check("T32n no_outer：无外框边、内部线连续贯通",
              px_top == "#ffffff" and px_inner == "#b8b8b8",
              f"top={px_top} inner={px_inner}")
        img_ti = render_page_image(g1, 4, 1, 0, style="thick_inner")
        lx = EX_M + EX_MINI + EXPORT_MINI_GAP    # 第1列与第2列之间竖线
        ly = EX_M + EX_MINI // 2             # 内线中段（避开行间线交点）
        cnt = sum(1 for dx in range(-3, 4)
                  if img_ti.pixelColor(lx + dx, ly).name() == "#b8b8b8")
        check("T32o thick_inner 内线 2px 连续（交点不叠加变粗）",
              1 <= cnt <= 2, f"cnt={cnt}")

        window.close()   # closeEvent：dirty=True → question 已注入 Yes → 放行

        # ---------------- 汇总 ----------------
        passed = sum(1 for _, ok in RESULTS if ok)
        total = len(RESULTS)
        print("-" * 60)
        print(f"TOTAL_OK: {passed}/{total}")
        return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
