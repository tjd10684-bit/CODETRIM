from pathlib import Path

from nc_commands import has_m_code, has_search_code, read_nc_lines
from output_document import OutputDocument, write_text_output


INDEX_SEPARATOR = "-" * 58


def index_header_lines(input_file, customer, part_number, notes):
    return [
        "INDEX",
        f"CUSTOMER: {customer}",
        f"PART NUMBER: {part_number}",
        f"PROGRAM NUMBER: {Path(input_file).stem}",
        f"NOTES: {notes}",
    ]


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
    return generate_index_document(
        input_file, m06_lines_before, m01_lines_before, m01_lines_after,
        customer, part_number, notes, search_code
    )[0]


def generate_index_document(
    input_file,
    m06_lines_before,
    m01_lines_before,
    m01_lines_after,
    customer,
    part_number,
    notes,
    search_code="M01",
):

    _validate_line_counts(m06_lines_before, m01_lines_before, m01_lines_after)
    lines = read_nc_lines(input_file)

    output = OutputDocument()

    # Header

    for line in index_header_lines(input_file, customer, part_number, notes):
        output.append(line)
    output.append(INDEX_SEPARATOR)
    output.append("")

    # First Operation (First M06)

    for i, line in enumerate(lines):

        if has_m_code(line, 6):

            start = max(
                0,
                i - m06_lines_before
            )

            for x in range(start, i + 1):
                output.append(lines[x], x)

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
                output.append(lines[x], x)

            output.append("")

    return output.result()


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

    return write_text_output(input_file, "INDEX", index_text)