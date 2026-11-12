import unittest
from unittest.mock import Mock

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QPainter

from group_markers import GroupMarker, assigned_markers, key_rows, paint_marker
from highlight_groups import HighlightGroup, HighlightGroups


class GroupMarkerTests(unittest.TestCase):
    def test_marker_numbers_are_bold_without_changing_lime_text_color(self):
        painter = Mock()
        painter.RenderHint = QPainter.RenderHint
        font = QFont()
        font.setBold(False)
        paint_marker(painter, QRectF(0, 0, 30, 12), GroupMarker(1, "Holes", "#00ff00"), font)
        self.assertTrue(painter.setFont.call_args.args[0].bold())
        self.assertFalse(font.bold())
        self.assertEqual(painter.setPen.call_args_list[-1].args[0], QColor("black"))
        painter.restore.assert_called_once()

    def test_numbers_follow_assigned_groups_in_order(self):
        state = HighlightGroups(
            groups=[
                HighlightGroup("empty", "Unused", "#00ff00"),
                HighlightGroup("a", "Drill", "#ffee00"),
                HighlightGroup("b", "Tap", "#283593"),
            ],
            assignments={7: "b", 9: "a", 12: "a"},
        )
        lines, groups = assigned_markers(state)
        self.assertEqual([(item.number, item.name) for item in groups], [(1, "Drill"), (2, "Tap")])
        self.assertEqual([lines[line].number for line in (7, 9, 12)], [2, 1, 1])
        del state.assignments[9]
        del state.assignments[12]
        lines, groups = assigned_markers(state)
        self.assertEqual((lines[7].number, groups[0].name), (1, "Tap"))

    def test_five_columns_add_rows_and_wrap_long_names(self):
        state = HighlightGroups(
            groups=[HighlightGroup(str(i), f"GROUP{i:02d}", "#ffee00") for i in range(1, 12)],
            assignments={i: str(i) for i in range(1, 12)},
        )
        _, groups = assigned_markers(state)
        rows, positions = key_rows(groups, 18)
        self.assertEqual([len(positions[row]) for row in (0, 1, 2)], [5, 5, 1])
        self.assertEqual([marker.number for _, marker in positions[1]], [6, 7, 8, 9, 10])
        self.assertTrue(all(name in "".join(rows) for name in ("GROUP01", "GROUP10", "GROUP11")))
        groups[0] = type(groups[0])(1, "A long name that needs wrapping", "#ffee00")
        rows, positions = key_rows(groups[:2], 14)
        self.assertGreater(len(rows), 1)
        self.assertEqual([marker.number for _, marker in positions[0]], [1, 2])


if __name__ == "__main__":
    unittest.main()
