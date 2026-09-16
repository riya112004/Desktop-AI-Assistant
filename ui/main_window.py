"""Main application window."""

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Empty shell for the assistant's main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Assistant")
        self.resize(900, 600)
