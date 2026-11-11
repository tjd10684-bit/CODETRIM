import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QTextDocument
from PySide6.QtWidgets import QApplication

from color_utils import contrast_ratio
from gcode_highlighter import GCodeHighlighter
from nc_commands import nc_comment_spans, strip_nc_comments


class GCodeHighlighterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def highlight(self, text, background="#ffffff", sources=None):
        document = QTextDocument()
        highlighter = GCodeHighlighter(document)
        document.setPlainText(text)
        if sources is None:
            sources = list(range(len(text.split("\n"))))
        highlighter.set_context(sources, QColor(background))
        return document, highlighter

    def color_at(self, block, offset):
        for item in block.layout().formats():
            if item.start <= offset < item.start + item.length:
                return item.format.foreground().color().name()
        return None

    def test_reference_word_colors_and_comments(self):
        text = "N120 G00 G54 X-26.3481 Y11.4492 Z5. W6. I2 J3 K4 S382 M03 T80 F260 (G01 X9)"
        document, highlighter = self.highlight(text)
        block = document.firstBlock()
        colors = {word: self.color_at(block, text.index(word)) for word in (
            "N120", "G00", "G54", "X-26.3481", "Y11.4492", "Z5.",
            "W6.", "I2", "J3", "K4", "S382", "M03", "T80", "F260", "(G01",
        )}
        self.assertIsNone(colors["N120"])
        self.assertIsNone(colors["G54"])
        self.assertEqual(colors["G00"], colors["Z5."])
        self.assertEqual(colors["G00"], colors["W6."])
        self.assertEqual(colors["G00"], colors["K4"])
        self.assertEqual(colors["X-26.3481"], colors["I2"])
        self.assertEqual(colors["Y11.4492"], colors["J3"])
        self.assertEqual(colors["S382"], colors["F260"])
        self.assertEqual(len({colors["G00"], colors["X-26.3481"], colors["Y11.4492"], colors["M03"], colors["(G01"]}), 5)
        self.assertEqual(
            self.color_at(block, text.index("G01")),
            colors["(G01"],
        )
        self.assertIsNotNone(highlighter)

    def test_motion_codes_contiguous_words_and_nested_comments(self):
        text = "g01x1y-2 G02 G03 G010 G01.1 (outer (M06 X9)) ; G00 Z2"
        document, highlighter = self.highlight(text)
        block = document.firstBlock()
        motion = self.color_at(block, text.index("g01"))
        self.assertEqual(motion, self.color_at(block, text.index("G02")))
        self.assertEqual(motion, self.color_at(block, text.index("G03")))
        self.assertNotEqual(motion, self.color_at(block, text.index("x1")))
        self.assertIsNone(self.color_at(block, text.index("G010")))
        self.assertIsNone(self.color_at(block, text.index("G01.1")))
        comment = self.color_at(block, text.index("(outer"))
        self.assertEqual(comment, self.color_at(block, text.index("M06")))
        self.assertEqual(comment, self.color_at(block, text.index(";")))
        self.assertEqual(comment, self.color_at(block, text.index("G00")))
        self.assertIsNotNone(highlighter)

    def test_non_source_header_is_not_colored_and_unicode_offsets_are_correct(self):
        text = "NOTES: G00 X2\n(😀 note) G00 X2"
        document, highlighter = self.highlight(text, sources=[None, 0])
        self.assertEqual(document.firstBlock().layout().formats(), [])
        block = document.findBlockByNumber(1)
        line = block.text()
        g_offset = len(line[:line.index("G00")].encode("utf-16-le")) // 2
        x_offset = len(line[:line.index("X2")].encode("utf-16-le")) // 2
        self.assertNotEqual(self.color_at(block, 0), self.color_at(block, g_offset))
        self.assertNotEqual(self.color_at(block, g_offset), self.color_at(block, x_offset))
        self.assertIsNotNone(highlighter)

    def test_syntax_colors_remain_readable_on_theme_colors(self):
        text = "N10 G00 X2 Y3 (comment)"
        for background in ("#ffffff", "#202020", "#ffee00", "#0099ff", "#ff0000", "#777777"):
            with self.subTest(background=background):
                document, highlighter = self.highlight(text, background=background)
                block = document.firstBlock()
                for word in ("G00", "X2", "Y3", "(comment)"):
                    color = self.color_at(block, text.index(word))
                    self.assertIsNotNone(color)
                    self.assertGreaterEqual(
                        contrast_ratio(QColor(color), QColor(background)), 4.5
                    )
                self.assertIsNotNone(highlighter)

    def test_comment_spans_match_command_parser_behavior(self):
        text = "M(outer(inner))06 X2 ; G00"
        self.assertEqual(list(nc_comment_spans(text)), [(1, 15), (21, 26)])
        self.assertEqual(strip_nc_comments(text), "M06 X2 ")
        self.assertEqual(strip_nc_comments("M06 (unfinished ; G00"), "M06 ")
        self.assertEqual(strip_nc_comments("M06 ) X2"), "M06 ) X2")


if __name__ == "__main__":
    unittest.main()
