import configparser
import tempfile
import unittest
from pathlib import Path

from index_generator import generate_index_text
from nc_commands import (
    count_search_code,
    has_m_code,
    has_search_code,
    parse_code,
    read_nc_lines,
)
from project_settings import load_project_settings, save_project_settings
from setup_copy_generator import generate_manuscript_text


class NCCommandTests(unittest.TestCase):
    def test_matches_m_codes_as_nc_words(self):
        for line in ("N10 M06 T14", "N10M06T14", "m6", "M006"):
            with self.subTest(line=line):
                self.assertTrue(has_m_code(line, 6))
        self.assertTrue(has_m_code("N20 M01", 1))
        self.assertTrue(has_m_code("N30 M30", 30))

    def test_ignores_comments_and_substring_matches(self):
        for line in (
            "(M06)",
            "N10 (M06) G00",
            "N10 (outer (M06)) G00",
            "N10 G00 ; M06",
            "XM06",
            "M060",
            "M06.1",
            "M601",
        ):
            with self.subTest(line=line):
                self.assertFalse(has_m_code(line, 6))

    def test_reads_utf16_and_windows_legacy_text(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            utf16_file = Path(temporary_directory) / "utf16.nc"
            utf16_file.write_bytes("N1 M06 (cafe)\n".encode("utf-16"))
            self.assertEqual(read_nc_lines(utf16_file), ["N1 M06 (cafe)"])

            legacy_file = Path(temporary_directory) / "legacy.nc"
            legacy_file.write_bytes("N1 (caf\xe9) M06\n".encode("cp1252"))
            self.assertEqual(read_nc_lines(legacy_file), ["N1 (café) M06"])

    def test_parse_code_accepts_m_and_g_words(self):
        self.assertEqual(parse_code("M01"), ("M", 1))
        self.assertEqual(parse_code("m6"), ("M", 6))
        self.assertEqual(parse_code("G28"), ("G", 28))

    def test_parse_code_rejects_malformed_text(self):
        for text in ("", "M", "01", "MM01", "M01 T2"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "not a valid"):
                    parse_code(text)

    def test_has_search_code_matches_g_codes(self):
        self.assertTrue(has_search_code("N10 G28 G91 Z0", "G28"))
        self.assertFalse(has_search_code("N10 G280", "G28"))
        self.assertFalse(has_search_code("(G28)", "G28"))

    def test_count_search_code_counts_matching_lines_only(self):
        lines = [
            "N1 M06 T1",
            "N2 M01",
            "(comment M01)",
            "N3 M01",
            "N4 G28 G91 Z0",
        ]
        self.assertEqual(count_search_code(lines, "M01"), 2)
        self.assertEqual(count_search_code(lines, "G28"), 1)
        self.assertEqual(count_search_code(lines, "M06"), 1)
        self.assertEqual(count_search_code([], "M01"), 0)


class GeneratorTests(unittest.TestCase):
    def write_program(self, directory, text):
        input_file = Path(directory) / "program.nc"
        input_file.write_text(text, encoding="utf-8")
        return input_file

    def test_index_extracts_command_lines_and_handles_missing_commands(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory,
                "(comment M06)\nN1 G00\nN2 M06 T1\nN3\nM601\n",
            )
            result = generate_index_text(input_file, 1, 0, 1, "", "", "")

        self.assertIn("N1 G00\nN2 M06 T1", result)
        self.assertNotIn("(comment M06)", result)
        self.assertNotIn("M601", result)

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory, "N1 G00\n(comment M06)\nN2 M601\n"
            )
            result = generate_index_text(input_file, 3, 0, 2, "", "", "")
        self.assertTrue(result.startswith("INDEX\n"))
        self.assertNotIn("M06", result)

    def test_index_supports_lines_before_each_search_code_match(self):
        lines = [
            "N0 HEADER",
            "N1 M06 T1",
            "N2 A",
            "N3 B",
            "N4 M01",
            "N5 C",
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory, "\n".join(lines) + "\n"
            )
            result = generate_index_text(input_file, 0, 2, 1, "", "", "")

        self.assertIn("N2 A\nN3 B\nN4 M01\nN5 C", result)

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory, "\n".join(lines) + "\n"
            )
            result_no_before = generate_index_text(
                input_file, 0, 0, 1, "", "", ""
            )

        self.assertIn("N4 M01\nN5 C", result_no_before)
        self.assertNotIn("N2 A", result_no_before)
        self.assertNotIn("N3 B", result_no_before)

    def test_manuscript_merges_overlaps_and_preserves_extraction_boundaries(self):
        lines = [
            "N0 HEADER",
            "N1 BEFORE",
            "N2 M06 T1",
            "N3 TOOL",
            "N4 APPROACH",
            "N5 M01",
            "N6 BETWEEN",
            "N7 M01",
            "N8 DEPART",
            "N9 M30",
            "N10 END",
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory, "\n".join(lines) + "\n"
            )
            result = generate_manuscript_text(input_file, 2, 1)

        self.assertIn(
            "N0 HEADER\nN1 BEFORE\nN2 M06 T1\nN3 TOOL\nN4 APPROACH",
            result,
        )
        self.assertEqual(result.count("(CODE REMOVED)"), 2)
        self.assertEqual(result.count("N6 BETWEEN"), 1)
        self.assertIn("N5 M01\nN6 BETWEEN\nN7 M01\nN8 DEPART", result)
        self.assertTrue(result.endswith("N9 M30\nN10 END"))

    def test_manuscript_handles_missing_m06_m01_and_m30(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory,
                "N1 G00\n(comment M01)\nN2 M601\n",
            )
            self.assertEqual(generate_manuscript_text(input_file, 2, 2), "")

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory, "N1 M06 T1\nN2 TOOL\n"
            )
            result = generate_manuscript_text(input_file, 1, 1)
        self.assertIn("N1 M06 T1\nN2 TOOL", result)
        self.assertNotIn("M30", result)

    def test_rejects_negative_line_counts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(temporary_directory, "N1 M06\n")
            with self.assertRaisesRegex(ValueError, "non-negative"):
                generate_index_text(input_file, -1, 0, 0, "", "", "")
            with self.assertRaisesRegex(ValueError, "non-negative"):
                generate_manuscript_text(input_file, 0, -1)

    def test_index_supports_alternate_search_code(self):
        lines = [
            "N0 HEADER",
            "N1 M06 T1",
            "N2 TOOL",
            "N3 G28 G91 Z0",
            "N4 X0 Y0",
            "N5 G00",
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory, "\n".join(lines) + "\n"
            )
            result = generate_index_text(
                input_file, 1, 0, 1, "", "", "", search_code="G28"
            )

        self.assertIn("N3 G28 G91 Z0\nN4 X0 Y0", result)
        self.assertNotIn("N5 G00", result)

    def test_manuscript_supports_alternate_search_code(self):
        lines = [
            "N0 HEADER",
            "N1 M06 T1",
            "N2 TOOL",
            "N3 G28 G91 Z0",
            "N4 X0 Y0",
            "N5 M30",
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = self.write_program(
                temporary_directory, "\n".join(lines) + "\n"
            )
            result = generate_manuscript_text(
                input_file, 1, 1, search_code="G28"
            )

        self.assertIn("N3 G28 G91 Z0\nN4 X0 Y0", result)


class ProjectSettingsTests(unittest.TestCase):
    def test_loads_legacy_unindented_multiline_notes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = Path(temporary_directory) / "program.nc"
            settings_file = input_file.parent / "project_settings.ini"
            settings_file.write_text(
                "# Mastercam Tools Project Settings\n"
                "# Automatically created by Mastercam Tools.\n"
                "\n[Project]\n"
                "Customer=Customer\nPartNumber=Part\n"
                "Notes=first line\nsecond: 100% = ok\n"
                "# note, not a comment\n[also a note]\n\nlast line\n",
                encoding="utf-8",
            )
            values = load_project_settings(input_file)
            self.assertEqual(values, {
                "customer": "Customer",
                "part_number": "Part",
                "notes": "first line\nsecond: 100% = ok\n"
                         "# note, not a comment\n[also a note]\n\nlast line",
            })
            save_project_settings(input_file, **values)
            self.assertEqual(load_project_settings(input_file), values)

    def test_legacy_empty_first_note_line_and_trailing_blank_line(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = Path(temporary_directory) / "program.nc"
            (input_file.parent / "project_settings.ini").write_text(
                "# Mastercam Tools Project Settings\n"
                "[Project]\nCustomer=Customer\nPartNumber=Part\n"
                "Notes=\nsecond line\n\n",
                encoding="utf-8",
            )
            self.assertEqual(load_project_settings(input_file)["notes"], "\nsecond line\n")

    def test_malformed_nonlegacy_settings_still_raise(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = Path(temporary_directory) / "program.nc"
            (input_file.parent / "project_settings.ini").write_text(
                "[Project]\nCustomer=Customer\ninvalid line\n",
                encoding="utf-8",
            )
            with self.assertRaises(configparser.ParsingError):
                load_project_settings(input_file)

    def test_settings_round_trip_preserves_special_and_multiline_values(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = Path(temporary_directory) / "program.nc"
            values = {
                "customer": "Café Co. = 100%",
                "part_number": "PART:#42",
                "notes": "first line\nsecond: 100% = ok\nline with ; and #",
            }
            save_project_settings(input_file, **values)
            self.assertEqual(load_project_settings(input_file), values)

    def test_settings_round_trip_preserves_whitespace_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = Path(temporary_directory) / "program.nc"
            notes = "  first line  \n# note\n; another note\n\nlast line\n"
            save_project_settings(input_file, "Customer", "Part", notes)
            self.assertEqual(load_project_settings(input_file)["notes"], notes)

    def test_missing_settings_returns_empty_defaults(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_file = Path(temporary_directory) / "program.nc"
            self.assertEqual(
                load_project_settings(input_file),
                {"customer": "", "part_number": "", "notes": ""},
            )


if __name__ == "__main__":
    unittest.main()
