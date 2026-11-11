from nc_commands import has_m_code, has_search_code, read_nc_lines
from output_document import OutputDocument, write_text_output


def generate_manuscript_text(
        input_file,
        m06_lines_after,
        m01_surrounding_lines,
        search_code="M01"
):
    return generate_manuscript_document(
        input_file, m06_lines_after, m01_surrounding_lines, search_code
    )[0]


def generate_manuscript_document(
        input_file,
        m06_lines_after,
        m01_surrounding_lines,
        search_code="M01"
):

    _validate_line_counts(m06_lines_after, m01_surrounding_lines)
    lines = read_nc_lines(input_file)

    output = OutputDocument()

    # First M06 Section

    m06_end = 0

    for i, line in enumerate(lines):

        if has_m_code(line, 6):

            end = min(
                len(lines),
                i + m06_lines_after + 1
            )

            m06_end = end

            for x in range(0, end):
                output.append(lines[x], x)

            output.append("")
            output.append("(CODE REMOVED)")
            output.append("")
            break

    # Build Ranges (search code, default M01)

    ranges = []

    for i, line in enumerate(lines):

        if has_search_code(line, search_code):

            start = max(
                0,
                i - m01_surrounding_lines
            )

            end = min(
                len(lines),
                i + m01_surrounding_lines + 1
            )

            ranges.append((start, end))

    # Merge Overlapping Ranges

    merged_ranges = []

    for start, end in sorted(ranges):

        if not merged_ranges:

            merged_ranges.append([start, end])

        else:

            prev_start, prev_end = merged_ranges[-1]

            if start <= prev_end:

                merged_ranges[-1][1] = max(
                    prev_end,
                    end
                )

            else:

                merged_ranges.append(
                    [start, end]
                )

    # Output Blocks

    first_block = True
    last_output_end = m06_end

    for start, end in merged_ranges:

        # Skip blocks already contained in M06 section

        if end <= m06_end:
            continue

        start = max(start, m06_end)

        if not first_block:

            output.append("")
            output.append("(CODE REMOVED)")
            output.append("")

        for x in range(start, end):
            output.append(lines[x], x)

        first_block = False
        last_output_end = end

    # End of Program (M30 Section)

    for i in range(len(lines) - 1, -1, -1):

        if has_m_code(lines[i], 30):

            start = max(
                0,
                i - m06_lines_after
            )

            # Prevent duplicates

            if start < last_output_end:
                start = last_output_end

            if start < len(lines):

                output.append("")
                output.append("(CODE REMOVED)")
                output.append("")

                for x in range(start, len(lines)):
                    output.append(lines[x], x)

            break

    return output.result()


def _validate_line_counts(*values):
    if any(not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("Line counts must be non-negative whole numbers.")


def create_manuscript(
        input_file,
        m06_lines_after,
        m01_surrounding_lines,
        search_code="M01"
):

    manuscript_text = generate_manuscript_text(
        input_file,
        m06_lines_after,
        m01_surrounding_lines,
        search_code
    )

    return write_text_output(input_file, "MANUSCRIPT", manuscript_text)