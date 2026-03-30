from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from btz_console.app import AppState
from btz_console.config import APP_NAME, ORG_NAME
from btz_console.ui.pages import GroupsPage, PlaceholderPage, PreparePage


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, initial_page: str = "Prepare", open_prompt: bool = False):
        super(MainWindow, self).__init__()
        self.state = state
        self.initial_page = initial_page
        self.open_prompt = open_prompt
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.nav_buttons = {}
        self._build_ui()
        self._restore_window()
        self.refresh_all()

    def _build_ui(self):
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(980, 640)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(8)
        self.lbl_app = QLabel("BTZ Console")
        self.lbl_app.setObjectName("Title")
        self.lbl_stage = QLabel("Flujo BTZ local")
        self.lbl_stage.setObjectName("Subtitle")
        side_layout.addWidget(self.lbl_app)
        side_layout.addWidget(self.lbl_stage)
        side_layout.addSpacing(12)

        for key in ["Prepare", "Groups", "Suggestions", "Confirm", "Report"]:
            btn = QPushButton(key)
            btn.setProperty("nav", True)
            btn.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav_buttons[key] = btn
            side_layout.addWidget(btn)
        side_layout.addStretch(1)
        layout.addWidget(self.sidebar, stretch=0)

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        layout.addWidget(right, stretch=1)

        self.topbar = QFrame()
        self.topbar.setObjectName("Topbar")
        top_layout = QHBoxLayout(self.topbar)
        top_layout.setContentsMargins(12, 10, 12, 10)
        self.lbl_project = QLabel("Proyecto: -")
        self.lbl_path = QLabel("Public: -")
        self.lbl_path.setObjectName("Subtitle")
        self.btn_refresh = QPushButton("Refrescar")
        self.btn_refresh.clicked.connect(self.refresh_all)
        top_layout.addWidget(self.lbl_project)
        top_layout.addSpacing(12)
        top_layout.addWidget(self.lbl_path, stretch=1)
        top_layout.addWidget(self.btn_refresh)
        right_layout.addWidget(self.topbar)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, stretch=1)

        self.prepare_page = PreparePage(self.state, on_go_groups=lambda: self.show_page("Groups"))
        self.groups_page = GroupsPage(self.state)
        self.suggestions_page = PlaceholderPage(
            "Suggestions",
            "Fase 3: revisión detallada del grupo seleccionado y acciones aprobar/revisión/omitir.",
        )
        self.confirm_page = PlaceholderPage(
            "Confirm",
            "Fase 4: preview de aplicación sobre parámetros BTZ antes de ejecutar.",
        )
        self.report_page = PlaceholderPage(
            "Report",
            "Fase 4: resumen final de apply_results y logs operativos.",
        )
        self.pages = {
            "Prepare": self.prepare_page,
            "Groups": self.groups_page,
            "Suggestions": self.suggestions_page,
            "Confirm": self.confirm_page,
            "Report": self.report_page,
        }
        for key in ["Prepare", "Groups", "Suggestions", "Confirm", "Report"]:
            self.stack.addWidget(self.pages[key])

        self.show_page(self.initial_page if self.initial_page in self.pages else "Prepare")
        if self.open_prompt:
            self.show_page("Prepare")
            self.prepare_page.focus_prompt_editor()

    def refresh_all(self):
        self.state.refresh()
        if self.state.context:
            ctx = self.state.context
            self.lbl_project.setText("Proyecto: {}".format(ctx.project_name))
            self.lbl_path.setText("Public: {}".format(ctx.public_dir))
        self.prepare_page.render()
        self.groups_page.render()

    def show_page(self, key: str):
        idx = ["Prepare", "Groups", "Suggestions", "Confirm", "Report"].index(key)
        self.stack.setCurrentIndex(idx)
        for k, b in self.nav_buttons.items():
            b.setProperty("active", k == key)
            b.style().unpolish(b)
            b.style().polish(b)

    def closeEvent(self, event):
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        super(MainWindow, self).closeEvent(event)

    def _restore_window(self):
        g = self.settings.value("window_geometry")
        s = self.settings.value("window_state")
        if g is not None:
            self.restoreGeometry(g)
        if s is not None:
            self.restoreState(s)
        # default split-screen friendly position
        if g is None:
            screen = self.screen()
            if screen:
                geo = screen.availableGeometry()
                w = int(geo.width() * 0.48)
                h = int(geo.height() * 0.92)
                x = geo.x() + geo.width() - w
                y = geo.y() + int((geo.height() - h) * 0.5)
                self.setGeometry(x, y, w, h)

