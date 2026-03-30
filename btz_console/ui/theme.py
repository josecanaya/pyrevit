from __future__ import annotations


def build_dark_stylesheet() -> str:
    return """
    QWidget {
        background-color: #12161c;
        color: #d7dde8;
        font-family: Segoe UI, Arial, sans-serif;
        font-size: 12px;
    }
    QFrame#Sidebar {
        background-color: #0f141a;
        border-right: 1px solid #222a35;
    }
    QFrame#Topbar {
        background-color: #151b23;
        border-bottom: 1px solid #222a35;
    }
    QFrame#Card {
        background-color: #1a212c;
        border: 1px solid #2a3444;
        border-radius: 8px;
    }
    QLabel#Title {
        font-size: 16px;
        font-weight: 600;
        color: #e9eef8;
    }
    QLabel#Subtitle {
        color: #8fa0b8;
    }
    QPushButton {
        background-color: #243044;
        border: 1px solid #33445f;
        border-radius: 6px;
        padding: 6px 10px;
        color: #e6ecf7;
    }
    QPushButton:hover {
        background-color: #2b3a53;
    }
    QPushButton:pressed {
        background-color: #213049;
    }
    QPushButton[nav="true"] {
        text-align: left;
        padding: 8px 10px;
    }
    QPushButton[active="true"] {
        background-color: #1f6feb;
        border-color: #1f6feb;
    }
    QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {
        background-color: #0f141a;
        border: 1px solid #2a3444;
        border-radius: 6px;
        padding: 6px;
        color: #d7dde8;
    }
    QTableWidget, QTableView {
        background-color: #0f141a;
        alternate-background-color: #121924;
        border: 1px solid #2a3444;
        gridline-color: #2a3444;
        selection-background-color: #1f6feb;
        selection-color: #ffffff;
    }
    QHeaderView::section {
        background-color: #1a212c;
        border: 0;
        border-right: 1px solid #2a3444;
        border-bottom: 1px solid #2a3444;
        padding: 6px;
        font-weight: 600;
    }
    """

