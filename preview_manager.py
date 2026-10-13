from index_generator import generate_index_text
from setup_copy_generator import generate_manuscript_text


def get_index_preview(
    input_file,
    m06_lines_before,
    m01_lines_before,
    m01_lines_after,
    customer,
    part_number,
    notes,
    search_code="M01"
):

    return generate_index_text(
        input_file,
        m06_lines_before,
        m01_lines_before,
        m01_lines_after,
        customer,
        part_number,
        notes,
        search_code
    )


def get_manuscript_preview(
    input_file,
    m06_lines_after,
    m01_surrounding_lines,
    search_code="M01"
):

    return generate_manuscript_text(
        input_file,
        m06_lines_after,
        m01_surrounding_lines,
        search_code
    )