"""Main chat window with non-blocking LLM calls."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSystemTrayIcon,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from connectors.calendar import GoogleCalendarConnector
from core.context_engine import SYSTEM_PROMPT, build_context
from core.config import load_config
from core.llm_client import LLMError, create_llm_client
from db.database import Database
from features.briefing import generate_daily_briefing, should_generate_daily_briefing
from features.memory import MemoryIntent, apply_memory_action, extract_memory_intent, is_calendar_question
from features.notifications import show_reminder_notification
from features.reminders import (
    ReminderIntent,
    ReminderScheduler,
    extract_reminder_intent,
    format_reminder_confirmation,
    is_reminder_request,
    save_reminder,
)
from ui.memory_manager import MemoryManagerDialog
from ui.settings_window import SettingsDialog


def _is_echo(message: str, reply: str) -> bool:
    return " ".join(message.lower().split()) == " ".join(reply.lower().split())


def _service_date_text(message: str, today: date = date(2026, 9, 22)) -> str | None:
    normalized = " ".join(message.lower().split())
    weekday_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    match = re.search(r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", normalized)
    if match:
        days_ahead = (weekday_names[match.group(1)] - today.weekday()) % 7 or 7
        return (today + timedelta(days=days_ahead)).isoformat()
    match = re.search(r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b", normalized)
    if match:
        try:
            month = date.fromisoformat(f"{today.year}-{match.group(2)[:3]}-01").month
        except ValueError:
            month = {name: index for index, name in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)}[match.group(2)]
        return date(today.year, month, int(match.group(1))).isoformat()
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", normalized)
    if match:
        return date(today.year, int(match.group(2)), int(match.group(1))).isoformat()
    match = re.search(r"agle\s+mahine\s+ki\s+(\d{1,2})", normalized)
    if match:
        month = today.month % 12 + 1
        year = today.year + (1 if today.month == 12 else 0)
        return date(year, month, int(match.group(1))).isoformat()
    return None


class ChatWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, system_prompt: str, message: str, context: str, calendar_enabled: bool | None = None) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.message = message
        self.context = context
        self.calendar_enabled = calendar_enabled

    @Slot()
    def run(self) -> None:
        try:
            client = create_llm_client()
            reminder_intent = extract_reminder_intent(client, self.message)
            if is_reminder_request(self.message):
                self.completed.emit({"kind": "reminder", "intent": reminder_intent, "reply": format_reminder_confirmation(reminder_intent)})
                return
            intent = (
                MemoryIntent(operation="none", language="en")
                if is_calendar_question(self.message)
                else extract_memory_intent(client, self.message, self.context)
            )
            if intent.operation == "none":
                if is_calendar_question(self.message):
                    calendar = GoogleCalendarConnector(enabled=self.calendar_enabled)
                    reply = calendar.availability_at(self.message) or calendar.summary_for_context()
                elif intent.clarification:
                    reply = intent.response
                else:
                    personality = load_config().assistant.personality
                    reply = client.chat(
                        f"{self.system_prompt}\nUse this personality and tone: {personality}.\n"
                        f"Reply in {intent.language} (English, Hindi, or Hinglish) to match the user.",
                        [{"role": "user", "content": self.message}],
                    )
                    service_date = _service_date_text(self.message)
                    if service_date and "service" in self.message.lower():
                        reply = f"I understood the service date as {service_date}. Which vehicle should I associate it with?"
                    elif _is_echo(self.message, reply):
                        reply = (
                            f"I understood the service date as {service_date}. Which vehicle should I associate it with?"
                            if service_date
                            else "Which vehicle should I associate this service date with?"
                        )
            else:
                reply = intent.response
            self.completed.emit({"intent": intent, "reply": reply})
        except LLMError as error:
            self.failed.emit(f"AI unavailable: {error}")
        except ValueError as error:
            self.failed.emit(str(error))

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Chat UI that keeps provider calls off the GUI thread."""

    due_signal = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        icon_path = Path(__file__).resolve().parents[1] / "logo.ico"
        if icon_path.exists():
            app_icon = QIcon(str(icon_path))
            self.setWindowIcon(app_icon)
        self.setWindowTitle("Assistant")
        self.resize(900, 600)
        self.database = Database()
        self.thread: QThread | None = None
        self.worker: ChatWorker | None = None
        self.pending_intent: MemoryIntent | None = None
        self.pending_reminder: ReminderIntent | None = None
        self.last_reminder: dict | None = None

        self.messages = QListWidget()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message...")
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        self.input.returnPressed.connect(self.send_message)
        self.memory_button = QPushButton("Memory Manager")
        self.memory_button.clicked.connect(self.open_memory_manager)
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input)
        input_layout.addWidget(self.send_button)
        input_layout.addWidget(self.memory_button)
        input_layout.addWidget(self.settings_button)
        layout = QVBoxLayout()
        layout.addWidget(self.messages)
        layout.addLayout(input_layout)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.tray = QSystemTrayIcon(self)
        icon_path = Path(__file__).resolve().parents[1] / "logo.ico"
        if icon_path.exists():
            self.tray.setIcon(QIcon(str(icon_path)))
        self.tray.setToolTip("Assistant reminders")
        tray_menu = QMenu(self)
        self.snooze_action = QAction("Snooze 10 minutes", self)
        self.done_action = QAction("Mark reminder done", self)
        self.snooze_action.triggered.connect(self._snooze_last_reminder)
        self.done_action.triggered.connect(self._mark_last_reminder_done)
        tray_menu.addAction(self.snooze_action)
        tray_menu.addAction(self.done_action)
        self.tray.setContextMenu(tray_menu)
        self.tray.show()
        self.scheduler = ReminderScheduler(self.database, self._reminder_due)
        self.due_signal.connect(self._show_due_reminder)
        self.scheduler.start()
        self._load_conversation()
        self._trigger_daily_briefing_on_open()

    def _load_conversation(self) -> None:
        for message in self.database.get_conversation():
            speaker = "You" if message["role"] == "user" else "Assistant"
            self.messages.addItem(f"{speaker}: {message['content']}")
        self.messages.scrollToBottom()

    def _trigger_daily_briefing_on_open(self) -> None:
        if not should_generate_daily_briefing(self.database):
            return
        briefing = generate_daily_briefing(self.database)
        self.messages.addItem(f"Assistant: {briefing}")
        self.database.log_message("assistant", briefing)
        self.messages.scrollToBottom()

    @Slot()
    def send_message(self) -> None:
        message = self.input.text().strip()
        if not message or self.thread is not None:
            return
        self.messages.addItem(f"You: {message}")
        self.input.clear()
        self.database.log_message("user", message)
        if self.pending_reminder is not None:
            if self._is_confirmation(message) is not None or not self._looks_like_new_request(message):
                self._handle_reminder_confirmation(message)
                return
            self.pending_reminder = None
        if self.pending_intent is not None:
            if self._is_confirmation(message) is not None or not self._looks_like_new_request(message):
                self._handle_confirmation(message)
                return
            self.pending_intent = None
        self.messages.addItem("Assistant: thinking...")
        self.messages.scrollToBottom()
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)

        context = build_context(self.database)
        self.thread = QThread(self)
        self.worker = ChatWorker(
            f"{SYSTEM_PROMPT}\n\nCONTEXT BLOCK:\n{context}",
            message,
            context,
            self._calendar_enabled(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.completed.connect(self._handle_reply)
        self.worker.failed.connect(self._handle_failure)
        self.worker.completed.connect(self._finish_request)
        self.worker.failed.connect(self._finish_request)
        self.thread.finished.connect(self._clear_worker)
        self.thread.start()

    def _calendar_enabled(self) -> bool | None:
        stored = self.database.get_state("calendar_enabled")
        return None if stored is None else stored == "1"

    @Slot()
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.database, self)
        dialog.exec()

    @Slot(object)
    def _handle_reply(self, result: object) -> None:
        self.messages.takeItem(self.messages.count() - 1)
        if not isinstance(result, dict):
            return
        reply = str(result["reply"])
        if result.get("kind") == "reminder":
            self.pending_reminder = result["intent"] if result["intent"].operation == "add" else None
            self.messages.addItem(f"Assistant: {reply}")
            self.database.log_message("assistant", reply)
            self.messages.scrollToBottom()
            return
        intent = result["intent"]
        if isinstance(intent, MemoryIntent) and intent.operation in {"add", "edit", "delete"}:
            if intent.operation == "delete" and intent.memory_id is None:
                reply = self._localized(intent.language, "Please specify which memory to delete.", "कौन सी memory delete करनी है बताइए।", "Kaunsi memory delete karni hai, bataiye.")
            else:
                try:
                    if intent.operation in {"add", "edit"}:
                        intent.validated_details()
                    if intent.operation == "edit" and (intent.memory_id is None or self.database.get_memory(intent.memory_id) is None):
                        raise ValueError("Memory not found.")
                    self.pending_intent = intent
                    confirmation = self._confirmation_prompt(intent)
                    reply = f"{reply}\n{confirmation}" if reply else confirmation
                except ValueError as error:
                    reply = str(error)
        self.messages.addItem(f"Assistant: {reply}")
        self.database.log_message("assistant", reply)
        self.messages.scrollToBottom()

    def _confirmation_prompt(self, intent: MemoryIntent) -> str:
        action = {"add": "save", "edit": "update", "delete": "delete"}[intent.operation]
        details = ", ".join(f"{key}: {value}" for key, value in intent.details.items())
        date_summary = f", {intent.date_type}: {intent.date_value}" if intent.date_value and intent.date_type else ""
        summary = f"{intent.title or 'this memory'} ({details}{date_summary})"
        return self._localized(
            intent.language,
            f"I found this memory: {summary}. Should I {action} it? Please reply yes or no.",
            f"मुझे यह जानकारी मिली: {summary}। क्या मैं इसे {action} कर दूँ? कृपया हाँ या नहीं लिखें।",
            f"Mujhe yeh memory mili: {summary}. Kya main ise {action} kar doon? Haan ya nahi likhiye.",
        )

    @staticmethod
    def _localized(language: str, english: str, hindi: str, hinglish: str) -> str:
        return {"hi": hindi, "hinglish": hinglish}.get(language, english)

    @staticmethod
    def _is_confirmation(message: str) -> bool | None:
        normalized = message.lower().strip().strip(".!?")
        if normalized in {"yes", "y", "haan", "han", "ha", "ji", "हाँ", "हां", "हूँ", "जी"}:
            return True
        if normalized in {"no", "n", "nahi", "nahin", "na", "नहीं", "नही"}:
            return False
        return None

    @staticmethod
    def _looks_like_new_request(message: str) -> bool:
        normalized = message.lower()
        return any(
            keyword in normalized
            for keyword in ("add", "save", "remember", "delete", "remove", "edit", "update", "insurance", "vehicle", "memory", "remind", "reminder")
        )

    def _handle_reminder_confirmation(self, message: str) -> None:
        intent = self.pending_reminder
        if intent is None:
            return
        decision = self._is_confirmation(message)
        if decision is None:
            reply = format_reminder_confirmation(intent)
        elif not decision:
            self.pending_reminder = None
            reply = "Reminder cancelled."
        else:
            save_reminder(self.database, intent)
            self.pending_reminder = None
            reply = "Reminder saved."
        self.messages.addItem(f"Assistant: {reply}")
        self.database.log_message("assistant", reply)
        self.messages.scrollToBottom()

    def _reminder_due(self, reminder: dict) -> None:
        self.due_signal.emit(reminder)

    @Slot(object)
    def _show_due_reminder(self, reminder: dict) -> None:
        self.last_reminder = reminder
        self.snooze_action.setEnabled(True)
        self.done_action.setEnabled(True)
        try:
            show_reminder_notification(reminder["text"], reminder["due_at"], reminder["missed"])
        except Exception:
            self.messages.addItem(f"Assistant: Reminder due: {reminder['text']}")

    def _snooze_last_reminder(self) -> None:
        if self.last_reminder is None:
            return
        reminder = self.last_reminder
        new_due = (datetime.fromisoformat(reminder["due_at"]) + timedelta(minutes=10)).isoformat(timespec="seconds")
        self.database.update_reminder(reminder["id"], new_due, "pending")

    def _mark_last_reminder_done(self) -> None:
        if self.last_reminder is not None:
            self.database.update_reminder_status(self.last_reminder["id"], "done")
            self.last_reminder = None

    def closeEvent(self, event: object) -> None:
        self.scheduler.stop()
        self.tray.hide()
        super().closeEvent(event)

    def _handle_confirmation(self, message: str) -> None:
        intent = self.pending_intent
        decision = self._is_confirmation(message)
        if intent is None:
            return
        if decision is None:
            reply = self._confirmation_prompt(intent)
        elif not decision:
            self.pending_intent = None
            reply = self._localized(intent.language, "Cancelled.", "रद्द कर दिया गया।", "Cancel kar diya.")
        else:
            try:
                if intent.operation == "delete":
                    if intent.memory_id is None:
                        raise ValueError("Memory not found.")
                    self.database.delete_memory(intent.memory_id)
                else:
                    apply_memory_action(self.database, intent)
                self.pending_intent = None
                reply = self._localized(
                    intent.language,
                    "Done. Memory deleted." if intent.operation == "delete" else "Done. Memory saved.",
                    "ठीक है, memory delete कर दी।" if intent.operation == "delete" else "ठीक है, memory save कर दी।",
                    "Theek hai, memory delete kar di." if intent.operation == "delete" else "Theek hai, memory save kar di.",
                )
            except ValueError as error:
                self.pending_intent = None
                reply = str(error)
        self.messages.addItem(f"Assistant: {reply}")
        self.database.log_message("assistant", reply)
        self.messages.scrollToBottom()

    def open_memory_manager(self) -> None:
        MemoryManagerDialog(self.database, self).exec()

    @Slot(str)
    def _handle_failure(self, error: str) -> None:
        self.messages.takeItem(self.messages.count() - 1)
        self.messages.addItem(f"Assistant: {error}")
        self.messages.scrollToBottom()

    @Slot()
    def _finish_request(self) -> None:
        if self.thread is not None:
            self.thread.quit()

    @Slot()
    def _clear_worker(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None
        self.input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.input.setFocus()

    def closeEvent(self, event: object) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
        super().closeEvent(event)
