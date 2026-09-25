"""Manual memory manager with typed category forms."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from db.database import Database, Memory
from features.memory import FamilyDetails, InsuranceDetails, VehicleDetails


DETAIL_FIELDS = {
    "family": ["relationship", "birthday", "phone", "email"],
    "vehicle": ["make", "model", "year", "registration", "color"],
    "insurance": ["provider", "policy_number", "type", "renewal_date"],
}


class MemoryManagerDialog(QDialog):
    def __init__(self, database: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("Memory Manager")
        self.resize(900, 650)
        self.setMinimumSize(760, 520)
        self.setStyleSheet(
            """
            QDialog { background: #f4f7fb; }
            QLabel#managerTitle { font-size: 18pt; font-weight: 700; color: #172033; }
            QLabel#managerSubtitle { color: #65728a; }
            QLabel#sectionLabel { color: #344054; font-weight: 700; }
            QLabel#countLabel { color: #65728a; }
            QLineEdit, QComboBox { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; }
            QLineEdit:focus, QComboBox:focus { border: 2px solid #4f7cff; padding: 7px 9px; }
            QTableView { background: white; border: 1px solid #dce3ee; border-radius: 10px; gridline-color: #edf1f6; }
            QTableView::item { padding: 8px; }
            QTableView::item:selected { background: #d9eee9; color: #172033; }
            QHeaderView::section { background: #edf5f3; color: #344054; border: 0; padding: 9px; font-weight: 700; }
            QScrollBar:vertical { background: #edf1f6; width: 13px; margin: 3px; border-radius: 6px; }
            QScrollBar::handle:vertical { background: #9bb8b2; min-height: 34px; border-radius: 6px; }
            QScrollBar::handle:vertical:hover { background: #6e9c93; }
            QGroupBox { background: white; border: 1px solid #dce3ee; border-radius: 10px; margin-top: 10px; padding: 12px; font-weight: 600; }
            QPushButton { background: #e8eef8; border: 0; border-radius: 8px; padding: 9px 15px; font-weight: 600; }
            QPushButton:hover { background: #d8e4fb; }
            QPushButton#addButton { background: #2d7a72; color: white; }
            QPushButton#addButton:hover { background: #24645e; }
            QPushButton#deleteButton { color: #b42318; }
            """
        )
        self.selected_id: int | None = None
        self.fields: dict[str, QLineEdit] = {}

        title = QLabel("Memory Manager")
        title.setObjectName("managerTitle")
        subtitle = QLabel("Keep your people, vehicles and insurance details organized")
        subtitle.setObjectName("managerSubtitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search memories...")
        self.search.textChanged.connect(self._refresh)
        self.records_label = QLabel()
        self.records_label.setObjectName("countLabel")

        self.table = QTableView()
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setMinimumWidth(440)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.clicked.connect(self._select_row)
        self.table.doubleClicked.connect(self._show_details)
        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(["", "Type", "Name", "Details", "Notes"])
        self.table.setModel(self.model)
        self.table.hideColumn(0)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.category = QComboBox()
        self.category.addItems(["family", "vehicle", "insurance"])
        self.category.currentTextChanged.connect(self._build_fields)
        self.title = QLineEdit()
        self.notes = QLineEdit()
        self.form = QFormLayout()
        self.form.addRow("Category", self.category)
        self.form.addRow("Title", self.title)
        self.form.addRow("Notes", self.notes)
        self.details_widget = QWidget()
        self.details_layout = QFormLayout(self.details_widget)
        self.form.addRow(self.details_widget)
        self.editor_group = QGroupBox("Memory details")
        self.editor_group.setLayout(self.form)

        self.add_button = QPushButton("Add")
        self.add_button.setObjectName("addButton")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("deleteButton")
        self.clear_button = QPushButton("Clear")
        self.add_button.clicked.connect(self._add)
        self.edit_button.clicked.connect(self._edit)
        self.delete_button.clicked.connect(self._delete)
        self.clear_button.clicked.connect(self._clear)
        buttons = QHBoxLayout()
        for button in (self.add_button, self.edit_button, self.delete_button, self.clear_button):
            buttons.addWidget(button)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        editor_layout = QVBoxLayout()
        editor_layout.setContentsMargins(4, 0, 4, 0)
        editor_layout.addWidget(self.editor_group)
        editor_layout.addLayout(buttons)
        self.editor_dialog = QDialog(self)
        self.editor_dialog.setWindowTitle("Edit memory")
        self.editor_dialog.setMinimumWidth(420)
        self.editor_dialog.setStyleSheet(self.styleSheet())
        self.editor_dialog.setLayout(editor_layout)

        actions = QHBoxLayout()
        view_button = QPushButton("View details")
        new_button = QPushButton("Add memory")
        edit_button = QPushButton("Edit selected")
        delete_button = QPushButton("Delete selected")
        view_button.clicked.connect(self._show_details)
        new_button.clicked.connect(self._open_new_editor)
        edit_button.clicked.connect(self._open_selected_editor)
        delete_button.clicked.connect(self._delete)
        for button in (view_button, new_button, edit_button, delete_button):
            actions.addWidget(button)
        self.table.setMinimumWidth(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        list_heading = QHBoxLayout()
        section_label = QLabel("Saved memories")
        section_label.setObjectName("sectionLabel")
        list_heading.addWidget(section_label)
        list_heading.addStretch()
        list_heading.addWidget(self.records_label)
        layout.addLayout(list_heading)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Find"))
        search_row.addWidget(self.search)
        layout.addLayout(search_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        layout.addWidget(close_buttons)
        self._build_fields(self.category.currentText())
        self._refresh()

    def _build_fields(self, category: str) -> None:
        while self.details_layout.rowCount():
            self.details_layout.removeRow(0)
        self.fields = {}
        for name in DETAIL_FIELDS[category]:
            field = QLineEdit()
            self.fields[name] = field
            self.details_layout.addRow(name.replace("_", " ").title(), field)

    def _refresh(self) -> None:
        self.model.removeRows(0, self.model.rowCount())
        query = self.search.text().strip().lower()
        memories = self.database.list_memories()
        visible_count = 0
        for memory in memories:
            search_text = " ".join((memory.category, memory.title, memory.notes, str(memory.details))).lower()
            if query and query not in search_text:
                continue
            visible_count += 1
            self.model.appendRow([
                QStandardItem(str(memory.id)),
                QStandardItem(memory.category),
                QStandardItem(memory.title),
                QStandardItem(", ".join(f"{key}={value}" for key, value in memory.details.items())),
                QStandardItem(memory.notes),
            ])
            self.records_label.setText(
            f"{visible_count} shown of {len(memories)} | Scroll to see more" if len(memories) > 1
            else f"{visible_count} memory saved"
            )
        self.table.hideColumn(0)

    def _select_row(self, index: Any) -> None:
        row = index.row()
        self.selected_id = int(self.model.item(row, 0).text())
        memory = self.database.get_memory(self.selected_id)
        if memory is None:
            return
        self.category.setCurrentText(memory.category)
        self.title.setText(memory.title)
        self.notes.setText(memory.notes)
        for name, field in self.fields.items():
            field.setText(str(memory.details.get(name, "")))

    def _show_details(self, index: Any = None) -> None:
        if index is not None and hasattr(index, "isValid") and index.isValid():
            self._select_row(index)
        if self.selected_id is None:
            QMessageBox.information(self, "Select a memory", "Select a memory to view its details.")
            return
        memory = self.database.get_memory(self.selected_id)
        if memory is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{memory.title} details")
        dialog.setMinimumWidth(440)
        dialog.setStyleSheet(self.styleSheet())
        layout = QFormLayout(dialog)
        layout.addRow("Type", QLabel(memory.category.title()))
        layout.addRow("Name", QLabel(memory.title))
        for key, value in memory.details.items():
            layout.addRow(key.replace("_", " ").title(), QLabel(str(value)))
        if memory.notes:
            layout.addRow("Notes", QLabel(memory.notes))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        dialog.exec()

    def _open_new_editor(self) -> None:
        self._clear()
        self.editor_dialog.setWindowTitle("Add memory")
        self.editor_dialog.exec()

    def _open_selected_editor(self) -> None:
        if self.selected_id is None:
            QMessageBox.information(self, "Select a memory", "Select a memory to edit first.")
            return
        self.editor_dialog.setWindowTitle("Edit memory")
        self.editor_dialog.exec()

    def _details(self) -> dict[str, Any]:
        details = {name: field.text().strip() for name, field in self.fields.items() if field.text().strip()}
        if self.category.currentText() == "vehicle" and "year" in details:
            details["year"] = int(details["year"])
        model = {"family": FamilyDetails, "vehicle": VehicleDetails, "insurance": InsuranceDetails}[self.category.currentText()]
        return model.model_validate(details).model_dump(exclude_none=True)

    def _memory(self) -> Memory:
        title = self.title.text().strip()
        if not title:
            raise ValueError("Title is required.")
        return Memory(
            self.category.currentText(),
            title,
            self._details(),
            self.notes.text().strip(),
            self.selected_id,
        )

    def _add(self) -> None:
        try:
            memory = self._memory()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Invalid memory", str(error))
            return
        if QMessageBox.question(self, "Confirm add", f"Add memory '{memory.title}'?") != QMessageBox.StandardButton.Yes:
            return
        self.database.add_memory(memory)
        self._refresh()
        self._clear()
        self.editor_dialog.accept()

    def _edit(self) -> None:
        if self.selected_id is None:
            QMessageBox.information(self, "Select memory", "Select a memory first.")
            return
        try:
            memory = self._memory()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Invalid memory", str(error))
            return
        if QMessageBox.question(self, "Confirm edit", f"Edit memory '{memory.title}'?") != QMessageBox.StandardButton.Yes:
            return
        self.database.update_memory(memory)
        self._refresh()
        self.editor_dialog.accept()

    def _delete(self) -> None:
        if self.selected_id is None:
            QMessageBox.information(self, "Select memory", "Select a memory first.")
            return
        memory = self.database.get_memory(self.selected_id)
        if memory is None:
            return
        if QMessageBox.question(self, "Confirm delete", f"Delete memory '{memory.title}'?") != QMessageBox.StandardButton.Yes:
            return
        self.database.delete_memory(self.selected_id)
        self._refresh()
        self._clear()

    def _clear(self) -> None:
        self.selected_id = None
        self.title.clear()
        self.notes.clear()
        for field in self.fields.values():
            field.clear()
