import configparser
from pathlib import Path
import re


_LEGACY_HEADER = "# Mastercam Tools Project Settings"
_CURRENT_HEADER = "# Gcode Trim Tool Project Settings"
_SECTION_PATTERN = re.compile(r"^\s*\[([^]]+)\]")
_NOTES_PATTERN = re.compile(r"^[ \t]*notes[ \t]*[=:]", re.IGNORECASE)


def _read_tool_settings(config, text, settings_file, legacy):
    lines = text.splitlines(keepends=True)
    section = None
    for index, line in enumerate(lines):
        section_match = _SECTION_PATTERN.match(line)
        notes_match = _NOTES_PATTERN.match(line)
        if section_match:
            section = section_match.group(1)
        elif section == "Project" and notes_match:
            continuation = lines[index + 1:]
            if not legacy and (
                not continuation
                or continuation[-1] != "\n"
                or any(not item.startswith("\t") for item in continuation[:-1])
            ):
                break

            config.read_string("".join(lines[:index + 1]), source=str(settings_file))
            first_line = line[notes_match.end():].removesuffix("\n")
            if not legacy:
                first_line = first_line.removeprefix(" ")
                continuation = [item[1:] for item in continuation[:-1]]
            if continuation:
                # Both writers add a final newline after the notes.
                first_line += "\n" + "".join(continuation).removesuffix("\n")
            config.set("Project", "Notes", first_line)
            return
    config.read_string(text, source=str(settings_file))


def load_project_settings(nc_file):
    settings_file = Path(nc_file).parent / "project_settings.ini"

    if not settings_file.exists():
        return {"customer": "", "part_number": "", "notes": ""}

    config = configparser.ConfigParser(interpolation=None)
    with settings_file.open("r", encoding="utf-8-sig") as settings:
        text = settings.read()
    if text.lstrip().startswith(_LEGACY_HEADER):
        _read_tool_settings(config, text, settings_file, legacy=True)
    elif text.lstrip().startswith(_CURRENT_HEADER):
        _read_tool_settings(config, text, settings_file, legacy=False)
    else:
        config.read_string(text, source=str(settings_file))

    return {
        "customer": config.get("Project", "Customer", fallback=""),
        "part_number": config.get("Project", "PartNumber", fallback=""),
        "notes": config.get("Project", "Notes", fallback=""),
    }


def save_project_settings(
    nc_file,
    customer,
    part_number,
    notes
):

    settings_file = Path(nc_file).parent / "project_settings.ini"
    config = configparser.ConfigParser(interpolation=None)
    config["Project"] = {
        "Customer": customer,
        "PartNumber": part_number,
        "Notes": notes,
    }

    temporary_file = settings_file.with_suffix(".ini.tmp")
    with temporary_file.open("w", encoding="utf-8", newline="\n") as settings:
        settings.write("# Gcode Trim Tool Project Settings\n")
        settings.write("# Automatically created by Gcode Trim Tool.\n\n")
        config.write(settings)
    temporary_file.replace(settings_file)