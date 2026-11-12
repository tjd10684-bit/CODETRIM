# Gcode Trim Tool

Gcode Trim Tool generates an index and a manuscript from a G-code program.
The unified graphical application is `MASTERCAM_MAIN.py`; it previews each
output and saves customer, part number, and notes to a
`project_settings.ini` file beside the selected G-code program.
Existing Mastercam Tools settings files with unindented multiline notes are
also supported; the legacy format stores notes as the final field in the file.

## Requirements

- Python 3.10 or newer
- PySide6 (Qt for Python)

Install the Python dependency and start the GUI:

```powershell
python -m pip install -r requirements.txt
python MASTERCAM_MAIN.py
```

## Portable Windows executable

On Windows, install the build dependencies and package the application:

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --onefile --windowed --name "Gcode Trim Tool" MASTERCAM_MAIN.py
```

The resulting `dist\Gcode Trim Tool.exe` can be copied to a compatible 64-bit
Windows computer and run without installing Python or the application. The
executable extracts its bundled components to a temporary directory on startup;
the selected program's folder must still be writable to save settings and
outputs.

Select a program using Browse or drag and drop it onto the file field.
Use the preview tabs to switch between the index and manuscript before
generating either or both outputs. Settings and output options are on the
left; drag the divider to adjust their width. The settings panel scrolls when
the window is too short to show all controls.

Press **Ctrl+F** or click **Find** to search the active preview. Use Enter or
F3 for the next match and Shift+F3 for the previous match; searching wraps at
the end or beginning. The Find window stays available while you switch
between the index and manuscript, and can optionally match case.

The output format defaults to **PDF**. In Output Options, choose **Text (.nc)**
or **PDF and text (.nc)** if you also need the original plain-text outputs.
PDFs use US Letter portrait pages, wrap long lines, and preserve syntax colors
and saved highlight groups. Each PDF page has the source filename centered at
the top and its page number centered at the bottom. PDFs and optional text
files are saved alongside the program as `<program> - INDEX` and
`<program> - MANUSCRIPT` with the appropriate extensions.

Both previews use G-code syntax colors: comments are green; rapid moves and
Z/W/K words are red; feed moves are teal; X/I words are blue; and Y/J words
are orange. M-codes, tool words, and feed/spindle values have their own colors.
Colors adjust for the preview background. Grouped lines retain their normal
syntax colors, with numbered color bubbles in a separate left gutter. PDF colors
are adapted to a white page; optional NC files remain unchanged plain text.

## Highlight groups

Use **Highlight Groups** below the previews to create named groups and choose
from a high-contrast color palette. Each palette color has at least a 7:1
contrast ratio with its black or white text.
Click a G-code line in either preview to select it; Ctrl-click toggles
individual lines and Shift-click selects a range of visible lines. Choose a
group and click **Assign Selected**. A line belongs to one group at a time.
A numbered color bubble with a bold number appears beside that line in either
preview or PDF; the line itself remains uncolored for readability and
handwritten notes.
Groups can be edited or deleted, and selected lines can be unassigned.
The index preview and index PDF include a five-column color key below the
header, listing every group with an assigned line, including lines appearing
only in the manuscript. Group numbers are assigned sequentially in group order
and match between both outputs. Names wrap within their columns and additional
groups add rows. The key uses 1.5-line spacing and ends with a separator before
the G-code. The manuscript has no key, and text-only output remains unchanged.

### Suggested groups

Select **Suggest Groups** to analyze the full program and review possible
matching hole patterns. Suggestions require the same complete set of X/Y
locations, with a tolerance of 0.01 inch independently on each axis (0.254 mm
for metric programs), the same known work offset, and matching programmed
rotary values. Unprogrammed rotary positions remain unknown.
The review lists each operation, its marker line, tool, and programmed
coordinates. Accepting a suggestion lets you name it and choose a color; it
adds numbered bubbles beside the selected `M01` markers (or `M06` where no
`M01` precedes an operation) without changing the G-code. Uncheck operations
that do not belong before accepting; at least two operations must remain.
Existing marker assignments are never overwritten. Each operation appears in
at most one suggestion, and every pair within that suggestion satisfies the
tolerance; ambiguous alternatives may therefore not all be suggested.

The analysis recognizes G73 and G81-G89 canned cycles in the G17 plane, tracks
modal X/Y positions and G90/G91 movement, and skips operations it cannot
interpret safely, reporting the reasons. It does not interpret other cycles,
contour or helical operations, macros, subprograms, or coordinate
transformations. It does not simulate the machine or verify physical
positions; the programmer must review every suggestion. Some marker lines may
not appear in the current preview unless its search and line-range settings
include them.

Groups are saved automatically in a separate `<program filename>.groups.json`
file beside each source program. Keep that file with the program to retain the
groups. The generated PDFs include those colors; optional NC files do not.
When an existing group uses a color outside the palette, the app replaces it
with the nearest palette color, saves the change, and reports the conversion.
If the source changes, assignments are reconnected only when their original
line text matches uniquely. Any missing or ambiguous assignments are retained
and listed in Highlight Groups, where they can be reviewed or discarded.

Generator functions live in `index_generator.py` and
`setup_copy_generator.py`; both can be imported independently without
starting the GUI.

## Search code

Both outputs include a section around the first `M06` and extract lines around
every occurrence of a second search code throughout the program, including
matches before the first `M06`. The "Search Settings" dropdown lets you choose
that code per session: `M01` (default), `M06`, or `G28`. Pass
`search_code="G28"` (or any `M`/`G` code such as `"M01"`) to
`generate_index_text`/`create_index` and
`generate_manuscript_text`/`create_manuscript` to use the same behavior
outside the GUI; the parameter defaults to `"M01"` for backward
compatibility.

In the Index output, "Lines Before Each" and "Lines After Each" are
independent settings, so `generate_index_text`/`create_index` take separate
`m01_lines_before` and `m01_lines_after` counts (in that order, both
non-negative whole numbers). The Manuscript output keeps a single symmetric
"Lines Before/After" count for its search-code ranges.

The Search Settings box also shows a live count of how many lines in the
selected program match the chosen search code (comments are ignored), so you
can confirm the dropdown is set correctly before generating output. This is
powered by `count_search_code()` in `nc_commands.py`, which can also be
called directly if you need the count outside the GUI.

## Tests

Run the standard-library test suite and a syntax compilation check:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
```

NC command detection accepts M-code words such as `M06`, `M6`, and `M006`,
ignores nested parenthetical and semicolon comments, and does not match a
command embedded in another word or a longer numeric code.
