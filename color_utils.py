from PySide6.QtGui import QColor


def _luminance(color):
    def linear(channel):
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linear(color.red())
        + 0.7152 * linear(color.green())
        + 0.0722 * linear(color.blue())
    )


def contrast_ratio(first, second):
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def contrasting_text_color(background):
    black, white = QColor("black"), QColor("white")
    return black if contrast_ratio(black, background) >= contrast_ratio(white, background) else white
