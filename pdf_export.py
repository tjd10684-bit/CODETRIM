import math
from pathlib import Path

from PySide6.QtCore import QIODevice, QMarginsF, QPointF, QRectF, QSaveFile, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QFontMetricsF,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextCursor,
    QTextBlockFormat,
    QTextDocument,
    QTextLayout,
    QTextOption,
)

from gcode_highlighter import GCodeHighlighter
from group_markers import key_rows, marker_width, paint_marker
from index_generator import INDEX_SEPARATOR
from output_document import output_path


def create_pdf(input_file, label, text, sources, group_colors, legend=(), header_line_count=0):
    if len(sources) != len(text.split("\n")) and (text or sources):
        raise ValueError("PDF source-line mapping does not match the output text.")
    if legend and (header_line_count <= 0 or header_line_count >= len(sources)):
        raise ValueError("PDF group index requires a valid index header.")

    path = output_path(input_file, label, ".pdf")
    file = QSaveFile(str(path))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(f"Could not open PDF {path}: {file.errorString()}")

    try:
        return _write_pdf(file, path, input_file, label, text, sources, group_colors, legend, header_line_count)
    finally:
        if file.isOpen():
            file.cancelWriting()
            file.commit()


def _write_pdf(file, path, input_file, label, text, sources, group_colors, legend, header_line_count):
    writer = QPdfWriter(file)
    writer.setResolution(72)
    if not writer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter)):
        file.cancelWriting()
        raise OSError("Could not set the PDF page size.")
    if not writer.setPageMargins(QMarginsF(12.7, 12.7, 12.7, 12.7), QPageLayout.Unit.Millimeter):
        file.cancelWriting()
        raise OSError("Could not set the PDF page margins.")
    writer.setTitle(f"{label} - {input_file}")

    document = QTextDocument()
    if not QFontDatabase.families():
        file.cancelWriting()
        raise ValueError("No fonts are available for PDF export.")
    document.documentLayout().setPaintDevice(writer)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSizeF(9)
    filename = Path(input_file).name
    if not filename:
        raise ValueError("A source filename is required for the PDF header.")

    header = QTextLayout(filename, font, writer)
    header_option = QTextOption()
    header_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    header_option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    header.setTextOption(header_option)
    header.beginLayout()
    header_height = 0.0
    while True:
        line = header.createLine()
        if not line.isValid():
            break
        line.setLineWidth(writer.width())
        line.setPosition(QPointF(0, header_height))
        header_height += line.height()
    header.endLayout()
    header_band = math.ceil(header_height) + 8
    footer_band = math.ceil(QFontMetricsF(font, writer).height()) + 8
    content_height = writer.height() - header_band - footer_band
    if content_height < 72:
        raise ValueError("The source filename is too long to leave room for PDF content.")

    document.setDefaultFont(font)
    document.setDocumentMargin(0)
    option = document.defaultTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    count = max((marker.number for marker in group_colors.values()), default=0)
    gutter_width = marker_width(font, writer, count) + 4
    content_width = writer.width() - gutter_width
    document.setPageSize(QSizeF(content_width, content_height))
    document.setPlainText(text)

    legend_document = None
    legend_positions = {}
    if legend:
        width, height = content_width, content_height
        separator = document.findBlockByNumber(header_line_count)
        if not separator.isValid() or separator.text() != INDEX_SEPARATOR:
            raise ValueError("PDF group index requires an index header separator.")

        def make_legend(start_y):
            result = QTextDocument()
            result.documentLayout().setPaintDevice(writer)
            result.setDefaultFont(font)
            result.setDocumentMargin(0)
            result.setDefaultTextOption(option)
            result.setPageSize(QSizeF(width, height))
            cursor = QTextCursor(result)
            cursor.insertBlock()
            cursor.insertText("GROUP INDEX")
            cursor.insertBlock()
            cell_width = max(8, int(width / (5 * QFontMetricsF(font, writer).horizontalAdvance("0"))))
            rows, positions = key_rows(legend, cell_width, QFontMetricsF(font, writer))
            cursor.insertText("\n".join(rows))
            cursor.insertBlock()
            cursor.insertText(INDEX_SEPARATOR)
            for row in range(len(rows)):
                row_cursor = QTextCursor(result.findBlockByNumber(row + 2))
                row_format = row_cursor.blockFormat()
                row_format.setLineHeight(150, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                row_cursor.setBlockFormat(row_format)
            spacer = result.firstBlock()
            title = spacer.next()
            initial_top = result.documentLayout().blockBoundingRect(title).top()
            cursor = QTextCursor(spacer)
            block_format = cursor.blockFormat()
            block_format.setBottomMargin(max(0, start_y - initial_top) * 96 / writer.resolution())
            cursor.setBlockFormat(block_format)
            legend_positions.update({row + 2: items for row, items in positions.items()})
            return result

        separator_bottom = document.documentLayout().blockBoundingRect(separator).bottom()
        legend_document = make_legend(separator_bottom)
        legend_bottom = legend_document.documentLayout().documentSize().height()
        cursor = QTextCursor(separator)
        block_format = cursor.blockFormat()
        spacing = max(0, legend_bottom - separator_bottom) * 96 / writer.resolution()
        block_format.setBottomMargin(block_format.bottomMargin() + spacing)
        cursor.setBlockFormat(block_format)

    highlighter = GCodeHighlighter(document)
    highlighter.set_context(
        sources,
        QColor("white"),
    )
    page_count = max(
        1, document.pageCount(),
        legend_document.pageCount() if legend_document is not None else 0,
    )
    height = content_height
    page_lines = [[] for _ in range(page_count)]

    def collect_lines(current_document, current_sources, markers, x_offset, key_positions=None):
        block = current_document.firstBlock()
        while block.isValid():
            number = block.blockNumber()
            source = current_sources[number] if number < len(current_sources) else None
            marker = markers.get(source)
            block_rect = current_document.documentLayout().blockBoundingRect(block)
            text_layout = block.layout()
            for index in range(text_layout.lineCount()):
                line = text_layout.lineAt(index)
                line_top = block_rect.top() + line.y()
                page = int(line_top // height)
                if page < 0 or page >= page_count:
                    raise ValueError("A PDF line falls outside the calculated page range.")
                offset_x = block_rect.left() + x_offset
                offset_y = block_rect.top() - page * height
                page_lines[page].append((
                    line,
                    QPointF(offset_x, offset_y),
                    line.naturalTextRect().translated(offset_x, offset_y),
                    marker if index == 0 else None,
                    [(column, item) for column, item in (key_positions or {}).get(number, [])
                     if line.textStart() <= len(block.text()[:column].encode("utf-16-le")) // 2
                     < line.textStart() + line.textLength()],
                    block.text(),
                ))
            block = block.next()

    collect_lines(document, sources, group_colors, gutter_width)
    if legend_document is not None:
        collect_lines(legend_document, (), {}, gutter_width, legend_positions)
        for lines in page_lines:
            lines.sort(key=lambda item: (item[2].top(), item[2].left()))

    painter = QPainter()
    if not painter.begin(writer):
        file.cancelWriting()
        raise OSError(f"Could not write PDF {path}: {file.errorString()}")
    try:
        for page in range(page_count):
            if page and not writer.newPage():
                raise OSError(f"Could not add a page to PDF {path}: {file.errorString()}")
            painter.setPen(QColor("black"))
            painter.setFont(font)
            header.draw(painter, QPointF(0, 0))
            painter.save()
            painter.translate(0, header_band)
            for line, position, rect, marker, key_items, block_text in page_lines[page]:
                line.draw(painter, position)
                if marker is not None:
                    paint_marker(painter, QRectF(0, rect.top(), gutter_width - 4, line.height()), marker, font)
                for column, item in key_items:
                    offset = len(block_text[:column].encode("utf-16-le")) // 2
                    x = line.cursorToX(offset)[0] + position.x()
                    paint_marker(painter, QRectF(x, rect.top(), marker_width(font, writer, item.number), line.height()), item, font)
            painter.restore()
            painter.setPen(QColor("black"))
            painter.setFont(font)
            painter.drawText(
                QRectF(0, writer.height() - footer_band, writer.width(), footer_band),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                f"Page {page + 1} of {page_count}",
            )
    finally:
        finished = painter.end()
    if not finished:
        file.cancelWriting()
        raise OSError(f"Could not finish PDF {path}: {file.errorString()}")
    if not file.commit():
        raise OSError(f"Could not save PDF {path}: {file.errorString()}")
    return path
