from functools import lru_cache

from PySide6.QtGui import QColor, QSyntaxHighlighter

from color_utils import contrast_ratio, contrasting_text_color
from nc_commands import iter_nc_words, nc_comment_spans

_COLORS = {
    "comment": "#1c9a1c",
    "rapid": "#f80000",
    "motion": "#009999",
    "x": "#1326ff",
    "y": "#b25613",
    "z": "#f80000",
    "misc": "#1e699c",
    "tool": "#15369c",
    "feed": "#aa7575",
}


@lru_cache(maxsize=512)
def _readable_color(color_name, background_name):
    color = QColor(color_name)
    background = QColor(background_name)
    if contrast_ratio(color, background) >= 4.5:
        return color.name()

    target = contrasting_text_color(background)
    low, high = 0, 256
    while low < high:
        amount = (low + high) // 2
        mixed = QColor(
            *(round((source * (256 - amount) + destination * amount) / 256)
              for source, destination in zip(color.getRgb()[:3], target.getRgb()[:3]))
        )
        if contrast_ratio(mixed, background) >= 4.5:
            high = amount
        else:
            low = amount + 1
    return QColor(
        *(round((source * (256 - low) + destination * low) / 256)
          for source, destination in zip(color.getRgb()[:3], target.getRgb()[:3]))
    ).name()


def _word_kind(letter, number):
    letter = letter.upper()
    if letter == "G" and number.isdigit():
        code = int(number)
        if code == 0:
            return "rapid"
        if code in (1, 2, 3):
            return "motion"
    if letter in "XI":
        return "x"
    if letter in "YJ":
        return "y"
    if letter in "ZWK":
        return "z"
    if letter == "M":
        return "misc"
    if letter == "T":
        return "tool"
    if letter in "FS":
        return "feed"
    return None


class GCodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._sources = ()
        self._background = "#ffffff"
        self._group_foregrounds = {}
        self._context = None

    def set_context(self, sources, background, group_foregrounds=None):
        context = (
            tuple(sources),
            background.name(),
            tuple(sorted((group_foregrounds or {}).items())),
        )
        if context == self._context:
            return
        self._context = context
        self._sources = context[0]
        self._background = background.name()
        self._group_foregrounds = dict(context[2])
        self.rehighlight()

    def set_background(self, background):
        self.set_context(self._sources, background, self._group_foregrounds)

    def highlightBlock(self, text):
        block_number = self.currentBlock().blockNumber()
        if block_number >= len(self._sources):
            return
        source = self._sources[block_number]
        if source is None:
            return

        background = self._background

        def position(index):
            return len(text[:index].encode("utf-16-le")) // 2

        def apply(start, end, color):
            self.setFormat(position(start), position(end) - position(start), QColor(color))

        if source in self._group_foregrounds:
            apply(0, len(text), self._group_foregrounds[source])
            return

        mask = list(text)
        comments = list(nc_comment_spans(text))
        for start, end in comments:
            mask[start:end] = " " * (end - start)
        for match in iter_nc_words("".join(mask)):
            kind = _word_kind(match.group(1), match.group(2))
            if kind:
                apply(match.start(), match.end(), _readable_color(_COLORS[kind], background))
        for start, end in comments:
            apply(start, end, _readable_color(_COLORS["comment"], background))
