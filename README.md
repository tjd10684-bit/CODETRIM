# Gcode Trim Tool

Gcode Trim Tool generates an index file and a manuscript from a G-code
program. The unified graphical application is `MASTERCAM_MAIN.py`; it previews
each output and saves customer, part number, and notes to a
`project_settings.ini` file beside the selected G-code program.

## Requirements

- Python 3.10 or newer
- Tkinter (included with standard Windows Python distributions)
- `tkinterdnd2` for drag-and-drop support

Install the Python dependency and start the GUI:

```powershell
python -m pip install -r requirements.txt
python MASTERCAM_MAIN.py
```

Generator functions live in `index_generator.py` and
`setup_copy_generator.py`; both can be imported independently without
starting the GUI.

## Search code

Both outputs locate the first `M06` and then extract lines around every
subsequent occurrence of a second search code, which the "Search Settings"
dropdown lets you choose per session: `M01` (default), `M06`, or `G28`. Pass
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
