import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from highlight_groups import HighlightGroup, HighlightGroups, save_highlight_groups, source_hash
from group_suggestions import analyze_group_suggestions
from group_markers import GroupMarker
from index_generator import INDEX_SEPARATOR, generate_index_document, index_header_lines
from MASTERCAM_MAIN import MainWindow
from nc_commands import read_nc_lines
from pdf_export import create_pdf as export_pdf


def create_pdf(input_file, label, text, sources, group_colors, legend=(), header_line_count=0):
    markers = {
        line: GroupMarker(index, f"Group {index}", color)
        for index, (line, color) in enumerate(group_colors.items(), 1)
    }
    key = [
        GroupMarker(index, name, color)
        for index, (name, color) in enumerate(legend, 1)
    ]
    return export_pdf(
        input_file, label, text, sources, markers,
        legend=key, header_line_count=header_line_count,
    )


class PDFExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.program = Path(self.directory.name) / "program.nc"
        self.program.write_text(
            "N0 HEADER\nN1 M06 T1\nN2 M01 G00 X123 Y456\nN3 G02 X-2 Y3\nN4 M30\n",
            encoding="utf-8",
        )

    def open_pdf(self, path):
        reader = QPdfDocument()
        self.assertEqual(reader.load(str(path)), QPdfDocument.Error.None_)
        return reader

    def page_body(self, reader, page):
        text = reader.getAllText(page).text()
        lines = text.splitlines()
        footer = f"Page {page + 1} of {reader.pageCount()}"
        if lines[0] == self.program.name and lines[-1] == footer:
            return "\n".join(lines[1:-1])
        compact = "".join(text.split())
        header_compact = "".join(self.program.name.split())
        footer_compact = "".join(footer.split())
        self.assertTrue(compact.startswith(header_compact))
        self.assertTrue(compact.endswith(footer_compact))
        return compact[len(header_compact):-len(footer_compact)]

    def test_letter_pdf_preserves_text_and_group_colors(self):
        text = "INDEX\nN1 M06\nN2 M01 G00 X123 Y456\nN3 G02 X-2 Y3"
        path = create_pdf(
            self.program, "INDEX", text, [None, 1, 2, 3],
            {2: "#ffee00", 3: "#283593"},
        )
        reader = self.open_pdf(path)
        try:
            self.assertEqual(reader.pageCount(), 1)
            size = reader.pagePointSize(0)
            self.assertAlmostEqual(size.width(), 612, delta=0.1)
            self.assertAlmostEqual(size.height(), 792, delta=0.1)
            compact = "".join(self.page_body(reader, 0).split())
            self.assertIn("N1M06", compact)
            self.assertIn("N2M01G00X123Y456", compact)
            self.assertIn("N3G02X-2Y3", compact)
            image = reader.render(0, QSize(1224, 1584))
            for background, light_text in (("#ffee00", False), ("#283593", True)):
                rows = [
                    y for y in range(60, 250)
                    if any(
                        image.pixelColor(x, y).name() == background
                        for x in range(72, 104)
                    )
                ]
                self.assertTrue(rows, background)
                self.assertTrue(all(
                    image.pixelColor(1000, y).name() != background for y in rows
                ), f"Highlight for {background} extends into the notes area")
                self.assertTrue(any(
                    pixel.alpha() > 0 and (
                        (pixel.red() > 200 and pixel.green() > 200 and pixel.blue() > 200)
                        if light_text else
                        (pixel.red() < 60 and pixel.green() < 60 and pixel.blue() < 60)
                    )
                    for y in rows
                    for x in range(72, 104)
                    for pixel in (image.pixelColor(x, y),)
                ), f"No readable {'white' if light_text else 'black'} text on {background}")
        finally:
            reader.close()
            del reader

    def test_long_lines_wrap_across_pages_without_text_loss_or_duplication(self):
        text = "LONG:" + ("0123456789" * 1000) + " END\n" + "\n".join(
            f"N{i:04d} G01 X{i}" for i in range(160)
        )
        sources = list(range(len(text.split("\n"))))
        path = create_pdf(self.program, "MANUSCRIPT", text, sources, {0: "#ffee00"})
        reader = self.open_pdf(path)
        try:
            self.assertGreater(reader.pageCount(), 2)
            pages = [self.page_body(reader, i) for i in range(reader.pageCount())]
            self.assertEqual("".join("".join(page.split()) for page in pages)[1:], "".join(text.split()))
            for page in (0,):
                image = reader.render(page, QSize(612, 792))
                self.assertTrue(
                    any(image.pixelColor(40, y).name() == "#ffee00" for y in range(36, 756)),
                    f"Missing marker on page {page + 1}",
                )
        finally:
            reader.close()
            del reader

    def test_filename_and_page_numbers_are_centered_on_every_page(self):
        text = "\n".join(f"N{i:04d} G01 X{i}" for i in range(150))
        for label in ("INDEX", "MANUSCRIPT"):
            with self.subTest(output=label):
                path = create_pdf(self.program, label, text, list(range(150)), {})
                reader = self.open_pdf(path)
                try:
                    self.assertGreater(reader.pageCount(), 1)
                    pages = [self.page_body(reader, i) for i in range(reader.pageCount())]
                    self.assertEqual(
                        "".join("".join(page.split()) for page in pages),
                        "".join(text.split()),
                    )
                    for page in range(reader.pageCount()):
                        image = reader.render(page, QSize(612, 792))
                        for top, bottom in ((36, 52), (738, 756)):
                            ink_x = [
                                x for x in range(36, 576)
                                if any(image.pixelColor(x, y).alpha() > 0 for y in range(top, bottom))
                            ]
                            self.assertTrue(ink_x, f"Missing page label on page {page + 1}")
                            self.assertAlmostEqual(
                                (ink_x[0] + ink_x[-1]) / 2, 306, delta=3,
                                msg=f"Page label is not centered on page {page + 1}",
                            )
                finally:
                    reader.close()
                    del reader

    def test_long_source_filename_wraps_without_clipping(self):
        source = self.program.with_name("program_" + "X" * 150 + ".nc")
        path = create_pdf(source, "INDEX", "N1 M06", [0], {})
        reader = self.open_pdf(path)
        try:
            compact = "".join(reader.getAllText(0).text().split())
            self.assertTrue(compact.startswith(source.name))
            self.assertIn("N1M06", compact)
            self.assertTrue(compact.endswith("Page1of1"))
            self.assertNotIn("INDEX.pdf", compact)
        finally:
            reader.close()
            del reader

    def test_source_filename_with_spaces_and_unicode_is_preserved(self):
        source = self.program.with_name("Pièce 42.nc")
        path = create_pdf(source, "INDEX", "N1 M06", [0], {})
        reader = self.open_pdf(path)
        try:
            lines = reader.getAllText(0).text().splitlines()
            self.assertEqual(lines[0], source.name)
            self.assertEqual(lines[-1], "Page 1 of 1")
        finally:
            reader.close()
            del reader

    def test_failed_export_does_not_replace_existing_pdf(self):
        path = self.program.with_name("program - INDEX.pdf")
        path.write_bytes(b"existing file")
        with patch("pdf_export.QFontDatabase.families", return_value=[]):
            with self.assertRaisesRegex(ValueError, "No fonts"):
                create_pdf(self.program, "INDEX", "N1 M06", [0], {})
        self.assertEqual(path.read_bytes(), b"existing file")

    def test_mapping_errors_are_reported(self):
        with self.assertRaisesRegex(ValueError, "mapping"):
            create_pdf(self.program, "INDEX", "N1 M06\nN2 M01", [0], {})
        self.assertFalse(self.program.with_name("program - INDEX.pdf").exists())

    def test_empty_output_and_unicode_text(self):
        empty_path = create_pdf(self.program, "MANUSCRIPT", "", [], {})
        reader = self.open_pdf(empty_path)
        try:
            self.assertEqual(reader.pageCount(), 1)
            self.assertEqual(self.page_body(reader, 0), "")
        finally:
            reader.close()
            del reader
        text = "INDEX\nCUSTOMER: Café\nNOTES: première opération\nN1 M06"
        path = create_pdf(self.program, "INDEX", text, [None, None, None, 1], {})
        reader = self.open_pdf(path)
        try:
            self.assertEqual(self.page_body(reader, 0), text)
        finally:
            reader.close()
            del reader

    def test_large_index_key_paginates_without_losing_names_or_overlapping_body(self):
        note_words = [f"NOTE{i:03d}" for i in range(250)]
        notes = " ".join(note_words)
        text, sources = generate_index_document(
            self.program, 3, 0, 0, "Example", "Part", notes
        )
        header_count = sum(
            line.count("\n") + 1
            for line in index_header_lines(self.program, "Example", "Part", notes)
        )
        legend = [(f"GROUP{i:04d}", "#ffee00") for i in range(1200)]
        path = create_pdf(
            self.program, "INDEX", text, sources, {}, legend=legend,
            header_line_count=header_count,
        )
        reader = self.open_pdf(path)
        try:
            self.assertGreater(reader.pageCount(), 2)
            pages = ["".join(self.page_body(reader, i).split()) for i in range(reader.pageCount())]
            for word in note_words:
                self.assertEqual(sum(page.count(word) for page in pages), 1, word)
            for name, _ in legend:
                self.assertEqual(sum(page.count(name) for page in pages), 1, name)
            last_note_page = next(i for i, page in enumerate(pages) if "NOTE249" in page)
            first_group_page = next(i for i, page in enumerate(pages) if "GROUP0000" in page)
            self.assertGreaterEqual(first_group_page, last_note_page)
            if first_group_page == last_note_page:
                self.assertGreater(pages[first_group_page].index("GROUP0000"), pages[first_group_page].index("NOTE249"))
            last_group_page = next(i for i, page in enumerate(pages) if "GROUP1199" in page)
            first_body_page = next(i for i, page in enumerate(pages) if "N0HEADER" in page)
            self.assertGreaterEqual(first_body_page, last_group_page)
            if first_body_page == last_group_page:
                self.assertGreater(pages[first_body_page].index("N0HEADER"), pages[first_body_page].index("GROUP1199"))
        finally:
            reader.close()
            del reader

    def test_long_group_names_wrap_without_clipping(self):
        text, sources = generate_index_document(
            self.program, 3, 0, 0, "Example", "Part", "Notes"
        )
        name = "z" * 400
        path = create_pdf(
            self.program, "INDEX", text, sources, {},
            legend=[(name, "#ffee00")], header_line_count=5,
        )
        reader = self.open_pdf(path)
        try:
            all_text = "".join(self.page_body(reader, i) for i in range(reader.pageCount()))
            self.assertEqual(all_text.count("z"), len(name))
            image = reader.render(0, QSize(612, 792))
            self.assertTrue(any(
                image.pixelColor(x, y).name() == "#ffee00"
                for x in range(50, 80) for y in range(80, 300)
            ))
        finally:
            reader.close()
            del reader

    def test_legend_is_below_index_header_and_before_body(self):
        text, sources = generate_index_document(
            self.program, 3, 0, 0, "Example", "Part", "Notes"
        )
        path = create_pdf(
            self.program, "INDEX", text, sources, {2: "#ffee00"},
            legend=[("Drilling", "#ffee00")], header_line_count=5,
        )
        reader = self.open_pdf(path)
        try:
            compact = "".join(self.page_body(reader, 0).split())
            self.assertLess(compact.index("---"), compact.index("GROUPINDEX"))
            self.assertLess(compact.index("Drilling"), compact.index("N0HEADER"))
        finally:
            reader.close()
            del reader

    def test_five_even_columns_and_additional_rows(self):
        text, sources = generate_index_document(self.program, 3, 0, 0, "C", "P", "")
        path = create_pdf(
            self.program, "INDEX", text, sources, {},
            legend=[(f"G{i:02}", "#ffee00") for i in range(1, 7)], header_line_count=5,
        )
        reader = self.open_pdf(path)
        try:
            image = reader.render(0, QSize(612, 792))
            regions = []
            for x1, x2 in ((50, 80), (140, 180), (230, 280), (330, 380), (420, 480)):
                regions.append({
                    y for y in range(100, 300)
                    if any(image.pixelColor(x, y).name() == "#ffee00" for x in range(x1, x2))
                })
            self.assertTrue(set.intersection(*regions), "Five bubbles must share a row")
            self.assertTrue(regions[0] - regions[1], "Sixth bubble must start another row")
            image = reader.render(0, QSize(1224, 1584))
            colored = [
                y for y in range(150, 600)
                if any(image.pixelColor(x, y).name() == "#ffee00" for x in range(110, 145))
            ]
            runs = []
            for y in colored:
                if not runs or y > runs[-1][-1] + 1:
                    runs.append([y])
                else:
                    runs[-1].append(y)
            self.assertEqual(len(runs), 2)
            self.assertGreater(runs[1][0] - runs[0][-1] - 1, 0)
            self.assertAlmostEqual(
                (runs[1][0] - runs[0][0]) / len(runs[0]), 1.5, delta=0.15
            )
            text = self.page_body(reader, 0)
            self.assertEqual(text.count(INDEX_SEPARATOR), 2)
            self.assertLess(text.index("GROUP INDEX"), text.rindex(INDEX_SEPARATOR))
            self.assertLess(text.rindex(INDEX_SEPARATOR), text.index("N0 HEADER"))
        finally:
            reader.close()
            del reader

    def test_double_digit_bubble_numbers_are_not_duplicated_in_pdf_text(self):
        text, sources = generate_index_document(self.program, 3, 0, 0, "C", "P", "")
        legend = [(f"Group{i}", "#ffee00") for i in range(1, 12)]
        path = create_pdf(
            self.program, "INDEX", text, sources, {}, legend=legend, header_line_count=5
        )
        reader = self.open_pdf(path)
        try:
            compact = "".join(reader.getAllText(0).text().split())
            self.assertNotIn("1100-Group10", compact)
            self.assertNotIn("1111-Group11", compact)
            for name, _ in legend:
                self.assertIn(name, compact)
        finally:
            reader.close()
            del reader

    def test_wide_header_moves_key_below_separator_and_before_body(self):
        notes = "LONGNOTE0123456789" * 5
        text, sources = generate_index_document(self.program, 3, 0, 0, "C", "P", notes)
        path = create_pdf(
            self.program, "INDEX", text, sources, {},
            legend=[("G01", "#ffee00"), ("G02", "#ffee00")], header_line_count=5,
        )
        reader = self.open_pdf(path)
        try:
            compact = "".join(self.page_body(reader, 0).split())
            self.assertIn(notes, compact)
            self.assertLess(compact.index("---"), compact.index("GROUPINDEX"))
            self.assertLess(compact.index("GROUPINDEX"), compact.index("N0HEADER"))
            self.assertIn("G01", compact)
            self.assertIn("G02", compact)
        finally:
            reader.close()
            del reader

    def test_tall_key_moves_below_separator_and_before_body(self):
        text, sources = generate_index_document(self.program, 3, 0, 0, "C", "P", "")
        legend = [(f"G{i:03d}", "#ffee00") for i in range(40)]
        path = create_pdf(
            self.program, "INDEX", text, sources, {}, legend=legend, header_line_count=5,
        )
        reader = self.open_pdf(path)
        try:
            compact = "".join(self.page_body(reader, 0).split())
            self.assertLess(compact.index("---"), compact.index("GROUPINDEX"))
            self.assertLess(compact.index("GROUPINDEX"), compact.index("G000"))
            self.assertLess(compact.index("G039"), compact.index("N0HEADER"))
        finally:
            reader.close()
            del reader

    def test_multi_page_headers_keep_key_and_body_in_order(self):
        for count in (650, 900, 1400):
            with self.subTest(note_words=count):
                notes = " ".join(f"NTE{i:04d}" for i in range(count))
                text, sources = generate_index_document(
                    self.program, 3, 0, 0, "C", "P", notes
                )
                path = create_pdf(
                    self.program, "INDEX", text, sources, {},
                    legend=[(f"G{i:03d}", "#ffee00") for i in range(20)],
                    header_line_count=5,
                )
                reader = self.open_pdf(path)
                try:
                    pages = [
                        "".join(self.page_body(reader, i).split())
                        for i in range(reader.pageCount())
                    ]
                    combined = "".join(pages)
                    self.assertEqual(combined.count(INDEX_SEPARATOR), 2)
                    markers = (f"NTE{count - 1:04d}", "GROUPINDEX", "G019", "N0HEADER")
                    for marker in markers:
                        self.assertEqual(combined.count(marker), 1, marker)
                    positions = [combined.index(marker) for marker in markers]
                    self.assertEqual(positions, sorted(positions))
                    self.assertLess(combined.index(INDEX_SEPARATOR), combined.index("GROUPINDEX"))
                    self.assertGreater(combined.rindex(INDEX_SEPARATOR), combined.index("G019"))
                    self.assertLess(combined.rindex(INDEX_SEPARATOR), combined.index("N0HEADER"))
                finally:
                    reader.close()
                    del reader

    def test_gui_pdf_text_and_combined_formats(self):
        window = MainWindow()
        self.addCleanup(window.close)
        window.select_file(str(self.program))
        self.assertEqual(window.output_format.currentData(), "pdf")
        lines = read_nc_lines(self.program)
        state = HighlightGroups(
            groups=[
                HighlightGroup("one", "Holes", "#ffee00"),
                HighlightGroup("two", "Excluded", "#283593"),
                HighlightGroup("three", "Unassigned", "#00ff00"),
            ],
            assignments={2: "one", 3: "two"},
            source_hash=source_hash(lines),
        )
        save_highlight_groups(self.program, lines, state)
        window.select_file(str(self.program))
        window.index_after.setValue(0)
        with patch("MASTERCAM_MAIN.QMessageBox.information") as success:
            window.generate()
        success.assert_called_once()
        index_pdf = self.program.with_name("program - INDEX.pdf")
        manuscript_pdf = self.program.with_name("program - MANUSCRIPT.pdf")
        index_nc = self.program.with_name("program - INDEX.nc")
        manuscript_nc = self.program.with_name("program - MANUSCRIPT.nc")
        self.assertTrue(index_pdf.exists())
        self.assertTrue(manuscript_pdf.exists())
        self.assertFalse(index_nc.exists())
        self.assertFalse(manuscript_nc.exists())
        for path in (index_pdf, manuscript_pdf):
            reader = self.open_pdf(path)
            try:
                page_text = reader.getAllText(0).text()
                compact = "".join(page_text.split())
                self.assertIn("N2M01G00X123Y456", compact)
                if path == index_pdf:
                    self.assertIn("GROUPINDEX", compact)
                    self.assertIn("Holes", compact)
                    self.assertIn("Excluded", compact)
                    self.assertNotIn("Unassigned", compact)
                else:
                    self.assertNotIn("GROUPINDEX", compact)
                    self.assertNotIn("Holes", compact)
                image = reader.render(0, QSize(612, 792))
                self.assertTrue(any(
                    image.pixelColor(40, y).name() == "#ffee00" for y in range(36, 756)
                ))
            finally:
                reader.close()
                del reader

        window.output_format.setCurrentIndex(window.output_format.findData("text"))
        with patch("MASTERCAM_MAIN.QMessageBox.information"):
            window.generate()
        self.assertTrue(index_nc.exists())
        self.assertTrue(manuscript_nc.exists())
        self.assertNotIn("Holes", index_nc.read_text(encoding="utf-8"))
        index_nc.unlink()
        manuscript_nc.unlink()
        window.output_format.setCurrentIndex(window.output_format.findData("both"))
        with patch("MASTERCAM_MAIN.QMessageBox.information"):
            window.generate()
        self.assertTrue(index_nc.exists())
        self.assertTrue(manuscript_nc.exists())
        self.assertTrue(index_pdf.exists())
        self.assertTrue(manuscript_pdf.exists())

    def test_accepted_suggestion_appears_in_index_pdf(self):
        source_text = (
            "G20 G17 G90 G54\nN10 M06 T1\nG00 X0 Y0\nG81 Z-1 R.1\n"
            "X1 Y1\nG80\nN20 M01\n(DRILL HOLES)\nN30 M06 T2\n"
            "G00 X.01 Y-.01\nG81 Z-1 R.1\nX1.01 Y1.01\nG80\nM30\n"
        )
        self.program.write_text(source_text, encoding="utf-8")
        window = MainWindow()
        self.addCleanup(window.close)
        window.select_file(str(self.program))
        suggestion = analyze_group_suggestions(read_nc_lines(self.program)).suggestions[0]
        with patch("MASTERCAM_MAIN.QInputDialog.getText", return_value=("Hole Set", True)):
            with patch("MASTERCAM_MAIN.choose_group_color", return_value="#ffee00"):
                self.assertTrue(window.accept_suggested_group(suggestion, window))
        with patch("MASTERCAM_MAIN.QMessageBox.information"):
            window.generate()
        index_pdf = self.program.with_name("program - INDEX.pdf")
        reader = self.open_pdf(index_pdf)
        try:
            compact = "".join(reader.getAllText(0).text().split())
            self.assertIn("GROUPINDEX", compact)
            self.assertIn("HoleSet", compact)
            self.assertIn("N20M01", compact)
        finally:
            reader.close()
            del reader
        self.assertEqual(self.program.read_text(encoding="utf-8"), source_text)


if __name__ == "__main__":
    unittest.main()
