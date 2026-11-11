import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from nc_commands import iter_nc_words, nc_comment_spans, strip_nc_comments


TOLERANCE_INCHES = Fraction(1, 100)
_MM_PER_INCH = Fraction(254, 10)
_CYCLES = {Decimal(code) for code in (73, 81, 82, 83, 84, 85, 86, 87, 88, 89)}
_MOTION_CANCEL = {Decimal(code) for code in (0, 1, 2, 3, 80)}
_SUPPORTED_XY_G = _CYCLES | _MOTION_CANCEL | {
    Decimal(code) for code in (17, 20, 21, 40, 41, 42, 43, 49, 54, 55, 56, 57, 58, 59, 90, 91, 94, 95, 98, 99)
}
_UNSUPPORTED_TRANSFORMS = {
    Decimal(code) for code in (10, 15, 16, 50, 51, 52, 68, 69, 92)
}
_UNSUPPORTED_CALLS = {Decimal(code) for code in (97, 98, 99, 198)}
_UNSUPPORTED_MACROS = {Decimal(code) for code in (65, 66, 67)}
_MALFORMED_AXIS = re.compile(r"(?<![A-Za-z_])[XYZABC](?![A-Za-z_])", re.IGNORECASE | re.ASCII)
_EXPONENT_AXIS = re.compile(
    r"(?<![A-Za-z_])[XYZABC]\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)[Ee][+-]?\d+",
    re.ASCII,
)


@dataclass(frozen=True)
class SuggestedOperation:
    marker_index: int
    marker_line: str
    description: str
    tool: str
    work_offset: str
    locations: tuple[tuple[Fraction, Fraction], ...]
    orientation: tuple[Decimal | None, Decimal | None, Decimal | None]


@dataclass(frozen=True)
class GroupSuggestion:
    operations: tuple[SuggestedOperation, ...]


@dataclass(frozen=True)
class SkippedOperation:
    marker_index: int
    marker_line: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SuggestionAnalysis:
    suggestions: tuple[GroupSuggestion, ...]
    skipped: tuple[SkippedOperation, ...]
    warnings: tuple[str, ...]


@dataclass
class _Operation:
    marker_index: int
    marker_line: str
    tool: str
    descriptions: list[str] = field(default_factory=list)
    points: set[tuple[Fraction, Fraction]] = field(default_factory=set)
    contexts: set[tuple[str, str, tuple[Decimal | None, Decimal | None, Decimal | None]]] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)
    saw_cycle: bool = False
    saw_tool_change: bool = False


@dataclass
class _ModalState:
    units: str | None = None
    distance_mode: str | None = None
    plane: str | None = None
    offset: str | None = None
    x: Fraction | None = None
    y: Fraction | None = None
    orientation: dict[str, Decimal | None] = field(default_factory=lambda: {"A": None, "B": None, "C": None})
    selected_tool: str = "Unknown"
    active_tool: str = "Unknown"
    cycle: Decimal | None = None
    unsafe: set[str] = field(default_factory=set)


def _words(line):
    visible = strip_nc_comments(line)
    matches = list(iter_nc_words(visible))
    words = [(match.group(1).upper(), Decimal(match.group(2))) for match in matches]
    remainder = list(visible)
    for match in matches:
        remainder[match.start():match.end()] = " " * (match.end() - match.start())
    return visible, words, "".join(remainder)


def _descriptions(line):
    for start, end in nc_comment_spans(line):
        comment = line[start:end]
        if comment.startswith("("):
            comment = comment[1:]
            if comment.endswith(")"):
                comment = comment[:-1]
        else:
            comment = comment[1:]
        comment = comment.strip()
        if comment:
            yield comment


