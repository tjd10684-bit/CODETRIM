import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from color_utils import contrast_ratio, contrasting_text_color
from group_palette import GROUP_COLORS, GROUP_COLOR_VALUES, GroupColorDialog, nearest_group_color


class GroupPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_palette_color_has_at_least_seven_to_one_contrast(self):
        self.assertEqual(len(GROUP_COLORS), len(GROUP_COLOR_VALUES))
        for name, value in GROUP_COLORS:
            with self.subTest(color=name):
                background = QColor(value)
                foreground = contrasting_text_color(background)
                self.assertIn(foreground.name(), ("#000000", "#ffffff"))
                self.assertGreaterEqual(contrast_ratio(foreground, background), 7.0)

    def test_nearest_color_is_in_palette_and_preserves_exact_matches(self):
        for _, color in GROUP_COLORS:
            self.assertEqual(nearest_group_color(color), color)
        for color in ("#ff0000", "#0099ff", "#777777", "#123456"):
            self.assertIn(nearest_group_color(color), GROUP_COLOR_VALUES)

    def test_dialog_only_offers_palette_colors_and_accepts_clicked_swatch(self):
        dialog = GroupColorDialog(None, "#ffee00")
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        for name, _ in GROUP_COLORS:
            self.assertIn(f"{name}  Aa", buttons)
        QTest.mouseClick(buttons["Navy  Aa"], Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.selected_color, "#283593")


if __name__ == "__main__":
    unittest.main()
