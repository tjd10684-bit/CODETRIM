import json
import tempfile
import unittest
from pathlib import Path

from highlight_groups import (
    HighlightGroup,
    HighlightGroups,
    groups_path,
    load_highlight_groups,
    save_highlight_groups,
    source_hash,
)
from index_generator import generate_index_document, generate_index_text
from setup_copy_generator import generate_manuscript_document, generate_manuscript_text


class HighlightGroupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.program = Path(self.directory.name) / "program.nc"
        self.lines = ["HEADER", "N1 M06", "N2 M01", "N3 M01", "M30"]
        self.program.write_text("\n".join(self.lines), encoding="utf-8")
        self.group = HighlightGroup("group1", "Holes", "#ffee00")

    def save_assignments(self, assignments):
        state = HighlightGroups(
            groups=[self.group], assignments=assignments, source_hash=source_hash(self.lines)
        )
        save_highlight_groups(self.program, self.lines, state)
        return state

    def test_round_trip_and_program_specific_files(self):
        self.save_assignments({2: "group1", 3: "group1"})
        loaded = load_highlight_groups(self.program, self.lines)
        self.assertEqual(loaded.groups, [self.group])
        self.assertEqual(loaded.assignments, {2: "group1", 3: "group1"})
        other = self.program.with_suffix(".txt")
        self.assertNotEqual(groups_path(self.program), groups_path(other))
        self.assertEqual(load_highlight_groups(other, self.lines).groups, [])

    def test_changed_program_matches_unique_lines_and_retains_unmatched(self):
        self.save_assignments({1: "group1", 2: "group1", 3: "group1"})
        changed = ["NEW", "HEADER", "N1 M06", "N2 M01", "N2 M01", "M30"]
        loaded = load_highlight_groups(self.program, changed)
        self.assertEqual(loaded.assignments, {2: "group1"})
        self.assertEqual(
            [(item.text, item.group_id) for item in loaded.unmatched],
            [("N2 M01", "group1"), ("N3 M01", "group1")],
        )
        save_highlight_groups(self.program, changed, loaded)
        reloaded = load_highlight_groups(self.program, changed)
        self.assertEqual(reloaded.assignments, {2: "group1"})
        self.assertEqual(reloaded.unmatched, loaded.unmatched)

        restored = ["NEW", "N1 M06", "N2 M01", "N3 M01", "M30"]
        restored_state = load_highlight_groups(self.program, restored)
        self.assertEqual(restored_state.assignments, {1: "group1", 2: "group1", 3: "group1"})
        self.assertEqual(restored_state.unmatched, [])

    def test_duplicate_assigned_lines_are_never_guessed_after_edit(self):
        self.lines = ["DUP", "DUP", "M30"]
        self.save_assignments({0: "group1", 1: "group1"})
        loaded = load_highlight_groups(self.program, ["NEW", "DUP", "M30"])
        self.assertEqual(loaded.assignments, {})
        self.assertEqual(len(loaded.unmatched), 2)

    def test_refuses_to_overwrite_changed_source_or_group_file(self):
        state = self.save_assignments({2: "group1"})
        with self.assertRaisesRegex(ValueError, "program changed"):
            save_highlight_groups(self.program, ["changed"], state)
        path = groups_path(self.program)
        path.write_text("changed externally", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "groups file changed"):
            save_highlight_groups(self.program, self.lines, state)
        self.assertEqual(path.read_text(encoding="utf-8"), "changed externally")

    def test_invalid_assignments_are_reported(self):
        self.save_assignments({2: "group1"})
        path = groups_path(self.program)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["assignments"][0]["group_id"] = []
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid line assignment"):
            load_highlight_groups(self.program, self.lines)

    def test_document_mapping_matches_text_and_source_lines(self):
        documents = [
            (
                generate_index_document(self.program, 3, 1, 2, "C", "P", "line 1\nline 2"),
                generate_index_text(self.program, 3, 1, 2, "C", "P", "line 1\nline 2"),
            ),
            (
                generate_manuscript_document(self.program, 1, 1),
                generate_manuscript_text(self.program, 1, 1),
            ),
        ]
        for (text, mapping), expected in documents:
            with self.subTest(text=text):
                self.assertEqual(text, expected)
                self.assertEqual(len(text.split("\n")), len(mapping))
                for rendered, source in zip(text.split("\n"), mapping):
                    if source is not None:
                        self.assertEqual(rendered, self.lines[source])
                self.assertIn(2, mapping)

    def test_index_mapping_preserves_repeated_source_lines(self):
        text, mapping = generate_index_document(
            self.program, 3, 1, 2, "C", "P", "", search_code="M06"
        )
        self.assertEqual(mapping.count(1), 2)
        self.assertEqual(
            [line for line, source in zip(text.split("\n"), mapping) if source == 1],
            ["N1 M06", "N1 M06"],
        )


if __name__ == "__main__":
    unittest.main()
