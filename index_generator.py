from pathlib import Path

from nc_commands import has_m_code, has_search_code, read_nc_lines


def generate_index_text(
    input_file,
    m06_lines_before,
    m01_lines_before,
    m01_lines_after,
    customer,
    part_number,
    notes,
    search_code="M01"
):

    _validate_line_counts(m06_lines_before, m01_lines_before, m01_lines_after)
    lines = read_nc_lines(input_file)

    input_path = Path(input_file)

    output = []

    # Header

    output.append("INDEX")
    output.append(f"CUSTOMER: {customer}")
    output.append(f"PART NUMBER: {part_number}")
    output.append(f"PROGRAM NUMBER: {input_path.stem}")
    output.append(f"NOTES: {notes}")
    output.append("-" * 58)
    output.append("")

    # First Operation (First M06)

    for i, line in enumerate(lines):

        if has_m_code(line, 6):

            start = max(
                0,
                i - m06_lines_before
            )

            for x in range(start, i + 1):
                output.append(lines[x])

            output.append("")
            break

    # Remaining Operations (search code, default M01)

    for i, line in enumerate(lines):

        if has_search_code(line, search_code):

            start = max(
                0,
                i - m01_lines_before
            )

            end = min(
                len(lines),
                i + m01_lines_after + 1
            )

            for x in range(start, end):
                output.append(lines[x])

            output.append("")

    return "\n".join(output)


def _validate_line_counts(*values):
    if any(not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("Line counts must be non-negative whole numbers.")


def create_index(
    input_file,
    m06_lines_before,
    m01_lines_before,
    m01_lines_after,
    customer,
    part_number,
    notes,
    search_code="M01"
):

    index_text = generate_index_text(
        input_file,
        m06_lines_before,
        m01_lines_before,
        m01_lines_after,
        customer,
        part_number,
        notes,
        search_code
    )

    input_path = Path(input_file)

    output_file = (
        input_path.parent /
        f"{input_path.stem} - INDEX.nc"
    )

    output_file.write_text(index_text, encoding="utf-8", newline="\n")

    return output_file