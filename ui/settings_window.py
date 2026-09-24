"""Application settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout

from connectors.calendar import GoogleCalendarConnector
from db.database import Database


class SettingsDialog(QDialog):
	def __init__(self, database: Database, parent: object | None = None) -> None:
		super().__init__(parent)  # type: ignore[arg-type]
		self.database = database
		self.setWindowTitle("Settings")
		self.calendar_checkbox = QCheckBox("Enable Google Calendar")
		stored = database.get_state("calendar_enabled")
		default_enabled = GoogleCalendarConnector().enabled
		self.calendar_checkbox.setChecked(default_enabled if stored is None else stored == "1")
		buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
		buttons.accepted.connect(self.accept)
		buttons.rejected.connect(self.reject)
		layout = QVBoxLayout(self)
		layout.addWidget(self.calendar_checkbox)
		layout.addWidget(buttons)

	def accept(self) -> None:
		self.database.set_state("calendar_enabled", "1" if self.calendar_checkbox.isChecked() else "0")
		super().accept()
