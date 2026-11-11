import itertools
import random
import unittest
from fractions import Fraction
from pathlib import Path

from group_suggestions import TOLERANCE_INCHES, _matching_locations, analyze_group_suggestions
from nc_commands import read_nc_lines


def pattern_program(second_x="0.01", second_y="-0.01", second_end_x="1.01", second_end_y="1.01"):
    return [
        "G20 G17 G90 G54",
        "N10 M06 T1",
        "G00 X0 Y0",
        "G81 Z-1 R0.1",
        "X1 Y1",
        "G80",
        "N20 M01",
        "(DRILL HOLES)",
        "N30 M06 T2",
        f"G00 X{second_x} Y{second_y}",
        "G81 Z-1 R0.1",
        f"X{second_end_x} Y{second_end_y}",
        "G80",
        "M30",
    ]


class GroupSuggestionTests(unittest.TestCase):
    def test_bundled_sample_suggests_spot_drill_and_drill(self):
        sample = Path(__file__).resolve().parent.parent / "index proj" / "894OP1.nc"
        result = analyze_group_suggestions(read_nc_lines(sample))
        matching = [
            item for item in result.suggestions
            if {operation.marker_line for operation in item.operations}
            == {"N2035 M01", "N2115 M01"}
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(len(matching[0].operations[0].locations), 4)
        self.assertEqual(result.warnings, ())

    def test_suggests_four_related_drilling_and_tapping_operations(self):
        lines = ["G20 G17 G90 G54"]
        for index, code in enumerate(("G81", "G81", "G82", "G84", "G81"), 1):
            if index > 1:
                lines.append(f"N{index * 10} M01")
            lines.extend([
                f"(OPERATION {index})",
                f"M06 T{index}",
                "G00 X10 Y10" if index == 5 else "G00 X0 Y0",
                f"{code} Z-1 R.1",
                "X11 Y11" if index == 5 else "X1 Y1",
                "G80",
            ])
        lines.append("M30")
        result = analyze_group_suggestions(lines)
        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual([op.tool for op in result.suggestions[0].operations], ["T1", "T2", "T3", "T4"])

    def test_tolerance_is_inclusive_per_axis(self):
        for value, expected in (("0.009999", 1), ("0.01", 1), ("0.010001", 0)):
            with self.subTest(value=value):
                result = analyze_group_suggestions(pattern_program(second_x=value))
                self.assertEqual(len(result.suggestions), expected)

    def test_metric_coordinates_use_the_same_inch_tolerance(self):
        lines = pattern_program()
        lines[9:12] = [
            "G21 G00 X0.254 Y-0.254",
            "G81 Z-25.4 R2.54",
            "X25.654 Y25.654",
        ]
        self.assertEqual(len(analyze_group_suggestions(lines).suggestions), 1)
        lines[9] = "G21 G00 X0.254001 Y-0.254"
        self.assertEqual(len(analyze_group_suggestions(lines).suggestions), 0)

    def test_requires_matching_complete_sets_and_work_offsets(self):
        lines = pattern_program()
        lines.insert(12, "X5 Y5")
        self.assertEqual(analyze_group_suggestions(lines).suggestions, ())
        lines = pattern_program()
        lines[9] = "G55 G00 X0.01 Y-0.01"
        self.assertEqual(analyze_group_suggestions(lines).suggestions, ())

    def test_modal_xy_and_incremental_moves_are_tracked(self):
        lines = [
            "G20 G17 G90 G54", "M06 T1", "G0 X0 Y0", "G81 Z-1 R.1",
            "G91 X1 Y2", "X1 Y2", "G80", "M01", "M06 T2",
            "G90 G0 X0 Y0", "G81 Z-1 R.1", "X1 Y2", "X2 Y4", "G80", "M30",
        ]
        result = analyze_group_suggestions(lines)
        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual(len(result.suggestions[0].operations[0].locations), 3)

    def test_rotary_positions_and_planes_are_not_mixed(self):
        lines = pattern_program()
        lines[9] = "G00 B90 X0.01 Y-0.01"
        self.assertEqual(analyze_group_suggestions(lines).suggestions, ())
        lines = pattern_program()
        lines[9] = "G18 G00 X0.01 Y-0.01"
        result = analyze_group_suggestions(lines)
        self.assertEqual(result.suggestions, ())
        self.assertEqual(len(result.skipped), 1)
        self.assertIn("G17", " ".join(result.skipped[0].reasons))

    def test_requires_known_units_position_and_mode(self):
        lines = pattern_program()
        lines[0] = "G17 G90 G54"
        result = analyze_group_suggestions(lines)
        self.assertEqual(result.suggestions, ())
        self.assertEqual(len(result.skipped), 2)
        self.assertIn("Units", " ".join(result.skipped[0].reasons))

    def test_unsupported_macro_transform_and_repetitions_are_reported(self):
        for line in (
            "G65 P123", "M98 P123", "G68.2 X0 Y0", "X#100", "/ X1",
            "G81 X1 Y1 L4", "X1.2.3", "X1E-3",
        ):
            with self.subTest(line=line):
                lines = pattern_program()
                lines.insert(4, line)
                result = analyze_group_suggestions(lines)
                self.assertEqual(result.suggestions, ())
                self.assertTrue(result.skipped or result.warnings)

    def test_uninterpreted_cycle_repetitions_invalidate_inherited_position(self):
        lines = [
            "G20 G17 G90 G54", "M06 T1", "G0 X0 Y0",
            "G81 X1 Z-1 R.1 L4", "G80", "M01", "M06 T2",
            "G81 X1 Z-1 R.1", "G80", "M01", "M06 T3",
            "G81 X1 Z-1 R.1", "G80", "M30",
        ]
        result = analyze_group_suggestions(lines)
        self.assertEqual(result.suggestions, ())
        self.assertEqual(len(result.skipped), 3)
        self.assertIn("X/Y", " ".join(result.skipped[1].reasons))

    def test_comments_are_not_treated_as_code_and_common_g80_setup_is_supported(self):
        lines = pattern_program()
        lines[0] = "G00 G17 G20 G40 G80 G90 G54 (G91 X999 M98)"
        lines.insert(5, "; G91 X999 M98")
        result = analyze_group_suggestions(lines)
        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual(result.skipped, ())
        self.assertEqual(result.warnings, ())

    def test_matching_is_one_to_one_with_overlapping_tolerance_ranges(self):
        lines = [
            "G20 G17 G90 G54", "M06 T1", "G0 X0 Y0", "G81 Z-1 R.1",
            "X.015", "G80", "M01", "M06 T2", "G0 X.007 Y0",
            "G81 Z-1 R.1", "X.017", "G80", "M30",
        ]
        self.assertEqual(len(analyze_group_suggestions(lines).suggestions), 1)
        lines[8] = "G0 X-.007 Y0"
        lines[10] = "X-.008"
        self.assertEqual(analyze_group_suggestions(lines).suggestions, ())

    def test_nontransitive_matches_do_not_become_one_group(self):
        lines = [
            "G20 G17 G90 G54", "M06 T1", "G0 X0 Y0", "G81 Z-1 R.1", "G80",
            "M01", "M06 T2", "G0 X.009 Y0", "G81 Z-1 R.1", "G80",
            "M01", "M06 T3", "G0 X.018 Y0", "G81 Z-1 R.1", "G80", "M30",
        ]
        result = analyze_group_suggestions(lines)
        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual([op.tool for op in result.suggestions[0].operations], ["T1", "T2"])

    def test_large_hole_patterns_are_matched(self):
        lines = ["G20 G17 G90 G54", "M06 T1", "G0 X0 Y0", "G81 Z-1 R.1"]
        lines.extend(f"X{i} Y0" for i in range(1, 1000))
        lines.extend(["G80", "M01", "M06 T2", "G0 X.01 Y.01", "G81 Z-1 R.1"])
        lines.extend(f"X{i}.01 Y.01" for i in range(1, 1000))
        lines.extend(["G80", "M30"])
        result = analyze_group_suggestions(lines)
        self.assertEqual(len(result.suggestions), 1)
        self.assertEqual(len(result.suggestions[0].operations[0].locations), 1000)

    def test_tolerance_matching_agrees_with_exhaustive_one_to_one_matching(self):
        rng = random.Random(24)
        grid = [
            (Fraction(x, 200), Fraction(y, 200))
            for x in range(-4, 5) for y in range(-4, 5)
        ]
        for _ in range(250):
            first = tuple(sorted(rng.sample(grid, 4)))
            second = tuple(sorted(rng.sample(grid, 4)))
            expected = any(
                all(
                    abs(a[0] - b[0]) <= TOLERANCE_INCHES
                    and abs(a[1] - b[1]) <= TOLERANCE_INCHES
                    for a, b in zip(first, candidate)
                )
                for candidate in itertools.permutations(second)
            )
            self.assertEqual(_matching_locations(first, second, TOLERANCE_INCHES), expected)

    def test_program_end_prevents_analyzing_appended_code(self):
        lines = pattern_program()
        lines.extend(["M01", "M06 T3", "G00 X0 Y0", "G81 Z-1 R.1", "X1 Y1", "G80"])
        result = analyze_group_suggestions(lines)
        self.assertEqual(len(result.suggestions[0].operations), 2)

    def test_tool_change_without_m01_uses_m06_as_the_operation_marker(self):
        lines = pattern_program()
        lines.pop(6)
        result = analyze_group_suggestions(lines)
        self.assertEqual(
            [op.marker_line for op in result.suggestions[0].operations],
            ["N10 M06 T1", "N30 M06 T2"],
        )

    def test_m02_also_ends_the_program(self):
        lines = pattern_program()
        lines[-1] = "M02"
        lines.extend(["M01", "M06 T3", "G00 X0 Y0", "G81 Z-1 R.1", "X1 Y1", "G80"])
        self.assertEqual(len(analyze_group_suggestions(lines).suggestions[0].operations), 2)


if __name__ == "__main__":
    unittest.main()
