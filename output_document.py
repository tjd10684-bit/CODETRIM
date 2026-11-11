from pathlib import Path


def output_path(input_file, label, extension):
    input_path = Path(input_file)
    return input_path.parent / f"{input_path.stem} - {label}{extension}"


def write_text_output(input_file, label, text):
    path = output_path(input_file, label, ".nc")
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


class OutputDocument:
    def __init__(self):
        self._text = []
        self._source_lines = []

    def append(self, text, source_line=None):
        self._text.append(text)
        self._source_lines.extend([source_line] * (text.count("\n") + 1))

    def result(self):
        return "\n".join(self._text), self._source_lines
