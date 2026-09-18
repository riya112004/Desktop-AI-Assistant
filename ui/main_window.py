"""Main chat window with non-blocking LLM calls."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.context_engine import SYSTEM_PROMPT, build_context
from core.llm_client import LLMError, create_llm_client
from db.database import Database


class ChatWorker(QObject):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, system_prompt: str, message: str) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.message = message

    @Slot()
    def run(self) -> None:
        try:
            reply = create_llm_client().chat(
                self.system_prompt,
                [{"role": "user", "content": self.message}],
            )
        except LLMError as error:
            self.failed.emit(f"AI unavailable: {error}")
            return
        self.completed.emit(reply)

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Chat UI that keeps provider calls off the GUI thread."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Assistant")
        self.resize(900, 600)
        self.database = Database()
        self.thread: QThread | None = None
        self.worker: ChatWorker | None = None

        self.messages = QListWidget()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message...")
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        self.input.returnPressed.connect(self.send_message)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input)
        input_layout.addWidget(self.send_button)
        layout = QVBoxLayout()
        layout.addWidget(self.messages)
        layout.addLayout(input_layout)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    @Slot()
    def send_message(self) -> None:
        message = self.input.text().strip()
        if not message or self.thread is not None:
            return
        self.messages.addItem(f"You: {message}")
        self.input.clear()
        self.messages.addItem("Assistant: thinking...")
        self.messages.scrollToBottom()
        self.input.setEnabled(False)
        self.send_button.setEnabled(False)

        context = build_context(self.database)
        self.database.log_message("user", message)
        self.thread = QThread(self)
        self.worker = ChatWorker(f"{SYSTEM_PROMPT}\n\nCONTEXT BLOCK:\n{context}", message)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.completed.connect(self._handle_reply)
        self.worker.failed.connect(self._handle_failure)
        self.worker.completed.connect(self._finish_request)
        self.worker.failed.connect(self._finish_request)
        self.thread.finished.connect(self._clear_worker)
        self.thread.start()

    @Slot(str)
    def _handle_reply(self, reply: str) -> None:
        self.messages.takeItem(self.messages.count() - 1)
        self.messages.addItem(f"Assistant: {reply}")
        self.database.log_message("assistant", reply)
        self.messages.scrollToBottom()

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
