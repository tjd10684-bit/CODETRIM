import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HighlightGroup:
    id: str
    name: str
    color: str


@dataclass
class UnmatchedLine:
    text: str
    group_id: str


@dataclass
class HighlightGroups:
    groups: list[HighlightGroup] = field(default_factory=list)
    assignments: dict[int, str] = field(default_factory=dict)
    unmatched: list[UnmatchedLine] = field(default_factory=list)
    source_hash: str = ""
    file_hash: str | None = None


def source_hash(lines):
    content = json.dumps(lines, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def groups_path(input_file):
    path = Path(input_file)
    return path.with_name(f"{path.name}.groups.json")


def load_highlight_groups(input_file, lines):
    current_hash = source_hash(lines)
    path = groups_path(input_file)
    if not path.exists():
        return HighlightGroups(source_hash=current_hash)

    contents = path.read_bytes()
    data = json.loads(contents.decode("utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError(f"Unsupported or invalid highlight groups file: {path}")
    saved_hash = data.get("source_hash")
    raw_groups = data.get("groups")
    raw_assignments = data.get("assignments")
    if (
        not isinstance(saved_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", saved_hash)
        or not isinstance(raw_groups, list)
        or not isinstance(raw_assignments, list)
    ):
        raise ValueError(f"Invalid highlight groups file: {path}")

    groups = []
    group_ids = set()
    names = set()
    for item in raw_groups:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid group in {path}")
        group_id, name, color = item.get("id"), item.get("name"), item.get("color")
        if (
            not isinstance(group_id, str) or not group_id
            or not isinstance(name, str) or not name.strip()
            or not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            or group_id in group_ids or name.casefold() in names
        ):
            raise ValueError(f"Invalid or duplicate group in {path}")
        groups.append(HighlightGroup(group_id, name, color))
        group_ids.add(group_id)
        names.add(name.casefold())

    entries = []
    saved_indices = set()
    for item in raw_assignments:
        if not isinstance(item, dict):
            raise ValueError(f"Invalid line assignment in {path}")
        line, text, group_id = item.get("line"), item.get("text"), item.get("group_id")
        if (
            (line is not None and (type(line) is not int or line < 0))
            or not isinstance(text, str) or not isinstance(group_id, str)
            or group_id not in group_ids
            or (line is not None and line in saved_indices)
        ):
            raise ValueError(f"Invalid line assignment in {path}")
        if line is not None:
            saved_indices.add(line)
        entries.append((line, text, group_id))

    state = HighlightGroups(
        groups=groups,
        source_hash=current_hash,
        file_hash=hashlib.sha256(contents).hexdigest(),
    )
    if saved_hash == current_hash:
        for line, text, group_id in entries:
            if line is None:
                state.unmatched.append(UnmatchedLine(text, group_id))
            elif line >= len(lines) or lines[line] != text:
                raise ValueError(f"Highlight assignment does not match the program: {path}")
            else:
                state.assignments[line] = group_id
        return state

    positions = defaultdict(list)
    for index, text in enumerate(lines):
        positions[text].append(index)
    old_counts = Counter(text for _, text, _ in entries)
    for _, text, group_id in entries:
        candidates = positions[text]
        if len(candidates) == 1 and old_counts[text] == 1:
            state.assignments[candidates[0]] = group_id
        else:
            state.unmatched.append(UnmatchedLine(text, group_id))
    return state


def save_highlight_groups(input_file, lines, state):
    if source_hash(lines) != state.source_hash:
        raise ValueError("The program changed. Reload it before changing highlight groups.")
    path = groups_path(input_file)
    current_file_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if current_file_hash != state.file_hash:
        raise ValueError("The highlight groups file changed. Reload the program before editing groups.")
    assignments = [
        {"line": index, "text": lines[index], "group_id": group_id}
        for index, group_id in sorted(state.assignments.items())
    ]
    assignments.extend(
        {"line": None, "text": item.text, "group_id": item.group_id}
        for item in state.unmatched
    )
    data = {
        "version": 1,
        "source_hash": state.source_hash,
        "groups": [
            {"id": group.id, "name": group.name, "color": group.color}
            for group in state.groups
        ],
        "assignments": assignments,
    }
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_path, path)
        state.file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
