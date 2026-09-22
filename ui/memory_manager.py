"""Manual memory manager with typed category forms."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
        self.resize(760, 500)
        self.selected_id: int | None = None
        self.fields: dict[str, QLineEdit] = {}

        self.table = QTableView()
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.clicked.connect(self._select_row)
        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(["ID", "Category", "Title", "Details", "Notes"])
        self.table.setModel(self.model)

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

        self.add_button = QPushButton("Add")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")
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
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(self.form)
        layout.addLayout(buttons)
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
        for memory in self.database.list_memories():
            self.model.appendRow([
                QStandardItem(str(memory.id)),
                QStandardItem(memory.category),
                QStandardItem(memory.title),
                QStandardItem(", ".join(f"{key}={value}" for key, value in memory.details.items())),
                QStandardItem(memory.notes),
            ])
        self.table.resizeColumnsToContents()

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
