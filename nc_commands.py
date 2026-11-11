from functools import lru_cache
from pathlib import Path
import re


def nc_comment_spans(line):
    comment_depth = 0
    start = None

    for index, character in enumerate(line):
        if character == ";" and comment_depth == 0:
            yield index, len(line)
            return
        if character == "(":
            if comment_depth == 0:
                start = index
            comment_depth += 1
        elif character == ")" and comment_depth:
            comment_depth -= 1
            if comment_depth == 0:
                yield start, index + 1
                start = None
    if start is not None:
        yield start, len(line)


def strip_nc_comments(line):
    visible = []
    start = 0
    for comment_start, comment_end in nc_comment_spans(line):
        visible.append(line[start:comment_start])
        start = comment_end
    visible.append(line[start:])

    return "".join(visible)


_CODE_TEXT_PATTERN = re.compile(r"\s*([A-Za-z])0*(\d+)\s*")
_WORD_PATTERN = re.compile(
    r"(?<![A-Za-z_])([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))",
    re.ASCII,
)


def iter_nc_words(text):
    return _WORD_PATTERN.finditer(text)


@lru_cache(maxsize=None)
def _code_pattern(letter, number):
    if not isinstance(number, int) or number < 0:
        raise ValueError("Code number must be a non-negative integer.")
    if not isinstance(letter, str) or len(letter) != 1 or not letter.isalpha():
        raise ValueError("Code letter must be a single letter, e.g. 'M' or 'G'.")
    return re.compile(
        rf"(?<![A-Z_]){letter.upper()}0*{number}(?![\d.])",
        re.IGNORECASE | re.ASCII,
    )


def has_code(line, letter, number):
    return _code_pattern(letter, number).search(strip_nc_comments(line)) is not None


def has_m_code(line, code):
    return has_code(line, "M", code)


def parse_code(code_text):
    """Parse text such as "M01" or "G28" into a (letter, number) pair."""

    match = _CODE_TEXT_PATTERN.fullmatch(code_text or "")
    if not match:
        raise ValueError(
            f"'{code_text}' is not a valid G/M code (e.g. M01, M06, G28)."
        )
    return match.group(1).upper(), int(match.group(2))


def has_search_code(line, code_text):
    letter, number = parse_code(code_text)
    return has_code(line, letter, number)


def count_search_code(lines, code_text):
    """Count how many of the given lines contain the search code."""

    letter, number = parse_code(code_text)
    pattern = _code_pattern(letter, number)
    return sum(
        1 for line in lines if pattern.search(strip_nc_comments(line))
    )


def read_nc_lines(input_file):
    data = Path(input_file).read_bytes()

    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    elif data.startswith(b"\xef\xbb\xbf"):
        text = data.decode("utf-8-sig")
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1252")
            except UnicodeDecodeError:
                text = data.decode("latin-1")

    return [line.rstrip() for line in text.splitlines()]
