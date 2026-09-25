"""Application settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QVBoxLayout

from connectors.calendar import GoogleCalendarConnector
from db.database import Database, UserProfile


class SettingsDialog(QDialog):
	def __init__(self, database: Database, parent: object | None = None) -> None:
		super().__init__(parent)  # type: ignore[arg-type]
		self.database = database
		self.setWindowTitle("Settings")
		self.setMinimumWidth(420)
		self.setStyleSheet(
			"""
			QDialog { background: #f4f7fb; }
			QLineEdit, QComboBox { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 8px 10px; }
			QCheckBox { padding: 6px 0; }
			"""
		)
		profile = database.get_profile() or UserProfile(name="")
		self.name = QLineEdit(profile.name)
		self.language = QComboBox()
		self.language.addItems(["en", "hi", "hinglish"])
		self.language.setCurrentText(profile.language_pref or "en")
		self.personality = QLineEdit(profile.personality)
		self.city = QLineEdit(profile.city)
		self.city.setPlaceholderText("For example: Delhi, India")
		self.zodiac = QLineEdit(profile.zodiac_sign)
		self.zodiac.setPlaceholderText("Optional")
		profile_form = QFormLayout()
		profile_form.addRow("Name", self.name)
		profile_form.addRow("Language", self.language)
		profile_form.addRow("Personality", self.personality)
		profile_form.addRow("City", self.city)
		profile_form.addRow("Zodiac sign", self.zodiac)
		self.calendar_checkbox = QCheckBox("Enable Google Calendar")
		stored = database.get_state("calendar_enabled")
		default_enabled = GoogleCalendarConnector().enabled
		self.calendar_checkbox.setChecked(default_enabled if stored is None else stored == "1")
		buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
		buttons.accepted.connect(self.accept)
		buttons.rejected.connect(self.reject)
		layout = QVBoxLayout(self)
		layout.addLayout(profile_form)
		layout.addWidget(self.calendar_checkbox)
		layout.addWidget(buttons)

	def accept(self) -> None:
		self.database.upsert_profile(
			UserProfile(
				name=self.name.text().strip(),
				language_pref=self.language.currentText(),
				personality=self.personality.text().strip(),
				city=self.city.text().strip(),
				zodiac_sign=self.zodiac.text().strip(),
			)
		)
		self.database.set_state("calendar_enabled", "1" if self.calendar_checkbox.isChecked() else "0")
		super().accept()