def _matching_locations(first, second, tolerance):
    if len(first) != len(second):
        return False
    buckets = defaultdict(list)
    for index, (x, y) in enumerate(second):
        buckets[(x // tolerance, y // tolerance)].append(index)
    candidates = []
    for x, y in first:
        bucket_x, bucket_y = x // tolerance, y // tolerance
        nearby = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in buckets.get((bucket_x + dx, bucket_y + dy), ()):
                    x2, y2 = second[index]
                    if abs(x - x2) <= tolerance and abs(y - y2) <= tolerance:
                        nearby.append(index)
        candidates.append(nearby)
    right_matches = {}
    left_matches = {}
    for start in range(len(first)):
        queue = deque([start])
        seen_left = {start}
        seen_right = set()
        previous = {}
        free_right = None
        while queue and free_right is None:
            left = queue.popleft()
            for right in candidates[left]:
                if right in seen_right:
                    continue
                seen_right.add(right)
                previous[right] = left
                if right not in right_matches:
                    free_right = right
                    break
                next_left = right_matches[right]
                if next_left not in seen_left:
                    seen_left.add(next_left)
                    queue.append(next_left)
        if free_right is None:
            return False
        right = free_right
        while right is not None:
            left = previous[right]
            old_right = left_matches.get(left)
            left_matches[left] = right
            right_matches[right] = left
            right = old_right
    return True


def analyze_group_suggestions(lines):
    state = _ModalState()
    current = None
    operations = []
    skipped = []
    warnings = set()
    started = False

    def finish():
        if current is None or not current.saw_cycle:
            return
        reasons = set(current.reasons)
        if len(current.contexts) > 1:
            reasons.add("Hole locations use different work offsets, planes, or rotary positions.")
        if not current.points:
            reasons.add("No complete X/Y hole locations could be determined.")
        if reasons:
            skipped.append(SkippedOperation(current.marker_index, current.marker_line, tuple(sorted(reasons))))
        else:
            offset, _, orientation = next(iter(current.contexts))
            operations.append(SuggestedOperation(
                current.marker_index, current.marker_line,
                " | ".join(current.descriptions[:3]) or "No operation comment",
                current.tool, offset, tuple(sorted(current.points)), orientation,
            ))

    for index, line in enumerate(lines):
        visible, words, remainder = _words(line)
        gs = [value for letter, value in words if letter == "G"]
        ms = [value for letter, value in words if letter == "M"]
        axes = {letter: value for letter, value in words if letter in "XYZABC"}
        tools = [value for letter, value in words if letter == "T"]
        m01, m06 = Decimal(1) in ms, Decimal(6) in ms
        if tools:
            value = tools[-1]
            if value >= 0 and value == value.to_integral_value():
                state.selected_tool = f"T{int(value)}"

        if not started and m06:
            started = True
            current = _Operation(index, line, state.active_tool)
            for preceding in lines[max(0, index - 2):index]:
                current.descriptions.extend(_descriptions(preceding))
        elif started and m01:
            if state.cycle is not None and current is not None:
                current.reasons.add("A canned cycle is active at an operation boundary.")
            finish()
            current = _Operation(index, line, state.active_tool)
            if state.cycle is not None:
                current.reasons.add("A canned cycle is active at an operation boundary.")
        elif started and m06 and current is not None and (current.saw_tool_change or current.saw_cycle):
            if state.cycle is not None:
                current.reasons.add("A canned cycle is active at a tool change.")
            finish()
            current = _Operation(index, line, state.active_tool)
            for preceding in lines[max(0, index - 2):index]:
                current.descriptions.extend(_descriptions(preceding))
            if state.cycle is not None:
                current.reasons.add("A canned cycle is active at a tool change.")
        if current is not None:
            current.descriptions.extend(_descriptions(line))
            if m06:
                state.active_tool = state.selected_tool
                current.tool = state.active_tool
                current.saw_tool_change = True

        unsafe = []
        if any(character in visible for character in "#[]{}") or re.search(r"\b(?:GOTO|WHILE|IF|END)\b", visible, re.IGNORECASE):
            unsafe.append("Macro expressions or control flow cannot be interpreted.")
        if any(code in _UNSUPPORTED_CALLS for code in ms) or any(code in _UNSUPPORTED_MACROS for code in gs):
            unsafe.append("Subprogram or macro calls cannot be interpreted.")
        if any(
            code in _UNSUPPORTED_TRANSFORMS
            or (code != code.to_integral_value() and int(code) in (50, 51, 52, 54, 59, 68, 69, 92))
            for code in gs
        ):
            unsafe.append("Coordinate transformations or extended work offsets cannot be interpreted.")
        if visible.lstrip().startswith("/"):
            unsafe.append("Optional block execution cannot be determined.")
        if any(
            sum(1 for letter, _ in words if letter == axis) > 1
            for axis in "XYZABC"
        ):
            unsafe.append("Multiple values for the same axis occur in one block.")
        for modal_codes in ((20, 21), (90, 91), (17, 18, 19), (54, 55, 56, 57, 58, 59)):
            if sum(code in gs for code in modal_codes) > 1:
                unsafe.append("Conflicting modal commands occur in one block.")
                break
        if unsafe:
            state.unsafe.update(unsafe)
            warnings.update(unsafe)
            if current is not None:
                current.reasons.update(unsafe)

        if _MALFORMED_AXIS.search(remainder):
            reason = "An axis word has an unsupported or missing numeric value."
            state.unsafe.add(reason)
            warnings.add(reason)
            if current is not None:
                current.reasons.add(reason)
        if started and (re.search(r"[\d.]", remainder) or _EXPONENT_AXIS.search(visible)):
            reason = "A numeric expression or word has unsupported syntax."
            state.unsafe.add(reason)
            warnings.add(reason)
            if current is not None:
                current.reasons.add(reason)

        for code in gs:
            if code == 20:
                state.units = "inches"
            elif code == 21:
                state.units = "millimeters"
            elif code == 90:
                state.distance_mode = "absolute"
            elif code == 91:
                state.distance_mode = "incremental"
            elif code in (17, 18, 19):
                state.plane = f"G{int(code)}"
            elif code in (54, 55, 56, 57, 58, 59):
                offset = f"G{int(code)}"
                if state.offset != offset:
                    state.x = state.y = None
                state.offset = offset

        rotary_words = {axis: axes[axis] for axis in "ABC" if axis in axes}
        for axis, value in rotary_words.items():
            if state.distance_mode == "absolute":
                state.orientation[axis] = value
            elif state.distance_mode == "incremental" and state.orientation[axis] is not None:
                state.orientation[axis] += value
            else:
                state.orientation[axis] = None
                reason = "A rotary position could not be determined."
                state.unsafe.add(reason)
                warnings.add(reason)
                if current is not None:
                    current.reasons.add(reason)

        cycles = [code for code in gs if code in _CYCLES]
        moves = [code for code in gs if code in _MOTION_CANCEL and code != 80]
        if len(cycles) > 1 or len(moves) > 1 or (cycles and (moves or Decimal(80) in gs)):
            reason = "Multiple motion or cycle commands occur on one line."
            if current is not None:
                current.reasons.add(reason)
            warnings.add(reason)
            state.cycle = None
        elif cycles:
            state.cycle = cycles[0]
        elif moves or Decimal(80) in gs:
            state.cycle = None
        activated_cycle = len(cycles) == 1 and not moves and Decimal(80) not in gs

        xy_present = "X" in axes or "Y" in axes
        non_work_move = any(code in (Decimal(28), Decimal(30), Decimal(53)) for code in gs)
        unsupported_xy = xy_present and any(code not in _SUPPORTED_XY_G for code in gs) and not non_work_move
        if non_work_move and xy_present:
            state.x = state.y = None
            if state.cycle is not None and current is not None:
                current.reasons.add("A machine or reference move occurs during a canned cycle.")
        elif unsupported_xy:
            state.x = state.y = None
            if current is not None:
                current.reasons.add("An X/Y block uses a command whose motion is not interpreted.")
        else:
            for axis in ("X", "Y"):
                if axis not in axes:
                    continue
                previous = getattr(state, axis.lower())
                if state.units is None or state.distance_mode is None:
                    setattr(state, axis.lower(), None)
                else:
                    value = Fraction(axes[axis])
                    if state.units == "millimeters":
                        value /= _MM_PER_INCH
                    if state.distance_mode == "incremental":
                        value = previous + value if previous is not None else None
                    setattr(state, axis.lower(), value)

        if current is not None and state.cycle is not None:
            current.saw_cycle = True
            current.reasons.update(state.unsafe)
            repeated_cycle = any(letter == "L" and value != 1 for letter, value in words)
            if repeated_cycle:
                current.reasons.add("Canned-cycle repetitions are not interpreted.")
            if activated_cycle or xy_present:
                if state.plane != "G17":
                    current.reasons.add("The drilling plane is not known to be G17.")
                if state.offset is None:
                    current.reasons.add("The active work offset is not known.")
                if state.units is None or state.distance_mode is None:
                    current.reasons.add("Units or distance mode are not known.")
                if state.x is None or state.y is None:
                    current.reasons.add("A complete X/Y location is not known.")
                if state.x is not None and state.y is not None and state.offset and state.plane == "G17":
                    orientation = tuple(state.orientation[axis] for axis in "ABC")
                    current.contexts.add((state.offset, state.plane, orientation))
                    current.points.add((state.x, state.y))
            if repeated_cycle:
                state.x = state.y = None

        if Decimal(2) in ms or Decimal(30) in ms:
            break

    finish()
    groups = []
    for operation in operations:
        for group in groups:
            if all(
                operation.work_offset == other.work_offset
                and operation.orientation == other.orientation
                and _matching_locations(operation.locations, other.locations, TOLERANCE_INCHES)
                for other in group
            ):
                group.append(operation)
                break
        else:
            groups.append([operation])
    return SuggestionAnalysis(
        tuple(GroupSuggestion(tuple(group)) for group in groups if len(group) > 1),
        tuple(skipped),
        tuple(sorted(warnings)),
    )
