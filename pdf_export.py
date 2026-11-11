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
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextLayout,
    QTextOption,
)

from color_utils import contrasting_text_color
from gcode_highlighter import GCodeHighlighter
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
    document.setPageSize(QSizeF(writer.width(), content_height))
    document.setPlainText(text)

    legend_document = None
    legend_offset = 0
    if legend:
        width, height = writer.width(), content_height
        header_width = width * 0.52
        separator = document.findBlockByNumber(header_line_count)
        if not separator.isValid() or separator.text() != INDEX_SEPARATOR:
            raise ValueError("PDF group index requires an index header separator.")

        def make_legend(legend_width, start_y=0):
            result = QTextDocument()
            result.documentLayout().setPaintDevice(writer)
            result.setDefaultFont(font)
            result.setDocumentMargin(0)
            result.setDefaultTextOption(option)
            result.setPageSize(QSizeF(legend_width, height))
            cursor = QTextCursor(result)
            if start_y:
                cursor.insertBlock()
            cursor.insertText("GROUP INDEX")
            cursor.insertBlock()
            for number, (name, color) in enumerate(legend):
                if number:
                    cursor.insertText("   ", QTextCharFormat())
                text_format = QTextCharFormat()
                background = QColor(color)
                text_format.setBackground(background)
                text_format.setForeground(contrasting_text_color(background))
                cursor.insertText(name, text_format)
            if start_y:
                spacer = result.firstBlock()
                title = spacer.next()
                initial_top = result.documentLayout().blockBoundingRect(title).top()
                cursor = QTextCursor(spacer)
                block_format = cursor.blockFormat()
                # Qt scales vertical block margins from 96-DPI units to the paint device.
                block_format.setBottomMargin(max(0, start_y - initial_top) * 96 / writer.resolution())
                cursor.setBlockFormat(block_format)
            return result

        document.pageCount()
        header_too_wide = False
        for number in range(header_line_count):
            layout = document.findBlockByNumber(number).layout()
            if layout.lineCount() > 1 or any(
                layout.lineAt(index).naturalTextRect().right() > header_width
                for index in range(layout.lineCount())
            ):
                header_too_wide = True
                break

        side_offset = header_width + 12
        legend_document = make_legend(width - side_offset)
        separator_top = document.documentLayout().blockBoundingRect(separator).top()
        key_too_tall = legend_document.documentLayout().documentSize().height() > separator_top
        if header_too_wide or key_too_tall:
            separator_bottom = document.documentLayout().blockBoundingRect(separator).bottom()
            legend_document = make_legend(width, start_y=separator_bottom)
            legend_bottom = legend_document.documentLayout().documentSize().height()
            cursor = QTextCursor(separator)
            block_format = cursor.blockFormat()
            spacing = max(0, legend_bottom - separator_bottom) * 96 / writer.resolution()
            block_format.setBottomMargin(block_format.bottomMargin() + spacing)
            cursor.setBlockFormat(block_format)
        else:
            legend_offset = side_offset
            for number in range(header_line_count):
                cursor = QTextCursor(document.findBlockByNumber(number))
                block_format = cursor.blockFormat()
                block_format.setRightMargin(width - header_width)
                cursor.setBlockFormat(block_format)

    highlighter = GCodeHighlighter(document)
    highlighter.set_context(
        sources,
        QColor("white"),
        {line: contrasting_text_color(QColor(color)).name() for line, color in group_colors.items()},
    )
    page_count = max(
        1, document.pageCount(),
        legend_document.pageCount() if legend_document is not None else 0,
    )
    height = content_height
    page_lines = [[] for _ in range(page_count)]

    def collect_lines(current_document, current_sources, colors, x_offset):
        block = current_document.firstBlock()
        while block.isValid():
            number = block.blockNumber()
            source = current_sources[number] if number < len(current_sources) else None
            color = colors.get(source)
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
                    QColor(color) if color is not None else None,
                ))
            block = block.next()

    collect_lines(document, sources, group_colors, 0)
    if legend_document is not None:
        collect_lines(legend_document, (), {}, legend_offset)
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
            for line, position, rect, color in page_lines[page]:
                if color is not None:
                    painter.fillRect(rect, color)
                line.draw(painter, position)
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
