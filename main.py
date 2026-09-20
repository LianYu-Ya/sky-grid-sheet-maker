# -*- coding: utf-8 -*-
"""光遇格子谱制作器 —— 应用入口。

设置 Fusion 风格 + 简约白色主题（白底、浅灰网格线、统一强调色、深灰文字）。
"""

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from main_window import MainWindow

# 应用图标（assets/icon.ico），缺失时静默跳过
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "assets", "icon.ico")

# 简约白色主题样式表
STYLE_SHEET = """
QWidget {
    background-color: #FFFFFF;
    color: #333333;
    font-size: 13px;
}
QToolBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E0E0E0;
    spacing: 4px;
    padding: 4px;
}
QToolBar::separator {
    width: 1px;
    background: #E0E0E0;
    margin: 4px 6px;
}
#toolbarFlow {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E0E0E0;
    padding: 4px;
}
#toolbarFlow QPushButton {
    padding: 4px 10px;
}
QLineEdit, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #D0D0D0;
    border-radius: 4px;
    padding: 4px 8px;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #4A90D9;
}
QPushButton {
    background-color: #F5F5F5;
    border: 1px solid #D0D0D0;
    border-radius: 4px;
    padding: 5px 14px;
}
QPushButton:hover {
    background-color: #4A90D9;
    color: #FFFFFF;
    border: 1px solid #4A90D9;
}
QPushButton:pressed {
    background-color: #3A7BC0;
    color: #FFFFFF;
}
QScrollArea {
    border: none;
}
QStatusBar {
    background-color: #FAFAFA;
    border-top: 1px solid #E0E0E0;
}
QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 4px;
}
QListWidget::item {
    padding: 6px;
}
QListWidget::item:selected {
    background-color: #4A90D9;
    color: #FFFFFF;
}
QDialog {
    background-color: #FFFFFF;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE_SHEET)
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
