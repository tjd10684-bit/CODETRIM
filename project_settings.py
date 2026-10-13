import configparser
from pathlib import Path


def load_project_settings(nc_file):
    settings_file = Path(nc_file).parent / "project_settings.ini"

    if not settings_file.exists():
        return {"customer": "", "part_number": "", "notes": ""}

    config = configparser.ConfigParser(interpolation=None)
    with settings_file.open("r", encoding="utf-8-sig") as settings:
        config.read_file(settings)

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