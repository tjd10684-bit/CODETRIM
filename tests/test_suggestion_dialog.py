import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from group_suggestions import analyze_group_suggestions
from suggestion_dialog import SuggestionDialog


class SuggestionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def analysis(self):
        return analyze_group_suggestions([
            "G20 G17 G90 G54", "N10 M06 T1", "(SPOT HOLES)", "G0 X0 Y0",
            "G81 Z-1 R.1", "X1 Y1", "G80", "N20 M01", "(DRILL HOLES)",
            "M06 T2", "G0 X.01 Y0", "G81 Z-1 R.1", "X1.01 Y1", "G80", "M30",
        ])

    def test_review_accept_and_dismiss(self):
        callback = Mock(return_value=False)
        dialog = SuggestionDialog(self.analysis(), callback)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.suggestion_list.count(), 1)
        details = dialog.details.toPlainText()
        self.assertIn("not machine simulation", dialog.notice.text())
        self.assertIn("0.01 inch", details)
        self.assertIn("N10 M06 T1", details)
        self.assertIn("N20 M01", details)
        self.assertIn("SPOT HOLES", details)
        self.assertIn("DRILL HOLES", details)
        self.assertIn("X0.01000000", details)
        QTest.mouseClick(dialog.accept_button, Qt.MouseButton.LeftButton)
        callback.assert_called_once()
        self.assertEqual(dialog.suggestion_list.count(), 1)
        QTest.mouseClick(dialog.dismiss_button, Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.suggestion_list.count(), 0)
        self.assertIn("No suggestions", dialog.details.toPlainText())

    def test_accepted_suggestion_is_removed_from_review_list(self):
        callback = Mock(return_value=True)
        dialog = SuggestionDialog(self.analysis(), callback)
        self.addCleanup(dialog.close)
        dialog.show()
        QTest.mouseClick(dialog.accept_button, Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.suggestion_list.count(), 0)
        self.assertFalse(dialog.accept_button.isEnabled())
        callback.assert_called_once()

    def test_programmer_can_exclude_operations_before_accepting(self):
        lines = [
            "G20 G17 G90 G54", "M06 T1", "G0 X0 Y0", "G81 Z-1 R.1", "G80",
            "M01", "M06 T2", "G0 X0 Y0", "G81 Z-1 R.1", "G80",
            "M01", "M06 T3", "G0 X0 Y0", "G81 Z-1 R.1", "G80", "M30",
        ]
        callback = Mock(return_value=True)
        dialog = SuggestionDialog(analyze_group_suggestions(lines), callback)
        self.addCleanup(dialog.close)
        dialog.show()
        self.assertEqual(dialog.operation_list.count(), 3)
        dialog.operation_list.item(1).setCheckState(Qt.CheckState.Unchecked)
        self.assertIn("Excluded - source line", dialog.details.toPlainText())
        self.assertTrue(dialog.accept_button.isEnabled())
        dialog.operation_list.item(2).setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(dialog.accept_button.isEnabled())
        dialog.operation_list.item(2).setCheckState(Qt.CheckState.Checked)
        QTest.mouseClick(dialog.accept_button, Qt.MouseButton.LeftButton)
        accepted = callback.call_args.args[0]
        self.assertEqual([operation.tool for operation in accepted.operations], ["T1", "T3"])

    def test_skipped_operations_are_visible(self):
        analysis = analyze_group_suggestions([
            "G20 G17 G90 G54", "M06 T1", "G0 X0 Y0",
            "G81 Z-1 R.1 L4", "G80", "M30",
        ])
        dialog = SuggestionDialog(analysis, Mock())
        self.addCleanup(dialog.close)
        self.assertIn("1 operation(s) skipped", dialog.summary.text())
        self.assertIn("repetitions", dialog.details.toPlainText())
        self.assertFalse(dialog.accept_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
