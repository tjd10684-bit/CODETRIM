from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class FindDialog(QDialog):
    def __init__(self, parent, current_preview):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle("Find in Preview")
        self.setModal(False)
        self._current_preview = current_preview

        layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Find:"))
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search the active preview")
        search_row.addWidget(self.search_entry, 1)
        layout.addLayout(search_row)

        controls = QHBoxLayout()
        self.match_case = QCheckBox("Match case")
        controls.addWidget(self.match_case)
        controls.addStretch()
        self.previous_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.previous_button.setAutoDefault(False)
        self.next_button.setAutoDefault(False)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        layout.addLayout(controls)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.resize(420, self.sizeHint().height())

        self.search_entry.returnPressed.connect(self.find_next)
        self.search_entry.textChanged.connect(self.clear_status)
        self.match_case.toggled.connect(self.clear_status)
        self.previous_button.clicked.connect(self.find_previous)
        self.next_button.clicked.connect(self.find_next)
        self.finished.connect(lambda _result: self._current_preview().setFocus())

    def open_find(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.search_entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_entry.selectAll()

    def clear_status(self, *_args):
        self.status.clear()

    def find_next(self):
        self._find(backwards=False)

    def find_previous(self):
        self._find(backwards=True)

    def _find(self, backwards):
        term = self.search_entry.text()
        if not term:
            self.status.setText("Enter text to search.")
            self.search_entry.setFocus()
            return

        preview = self._current_preview()
        flags = QTextDocument.FindFlag(0)
        if backwards:
            flags |= QTextDocument.FindFlag.FindBackward
        if self.match_case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively

        original_cursor = preview.textCursor()
        wrapped = False
        if not preview.find(term, flags):
            cursor = preview.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.End if backwards else QTextCursor.MoveOperation.Start
            )
            preview.setTextCursor(cursor)
            wrapped = True
            if not preview.find(term, flags):
                preview.setTextCursor(original_cursor)
                self.status.setText("No matches in the active preview.")
                return

        preview.ensureCursorVisible()
        if wrapped:
            self.status.setText("Wrapped to the end." if backwards else "Wrapped to the beginning.")
        else:
            self.status.setText("Match found.")
