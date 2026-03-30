from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from btz_console.app import AppState
from btz_console.services import load_project_prompt, save_project_prompt


class PreparePage(QWidget):
    def __init__(self, state: AppState, on_go_groups):
        super(PreparePage, self).__init__()
        self.state = state
        self.on_go_groups = on_go_groups
        self._build_ui()
        self._prompt_dirty = False

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        action_row = QHBoxLayout()
        self.btn_refresh = QPushButton("Refrescar datos")
        self.btn_open = QPushButton("Abrir carpeta public")
        self.btn_groups = QPushButton("Abrir revisión de grupos")
        self.btn_export_hook = QPushButton("Hook exportación (pendiente)")
        self.btn_export_hook.setEnabled(False)
        action_row.addWidget(self.btn_refresh)
        action_row.addWidget(self.btn_open)
        action_row.addWidget(self.btn_groups)
        action_row.addWidget(self.btn_export_hook)
        action_row.addStretch(1)
        root.addLayout(action_row)

        kpi_frame = QFrame()
        kpi_frame.setObjectName("Card")
        kpi_layout = QHBoxLayout(kpi_frame)
        self.lbl_project = QLabel("Proyecto: -")
        self.lbl_path = QLabel("Ruta: -")
        self.lbl_elements = QLabel("Elementos: 0")
        self.lbl_groups = QLabel("Grupos: 0")
        self.lbl_status = QLabel("Estado: Pending")
        for w in [self.lbl_project, self.lbl_path, self.lbl_elements, self.lbl_groups, self.lbl_status]:
            kpi_layout.addWidget(w)
        kpi_layout.addStretch(1)
        root.addWidget(kpi_frame)

        self.tbl_artifacts = QTableWidget(0, 5)
        self.tbl_artifacts.setHorizontalHeaderLabels(
            ["Artefacto", "Estado", "Requerido", "Tamaño (bytes)", "Última actualización"]
        )
        self.tbl_artifacts.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.tbl_artifacts, stretch=2)

        warnings_frame = QFrame()
        warnings_frame.setObjectName("Card")
        wf_layout = QVBoxLayout(warnings_frame)
        wf_layout.addWidget(QLabel("Warnings principales"))
        self.txt_warnings = QPlainTextEdit()
        self.txt_warnings.setReadOnly(True)
        wf_layout.addWidget(self.txt_warnings)
        root.addWidget(warnings_frame, stretch=1)

        logs_frame = QFrame()
        logs_frame.setObjectName("Card")
        lf_layout = QVBoxLayout(logs_frame)
        lf_layout.addWidget(QLabel("Logs recientes"))
        self.txt_logs = QPlainTextEdit()
        self.txt_logs.setReadOnly(True)
        lf_layout.addWidget(self.txt_logs)
        root.addWidget(logs_frame, stretch=2)

        prompt_frame = QFrame()
        prompt_frame.setObjectName("Card")
        pf_layout = QVBoxLayout(prompt_frame)
        head = QHBoxLayout()
        head.addWidget(QLabel("Prompt de proyecto (desde Revit)"))
        head.addStretch(1)
        self.btn_prompt_load_file = QPushButton("Cargar archivo al prompt")
        self.btn_prompt_save = QPushButton("Guardar prompt")
        head.addWidget(self.btn_prompt_load_file)
        head.addWidget(self.btn_prompt_save)
        pf_layout.addLayout(head)
        self.txt_prompt = QPlainTextEdit()
        self.txt_prompt.setPlaceholderText("Pegá aquí el prompt de configuración de proyecto...")
        pf_layout.addWidget(self.txt_prompt)
        root.addWidget(prompt_frame, stretch=2)

        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_groups.clicked.connect(self.on_go_groups)
        self.btn_prompt_save.clicked.connect(self._save_prompt)
        self.btn_prompt_load_file.clicked.connect(self._load_prompt_file)
        self.txt_prompt.textChanged.connect(self._mark_prompt_dirty)

    def _open_folder(self):
        if os.path.isdir(str(self.state.public_dir)):
            os.startfile(str(self.state.public_dir))

    def _refresh(self):
        self.state.refresh()
        self.render()

    def _mark_prompt_dirty(self):
        self._prompt_dirty = True

    def focus_prompt_editor(self):
        self.txt_prompt.setFocus()
        self.txt_prompt.moveCursor(QTextCursor.End)

    def _load_prompt_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo para prompt",
            str(self.state.public_dir),
            "Text files (*.txt *.md *.json *.csv);;All files (*.*)",
        )
        if not file_path:
            return
        encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
        content = None
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as fp:
                    content = fp.read()
                break
            except Exception:
                continue
        if content is None:
            return
        current = self.txt_prompt.toPlainText()
        if current and (not current.endswith("\n")):
            current += "\n"
        current += content
        self.txt_prompt.setPlainText(current)
        self._prompt_dirty = True

    def _save_prompt(self):
        text = self.txt_prompt.toPlainText()
        save_project_prompt(self.state.public_dir, text)
        self._prompt_dirty = False

    def render(self):
        ctx = self.state.context
        if not ctx:
            return
        self.lbl_project.setText("Proyecto: {}".format(ctx.project_name))
        self.lbl_path.setText("Ruta: {}".format(ctx.public_dir))
        self.lbl_elements.setText("Elementos: {}".format(ctx.elements_count))
        self.lbl_groups.setText("Grupos base/refinados: {}/{}".format(ctx.groups_count, ctx.refined_groups_count))
        self.lbl_status.setText("Estado: {}".format(ctx.load_status))

        self.tbl_artifacts.setRowCount(len(ctx.artifacts))
        for i, art in enumerate(ctx.artifacts):
            status = "OK" if art.exists else ("Error" if art.required else "Pending")
            self.tbl_artifacts.setItem(i, 0, QTableWidgetItem(art.name))
            self.tbl_artifacts.setItem(i, 1, QTableWidgetItem(status))
            self.tbl_artifacts.setItem(i, 2, QTableWidgetItem("Sí" if art.required else "No"))
            self.tbl_artifacts.setItem(i, 3, QTableWidgetItem(str(art.size_bytes)))
            updated = art.updated_at.strftime("%Y-%m-%d %H:%M:%S") if art.updated_at else "-"
            self.tbl_artifacts.setItem(i, 4, QTableWidgetItem(updated))
            for col in range(5):
                item = self.tbl_artifacts.item(i, col)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)

        self.txt_warnings.setPlainText("\n".join(ctx.warnings) if ctx.warnings else "Sin warnings.")
        self.txt_logs.setPlainText("\n".join(ctx.recent_logs) if ctx.recent_logs else "Sin logs aún.")
        if not self._prompt_dirty:
            self.txt_prompt.setPlainText(load_project_prompt(self.state.public_dir))

