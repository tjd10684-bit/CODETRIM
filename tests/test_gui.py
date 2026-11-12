import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QColor, QDropEvent, QPalette, QTextCursor, QTextFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from index_generator import generate_index_text
from highlight_groups import (
    HighlightGroup,
    HighlightGroups,
    groups_path,
    load_highlight_groups,
    save_highlight_groups,
    source_hash,
)
from color_utils import contrast_ratio
from group_palette import GROUP_COLOR_VALUES, nearest_group_color
from group_suggestions import analyze_group_suggestions
from MASTERCAM_MAIN import MainWindow
from nc_commands import read_nc_lines
from project_settings import load_project_settings, save_project_settings
from setup_copy_generator import generate_manuscript_text


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.program = Path(self.directory.name) / "program.nc"
        self.program.write_text(
            "N0 HEADER\nN1 M06 T1\nN2 M01\nN3 G28\nN4 M30\n",
            encoding="utf-8",
        )
        self.window = MainWindow()
        self.addCleanup(self.window.close)

    def test_select_file_loads_settings_and_updates_previews(self):
        save_project_settings(self.program, "Customer", "Part", "First\nSecond")
        self.window.select_file(str(self.program))

        self.assertEqual(self.window.customer_entry.text(), "Customer")
        self.assertEqual(self.window.part_number_entry.text(), "Part")
        self.assertEqual(self.window.notes_text.toPlainText(), "First\nSecond")
        self.assertEqual(self.window.search_count.text(), "1 M01 match found")
        self.assertEqual(
            self.window.index_preview.toPlainText(),
            generate_index_text(self.program, 3, 0, 2, "Customer", "Part", "First\nSecond"),
        )

        self.window.search_code.setCurrentText("G28")
        self.window.index_before.setValue(1)
        self.assertEqual(self.window.search_count.text(), "1 G28 match found")
        self.assertEqual(self.window.index_before_label.text(), "Lines Before Each G28")
        self.assertEqual(
            self.window.index_preview.toPlainText(),
            generate_index_text(self.program, 3, 1, 2, "Customer", "Part", "First\nSecond", "G28"),
        )
        self.window.preview_tabs.setCurrentIndex(1)
        self.assertEqual(
            self.window.manuscript_preview.toPlainText(),
            generate_manuscript_text(self.program, 20, 20, "G28"),
        )
        self.window.notes_text.clear()
        self.window.preview_tabs.setCurrentIndex(0)
        self.assertIn("NOTES: \n", self.window.index_preview.toPlainText())

    def test_browse_and_drop_select_files(self):
        with patch("MASTERCAM_MAIN.QFileDialog.getOpenFileName", return_value=(str(self.program), "")):
            self.window.browse_file()
        self.assertEqual(self.window.file_entry.text(), str(self.program))
        self.window.file_entry.clear()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.program))])
        event = QDropEvent(
            QPointF(0, 0),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.window.file_entry.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(Path(self.window.file_entry.text()), self.program)
        self.assertEqual(self.window.search_count.text(), "1 M01 match found")

    def test_manual_file_entry_loads_project_information(self):
        save_project_settings(self.program, "Customer", "Part", "Notes")
        self.window.file_entry.setText(str(self.program))
        self.window.file_entry.editingFinished.emit()
        self.assertEqual(self.window.customer_entry.text(), "Customer")
        self.assertEqual(self.window.search_count.text(), "1 M01 match found")

    def test_ctrl_f_enter_and_f3_find_with_wraparound(self):
        self.window.show()
        self.window.select_file(str(self.program))
        self.window.activateWindow()
        self.window.index_preview.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.window.index_preview, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        dialog = self.window.find_dialog
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.Tool)
        dialog.search_entry.setText("M01")
        QTest.keyClick(dialog.search_entry, Qt.Key.Key_Return)
        self.assertEqual(self.window.index_preview.textCursor().selectedText(), "M01")
        self.assertEqual(dialog.status.text(), "Match found.")
        QTest.keyClick(dialog.search_entry, Qt.Key.Key_F3)
        self.assertEqual(dialog.status.text(), "Wrapped to the beginning.")
        QTest.keyClick(dialog.search_entry, Qt.Key.Key_F3, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(dialog.status.text(), "Wrapped to the end.")
        QTest.keyClick(dialog.search_entry, Qt.Key.Key_Escape)
        self.assertFalse(dialog.isVisible())

    def test_find_next_previous_and_case_matching(self):
        self.window.show()
        preview = self.window.index_preview
        preview.setPlainText("Alpha beta ALPHA\nalpha gamma")
        dialog = self.window.find_dialog
        dialog.open_find()
        dialog.search_entry.setText("alpha")
        dialog.find_next()
        self.assertEqual(preview.textCursor().selectedText(), "Alpha")
        dialog.find_next()
        self.assertEqual(preview.textCursor().selectedText(), "ALPHA")
        dialog.find_previous()
        self.assertEqual(preview.textCursor().selectedText(), "Alpha")
        dialog.find_previous()
        self.assertEqual(preview.textCursor().selectedText(), "alpha")
        self.assertEqual(dialog.status.text(), "Wrapped to the end.")

        dialog.match_case.setChecked(True)
        cursor = preview.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        preview.setTextCursor(cursor)
        dialog.find_next()
        self.assertEqual(preview.textCursor().selectedText(), "alpha")
        self.assertEqual(dialog.status.text(), "Match found.")

    def test_find_missing_or_empty_preserves_selection(self):
        self.window.show()
        preview = self.window.index_preview
        preview.setPlainText("Alpha beta")
        cursor = preview.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        preview.setTextCursor(cursor)
        dialog = self.window.find_dialog
        dialog.search_entry.setText("not present")
        dialog.find_next()
        self.assertEqual(dialog.status.text(), "No matches in the active preview.")
        self.assertEqual(preview.textCursor().selectedText(), "Alpha")
        dialog.search_entry.clear()
        dialog.find_next()
        self.assertEqual(dialog.status.text(), "Enter text to search.")
        self.assertEqual(preview.textCursor().selectedText(), "Alpha")

    def test_find_is_literal_and_supports_unicode(self):
        self.window.show()
        preview = self.window.index_preview
        preview.setPlainText("(Café) X1.0\n(CAFE) X1x0")
        dialog = self.window.find_dialog
        dialog.search_entry.setText("Café")
        dialog.find_next()
        self.assertEqual(preview.textCursor().selectedText(), "Café")
        dialog.search_entry.setText("1.0")
        dialog.find_next()
        self.assertEqual(preview.textCursor().selectedText(), "1.0")
        dialog.find_next()
        self.assertEqual(dialog.status.text(), "Wrapped to the beginning.")
        self.assertEqual(preview.textCursor().selectedText(), "1.0")

    def test_f3_reopens_find_with_previous_query(self):
        self.window.show()
        self.window.select_file(str(self.program))
        dialog = self.window.find_dialog
        dialog.open_find()
        dialog.search_entry.setText("M01")
        dialog.close()
        self.window.activateWindow()
        self.window.index_preview.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.window.index_preview, Qt.Key.Key_F3)
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.search_entry.text(), "M01")
        self.assertEqual(self.window.index_preview.textCursor().selectedText(), "M01")

    def test_find_tracks_active_preview_and_refreshes_status(self):
        self.window.show()
        self.window.index_after.setValue(0)
        self.window.select_file(str(self.program))
        dialog = self.window.find_dialog
        dialog.open_find()
        dialog.search_entry.setText("G28")
        dialog.find_next()
        self.assertEqual(dialog.status.text(), "No matches in the active preview.")
        self.window.preview_tabs.setCurrentIndex(1)
        self.assertEqual(dialog.status.text(), "")
        self.assertTrue(dialog.isVisible())
        dialog.find_next()
        self.assertEqual(self.window.manuscript_preview.textCursor().selectedText(), "G28")
        self.assertEqual(dialog.status.text(), "Match found.")
        self.window.manuscript_around.setValue(19)
        self.assertEqual(dialog.status.text(), "")

    def test_find_preserves_group_highlights_and_program_data(self):
        self.window.show()
        self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.window.new_group()
        self.window._selected_lines = {1}
        self.window.assign_selected()
        original_program = self.program.read_bytes()
        original_groups = groups_path(self.program).read_bytes()
        original_preview = self.window.index_preview.toPlainText()
        dialog = self.window.find_dialog
        dialog.search_entry.setText("M06")
        dialog.find_next()
        self.assertEqual(self.window.index_preview.textCursor().selectedText(), "M06")
        self.assertEqual(len(self.window.index_preview._markers), 1)
        self.assertEqual(self.window.index_preview.toPlainText(), original_preview)
        self.assertEqual(self.program.read_bytes(), original_program)
        self.assertEqual(groups_path(self.program).read_bytes(), original_groups)

    def test_select_file_loads_legacy_project_notes(self):
        (self.program.parent / "project_settings.ini").write_text(
            "# Mastercam Tools Project Settings\n[Project]\n"
            "Customer=Customer\nPartNumber=Part\nNotes=first\nsecond\n",
            encoding="utf-8",
        )
        with patch("MASTERCAM_MAIN.QMessageBox.critical") as error:
            self.window.select_file(str(self.program))
        error.assert_not_called()
        self.assertEqual(self.window.notes_text.toPlainText(), "first\nsecond")
        self.assertIn("NOTES: first\nsecond", self.window.index_preview.toPlainText())

    def click_source_line(self, preview, source_line, modifiers=Qt.KeyboardModifier.NoModifier):
        block_number = self.window._preview_sources[preview].index(source_line)
        block = preview.document().findBlockByNumber(block_number)
        cursor = QTextCursor(block)
        preview.setTextCursor(cursor)
        preview.ensureCursorVisible()
        self.app.processEvents()
        position = preview.cursorRect(cursor).center()
        QTest.mouseClick(
            preview.viewport(), Qt.MouseButton.LeftButton, modifiers, position
        )

    def suggestion_fixture(self):
        self.program.write_text(
            "G20 G17 G90 G54\nN10 M06 T1\nG00 X0 Y0\n"
            "G81 Z-1 R.1\nX1 Y1\nG80\nN20 M01\n(DRILL HOLES)\n"
            "N30 M06 T2\nG00 X.01 Y-.01\nG81 Z-1 R.1\n"
            "X1.01 Y1.01\nG80\nM30\n",
            encoding="utf-8",
        )
        self.window.select_file(str(self.program))
        return analyze_group_suggestions(read_nc_lines(self.program)).suggestions[0]

    def test_suggest_button_analyzes_without_changing_program_or_groups(self):
        self.suggestion_fixture()
        original = self.program.read_bytes()
        with patch("MASTERCAM_MAIN.SuggestionDialog") as dialog:
            self.window.suggest_groups()
        self.assertEqual(len(dialog.call_args.args[0].suggestions), 1)
        dialog.return_value.exec.assert_called_once()
        self.assertEqual(self.program.read_bytes(), original)
        self.assertFalse(groups_path(self.program).exists())
        self.assertEqual(self.window._group_state.groups, [])

    def test_accept_suggestion_saves_only_reviewed_operation_markers(self):
        suggestion = self.suggestion_fixture()
        original = self.program.read_bytes()
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Hole Set", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.assertTrue(self.window.accept_suggested_group(suggestion, self.window))
        state = load_highlight_groups(self.program, read_nc_lines(self.program))
        self.assertEqual(state.groups[0].name, "Hole Set")
        self.assertEqual(set(state.assignments), {op.marker_index for op in suggestion.operations})
        self.assertEqual(self.program.read_bytes(), original)
        self.assertIn("Hole Set", self.window.index_preview.toPlainText())
        self.window.preview_tabs.setCurrentIndex(1)
        self.assertEqual(len(self.window.manuscript_preview._markers), 2)

    def test_existing_marker_group_is_not_overwritten_by_suggestion(self):
        suggestion = self.suggestion_fixture()
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Existing", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.window.new_group()
        self.window._selected_lines = {suggestion.operations[0].marker_index}
        self.window.assign_selected()
        original = groups_path(self.program).read_bytes()
        with patch("MASTERCAM_MAIN.QMessageBox.warning") as warning:
            self.assertFalse(self.window.accept_suggested_group(suggestion, self.window))
        self.assertIn("already assigned", warning.call_args.args[2])
        self.assertEqual(groups_path(self.program).read_bytes(), original)

    def test_suggestion_cancellation_and_changed_source_do_not_save(self):
        suggestion = self.suggestion_fixture()
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("", False)):
            self.assertFalse(self.window.accept_suggested_group(suggestion, self.window))
        self.assertFalse(groups_path(self.program).exists())
        self.program.write_text(self.program.read_text(encoding="utf-8") + "N100\n", encoding="utf-8")
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Hole Set", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                with patch("MASTERCAM_MAIN.QMessageBox.critical") as error:
                    self.assertFalse(self.window.accept_suggested_group(suggestion, self.window))
        self.assertIn("program changed", error.call_args.args[2].lower())
        self.assertFalse(groups_path(self.program).exists())

    def test_group_lines_by_click_and_persist_across_previews(self):
        self.window.show()
        self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.window.new_group()
        self.assertTrue(groups_path(self.program).exists())
        self.click_source_line(self.window.index_preview, 1)
        self.click_source_line(
            self.window.index_preview, 2, Qt.KeyboardModifier.ControlModifier
        )
        self.assertEqual(self.window._selected_lines, {1, 2})
        self.window.assign_selected()
        self.assertEqual(self.window._selected_lines, set())
        self.assertEqual(len(self.window.index_preview._markers), 2)

        self.window.preview_tabs.setCurrentIndex(1)
        self.assertEqual(len(self.window.manuscript_preview._markers), 2)
        self.window.select_file(str(self.program))
        self.assertEqual(len(self.window.manuscript_preview._markers), 2)
        state = load_highlight_groups(self.program, read_nc_lines(self.program))
        self.assertEqual(set(state.assignments), {1, 2})
        self.assertEqual(state.groups[0].name, "Holes")

        self.click_source_line(self.window.manuscript_preview, 2)
        self.window.unassign_selected()
        self.window.preview_tabs.setCurrentIndex(0)
        self.assertEqual(len(self.window.index_preview._markers), 1)

    def test_grouped_lines_use_high_contrast_black_or_white_in_both_previews(self):
        self.window.show()
        self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.window.new_group()
        self.click_source_line(self.window.index_preview, 1)
        self.window.assign_selected()
        for tab, preview in enumerate((self.window.index_preview, self.window.manuscript_preview)):
            self.window.preview_tabs.setCurrentIndex(tab)
            self.app.processEvents()
            self.assertEqual(preview._markers[1].number, 1)
            self.assertEqual(preview._markers[1].color, "#ffee00")
            self.assertEqual(len(preview.extraSelections()), 0)
            self.assertGreaterEqual(contrast_ratio(QColor("#000000"), QColor("#ffee00")), 7.0)

    def test_group_marker_preserves_syntax_colors(self):
        self.window.select_file(str(self.program))
        preview = self.window.index_preview
        number = self.window._preview_sources[preview].index(1)
        before = [
            item.format.foreground().color().name()
            for item in preview.document().findBlockByNumber(number).layout().formats()
        ]
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.window.new_group()
        self.window._selected_lines = {1}
        self.window.assign_selected()
        number = self.window._preview_sources[preview].index(1)
        after = [
            item.format.foreground().color().name()
            for item in preview.document().findBlockByNumber(number).layout().formats()
        ]
        self.assertTrue(before)
        self.assertEqual(after, before)

    def test_group_highlight_covers_unicode_text_without_highlighting_line_end(self):
        self.program.write_text("N1 M06 (😀)\nN2 M01\n", encoding="utf-8")
        self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.window.new_group()
        self.window._selected_lines = {0}
        self.window.assign_selected()
        self.assertEqual(self.window.index_preview._markers[0].number, 1)
        self.assertIn("N1 M06 (😀)", self.window.index_preview.toPlainText())
        self.assertEqual(len(self.window.index_preview.extraSelections()), 0)

    def test_index_group_key_includes_groups_assigned_outside_index(self):
        lines = read_nc_lines(self.program)
        state = HighlightGroups(
            groups=[
                HighlightGroup("one", "Drilling", "#ffee00"),
                HighlightGroup("two", "Finishing", "#283593"),
                HighlightGroup("three", "Unassigned", "#00ff00"),
            ],
            assignments={2: "one", 3: "two"},
            source_hash=source_hash(lines),
        )
        save_highlight_groups(self.program, lines, state)
        self.window.show()
        self.window.index_after.setValue(0)
        self.window.select_file(str(self.program))
        text = self.window.index_preview.toPlainText()
        self.assertIn("Drilling", text)
        self.assertIn("Finishing", text)
        self.assertNotIn("Unassigned", text)
        self.assertLess(text.index("-----"), text.index("GROUP INDEX"))
        self.assertLess(text.index("GROUP INDEX"), text.index("N1 M06"))
        self.assertEqual(text.count("-" * 58), 2)
        self.assertLess(text.rindex("-" * 58), text.index("N1 M06"))
        self.window.search_code.setCurrentText("G28")
        self.assertEqual(self.window.index_preview._markers[3].number, 2)
        self.window.preview_tabs.setCurrentIndex(1)
        self.assertNotIn("GROUP INDEX", self.window.manuscript_preview.toPlainText())
        self.window.preview_tabs.setCurrentIndex(0)
        self.assertIn("GROUP INDEX", self.window.index_preview.toPlainText())
        self.window.search_code.setCurrentText("M06")
        self.assertIn("Finishing", self.window.index_preview.toPlainText())

    def test_index_key_rows_are_spaced_one_and_a_half_lines(self):
        self.program.write_text(
            "N1 M06\nN2 M01\nN3\nN4\nN5\nN6\nN7\nM30\n", encoding="utf-8"
        )
        lines = read_nc_lines(self.program)
        state = HighlightGroups(
            groups=[HighlightGroup(str(i), f"Group{i}", "#ffee00") for i in range(6)],
            assignments={i: str(i) for i in range(6)},
            source_hash=source_hash(lines),
        )
        save_highlight_groups(self.program, lines, state)
        self.window.show()
        self.window.select_file(str(self.program))
        self.app.processEvents()
        preview = self.window.index_preview
        rows = sorted(preview._key_markers)
        self.assertEqual(len(rows), 2)
        first = preview.document().findBlockByNumber(rows[0])
        second = preview.document().findBlockByNumber(rows[1])
        first_rect = preview.blockBoundingGeometry(first)
        second_rect = preview.blockBoundingGeometry(second)
        self.assertAlmostEqual(
            (second_rect.top() - first_rect.top()) / first_rect.height(),
            1.5,
            delta=0.15,
        )
        spacer = preview.document().findBlockByNumber(rows[0] + 1)
        self.assertEqual(spacer.text(), "")
        self.assertIsNone(self.window._preview_sources[preview][spacer.blockNumber()])
        text = preview.toPlainText()
        self.assertLess(text.index("GROUP INDEX"), text.rindex("-" * 58))
        self.assertLess(text.rindex("-" * 58), text.index("N1 M06"))

    def test_dark_group_uses_white_text_in_both_previews(self):
        self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#283593"):
                self.window.new_group()
        self.window._selected_lines = {1}
        self.window.assign_selected()
        for tab, preview in enumerate((self.window.index_preview, self.window.manuscript_preview)):
            self.window.preview_tabs.setCurrentIndex(tab)
            self.assertEqual(preview._markers[1].color, "#283593")
            self.assertEqual(len(preview.extraSelections()), 0)

    def test_existing_colors_are_converted_and_saved_once(self):
        lines = read_nc_lines(self.program)
        state = HighlightGroups(
            groups=[HighlightGroup("one", "Holes", "#0099ff")],
            assignments={2: "one"},
            source_hash=source_hash(lines),
        )
        save_highlight_groups(self.program, lines, state)
        with patch("MASTERCAM_MAIN.QMessageBox.information") as notice:
            self.window.select_file(str(self.program))
        notice.assert_called_once()
        saved = load_highlight_groups(self.program, lines)
        self.assertEqual(saved.groups[0].color, nearest_group_color("#0099ff"))
        self.assertIn(saved.groups[0].color, GROUP_COLOR_VALUES)
        self.assertEqual(saved.assignments, {2: "one"})
        with patch("MASTERCAM_MAIN.QMessageBox.information") as notice:
            self.window.select_file(str(self.program))
        notice.assert_not_called()

    def test_conversion_keeps_unmatched_assignments_after_source_change(self):
        lines = read_nc_lines(self.program)
        state = HighlightGroups(
            groups=[HighlightGroup("one", "Holes", "#ff0000")],
            assignments={2: "one"},
            source_hash=source_hash(lines),
        )
        save_highlight_groups(self.program, lines, state)
        self.program.write_text("N0 HEADER\nN1 M06 T1\nREMOVED\nN4 M30\n", encoding="utf-8")
        with patch("MASTERCAM_MAIN.QMessageBox.information"), patch("MASTERCAM_MAIN.QMessageBox.warning"):
            self.window.select_file(str(self.program))
        saved = load_highlight_groups(self.program, read_nc_lines(self.program))
        self.assertIn(saved.groups[0].color, GROUP_COLOR_VALUES)
        self.assertEqual([(item.text, item.group_id) for item in saved.unmatched], [("N2 M01", "one")])

    def test_conversion_save_error_preserves_old_file_and_can_retry(self):
        lines = read_nc_lines(self.program)
        state = HighlightGroups(
            groups=[HighlightGroup("one", "Holes", "#ff0000")],
            assignments={2: "one"},
            source_hash=source_hash(lines),
        )
        save_highlight_groups(self.program, lines, state)
        with patch("MASTERCAM_MAIN.save_highlight_groups", side_effect=OSError("read only")):
            with patch("MASTERCAM_MAIN.QMessageBox.warning") as warning:
                self.window.select_file(str(self.program))
        self.assertIn("read only", warning.call_args.args[2])
        self.assertIsNone(self.window._group_state)
        self.assertEqual(load_highlight_groups(self.program, lines).groups[0].color, "#ff0000")
        with patch("MASTERCAM_MAIN.QMessageBox.information"):
            self.window.select_file(str(self.program))
        self.assertIn(self.window._group_state.groups[0].color, GROUP_COLOR_VALUES)

    def test_syntax_colors_follow_preview_palette_changes(self):
        self.window.select_file(str(self.program))
        preview = self.window.index_preview
        number = self.window._preview_sources[preview].index(1)
        block = preview.document().findBlockByNumber(number)
        original = [item.format.foreground().color().name() for item in block.layout().formats()]
        palette = preview.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#101010"))
        preview.setPalette(palette)
        self.app.processEvents()
        changed = [item.format.foreground().color().name() for item in block.layout().formats()]
        self.assertNotEqual(changed, original)
        for color in changed:
            self.assertGreaterEqual(contrast_ratio(QColor(color), QColor("#101010")), 4.5)

    def test_shift_selects_visible_source_lines_and_skips_header(self):
        self.window.show()
        self.window.select_file(str(self.program))
        self.click_source_line(self.window.index_preview, 1)
        self.click_source_line(
            self.window.index_preview, 3, Qt.KeyboardModifier.ShiftModifier
        )
        self.assertEqual(self.window._selected_lines, {1, 2, 3})

    def test_changed_program_warns_and_preserves_unmatched_assignments(self):
        self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.window.new_group()
        self.window._selected_lines = {2}
        self.window.assign_selected()
        self.program.write_text("N0 HEADER\nN1 M06 T1\nREMOVED\nN4 M30\n", encoding="utf-8")
        with patch("MASTERCAM_MAIN.QMessageBox.warning") as warning:
            self.window.update_preview()
        warning.assert_called_once()
        self.assertEqual(len(self.window._group_state.unmatched), 1)
        self.assertIn("N2 M01", self.window.unmatched_list.toPlainText())

    def test_group_reassignment_edit_and_deletion(self):
        self.window.select_file(str(self.program))
        for name, color in (("Holes", "#ffee00"), ("Slots", "#90caf9")):
            with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=(name, True)):
                with patch("MASTERCAM_MAIN.choose_group_color", return_value=color):
                    self.window.new_group()
        self.window._selected_lines = {2}
        self.window.group_select.setCurrentIndex(0)
        self.window.assign_selected()
        self.window._selected_lines = {2}
        self.window.group_select.setCurrentIndex(1)
        self.window.assign_selected()
        self.assertEqual(
            self.window._group_state.assignments[2],
            self.window._group_state.groups[1].id,
        )
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Slots Edited", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#00ff00"):
                self.window.edit_group()
        self.assertEqual(self.window._group_state.groups[1].name, "Slots Edited")
        self.assertEqual(self.window.index_preview._markers[2].color, "#00ff00")
        with patch("MASTERCAM_MAIN.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window.delete_group()
        self.assertEqual(self.window._group_state.assignments, {})
        self.assertEqual(len(self.window._group_state.groups), 1)

    def test_invalid_group_file_is_not_overwritten(self):
        path = groups_path(self.program)
        path.write_text("invalid json", encoding="utf-8")
        with patch("MASTERCAM_MAIN.QMessageBox.warning") as warning:
            self.window.select_file(str(self.program))
        warning.assert_called_once()
        self.assertIsNone(self.window._group_state)
        self.assertEqual(path.read_text(encoding="utf-8"), "invalid json")

    def test_invalid_group_file_blocks_pdf_but_not_text_output(self):
        groups_path(self.program).write_text("invalid json", encoding="utf-8")
        with patch("MASTERCAM_MAIN.QMessageBox.warning"):
            self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.create_pdf") as pdf:
            with patch("MASTERCAM_MAIN.QMessageBox.critical") as error:
                self.window.generate()
        pdf.assert_not_called()
        self.assertIn("Highlight groups could not be loaded", error.call_args.args[2])
        self.window.output_format.setCurrentIndex(self.window.output_format.findData("text"))
        with patch("MASTERCAM_MAIN.QMessageBox.information") as success:
            self.window.generate()
        success.assert_called_once()
        self.assertTrue(self.program.with_name("program - INDEX.nc").exists())

    def test_group_save_error_is_reported_without_applying_change(self):
        self.window.select_file(str(self.program))
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                with patch("MASTERCAM_MAIN.save_highlight_groups", side_effect=OSError("read only")):
                    with patch("MASTERCAM_MAIN.QMessageBox.critical") as error:
                        self.window.new_group()
        self.assertIn("read only", error.call_args.args[2])
        self.assertEqual(self.window._group_state.groups, [])

    def test_window_layout_fits_at_minimum_size(self):
        self.window.show()
        self.window.resize(800, 560)
        self.app.processEvents()
        self.assertGreaterEqual(
            self.window.width(), self.window.minimumSizeHint().width()
        )
        self.assertGreaterEqual(
            self.window.height(), self.window.minimumSizeHint().height()
        )

    def test_side_by_side_layout_and_integrated_group_controls(self):
        self.window.show()
        self.app.processEvents()
        sizes = self.window.main_splitter.sizes()
        self.assertAlmostEqual(sizes[0] / sum(sizes), 1 / 3, delta=0.03)
        self.assertLess(self.window.settings_scroll.x(), self.window.preview_tabs.parentWidget().x())
        self.assertGreater(self.window.group_panel.y(), self.window.preview_tabs.y())
        self.assertTrue(self.window.group_panel.isVisible())
        self.assertFalse(self.window.group_panel.isEnabled())

        self.window.select_file(str(self.program))
        self.assertTrue(self.window.group_panel.isEnabled())
        buttons = {button.text(): button for button in self.window.group_panel.findChildren(QPushButton)}
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Holes", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                QTest.mouseClick(buttons["New"], Qt.MouseButton.LeftButton)
        self.click_source_line(self.window.index_preview, 2)
        QTest.mouseClick(buttons["Assign Selected"], Qt.MouseButton.LeftButton)
        self.assertEqual(len(self.window.index_preview._markers), 1)

        self.window.main_splitter.setSizes([500, 600])
        self.app.processEvents()
        self.assertGreater(self.window.main_splitter.sizes()[0], sizes[0])

    def test_generate_both_outputs(self):
        self.window.select_file(str(self.program))
        self.window.output_format.setCurrentIndex(self.window.output_format.findData("text"))
        with patch("MASTERCAM_MAIN.QMessageBox.information") as success:
            self.window.generate()
        success.assert_called_once()
        self.assertTrue(self.program.with_name("program - INDEX.nc").exists())
        self.assertTrue(self.program.with_name("program - MANUSCRIPT.nc").exists())

    def test_generate_selected_outputs_and_save_settings(self):
        self.window.select_file(str(self.program))
        self.window.output_format.setCurrentIndex(self.window.output_format.findData("text"))
        self.window.customer_entry.setText("Customer")
        self.window.part_number_entry.setText("Part")
        self.window.notes_text.setPlainText("Notes")
        self.window.manuscript_enabled.setChecked(False)
        with patch("MASTERCAM_MAIN.QMessageBox.information") as success:
            self.window.generate()
        success.assert_called_once()
        index = self.program.with_name("program - INDEX.nc")
        manuscript = self.program.with_name("program - MANUSCRIPT.nc")
        self.assertEqual(index.read_text(encoding="utf-8"), self.window.index_preview.toPlainText())
        self.assertFalse(manuscript.exists())
        self.assertEqual(
            load_project_settings(self.program),
            {"customer": "Customer", "part_number": "Part", "notes": "Notes"},
        )

        self.window.index_enabled.setChecked(False)
        self.window.manuscript_enabled.setChecked(True)
        self.window.preview_tabs.setCurrentIndex(1)
        with patch("MASTERCAM_MAIN.QMessageBox.information"):
            self.window.generate()
        self.assertEqual(
            manuscript.read_text(encoding="utf-8"),
            self.window.manuscript_preview.toPlainText(),
        )

    def test_pdf_is_default_and_uses_selected_output_types(self):
        self.window.select_file(str(self.program))
        self.assertEqual(self.window.output_format.currentData(), "pdf")
        self.window.manuscript_enabled.setChecked(False)
        with patch("MASTERCAM_MAIN.create_pdf", return_value=self.program.with_name("index.pdf")) as pdf:
            with patch("MASTERCAM_MAIN.QMessageBox.information") as success:
                self.window.generate()
        pdf.assert_called_once()
        success.assert_called_once()
        self.assertEqual(pdf.call_args.args[1], "INDEX")
        self.assertFalse(self.program.with_name("program - INDEX.nc").exists())

    def test_errors_are_visible_and_do_not_report_success(self):
        with patch("MASTERCAM_MAIN.QMessageBox.critical") as error:
            self.window.generate()
        self.assertIn("select a program", error.call_args.args[2].lower())

        self.window.select_file(str(self.program))
        self.window.index_enabled.setChecked(False)
        self.window.manuscript_enabled.setChecked(False)
        with patch("MASTERCAM_MAIN.QMessageBox.critical") as error:
            self.window.generate()
        self.assertIn("at least one output", error.call_args.args[2])

        self.window.select_file(str(self.program.with_name("missing.nc")))
        self.assertTrue(self.window.preview_status.text().startswith("Preview error:"))
        self.assertEqual(self.window.search_count.text(), "")


if __name__ == "__main__":
    unittest.main()
