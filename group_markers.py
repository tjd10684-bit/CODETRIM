import textwrap
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF

from color_utils import contrasting_text_color


@dataclass(frozen=True)
class GroupMarker:
    number: int
    name: str
    color: str


def assigned_markers(state):
    if state is None:
        return {}, []
    assigned = set(state.assignments.values())
    markers = [
        GroupMarker(number, group.name, group.color)
        for number, group in enumerate(
            (group for group in state.groups if group.id in assigned), 1
        )
    ]
    by_id = dict(zip((group.id for group in state.groups if group.id in assigned), markers))
    return {line: by_id[group_id] for line, group_id in state.assignments.items()}, markers


def key_rows(markers, cell_width, metrics=None):
    digits = max(3, len(str(len(markers))) + 2)
    prefix_width = digits + 3
    name_width = max(1, cell_width - prefix_width - 1)
    rows = []
    positions = {}
    for start in range(0, len(markers), 5):
        group = markers[start:start + 5]
        wrapped = []
        for marker in group:
            parts = textwrap.wrap(marker.name, width=name_width, replace_whitespace=False) or [""]
            if metrics is not None:
                max_width = metrics.horizontalAdvance("0") * name_width
                fitted = []
                for part in parts:
                    while part:
                        end = len(part)
                        while end > 1 and metrics.horizontalAdvance(part[:end]) > max_width:
                            end -= 1
                        fitted.append(part[:end])
                        part = part[end:]
                parts = fitted or [""]
            wrapped.append(parts)
        for line_index in range(max(map(len, wrapped))):
            cells = []
            for column, marker in enumerate(group):
                name = wrapped[column][line_index] if line_index < len(wrapped[column]) else ""
                prefix = " " * digits + " - " if line_index == 0 else " " * prefix_width
                cell = prefix + name
                if metrics is None:
                    cell = cell.ljust(cell_width)
                else:
                    target = metrics.horizontalAdvance("0") * cell_width
                    while metrics.horizontalAdvance(cell + " ") <= target + 0.01:
                        cell += " "
                cells.append(cell)
                if line_index == 0:
                    positions.setdefault(len(rows), []).append((sum(map(len, cells[:-1])), marker))
            rows.append("".join(cells).rstrip())
    return rows, positions


def paint_marker(painter, rect, marker, font):
    background = QColor(marker.color)
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(background)
    painter.drawRoundedRect(QRectF(rect), rect.height() / 2, rect.height() / 2)
    painter.setPen(contrasting_text_color(background))
    bold_font = QFont(font)
    bold_font.setBold(True)
    painter.setFont(bold_font)
    painter.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, str(marker.number))
    painter.restore()


def marker_width(font, device, count):
    metrics = QFontMetricsF(font, device)
    bold_font = QFont(font)
    bold_font.setBold(True)
    bold_metrics = QFontMetricsF(bold_font, device)
    return max(3 * metrics.horizontalAdvance("0"), bold_metrics.horizontalAdvance(str(max(1, count))) + 8)
