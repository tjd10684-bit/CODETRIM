from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QLabel, QPushButton, QVBoxLayout

from color_utils import contrasting_text_color


GROUP_COLORS = (
    ("Yellow", "#ffee00"),
    ("Amber", "#ffb74d"),
    ("Coral", "#ef9a9a"),
    ("Rose", "#f48fb1"),
    ("Lavender", "#ce93d8"),
    ("Sky Blue", "#90caf9"),
    ("Cyan", "#80deea"),
    ("Green", "#a5d6a7"),
    ("Lime", "#00ff00"),
    ("Sand", "#bcaaa4"),
    ("Light Gray", "#eeeeee"),
    ("Navy", "#283593"),
    ("Deep Teal", "#004d40"),
    ("Berry", "#880e4f"),
    ("Purple", "#7b1fa2"),
    ("Blue", "#0000ff"),
)

GROUP_COLOR_VALUES = frozenset(color for _, color in GROUP_COLORS)


def nearest_group_color(value):
    source = QColor(value)

    def distance(item):
        target = QColor(item[1])
        red_mean = (source.red() + target.red()) / 2
        red = source.red() - target.red()
        green = source.green() - target.green()
        blue = source.blue() - target.blue()
        return (2 + red_mean / 256) * red ** 2 + 4 * green ** 2 + (2 + (255 - red_mean) / 256) * blue ** 2

    return min(GROUP_COLORS, key=distance)[1]


class GroupColorDialog(QDialog):
    def __init__(self, parent, current_color):
        super().__init__(parent)
        self.setWindowTitle("Choose Group Color")
        self.selected_color = None
        layout = QVBoxLayout(self)
        label = QLabel("Choose a high-contrast color. The sample shows the text color.")
        label.setWordWrap(True)
        layout.addWidget(label)
        grid = QGridLayout()
        for index, (name, value) in enumerate(GROUP_COLORS):
            button = QPushButton(f"{name}  Aa")
            text_color = contrasting_text_color(QColor(value)).name()
            button.setStyleSheet(
                f"QPushButton {{ background-color: {value}; color: {text_color}; "
                "border: 1px solid #777777; padding: 8px; }"
                "QPushButton:focus { border: 2px solid #777777; }"
            )
            button.setToolTip(f"{name} ({value})")
            button.clicked.connect(lambda _checked=False, color=value: self.select_color(color))
            grid.addWidget(button, index // 4, index % 4)
            if value == current_color.lower():
                button.setDefault(True)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def select_color(self, color):
        self.selected_color = color
        self.accept()


def choose_group_color(parent, current_color):
    dialog = GroupColorDialog(parent, current_color)
    return dialog.selected_color if dialog.exec() == QDialog.DialogCode.Accepted else None
