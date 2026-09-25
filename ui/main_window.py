"""Main chat window with non-blocking LLM calls."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QSize, Signal, Slot, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
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
from features.memory import (
    MemoryIntent,
    apply_memory_action,
    extract_memory_intent,
    is_calendar_question,
    is_memory_candidate,
)
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
from ui.reminder_manager import ReminderManagerDialog
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


def _is_time_question(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    if "time" in normalized and any(marker in normalized for marker in ("abhi", "bata", "bta", "current")):
        return True
    return any(
        phrase in normalized
        for phrase in (
            "what time is it",
            "what time is today",
            "what's the time",
            "what is the time",
            "time today",
            "current time",
            "time kya",
            "abhi time",
            "kitne baje",
            "kya time",
            "samay kya",
            "waqt kya",
        )
    )


def _greeting_reply(message: str) -> str | None:
    normalized = " ".join(message.lower().strip().split()).strip(".!?").strip()
    if normalized in {"hi", "hello", "hey", "hii", "helo"}:
        return "Hi! How can I help you?"
    if normalized in {"kaise ho", "kaisi ho", "how are you", "how r you"}:
        return "Main theek hoon! Aapki kaise help karun?"
    return None


def _needs_personal_context(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    return any(
        marker in normalized
        for marker in (
            "reminder", "remember", "birthday", "insurance", "vehicle", "calendar",
            "meeting", "weather", "memory", "my ", "mere ", "meri ", "today", "tomorrow",
            "upcoming",
        )
    )


def _capability_reply(message: str) -> str | None:
    normalized = " ".join(message.lower().split())
    markers = (
        "what can you help", "how can you help", "what do you do",
        "tum meri help", "tum kya kar", "kya kr skte", "kaise help kar",
        "what are your capabilities",
    )
    if not any(marker in normalized for marker in markers):
        return None
    return (
        "Main aapki memories save aur manage kar sakta hoon, reminders set karke "
        "notifications de sakta hoon, birthdays aur important dates track kar sakta hoon, "
        "Google Calendar se meetings/free time check kar sakta hoon, weather aur daily "
        "briefing de sakta hoon, aur aapke din ke tasks prioritize karne me help kar sakta hoon. "
        "Aap mujhse English, Hindi ya Hinglish me baat kar sakti hain."
    )


class ChatMessageDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: object) -> None:
        painter.save()
        text = str(index.data(Qt.ItemDataRole.DisplayRole))  # type: ignore[union-attr]
        is_user = text.startswith("You:")
        content = text.split(":", 1)[1].strip() if ":" in text else text
        available_width = max(180, option.rect.width() - 72)
        font = option.font
        metrics = painter.fontMetrics()
        text_rect = metrics.boundingRect(0, 0, available_width - 28, 0, Qt.TextFlag.TextWordWrap, content)
        bubble_width = min(available_width, max(150, text_rect.width() + 28))
        bubble_height = max(42, text_rect.height() + 24)
        x = option.rect.right() - bubble_width - 16 if is_user else option.rect.left() + 16
        y = option.rect.top() + 7
        bubble = option.rect.__class__(x, y, bubble_width, bubble_height)
        painter.setPen(QPen(Qt.GlobalColor.transparent))
        painter.setBrush(QColor("#dce8ff") if is_user else QColor("#ffffff"))
        painter.drawRoundedRect(bubble, 12, 12)
        painter.setPen(QColor("#1d2a42"))
        painter.setFont(font)
        painter.drawText(bubble.adjusted(14, 11, -14, -11), Qt.TextFlag.TextWordWrap, content)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: object) -> QSize:
        text = str(index.data(Qt.ItemDataRole.DisplayRole))  # type: ignore[union-attr]
        content = text.split(":", 1)[1].strip() if ":" in text else text
        width = max(180, option.rect.width() - 72)
        height = option.fontMetrics.boundingRect(0, 0, width - 28, 0, Qt.TextFlag.TextWordWrap, content).height()
        return QSize(width, max(56, height + 38))


class ChatWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, system_prompt: str, message: str, database: Database, calendar_enabled: bool | None = None) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.message = message
        self.database = database
        self.calendar_enabled = calendar_enabled

    @Slot()
    def run(self) -> None:
        try:
            client = create_llm_client()
            if _is_time_question(self.message):
                now = datetime.now().astimezone()
                self.completed.emit({"kind": "time", "reply": now.strftime("It is %I:%M %p on %d %B %Y.")})
                return
            greeting = _greeting_reply(self.message)
            if greeting is not None:
                self.completed.emit({"kind": "greeting", "reply": greeting})
                return
            capability_reply = _capability_reply(self.message)
            if capability_reply is not None:
                self.completed.emit({"kind": "capability", "reply": capability_reply})
                return
            reminder_intent = extract_reminder_intent(client, self.message)
            if is_reminder_request(self.message):
                self.completed.emit({"kind": "reminder", "intent": reminder_intent, "reply": format_reminder_confirmation(reminder_intent)})
                return
            calendar_question = is_calendar_question(self.message)
            memory_candidate = is_memory_candidate(self.message)
            context = build_context(self.database) if calendar_question or memory_candidate or _needs_personal_context(self.message) else "(No personal context needed for this general question.)"
            intent = (
                MemoryIntent(operation="none", language="en")
                if calendar_question or not memory_candidate
                else extract_memory_intent(client, self.message, context)
            )
            if intent.operation == "none":
                if calendar_question:
                    calendar = GoogleCalendarConnector(enabled=self.calendar_enabled)
                    reply = calendar.availability_at(self.message) or calendar.summary_for_context()
                elif intent.clarification:
                    reply = intent.response
                else:
                    personality = load_config().assistant.personality
                    reply = client.chat(
                        f"{self.system_prompt}\n\nCONTEXT BLOCK:\n{context}\n"
                        f"Use this personality and tone: {personality}.\n"
                        f"Reply in {intent.language} (English, Hindi, or Hinglish) to match the user.",
                        [{"role": "user", "content": self.message}],
                    )
                    service_date = _service_date_text(self.message)
                    if service_date and "service" in self.message.lower():
                        reply = f"I understood the service date as {service_date}. Which vehicle should I associate it with?"
                    elif _is_echo(self.message, reply):
                        reply = "I received your message, but I could not understand the request. Please rephrase it."
            else:
                reply = intent.response
            self.completed.emit({"intent": intent, "reply": reply})
        except LLMError as error:
            self.failed.emit(f"AI unavailable: {error}")
        except ValueError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"Assistant error: {error}")

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
        self.resize(980, 680)
        self.setMinimumSize(720, 480)
        self.setStyleSheet(
            """
            QMainWindow { background: #f4f7fb; }
            QWidget { font-family: Segoe UI; font-size: 10pt; color: #172033; }
            QLabel#appTitle { font-size: 20pt; font-weight: 700; color: #172033; }
            QLabel#appSubtitle { color: #65728a; }
            QLabel#statusLabel { color: #2f7d5b; font-weight: 600; }
            QListWidget { background: #ffffff; border: 1px solid #dce3ee; border-radius: 12px; padding: 12px; outline: none; }
            QListWidget::item { padding: 10px 12px; border-bottom: 1px solid #eef2f7; }
            QListWidget::item:selected { background: #e8f0ff; color: #172033; }
            QLineEdit { background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 11px 13px; }
            QLineEdit:focus { border: 2px solid #4f7cff; padding: 10px 12px; }
            QPushButton { background: #e8eef8; border: 0; border-radius: 9px; padding: 10px 14px; font-weight: 600; }
            QPushButton:hover { background: #d8e4fb; }
            QPushButton#sendButton { background: #4f7cff; color: white; min-width: 76px; }
            QPushButton#sendButton:hover { background: #3d68dc; }
            QPushButton:disabled { background: #dce3ee; color: #8995a8; }
            """
        )
        self.database = Database()
        self.thread: QThread | None = None
        self.worker: ChatWorker | None = None
        self.pending_intent: MemoryIntent | None = None
        self.pending_reminder: ReminderIntent | None = None
        self.last_reminder: dict | None = None

        header = QVBoxLayout()
        title = QLabel("Desktop AI Assistant")
        title.setObjectName("appTitle")
        subtitle = QLabel("Your conversations, reminders, memories and calendar in one place")
        subtitle.setObjectName("appSubtitle")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addWidget(self.status_label)

        self.messages = QListWidget()
        self.messages.setWordWrap(True)
        self.messages.setSpacing(2)
        self.messages.setItemDelegate(ChatMessageDelegate(self.messages))
        self.messages.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask anything, save a memory, or set a reminder...")
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self.send_message)
        self.input.returnPressed.connect(self.send_message)
        self.memory_button = QPushButton("Memory Manager")
        self.memory_button.clicked.connect(self.open_memory_manager)
        self.reminder_button = QPushButton("Reminders")
        self.reminder_button.clicked.connect(self.open_reminder_manager)
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input)
        input_layout.addWidget(self.send_button)
        input_layout.addWidget(self.memory_button)
        input_layout.addWidget(self.reminder_button)
        input_layout.addWidget(self.settings_button)
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)
        layout.addLayout(header)
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
        calendar = GoogleCalendarConnector(enabled=self._calendar_enabled())
        briefing = generate_daily_briefing(
            self.database,
            calendar_summary=calendar.summary_for_context(),
        )
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
        self.status_label.setText("Thinking...")
        self.messages.scrollToBottom()
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)

        self.thread = QThread(self)
        self.worker = ChatWorker(
            SYSTEM_PROMPT,
            message,
            self.database,
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
        if result.get("kind") in {"time", "greeting", "capability"}:
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

    def open_reminder_manager(self) -> None:
        ReminderManagerDialog(self.database, self).exec()

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
        self.status_label.setText("Ready")
        self.input.setFocus()

    def closeEvent(self, event: object) -> None:
        self.scheduler.stop()
        self.tray.hide()
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
        super().closeEvent(event)
