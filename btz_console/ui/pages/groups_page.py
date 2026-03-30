from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from btz_console.app import AppState


class GroupsPage(QWidget):
    COLS = [
        "group_key",
        "refined_group_key",
        "macro_group",
        "category",
        "family",
        "type",
        "count",
        "confidence",
        "origin",
        "needs_review",
        "candidate_btz",
    ]

    def __init__(self, state: AppState):
        super(GroupsPage, self).__init__()
        self.state = state
        self.filtered = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Buscar"))
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("group_key, categoría, familia, candidato...")
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["Todos", "Review", "Auto"])
        filter_row.addWidget(self.ed_search, stretch=2)
        filter_row.addWidget(QLabel("Estado"))
        filter_row.addWidget(self.cmb_status)
        root.addLayout(filter_row)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)
        root.addWidget(splitter, stretch=1)

        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.tbl)

        detail_frame = QFrame()
        detail_frame.setObjectName("Card")
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.addWidget(QLabel("Detalle del grupo"))
        self.lbl_detail_title = QLabel("-")
        self.lbl_detail_title.setObjectName("Title")
        detail_layout.addWidget(self.lbl_detail_title)
        self.txt_detail = QLabel("Seleccioná una fila para ver detalle.")
        self.txt_detail.setWordWrap(True)
        self.txt_detail.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        detail_layout.addWidget(self.txt_detail, stretch=1)
        splitter.addWidget(detail_frame)
        splitter.setSizes([950, 330])

        self.ed_search.textChanged.connect(self._apply_filter)
        self.cmb_status.currentTextChanged.connect(self._apply_filter)
        self.tbl.itemSelectionChanged.connect(self._on_select)

    def render(self):
        self._apply_filter()

    def _apply_filter(self):
        q = (self.ed_search.text() or "").strip().lower()
        status = self.cmb_status.currentText()
        items = self.state.groups

        out = []
        for g in items:
            if status == "Review" and not g.needs_review:
                continue
            if status == "Auto" and g.needs_review:
                continue
            hay = " ".join(
                [
                    g.group_key,
                    g.refined_group_key,
                    g.macro_group,
                    g.category_name,
                    g.family_name,
                    g.type_name,
                    g.candidate_btz_principal,
                ]
            ).lower()
            if q and q not in hay:
                continue
            out.append(g)
        self.filtered = out
        self._render_table()

    def _render_table(self):
        self.tbl.setRowCount(len(self.filtered))
        for i, g in enumerate(self.filtered):
            vals = [
                g.group_key,
                g.refined_group_key,
                g.macro_group,
                g.category_name,
                g.family_name,
                g.type_name,
                str(g.count),
                "{:.3f}".format(g.confidence),
                g.source_origin,
                "Sí" if g.needs_review else "No",
                g.candidate_btz_principal,
            ]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.tbl.setItem(i, j, item)

    def _on_select(self):
        idx = self.tbl.currentRow()
        if idx < 0 or idx >= len(self.filtered):
            return
        g = self.filtered[idx]
        self.state.selected_group = g
        self.lbl_detail_title.setText(g.refined_group_key or g.group_key)
        lines = [
            "Macro: {}".format(g.macro_group),
            "Categoría: {}".format(g.category_name),
            "Familia: {}".format(g.family_name),
            "Tipo: {}".format(g.type_name),
            "Count: {}".format(g.count),
            "Confidence: {:.3f}".format(g.confidence),
            "Origen: {}".format(g.source_origin),
            "Needs review: {}".format("Sí" if g.needs_review else "No"),
            "Candidate principal: {}".format(g.candidate_btz_principal or "-"),
        ]
        if g.metadata:
            lines.append("")
            lines.append("Metadata")
            for k, v in g.metadata.items():
                lines.append("- {}: {}".format(k, v))
        if g.candidate_btz:
            lines.append("")
            lines.append("Top candidates")
            for c in g.candidate_btz[:5]:
                lines.append(
                    "- [{}] {} ({:.3f})".format(c.matched_code or "-", c.display_value or "-", c.confidence)
                )
        self.txt_detail.setText("\n".join(lines))

