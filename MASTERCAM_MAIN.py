import configparser
import copy
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFontDatabase, QIcon, QKeySequence, QPainter, QPalette, QPixmap, QShortcut, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from color_utils import contrasting_text_color
from find_dialog import FindDialog
from gcode_highlighter import GCodeHighlighter
from group_palette import GROUP_COLOR_VALUES, choose_group_color, nearest_group_color
from group_markers import assigned_markers, key_rows, marker_width, paint_marker
from group_suggestions import analyze_group_suggestions
from highlight_groups import (
    HighlightGroup,
    load_highlight_groups,
    save_highlight_groups,
    source_hash,
)
from nc_commands import count_search_code, read_nc_lines
from index_generator import INDEX_SEPARATOR, index_header_lines
from output_document import write_text_output
from pdf_export import create_pdf
from preview_manager import get_index_document, get_manuscript_document
from project_settings import load_project_settings, save_project_settings
from suggestion_dialog import SuggestionDialog


class FileEntry(QLineEdit):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.file_dropped.emit(urls[0].toLocalFile())
            event.acceptProposedAction()
        else:
            event.ignore()


class PreviewEdit(QPlainTextEdit):
    line_clicked = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._markers = {}
        self._key_markers = {}
        self._sources = []
        self._gutter = PreviewGutter(self)
        self.updateRequest.connect(self.update_gutter)
        self.syntax_highlighter = GCodeHighlighter(self.document())

    def set_markers(self, sources, markers, key_markers=None):
        self._sources = sources
        self._markers = markers
        self._key_markers = key_markers or {}
        count = max((marker.number for marker in markers.values()), default=0)
        width = int(marker_width(self.font(), self, count) + 4)
        self.setViewportMargins(width, 0, 0, 0)
        self._gutter.setGeometry(0, self.contentsRect().top(), width, self.contentsRect().height())
        self._gutter.update()
        self.viewport().update()

    def update_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._gutter.setGeometry(0, self.contentsRect().top(), self._gutter.width(), self.contentsRect().height())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        block = self.firstVisibleBlock()
        while block.isValid():
            top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
            if top > event.rect().bottom():
                break
            for column, marker in self._key_markers.get(block.blockNumber(), []):
                cursor = QTextCursor(block)
                cursor.setPosition(block.position() + len(block.text()[:column].encode("utf-16-le")) // 2)
                rect = self.cursorRect(cursor)
                width = marker_width(self.font(), self, marker.number)
                paint_marker(painter, QRectF(rect.x(), rect.y(), width, rect.height()), marker, self.font())
            block = block.next()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "syntax_highlighter"):
            self.syntax_highlighter.set_background(self.palette().color(QPalette.ColorRole.Base))

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            block = self.cursorForPosition(event.position().toPoint()).blockNumber()
            self.line_clicked.emit(block, event.modifiers().value)


