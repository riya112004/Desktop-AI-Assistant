"""Reminder list and lifecycle controls."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from db.database import Database


class ReminderManagerDialog(QDialog):
    def __init__(self, database: Database, parent: object | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.database = database
        self.selected_id: int | None = None
        self.setWindowTitle("Reminder Manager")
        self.resize(850, 520)
        self.setMinimumSize(700, 420)
        self.setStyleSheet(
            """
            QDialog { background: #f4f7fb; }
            QLabel#title { font-size: 18pt; font-weight: 700; color: #172033; }
            QLabel#subtitle, QLabel#count { color: #65728a; }
            QComboBox { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; }
            QTableView { background: white; border: 1px solid #dce3ee; border-radius: 10px; gridline-color: #edf1f6; }
            QTableView::item { padding: 8px; }
            QTableView::item:selected { background: #d9eee9; color: #172033; }
            QHeaderView::section { background: #edf5f3; color: #344054; border: 0; padding: 9px; font-weight: 700; }
            QPushButton { background: #e8eef8; border: 0; border-radius: 8px; padding: 9px 15px; font-weight: 600; }
            QPushButton:hover { background: #d8e4fb; }
            QPushButton#done { background: #2d7a72; color: white; }
            QPushButton#delete { color: #b42318; }
            """
        )

        title = QLabel("Reminder Manager")
        title.setObjectName("title")
        subtitle = QLabel("View and manage all your upcoming, completed and overdue reminders")
        subtitle.setObjectName("subtitle")

        self.status_filter = QComboBox()
        self.status_filter.addItems(["All reminders", "Pending", "Overdue", "Done"])
        self.status_filter.currentTextChanged.connect(self._refresh)
        self.count_label = QLabel()
        self.count_label.setObjectName("count")

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Show"))
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch()
        filter_row.addWidget(self.count_label)

        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(["ID", "Status", "Reminder", "Due", "Repeat"])
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.clicked.connect(self._select_row)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 95)
        self.table.setColumnWidth(2, 330)
        self.table.setColumnWidth(3, 170)

        self.snooze_button = QPushButton("Snooze 10 min")
        self.done_button = QPushButton("Mark done")
        self.done_button.setObjectName("done")
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("delete")
        self.refresh_button = QPushButton("Refresh")
        self.snooze_button.clicked.connect(self._snooze)
        self.done_button.clicked.connect(self._mark_done)
        self.delete_button.clicked.connect(self._delete)
        self.refresh_button.clicked.connect(self._refresh)
        action_row = QHBoxLayout()
        for button in (self.snooze_button, self.done_button, self.delete_button, self.refresh_button):
            button.setEnabled(False)
            action_row.addWidget(button)
        action_row.addStretch()

        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(filter_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(action_row)
        layout.addWidget(close_button)
        self._refresh()

    def _refresh(self) -> None:
        selected_status = self.status_filter.currentText().lower()
        status = None if selected_status == "all reminders" else selected_status
        reminders = self.database.list_reminders(status=status)
        self.model.removeRows(0, self.model.rowCount())
        for reminder in reminders:
            self.model.appendRow([
                QStandardItem(str(reminder["id"])),
                QStandardItem(str(reminder["status"]).title()),
                QStandardItem(str(reminder["text"])),
                QStandardItem(self._format_due(str(reminder["due_at"]))),
                QStandardItem(str(reminder["recurrence_rule"] or "Once")),
            ])
        self.count_label.setText(f"{len(reminders)} reminder(s)")
        self._set_actions_enabled(False)

    def _select_row(self, index: Any) -> None:
        self.selected_id = int(self.model.item(index.row(), 0).text())
        self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (self.snooze_button, self.done_button, self.delete_button):
            button.setEnabled(enabled)

    def _selected_reminder(self) -> dict[str, Any] | None:
        if self.selected_id is None:
            return None
        return self.database.get_reminder(self.selected_id)

    def _snooze(self) -> None:
        reminder = self._selected_reminder()
        if reminder is None:
            return
        due_at = datetime.fromisoformat(reminder["due_at"]) + timedelta(minutes=10)
        self.database.update_reminder(reminder["id"], due_at.isoformat(timespec="seconds"), "pending")
        self._refresh()

    def _mark_done(self) -> None:
        reminder = self._selected_reminder()
        if reminder is None:
            return
        self.database.update_reminder_status(reminder["id"], "done")
        self._refresh()

    def _delete(self) -> None:
        reminder = self._selected_reminder()
        if reminder is None:
            return
        answer = QMessageBox.question(self, "Delete reminder", f"Delete '{reminder['text']}'?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.database.delete_reminder(reminder["id"])
        self._refresh()

    @staticmethod
    def _format_due(value: str) -> str:
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%d %b %Y, %I:%M %p")
        except ValueError:
            return value
