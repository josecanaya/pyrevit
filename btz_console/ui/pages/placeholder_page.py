from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str):
        super(PlaceholderPage, self).__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        lbl_t = QLabel(title)
        lbl_t.setObjectName("Title")
        lbl_d = QLabel(description)
        lbl_d.setWordWrap(True)
        lbl_d.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        root.addWidget(lbl_t)
        root.addWidget(lbl_d)
        root.addStretch(1)

