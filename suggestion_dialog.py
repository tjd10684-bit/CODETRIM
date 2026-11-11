from decimal import Decimal

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from group_suggestions import GroupSuggestion


def _coordinate(value):
    number = Decimal(value.numerator) / Decimal(value.denominator)
    return format(number, ".8f")


class SuggestionDialog(QDialog):
    def __init__(self, analysis, accept_suggestion, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Suggested Highlight Groups")
        self.resize(900, 600)
        self._suggestions = list(analysis.suggestions)
        self._selected = [
            {operation.marker_index for operation in suggestion.operations}
            for suggestion in self._suggestions
        ]
        self._analysis = analysis
        self._accept_suggestion = accept_suggestion

        layout = QVBoxLayout(self)
        self.notice = QLabel(
            "Suggestions compare programmed hole locations, not machine simulation. "
            "Review the operations and locations before accepting."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.summary = QLabel()
        layout.addWidget(self.summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Suggestions"))
        self.suggestion_list = QListWidget()
        left_layout.addWidget(self.suggestion_list)
        left_layout.addWidget(QLabel("Operations to include"))
        self.operation_list = QListWidget()
        left_layout.addWidget(self.operation_list)
        splitter.addWidget(left_panel)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        splitter.addWidget(self.details)
        splitter.setSizes([320, 580])
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.accept_button = QPushButton("Accept Suggestion...")
        self.dismiss_button = QPushButton("Dismiss")
        close_button = QPushButton("Close")
        buttons.addWidget(self.accept_button)
        buttons.addWidget(self.dismiss_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.suggestion_list.currentRowChanged.connect(self.update_details)
        self.operation_list.itemChanged.connect(self.update_selection)
        self.accept_button.clicked.connect(self.accept_selected)
        self.dismiss_button.clicked.connect(self.dismiss_selected)
        close_button.clicked.connect(self.close)
        self.refresh()

    def refresh(self):
        self.suggestion_list.clear()
        for index, suggestion in enumerate(self._suggestions, 1):
            operation = suggestion.operations[0]
            self.suggestion_list.addItem(
                f"Suggestion {index}: {len(suggestion.operations)} operations, "
                f"{len(operation.locations)} locations ({operation.work_offset})"
            )
        self.summary.setText(
            f"{len(self._suggestions)} suggestion(s); "
            f"{len(self._analysis.skipped)} operation(s) skipped."
        )
        if self._suggestions:
            self.suggestion_list.setCurrentRow(0)
        else:
            self.update_details(-1)

    def update_details(self, row):
        valid = 0 <= row < len(self._suggestions)
        self.operation_list.blockSignals(True)
        self.operation_list.clear()
        if valid:
            for operation in self._suggestions[row].operations:
                item = QListWidgetItem(
                    f"{operation.marker_line} | {operation.tool} | {operation.description}"
                )
                item.setData(Qt.ItemDataRole.UserRole, operation.marker_index)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if operation.marker_index in self._selected[row]
                    else Qt.CheckState.Unchecked
                )
                item.setToolTip(operation.description)
                self.operation_list.addItem(item)
        self.operation_list.blockSignals(False)
        self.render_details(row)

    def update_selection(self, item):
        row = self.suggestion_list.currentRow()
        if not 0 <= row < len(self._suggestions):
            return
        marker = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected[row].add(marker)
        else:
            self._selected[row].discard(marker)
        self.render_details(row)

    def render_details(self, row):
        valid = 0 <= row < len(self._suggestions)
        self.accept_button.setEnabled(valid and len(self._selected[row]) >= 2)
        self.dismiss_button.setEnabled(valid)
        lines = [
            "Matching tolerance: 0.01 inch per X and Y axis.",
            "Only complete matching hole sets with the same work offset and programmed rotary values are suggested.",
            "Unprogrammed rotary positions are unknown.",
            "Only G17 G73 and G81-G89 canned cycles are analyzed; other cycles, contour, and helical operations are not.",
            "Machine-specific behavior is not simulated. Verify all suggestions.",
            "Coordinates below are in inches, rounded to eight decimal places.",
            "Uncheck any operations that do not belong; at least two are required.",
            "Accepting highlights the listed M01 or M06 marker lines; "
            "preview settings determine which markers are visible.",
            "",
        ]
        if valid:
            for operation in self._suggestions[row].operations:
                orientation = " ".join(
                    f"{axis}={value if value is not None else 'unspecified'}"
                    for axis, value in zip("ABC", operation.orientation)
                )
                lines.extend([
                    f"{'Included' if operation.marker_index in self._selected[row] else 'Excluded'} - "
                    f"source line {operation.marker_index + 1}: {operation.marker_line}",
                    f"Tool: {operation.tool} | Work offset: {operation.work_offset}",
                    f"Programmed rotary positions: {orientation}",
                    f"Operation: {operation.description}",
                    "Hole locations:",
                ])
                lines.extend(
                    f"  X{_coordinate(x)}  Y{_coordinate(y)}"
                    for x, y in operation.locations
                )
                lines.append("")
        else:
            lines.append("No suggestions to review.")
            lines.append("")
        if self._analysis.warnings:
            lines.append("Analysis limitations:")
            lines.extend(f"  {warning}" for warning in self._analysis.warnings)
            lines.append("")
        if self._analysis.skipped:
            lines.append("Skipped operations:")
            for operation in self._analysis.skipped:
                lines.append(
                    f"  Source line {operation.marker_index + 1}: "
                    f"{operation.marker_line} - {' '.join(operation.reasons)}"
                )
        self.details.setPlainText("\n".join(lines))

    def accept_selected(self):
        row = self.suggestion_list.currentRow()
        if not 0 <= row < len(self._suggestions) or len(self._selected[row]) < 2:
            return
        suggestion = GroupSuggestion(tuple(
            operation for operation in self._suggestions[row].operations
            if operation.marker_index in self._selected[row]
        ))
        if self._accept_suggestion(suggestion, self):
            self._suggestions.pop(row)
            self._selected.pop(row)
            self.refresh()

    def dismiss_selected(self):
        row = self.suggestion_list.currentRow()
        if 0 <= row < len(self._suggestions):
            self._suggestions.pop(row)
            self._selected.pop(row)
            self.refresh()