class PreviewGutter(QWidget):
    def __init__(self, preview):
        super().__init__(preview)
        self.preview = preview

    def paintEvent(self, event):
        painter = QPainter(self)
        block = self.preview.firstVisibleBlock()
        while block.isValid():
            top = self.preview.blockBoundingGeometry(block).translated(self.preview.contentOffset()).top()
            height = self.preview.blockBoundingRect(block).height()
            if top > event.rect().bottom():
                break
            number = block.blockNumber()
            source = self.preview._sources[number] if number < len(self.preview._sources) else None
            marker = self.preview._markers.get(source)
            if marker is not None:
                paint_marker(painter, QRectF(1, top, self.width() - 3, min(height, self.preview.fontMetrics().height())), marker, self.preview.font())
            block = block.next()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gcode Trim Tool")
        self.resize(1200, 820)
        self.setMinimumSize(800, 560)
        self._loading = False
        self._group_key = None
        self._group_state = None
        self._selected_lines = set()
        self._anchor_block = None
        self._preview_sources = {}

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel("Gcode Trim Tool")
        title.setObjectName("title")
        layout.addWidget(title)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        layout.addWidget(self.main_splitter, 1)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setMinimumWidth(250)
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        self.settings_scroll.setWidget(settings_widget)
        self.main_splitter.addWidget(self.settings_scroll)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.main_splitter.addWidget(preview_panel)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setSizes([400, 800])

        file_group = QGroupBox("Program File")
        file_layout = QHBoxLayout(file_group)
        self.file_entry = FileEntry()
        self.file_entry.setPlaceholderText("Select or drop a G-code program")
        file_layout.addWidget(self.file_entry, 1)
        browse_button = QPushButton("Browse")
        file_layout.addWidget(browse_button)
        settings_layout.addWidget(file_group)

        header_group = QGroupBox("Index Header Information")
        header_layout = QFormLayout(header_group)
        header_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.customer_entry = QLineEdit()
        self.part_number_entry = QLineEdit()
        self.notes_text = QPlainTextEdit()
        self.notes_text.setMaximumHeight(70)
        clear_notes = QPushButton("Clear Notes")
        header_layout.addRow("Customer", self.customer_entry)
        header_layout.addRow("Part Number", self.part_number_entry)
        header_layout.addRow("Notes", self.notes_text)
        header_layout.addRow(clear_notes)
        settings_layout.addWidget(header_group)

        search_group = QGroupBox("Search Settings")
        search_layout = QFormLayout(search_group)
        search_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.search_code = QComboBox()
        self.search_code.addItems(["M01", "M06", "G28"])
        search_layout.addRow("Search For (after first M06)", self.search_code)
        self.search_count = QLabel()
        search_layout.addRow(self.search_count)
        settings_layout.addWidget(search_group)

        index_group = QGroupBox("Index Settings")
        index_layout = QFormLayout(index_group)
        index_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.index_m06 = self._line_count(3)
        self.index_before = self._line_count(0)
        self.index_after = self._line_count(2)
        self.index_before_label = QLabel()
        self.index_after_label = QLabel()
        index_layout.addRow("Lines Before First M06", self.index_m06)
        index_layout.addRow(self.index_before_label, self.index_before)
        index_layout.addRow(self.index_after_label, self.index_after)
        settings_layout.addWidget(index_group)

        manuscript_group = QGroupBox("Manuscript Settings")
        manuscript_layout = QFormLayout(manuscript_group)
        manuscript_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.manuscript_m06 = self._line_count(20)
        self.manuscript_around = self._line_count(20)
        self.manuscript_around_label = QLabel()
        manuscript_layout.addRow("Lines After First M06", self.manuscript_m06)
        manuscript_layout.addRow(self.manuscript_around_label, self.manuscript_around)
        settings_layout.addWidget(manuscript_group)

        options_group = QGroupBox("Output Options")
        options_layout = QVBoxLayout(options_group)
        self.index_enabled = QCheckBox("Generate Index File")
        self.manuscript_enabled = QCheckBox("Generate Manuscript")
        self.index_enabled.setChecked(True)
        self.manuscript_enabled.setChecked(True)
        options_layout.addWidget(self.index_enabled)
        options_layout.addWidget(self.manuscript_enabled)
        format_layout = QFormLayout()
        self.output_format = QComboBox()
        self.output_format.addItem("PDF", "pdf")
        self.output_format.addItem("Text (.nc)", "text")
        self.output_format.addItem("PDF and text (.nc)", "both")
        format_layout.addRow("Format", self.output_format)
        options_layout.addLayout(format_layout)
        settings_layout.addWidget(options_group)

        generate_button = QPushButton("Generate")
        settings_layout.addWidget(generate_button)
        settings_layout.addStretch()

        find_layout = QHBoxLayout()
        find_layout.addStretch()
        find_button = QPushButton("Find...")
        find_button.setToolTip("Find text in the active preview (Ctrl+F)")
        find_layout.addWidget(find_button)
        preview_layout.addLayout(find_layout)

        self.preview_tabs = QTabWidget()
        self.index_preview = PreviewEdit()
        self.manuscript_preview = PreviewEdit()
        for preview in (self.index_preview, self.manuscript_preview):
            preview.setReadOnly(True)
            preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview_tabs.addTab(self.index_preview, "Index Preview")
        self.preview_tabs.addTab(self.manuscript_preview, "Manuscript Preview")
        preview_layout.addWidget(self.preview_tabs, 1)
        self.find_dialog = FindDialog(self, self.current_preview)
        self.find_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        self.find_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.find_shortcut.activated.connect(self.find_dialog.open_find)
        self.find_next_shortcut = QShortcut(QKeySequence("F3"), self)
        self.find_next_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.find_next_shortcut.activated.connect(self.find_next)
        self.find_previous_shortcut = QShortcut(QKeySequence("Shift+F3"), self)
        self.find_previous_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.find_previous_shortcut.activated.connect(self.find_previous)
        find_button.clicked.connect(self.find_dialog.open_find)
        self.preview_tabs.currentChanged.connect(self.find_dialog.clear_status)
        for preview in (self.index_preview, self.manuscript_preview):
            preview.textChanged.connect(self.find_dialog.clear_status)

        self.preview_status = QLabel("Select a program file to preview.")
        self.preview_status.setWordWrap(True)
        preview_layout.addWidget(self.preview_status)
        self.group_panel = QGroupBox("Highlight Groups")
        group_layout = QVBoxLayout(self.group_panel)
        instructions = QLabel(
            "Click a preview line to select it. Ctrl-click adds or removes lines; "
            "Shift-click selects a range. Select a group and assign the lines."
        )
        instructions.setWordWrap(True)
        group_layout.addWidget(instructions)
        group_row = QHBoxLayout()
        self.group_select = QComboBox()
        group_row.addWidget(self.group_select, 1)
        new_group = QPushButton("New")
        edit_group = QPushButton("Edit")
        delete_group = QPushButton("Delete")
        for button in (new_group, edit_group, delete_group):
            group_row.addWidget(button)
        group_layout.addLayout(group_row)
        selection_row = QGridLayout()
        assign_button = QPushButton("Assign Selected")
        unassign_button = QPushButton("Remove from Groups")
        clear_selection = QPushButton("Clear Selection")
        suggest_button = QPushButton("Suggest Groups...")
        selection_row.addWidget(assign_button, 0, 0)
        selection_row.addWidget(unassign_button, 0, 1)
        selection_row.addWidget(clear_selection, 1, 0)
        self.selection_status = QLabel()
        selection_row.addWidget(self.selection_status, 1, 1)
        selection_row.addWidget(suggest_button, 2, 0, 1, 2)
        group_layout.addLayout(selection_row)
        self.unmatched_status = QLabel()
        self.unmatched_status.setWordWrap(True)
        group_layout.addWidget(self.unmatched_status)
        self.unmatched_list = QPlainTextEdit()
        self.unmatched_list.setReadOnly(True)
        self.unmatched_list.setMaximumHeight(120)
        group_layout.addWidget(self.unmatched_list)
        self.discard_unmatched_button = QPushButton("Discard Unmatched Assignments")
        group_layout.addWidget(self.discard_unmatched_button)
        preview_layout.addWidget(self.group_panel)

        browse_button.clicked.connect(self.browse_file)
        self.file_entry.editingFinished.connect(self.load_project_information)
        self.file_entry.file_dropped.connect(self.select_file)
        clear_notes.clicked.connect(self.notes_text.clear)
        self.search_code.currentTextChanged.connect(self.update_search_labels)
        self.search_code.currentTextChanged.connect(self.update_preview)
        self.preview_tabs.currentChanged.connect(self.update_preview)
        for widget in (
            self.index_m06,
            self.index_before,
            self.index_after,
            self.manuscript_m06,
            self.manuscript_around,
        ):
            widget.valueChanged.connect(self.update_preview)
        self.customer_entry.textChanged.connect(self.update_preview)
        self.part_number_entry.textChanged.connect(self.update_preview)
        self.notes_text.textChanged.connect(self.update_preview)
        generate_button.clicked.connect(self.generate)
        new_group.clicked.connect(self.new_group)
        edit_group.clicked.connect(self.edit_group)
        delete_group.clicked.connect(self.delete_group)
        assign_button.clicked.connect(self.assign_selected)
        unassign_button.clicked.connect(self.unassign_selected)
        clear_selection.clicked.connect(self.clear_selection)
        suggest_button.clicked.connect(self.suggest_groups)
        self.discard_unmatched_button.clicked.connect(self.discard_unmatched)
        for preview in (self.index_preview, self.manuscript_preview):
            preview.line_clicked.connect(self.select_preview_line)
        self.update_search_labels()
        self.refresh_group_controls()

    @staticmethod
    def _line_count(value):
        spinbox = QSpinBox()
        spinbox.setRange(0, 2_147_483_647)
        spinbox.setMaximumWidth(110)
        spinbox.setValue(value)
        return spinbox

    def selected_file(self):
        file_path = self.file_entry.text().strip()
        if not file_path:
            raise ValueError("Please select a program file.")
        return file_path

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select G-code Program",
            "",
            "NC Files (*.nc);;Text Files (*.txt);;All Files (*)",
        )
        if file_path:
            self.select_file(file_path)

    def select_file(self, file_path):
        self.file_entry.setText(file_path)
        self._group_key = None
        self.load_project_information()

    def load_project_information(self):
        if not self.file_entry.text().strip():
            self.update_preview()
            return
        try:
            settings = load_project_settings(self.selected_file())
        except (OSError, ValueError, configparser.Error) as error:
            QMessageBox.critical(self, "Settings Error", str(error))
            self.update_preview()
            return

        self._loading = True
        try:
            self.customer_entry.setText(settings["customer"])
            self.part_number_entry.setText(settings["part_number"])
            self.notes_text.setPlainText(settings["notes"])
        finally:
            self._loading = False
        self.update_preview()

    def update_search_labels(self):
        code = self.search_code.currentText()
        self.index_before_label.setText(f"Lines Before Each {code}")
        self.index_after_label.setText(f"Lines After Each {code}")
        self.manuscript_around_label.setText(f"Lines Before/After {code}")

    def update_preview(self, *_args):
        if self._loading:
            return
        preview = self.current_preview()
        if not self.file_entry.text().strip():
            self.index_preview.clear()
            self.manuscript_preview.clear()
            self.index_preview.set_markers([], {})
            self.manuscript_preview.set_markers([], {})
            self.preview_status.setText("Select a program file to preview.")
            self.search_count.clear()
            self._group_key = None
            self._group_state = None
            self._selected_lines.clear()
            self.refresh_group_controls()
            return

        try:
            input_file = self.selected_file()
            code = self.search_code.currentText()
            lines = read_nc_lines(input_file)
            if preview is self.index_preview:
                content, sources = get_index_document(
                    input_file,
                    self.index_m06.value(),
                    self.index_before.value(),
                    self.index_after.value(),
                    self.customer_entry.text(),
                    self.part_number_entry.text(),
                    self.notes_text.toPlainText(),
                    code,
                )
            else:
                content, sources = get_manuscript_document(
                    input_file,
                    self.manuscript_m06.value(),
                    self.manuscript_around.value(),
                    code,
                )
            if lines != read_nc_lines(input_file):
                raise ValueError("The program changed while preparing the preview. Try again.")
            count = count_search_code(lines, code)
        except (OSError, UnicodeError, ValueError) as error:
            preview.clear()
            preview.set_markers([], {})
            self.search_count.clear()
            self.preview_status.setText(f"Preview error: {error}")
            self._group_key = None
            self._group_state = None
            self._selected_lines.clear()
            self.refresh_group_controls()
            return

        self.load_groups_if_needed(input_file, lines)
        markers, groups = assigned_markers(self._group_state)
        key_positions = {}
        if preview is self.index_preview and groups:
            parts = content.split("\n")
            separator = sum(
                line.count("\n") + 1
                for line in index_header_lines(input_file, self.customer_entry.text(), self.part_number_entry.text(), self.notes_text.toPlainText())
            )
            if separator >= len(parts) or parts[separator] != INDEX_SEPARATOR:
                raise ValueError("Index header separator was not found.")
            rows, positions = key_rows(groups, 22, self.index_preview.fontMetrics())
            spaced_rows = [line for row in rows for line in (row, "")]
            inserted = ["GROUP INDEX", *spaced_rows, INDEX_SEPARATOR, ""]
            parts[separator + 1:separator + 1] = inserted
            sources[separator + 1:separator + 1] = [None] * len(inserted)
            content = "\n".join(parts)
            key_positions = {separator + 2 + row * 2: value for row, value in positions.items()}
        self._preview_sources[preview] = sources
        preview.setPlainText(content)
        if preview is self.index_preview and groups:
            font = preview.font()
            if font.pointSizeF() > 0:
                font.setPointSizeF(font.pointSizeF() / 2)
            elif font.pixelSize() > 0:
                font.setPixelSize(max(1, round(font.pixelSize() / 2)))
            for row in range(len(rows)):
                spacer = preview.document().findBlockByNumber(separator + 3 + row * 2)
                cursor = QTextCursor(spacer)
                text_format = cursor.blockCharFormat()
                text_format.setFont(font)
                cursor.setBlockCharFormat(text_format)
        preview.set_markers(sources, markers, key_positions)
        self.highlight_preview()
        self.preview_status.clear()
        found = "match" if count == 1 else "matches"
        self.search_count.setText(f"{count} {code} {found} found")

    def load_groups_if_needed(self, input_file, lines):
        key = (str(Path(input_file).resolve()), source_hash(lines))
        if key == self._group_key:
            return
        self._group_key = key
        self._group_state = None
        self._selected_lines.clear()
        self._anchor_block = None
        try:
            state = load_highlight_groups(input_file, lines)
        except (OSError, UnicodeError, ValueError) as error:
            QMessageBox.warning(
                self, "Highlight Groups Error",
                f"Could not load highlight groups. Group editing is disabled.\n\n{error}",
            )
        else:
            converted = copy.deepcopy(state)
            changes = []
            for group in converted.groups:
                if group.color.lower() not in GROUP_COLOR_VALUES:
                    old_color = group.color
                    group.color = nearest_group_color(old_color)
                    changes.append(f"{group.name}: {old_color} -> {group.color}")
            if changes:
                try:
                    save_highlight_groups(input_file, read_nc_lines(input_file), converted)
                except (OSError, UnicodeError, ValueError) as error:
                    QMessageBox.warning(
                        self, "Highlight Groups Error",
                        "Could not save the high-contrast color conversion. "
                        f"Group editing is disabled; reload the program to retry.\n\n{error}",
                    )
                    self.refresh_group_controls()
                    return
                state = converted
                QMessageBox.information(
                    self, "Highlight Colors Updated",
                    "Existing group colors were replaced with the nearest "
                    "high-contrast colors:\n\n" + "\n".join(changes),
                )
            self._group_state = state
            if state.unmatched:
                QMessageBox.warning(
                    self, "Unmatched Highlight Assignments",
                    f"{len(state.unmatched)} saved line assignment(s) "
                    "could not be matched uniquely to this program. They were kept "
                    "and can be reviewed in Highlight Groups.",
                )
        self.refresh_group_controls()

    def refresh_group_controls(self):
        selected_group = self.group_select.currentData()
        self.group_select.blockSignals(True)
        self.group_select.clear()
        state = self._group_state
        if state is not None:
            for group in state.groups:
                swatch = QPixmap(16, 16)
                swatch.fill(QColor(group.color))
                self.group_select.addItem(QIcon(swatch), group.name, group.id)
            index = self.group_select.findData(selected_group)
            if index >= 0:
                self.group_select.setCurrentIndex(index)
        self.group_select.blockSignals(False)
        self.selection_status.setText(f"{len(self._selected_lines)} line(s) selected")
        unmatched = state.unmatched if state is not None else []
        if state is None:
            self.unmatched_status.setText("Select a readable program to manage groups.")
        elif unmatched:
            self.unmatched_status.setText(f"{len(unmatched)} unmatched assignment(s) retained.")
        else:
            self.unmatched_status.setText("No unmatched assignments.")
        self.group_panel.setEnabled(state is not None)
        names = {group.id: group.name for group in state.groups} if state else {}
        self.unmatched_list.setPlainText(
            "\n".join(f"{names[item.group_id]}: {item.text}" for item in unmatched)
        )
        self.unmatched_list.setVisible(bool(unmatched))
        self.discard_unmatched_button.setVisible(bool(unmatched))

    def current_preview(self):
        return self.index_preview if self.preview_tabs.currentIndex() == 0 else self.manuscript_preview

    def find_next(self):
        if not self.find_dialog.isVisible():
            self.find_dialog.open_find()
        self.find_dialog.find_next()

    def find_previous(self):
        if not self.find_dialog.isVisible():
            self.find_dialog.open_find()
        self.find_dialog.find_previous()

    def select_preview_line(self, block, modifiers):
        preview = self.sender()
        sources = self._preview_sources.get(preview, [])
        if self._group_state is None or block >= len(sources) or sources[block] is None:
            return
        source = sources[block]
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier.value)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier.value)
        if shift and self._anchor_block is not None and self._anchor_block[0] is preview:
            start, end = sorted((self._anchor_block[1], block))
            selected = {line for line in sources[start:end + 1] if line is not None}
            if not ctrl:
                self._selected_lines.clear()
            self._selected_lines.update(selected)
        elif ctrl:
            if source in self._selected_lines:
                self._selected_lines.remove(source)
            else:
                self._selected_lines.add(source)
            self._anchor_block = (preview, block)
        else:
            self._selected_lines = {source}
            self._anchor_block = (preview, block)
        self.refresh_group_controls()
        self.highlight_preview()

    def clear_selection(self):
        self._selected_lines.clear()
        self._anchor_block = None
        self.refresh_group_controls()
        self.highlight_preview()

    def highlight_preview(self):
        preview = self.current_preview()
        sources = self._preview_sources.get(preview, [])
        state = self._group_state
        preview.syntax_highlighter.set_context(
            sources,
            preview.palette().color(QPalette.ColorRole.Base),
        )
        selections = []
        block = preview.document().firstBlock()
        while block.isValid():
            number = block.blockNumber()
            source = sources[number] if number < len(sources) else None
            selected = source is not None and source in self._selected_lines
            if selected:
                selection = QTextEdit.ExtraSelection()
                selection.cursor = preview.textCursor()
                selection.cursor.setPosition(block.position())
                selection.cursor.movePosition(
                    QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
                )
                if selected:
                    selection.format.setFontWeight(700)
                    selection.format.setFontUnderline(True)
                    background = self.palette().highlight().color()
                    selection.format.setBackground(background)
                    selection.format.setForeground(contrasting_text_color(background))
                selections.append(selection)
            block = block.next()
        preview.setExtraSelections(selections)

    def save_group_change(self, state, parent=None):
        try:
            lines = read_nc_lines(self.selected_file())
            save_highlight_groups(self.selected_file(), lines, state)
        except (OSError, UnicodeError, ValueError) as error:
            QMessageBox.critical(parent or self, "Highlight Groups Error", str(error))
            return False
        self._group_state = state
        self.refresh_group_controls()
        self.update_preview()
        return True

    def group_details(self, group=None, parent=None, default_name=""):
        parent = parent or self.group_panel
        name, accepted = QInputDialog.getText(
            parent, "Highlight Group", "Group name:",
            text=group.name if group else default_name,
        )
        if not accepted:
            return None
        name = name.strip()
        if not name or any(
            item.name.casefold() == name.casefold() and (group is None or item.id != group.id)
            for item in self._group_state.groups
        ):
            QMessageBox.warning(parent, "Highlight Group", "Enter a unique group name.")
            return None
        color = choose_group_color(parent, group.color if group else "#ffee00")
        if color is None:
            return None
        return name, color

    def suggest_groups(self):
        self.update_preview()
        if self._group_state is None:
            QMessageBox.warning(self, "Suggested Groups", "Select a readable program with valid group settings first.")
            return
        try:
            lines = read_nc_lines(self.selected_file())
            if source_hash(lines) != self._group_state.source_hash:
                raise ValueError("The program changed. Reload it before analyzing suggestions.")
            analysis = analyze_group_suggestions(lines)
        except (OSError, UnicodeError, ValueError) as error:
            QMessageBox.critical(self, "Suggested Groups Error", str(error))
            return
        dialog = SuggestionDialog(analysis, self.accept_suggested_group, self)
        dialog.exec()

    def accept_suggested_group(self, suggestion, parent):
        if self._group_state is None:
            QMessageBox.warning(parent, "Suggested Groups", "Reload the program before accepting a suggestion.")
            return False
        conflicts = [
            operation.marker_line for operation in suggestion.operations
            if operation.marker_index in self._group_state.assignments
        ]
        if conflicts:
            QMessageBox.warning(
                parent, "Suggested Groups",
                "Some operation marker lines are already assigned to a group. "
                "Uncheck those operations, or close this review and remove or "
                "reassign the existing highlights first:\n\n"
                + "\n".join(conflicts),
            )
            return False
        number = 1
        existing_names = {group.name.casefold() for group in self._group_state.groups}
        while f"hole pattern {number}" in existing_names:
            number += 1
        details = self.group_details(parent=parent, default_name=f"Hole pattern {number}")
        if details is None:
            return False
        state = copy.deepcopy(self._group_state)
        group = HighlightGroup(uuid.uuid4().hex, *details)
        state.groups.append(group)
        for operation in suggestion.operations:
            state.assignments[operation.marker_index] = group.id
        if not self.save_group_change(state, parent=parent):
            return False
        self.group_select.setCurrentIndex(self.group_select.findData(group.id))
        self.clear_selection()
        return True

    def new_group(self):
        if self._group_state is None:
            return
        details = self.group_details()
        if details is None:
            return
        state = copy.deepcopy(self._group_state)
        group = HighlightGroup(uuid.uuid4().hex, *details)
        state.groups.append(group)
        if self.save_group_change(state):
            self.group_select.setCurrentIndex(self.group_select.findData(group.id))

    def edit_group(self):
        if self._group_state is None:
            return
        group = next((g for g in self._group_state.groups if g.id == self.group_select.currentData()), None)
        if group is None:
            QMessageBox.warning(self.group_panel, "Highlight Group", "Select a group first.")
            return
        details = self.group_details(group)
        if details is None:
            return
        state = copy.deepcopy(self._group_state)
        updated = next(g for g in state.groups if g.id == group.id)
        updated.name, updated.color = details
        self.save_group_change(state)

    def delete_group(self):
        if self._group_state is None:
            return
        group_id = self.group_select.currentData()
        group = next((g for g in self._group_state.groups if g.id == group_id), None)
        if group is None:
            QMessageBox.warning(self.group_panel, "Highlight Group", "Select a group first.")
            return
        if QMessageBox.question(
            self.group_panel, "Delete Highlight Group",
            f"Delete '{group.name}' and all its line assignments?",
        ) != QMessageBox.StandardButton.Yes:
            return
        state = copy.deepcopy(self._group_state)
        state.groups = [g for g in state.groups if g.id != group_id]
        state.assignments = {line: group for line, group in state.assignments.items() if group != group_id}
        state.unmatched = [item for item in state.unmatched if item.group_id != group_id]
        self.save_group_change(state)

    def assign_selected(self):
        if self._group_state is None:
            return
        group_id = self.group_select.currentData()
        if group_id is None or not self._selected_lines:
            QMessageBox.warning(self.group_panel, "Highlight Group", "Select a group and at least one line.")
            return
        state = copy.deepcopy(self._group_state)
        for line in self._selected_lines:
            state.assignments[line] = group_id
        if self.save_group_change(state):
            self.clear_selection()

    def unassign_selected(self):
        if self._group_state is None:
            return
        if not self._selected_lines:
            QMessageBox.warning(self.group_panel, "Highlight Group", "Select at least one line.")
            return
        state = copy.deepcopy(self._group_state)
        for line in self._selected_lines:
            state.assignments.pop(line, None)
        if self.save_group_change(state):
            self.clear_selection()

    def discard_unmatched(self):
        if self._group_state is None or not self._group_state.unmatched:
            return
        if QMessageBox.question(
            self.group_panel, "Discard Unmatched Assignments",
            "Discard all unmatched line assignments? This cannot be undone.",
        ) != QMessageBox.StandardButton.Yes:
            return
        state = copy.deepcopy(self._group_state)
        state.unmatched.clear()
        self.save_group_change(state)

    def generate(self):
        try:
            input_file = self.selected_file()
            if not self.index_enabled.isChecked() and not self.manuscript_enabled.isChecked():
                raise ValueError("Select at least one output type.")
            customer = self.customer_entry.text()
            part_number = self.part_number_entry.text()
            notes = self.notes_text.toPlainText()
            code = self.search_code.currentText()
            output_format = self.output_format.currentData()
            if output_format not in ("pdf", "text", "both"):
                raise ValueError("Select a valid output format.")
            lines = read_nc_lines(input_file)
            documents = []
            if self.index_enabled.isChecked():
                documents.append(("INDEX", *get_index_document(
                    input_file,
                    self.index_m06.value(),
                    self.index_before.value(),
                    self.index_after.value(),
                    customer,
                    part_number,
                    notes,
                    code,
                )))
            if self.manuscript_enabled.isChecked():
                documents.append(("MANUSCRIPT", *get_manuscript_document(
                    input_file,
                    self.manuscript_m06.value(),
                    self.manuscript_around.value(),
                    code,
                )))
            if lines != read_nc_lines(input_file):
                raise ValueError("The program changed while preparing the outputs. Try again.")

            group_colors = {}
            groups = []
            if output_format in ("pdf", "both"):
                self.load_groups_if_needed(input_file, lines)
                if self._group_state is None:
                    raise ValueError("Highlight groups could not be loaded; PDF output was not generated.")
                group_colors, groups = assigned_markers(self._group_state)

            save_project_settings(input_file, customer, part_number, notes)
            created_files = []
            for label, text, sources in documents:
                if output_format in ("pdf", "both"):
                    if label == "INDEX":
                        header_count = sum(
                            line.count("\n") + 1
                            for line in index_header_lines(input_file, customer, part_number, notes)
                        )
                        created_files.append(str(create_pdf(
                            input_file, label, text, sources, group_colors,
                            legend=groups, header_line_count=header_count,
                        )))
                    else:
                        created_files.append(str(create_pdf(input_file, label, text, sources, group_colors)))
                if output_format in ("text", "both"):
                    created_files.append(str(write_text_output(input_file, label, text)))
        except (OSError, UnicodeError, ValueError, configparser.Error) as error:
            QMessageBox.critical(self, "Generation Error", str(error))
            return

        QMessageBox.information(self, "Success", "Created:\n\n" + "\n".join(created_files))


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
