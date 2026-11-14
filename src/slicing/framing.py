"""Resolve source annotations into the renderer's rectangular panels."""

from dataclasses import dataclass
from itertools import product
from math import ceil, gcd


Rect = tuple[int, int, int, int]
Interval = tuple[int, int]
CANVAS = (720, 1280)
SPEAKER_CENTER = (50, 40)
SPEAKER_ZONE = ((45, 55), (35, 45))
_DUPLICATE_SIDE_DIVISOR = 2


def contains(outer: Rect, inner: Rect) -> bool:
    x, y, w, h = outer
    a, b, c, d = inner
    return x <= a and y <= b and a + c <= x + w and b + d <= y + h


def overlaps(a: Rect, b: Rect) -> bool:
    x, y, w, h = a
    u, v, s, t = b
    return x < u + s and u < x + w and y < v + t and v < y + h


def _intersection(a: Rect, b: Rect) -> Rect:
    x, y = max(a[0], b[0]), max(a[1], b[1])
    return x, y, min(a[0] + a[2], b[0] + b[2]) - x, min(a[1] + a[3], b[1] + b[3]) - y


def bounds(boxes) -> Rect:
    boxes = tuple(boxes)
    x, y = min(box[0] for box in boxes), min(box[1] for box in boxes)
    return x, y, max(a + w for a, _, w, _ in boxes) - x, max(b + h for _, b, _, h in boxes) - y


@dataclass(frozen=True)
class TimedBox:
    interval: Interval
    box: Rect


@dataclass(frozen=True)
class Region:
    name: str
    required: bool
    track: tuple[TimedBox, ...]
    viewport: Rect | None = None
    speaker: str | None = None

    @property
    def envelope(self) -> Rect:
        return bounds(part.box for part in self.track)


def _source_rect(value) -> Rect:
    if not (isinstance(value, list) and len(value) == 4 and all(type(v) is int and v >= 0 for v in value)
            and value[2] and value[3]):
        raise ValueError("Область исходника требует [x, y, ширина, высота] с целыми координатами.")
    return tuple(value)


def load_regions(data, interval: Interval) -> tuple[Region, ...]:
    if not isinstance(data, list) or not data:
        raise ValueError("framing.regions требует непустой список областей исходника.")
    regions = []
    for item in data:
        name, priority = item["name"], item["priority"]
        if not isinstance(name, str) or not name.strip() or any(region.name == name for region in regions):
            raise ValueError("Каждая область требует уникальное имя name.")
        if priority not in ("required", "secondary") or ("box" in item) == ("track" in item):
            raise ValueError(f"Область {name} требует priority required/secondary и один из box/track.")
        viewport = _source_rect(item["viewport"]) if "viewport" in item else None
        if "box" in item:
            track = [TimedBox(interval, _source_rect(item["box"]))]
        else:
            track = []
            previous = interval[0]
            if not isinstance(item["track"], list):
                raise ValueError(f"track области {name} должен быть списком.")
            for part in item["track"]:
                start, end = part["start_ms"], part["end_ms"]
                if not (type(start) is int and type(end) is int and start == previous < end <= interval[1]):
                    raise ValueError(f"track области {name} должен без разрывов покрывать интервал сцены.")
                track.append(TimedBox((start, end), _source_rect(part["box"])))
                previous = end
            if not track or previous != interval[1]:
                raise ValueError(f"track области {name} должен без разрывов покрывать интервал сцены.")
        if viewport is not None and any(not contains(viewport, part.box) for part in track):
            raise ValueError(f"Область {name} выходит за её viewport.")
        speaker = item.get("speaker")
        if speaker is not None and (not isinstance(speaker, str) or not speaker.strip()):
            raise ValueError(f"Область {name} требует непустое имя speaker.")
        regions.append(Region(name, priority == "required", tuple(track), viewport, speaker))
    if not any(region.required or region.speaker is not None for region in regions):
        raise ValueError("У сцены должна быть хотя бы одна область required.")
    return tuple(regions)


@dataclass(frozen=True)
class SpeakerTurn:
    interval: Interval
    speaker: str
    reaction: str | None = None


def load_speaker_turns(data, interval: Interval, regions: tuple[Region, ...]) -> tuple[SpeakerTurn, ...]:
    speakers = [region.speaker for region in regions if region.speaker is not None]
    if len(speakers) != len(set(speakers)):
        raise ValueError("Для каждого speaker укажите одну область лица.")
    if data is None:
        if len(speakers) > 1:
            raise ValueError("Для нескольких speaker требуется framing.speaker_turns.")
        return (SpeakerTurn(interval, speakers[0]),) if speakers else ()
    if not isinstance(data, list) or not data:
        raise ValueError("speaker_turns требует непустой список интервалов внимания.")
    turns = []
    previous = interval[0]
    for item in data:
        start, end, speaker = item["start_ms"], item["end_ms"], item["speaker"]
        reaction, hold = item.get("reaction"), item.get("hold", False)
        if not (type(start) is int and type(end) is int and start == previous < end <= interval[1]):
            raise ValueError("speaker_turns должен без разрывов покрывать отрезок.")
        if speaker not in speakers or (reaction is not None and (reaction == speaker or reaction not in speakers)):
            raise ValueError("speaker_turns требует имена размеченных участников. reaction указывает второго участника.")
        if type(hold) is not bool or (hold and (not turns or reaction is not None)):
            raise ValueError("hold требует предыдущий план и сохраняет его говорящего и реакцию.")
        if hold:
            speaker, reaction = turns[-1].speaker, turns[-1].reaction
        if turns and (speaker, reaction) == (turns[-1].speaker, turns[-1].reaction):
            start = turns.pop().interval[0]
        turns.append(SpeakerTurn((start, end), speaker, reaction))
        previous = end
    if previous != interval[1]:
        raise ValueError("speaker_turns должен без разрывов покрывать отрезок.")
    return tuple(turns)


@dataclass(frozen=True)
class Obstacle:
    object: str
    box: Rect
    interval: Interval | None = None
    platform: str | None = None


@dataclass(frozen=True)
class Profiles:
    kind: str
    source: str
    obstacles: tuple[Obstacle, ...]

    def text_area(self) -> Rect:
        # A rectangular corridor common to both stepped profiles.
        left = max(item.box[2] for item in self.obstacles if item.object == "left")
        top = max(item.box[3] for item in self.obstacles if item.object == "top")
        right = min(item.box[0] for item in self.obstacles if item.object in ("right", "buttons"))
        bottom = min(item.box[1] for item in self.obstacles if item.object == "bottom")
        return left, top, right - left, bottom - top


def load_profiles(data, size: tuple[int, int]) -> Profiles:
    source, kind = data["source"], data["kind"]
    rw, rh = data["reference_size_px"]
    if (not isinstance(source, str) or not source.strip() or kind not in ("estimate", "measured")
            or not all(type(v) is int and v > 0 for v in (rw, rh)) or rw * 16 != rh * 9):
        raise ValueError("Профили auto_layout требуют source, kind и опорный размер 9:16.")
    w, h = size
    obstacles = []
    for name in ("TikTok", "Shorts"):
        profile = data["platforms"][name]
        top, bottom, left, right, rail_top, rail_right = (profile[key] for key in (
            "top", "bottom", "left", "right", "rail_top", "rail_right",
        ))
        if (not all(type(v) is int for v in (top, bottom, left, right, rail_top, rail_right))
                or not (0 <= top <= rail_top <= rh - bottom <= rh and 0 <= right <= rail_right < rw - left <= rw)
                or rh - bottom - top < rh // 5 or rw - left - rail_right < rw // 4):
            raise ValueError(f"Некорректные границы UI {name}.")
        top, bottom, left, right, rail_top, rail_right = (
            (top * h + rh - 1) // rh, (bottom * h + rh - 1) // rh, (left * w + rw - 1) // rw,
            (right * w + rw - 1) // rw, rail_top * h // rh, (rail_right * w + rw - 1) // rw,
        )
        obstacles.extend(Obstacle(label, box, platform=name) for label, box in (
            ("top", (0, 0, w, top)), ("bottom", (0, h - bottom, w, bottom)),
            ("left", (0, 0, left, h)), ("right", (w - right, 0, right, rail_top)),
            ("buttons", (w - rail_right, rail_top, rail_right, h - rail_top)),
        ))
    return Profiles(kind, source, tuple(obstacles))


@dataclass(frozen=True)
class Tile:
    place: Rect  # Reference canvas, passed to the existing renderer.
    output: Rect  # Exact chroma-aligned rectangle in the exported video.


@dataclass(frozen=True)
class Placement:
    crop: Rect
    tile: Tile
    regions: tuple[Region, ...]
    secondary: frozenset[str] = frozenset()
    overlap_cost: int = 0
    center_error: int = 0


@dataclass(frozen=True)
class TextSlot:
    anchor: tuple[int, int] | None
    obstacles: tuple[Obstacle, ...] = ()


@dataclass(frozen=True)
class Layout:
    panels: tuple[Placement, ...]
    speech: TextSlot


def project(box: Rect, crop: Rect, output: Rect) -> Rect:
    """Enclose the entire scaled box, rounding outward to output pixels."""
    x, y, w, h = box
    cx, cy, cw, ch = crop
    px, py, pw, ph = output
    left, top = (x - cx) * pw // cw, (y - cy) * ph // ch
    right = ((x + w - cx) * pw + cw - 1) // cw
    bottom = ((y + h - cy) * ph + ch - 1) // ch
    return px + left, py + top, right - left, bottom - top


def conflict(part: TimedBox, obstacle: Obstacle) -> bool:
    return obstacle.box[2] > 0 and obstacle.box[3] > 0 and (
        obstacle.interval is None or max(part.interval[0], obstacle.interval[0])
        < min(part.interval[1], obstacle.interval[1])
    )


def _blocked_axis(start, length, ui_start, ui_length, crop_size, panel_start, panel_size):
    # The projected object overlaps this UI axis for an open interval of crop
    # origins. Return the corresponding closed interval on the 2px chroma grid.
    scale = 2 * panel_size
    lo = start * panel_size - (ui_start + ui_length - panel_start) * crop_size
    hi = (start + length) * panel_size - (ui_start - panel_start) * crop_size
    return lo // scale + 1, (hi - 1) // scale


# Origin windows use inclusive left/right/top/bottom bounds on the 2px grid.
def _clip_window(window, limits):
    left, right = max(window[0], limits[0]), min(window[1], limits[1])
    top, bottom = max(window[2], limits[2]), min(window[3], limits[3])
    return (left, right, top, bottom) if left <= right and top <= bottom else None


def _inside(window, x, y):
    return window[0] <= x <= window[1] and window[2] <= y <= window[3]


def _cover_window(box, size, limits, divisor):
    x, y, w, h = box
    cw, ch = size
    min_w, min_h = ((w + divisor - 1) // divisor, (h + divisor - 1) // divisor) if divisor is not None else (1, 1)
    if min_w > cw or min_h > ch:
        return None
    return _clip_window(((x + min_w - cw + 1) // 2, (x + w - min_w) // 2,
                         (y + min_h - ch + 1) // 2, (y + h - min_h) // 2), limits)


def _occlusions(regions, obstacles):
    return {(part.box, obstacle.box) for region in regions for part in region.track
            for obstacle in obstacles if conflict(part, obstacle)}


def _blocked_windows(pairs, size, output, limits):
    cw, ch = size
    px, py, pw, ph = output
    windows = set()
    for (x, y, w, h), (ux, uy, uw, uh) in pairs:
        x1, x2 = _blocked_axis(x, w, ux, uw, cw, px, pw)
        y1, y2 = _blocked_axis(y, h, uy, uh, ch, py, ph)
        window = _clip_window((x1, x2, y1, y2), limits)
        if window is not None:
            windows.add(window)
    return windows


def _axis_points(lo, hi, spans, target):
    edges = {lo, hi + 1}
    for start, end in spans:
        edges.update((start, end + 1))
    ordered = sorted(edges)
    return (max(a, min(target, b - 1)) for a, b in zip(ordered, ordered[1:]))


def _origins(limits, blocked, scored, target):
    # Between consecutive window boundaries every visibility test has the
    # same result. Visit the closest origin to the subject in each such cell.
    windows = blocked | scored
    for x in _axis_points(*limits[:2], (window[:2] for window in windows), target[0]):
        active = {window[2:] for window in windows if window[0] <= x <= window[1]}
        hard = {window[2:] for window in blocked if window[0] <= x <= window[1]}
        for y in _axis_points(*limits[2:], active, target[1]):
            if not any(start <= y <= end for start, end in hard):
                yield x, y


def _headroom(face: Region, view: Rect) -> Rect:
    x, y, w, h = face.envelope
    side = (w * 14 + 99) // 100
    above, below = (h * 22 + 99) // 100, (h * 14 + 99) // 100
    return _intersection((x - side, y - above, w + 2 * side, h + above + below), view)


@dataclass(frozen=True)
class _FaceAnchor:
    centers: tuple[tuple[int, int], tuple[int, int]]  # Extremes of doubled source centers by axis.
    canvas: tuple[int, int]
    in_zone: bool

    def origin(self, size, output, limits):
        target, window = [], []
        for axis, ((low, high), pct, (a, b)) in enumerate(zip(SPEAKER_ZONE, SPEAKER_CENTER, self.centers)):
            tile_start, tile_size = output[axis], output[axis + 2]
            span, canvas = size[axis], self.canvas[axis]
            # The origin is expressed in 2px steps and the projected center
            # is tile_start + (source_center - 2 * origin) * tile_size / span.
            scale = 100 * tile_size
            if self.in_zone:
                lower = b * scale - 2 * (high * canvas - 100 * tile_start) * span
                upper = a * scale - 2 * (low * canvas - 100 * tile_start) * span
                window.extend(((lower + 4 * scale - 1) // (4 * scale), upper // (4 * scale)))
            midpoint = (a + b) * scale - 4 * (pct * canvas - 100 * tile_start) * span
            target.append(round(midpoint / (8 * scale)))
        return (_clip_window(window, limits) if self.in_zone else limits), tuple(target)

    def error(self, origin, size, output):
        errors = []
        for axis, (pct, centers) in enumerate(zip(SPEAKER_CENTER, self.centers)):
            for center in centers:
                point = output[axis] + (center - 4 * origin[axis]) * output[axis + 2] / (2 * size[axis])
                errors.append(abs(100 * point / self.canvas[axis] - pct))
        # Sub-percent alignment should not win over a more readable scale.
        return round(max(errors))


def _face_anchor(face, canvas, in_zone):
    x_centers = [2 * part.box[0] + part.box[2] for part in face.track]
    y_centers = [2 * part.box[1] + part.box[3] for part in face.track]
    return _FaceAnchor(((min(x_centers), max(x_centers)), (min(y_centers), max(y_centers))), canvas, in_zone)


def _crops(regions: tuple[Region, ...], secondary: tuple[Region, ...], foreign: tuple[Region, ...],
           tile: Tile, frame: Rect, obstacles: tuple[Obstacle, ...], *, allow_duplicates: bool = False,
           face: Region | None = None, anchor: _FaceAnchor | None = None,
           min_width: int = 0) -> tuple[Placement, ...]:
    view = frame
    for region in regions:
        if region.viewport is not None:
            view = _intersection(view, region.viewport)
    x, y, w, h = bounds(region.envelope for region in regions)
    if not contains(view, (x, y, w, h)):
        return ()
    if face is not None:
        x, y, w, h = bounds(((x, y, w, h), _headroom(face, view)))
    pw, ph = tile.output[2:]
    d = gcd(pw, ph)
    base_w, base_h = 2 * pw // d, 2 * ph // d
    smallest = max((max(w, min_width) + base_w - 1) // base_w, (h + base_h - 1) // base_h)
    largest = min(view[2] // base_w, view[3] // base_h)
    pairs = _occlusions(regions, obstacles)
    context = [(region.name, region.envelope, _occlusions((region,), obstacles)) for region in secondary
               if contains(view, region.envelope)]
    other_parts = [part for region in foreign for part in region.track if overlaps(view, part.box)]
    best = {}
    for factor in range(smallest, largest + 1):
        size = base_w * factor, base_h * factor
        cw, ch = size
        left, right = (max(view[0], x + w - cw) + 1) // 2, min(x, view[0] + view[2] - cw) // 2
        top, bottom = (max(view[1], y + h - ch) + 1) // 2, min(y, view[1] + view[3] - ch) // 2
        if left > right or top > bottom:
            continue
        limits = left, right, top, bottom
        target = (2 * x + w - cw) // 4, (2 * y + h - ch) // 4
        if anchor is not None:
            limits, target = anchor.origin(size, tile.output, limits)
            if limits is None:
                continue
        blocked = _blocked_windows(pairs, size, tile.output, limits)
        # A second view of at least half the width and half the height of
        # another panel's required box repeats a substantial part of it.
        if not allow_duplicates:
            repeats = {_cover_window(part.box, size, limits, _DUPLICATE_SIDE_DIVISOR)
                       for part in other_parts} - {None}
            if limits in repeats:
                continue
            blocked.update(repeats)
        scored = set()
        visible = []
        for name, envelope, occlusions in context:
            window = _cover_window(envelope, size, limits, 1)
            if window is not None:
                hidden = _blocked_windows(occlusions, size, tile.output, window)
                visible.append((name, window, hidden))
                scored.add(window)
                scored.update(hidden)
        overlaps_by_time = []
        for part in other_parts:
            duration = part.interval[1] - part.interval[0]
            for divisor in (None, 4):
                window = _cover_window(part.box, size, limits, divisor)
                if window is not None:
                    overlaps_by_time.append((window, duration))
                    scored.add(window)
        for cx, cy in _origins(limits, blocked, scored, target):
            seen = frozenset(name for name, window, hidden in visible if _inside(window, cx, cy)
                             and not any(_inside(box, cx, cy) for box in hidden))
            cost = sum(duration for window, duration in overlaps_by_time if _inside(window, cx, cy))
            error = anchor.error((cx, cy), size, tile.output) if anchor is not None else 0
            rank = (-error, -cost, -cw, -abs(cx - target[0]) - abs(cy - target[1]), -cx, -cy)
            if seen not in best or rank > best[seen][0]:
                best[seen] = rank, Placement((2 * cx, 2 * cy, cw, ch), tile, regions, seen, cost, error)
        if anchor is None and not context and best and best[frozenset()][1].overlap_cost == 0:
            break  # A wider crop cannot improve scale or add context here.
    return tuple(panel for _, panel in best.values())


def _partitions(regions):
    groups = set()
    for axis in (0, 1):
        centers = [2 * region.envelope[axis] + region.envelope[axis + 2] for region in regions]
        order = sorted(range(len(regions)), key=centers.__getitem__)
        for i in range(1, len(order)):
            first, second = tuple(sorted(order[:i])), tuple(sorted(order[i:]))
            groups.update(((first, second), (second, first)))
    for first, second in sorted(groups):
        yield tuple(regions[i] for i in first), tuple(regions[i] for i in second)


def duplicated_regions(layout: Layout):
    """Yield required track parts substantially repeated in the other panel."""
    for index, panel in enumerate(layout.panels):
        for other_index, other in enumerate(layout.panels):
            if other_index == index:
                continue
            for region in panel.regions:
                for part in region.track:
                    _, _, w, h = _intersection(part.box, other.crop)
                    if w * _DUPLICATE_SIDE_DIVISOR >= part.box[2] and h * _DUPLICATE_SIDE_DIVISOR >= part.box[3]:
                        yield region, part, index + 1, other_index + 1


def _score(layout, focus):
    panels = layout.panels
    primary = next(panel for panel in panels if focus in panel.regions)
    # Count each safe secondary region once, even if both panels show it.
    context = frozenset().union(*(panel.secondary for panel in panels))
    scale = primary.tile.output[2] / primary.crop[2]
    other = min(panel.tile.output[2] / panel.crop[2] for panel in panels)
    return len(context), -sum(panel.overlap_cost for panel in panels), scale, other


def solve(regions: tuple[Region, ...], source_size: tuple[int, int], tile_sets: tuple[tuple[Tile, ...], ...],
          ui: tuple[Obstacle, ...], slots: tuple[TextSlot, ...], *, allow_duplicates: bool = False) -> Layout | None:
    required = tuple(region for region in regions if region.required)
    secondary = tuple(region for region in regions if not region.required)
    frame = (0, 0, *source_size)
    partitions = tuple(_partitions(required))
    cache = {}
    best = None
    best_score = None
    for tiles in tile_sets:
        if best is not None and len(tiles) > len(best.panels):
            break
        arrangements = ((required,),) if len(tiles) == 1 else partitions
        for slot in slots:
            obstacles = ui + slot.obstacles
            for groups in arrangements:
                options = []
                for group, tile in zip(groups, tiles):
                    relevant = tuple(obstacle for obstacle in obstacles if overlaps(obstacle.box, tile.output))
                    key = (group, tile, relevant)
                    if key not in cache:
                        foreign = tuple(region for region in required if region not in group)
                        cache[key] = _crops(group, secondary, foreign, tile, frame, relevant,
                                            allow_duplicates=allow_duplicates)
                    options.append(cache[key])
                    if not options[-1]:
                        break
                for panels in product(*options):
                    candidate = Layout(panels, slot)
                    score = _score(candidate, required[0])
                    if best is None or score > best_score:
                        best, best_score = candidate, score
    return best


def solve_speaker(regions: tuple[Region, ...], turn: SpeakerTurn, source_size: tuple[int, int],
                  main: Tile, insets: tuple[Tile, ...], ui: tuple[Obstacle, ...],
                  slots: tuple[TextSlot, ...]) -> Layout | None:
    face = next(region for region in regions if region.speaker == turn.speaker)
    reaction = next((region for region in regions if region.speaker == turn.reaction), None) if turn.reaction else None
    required = (face, *(region for region in regions if region.required and region.speaker is None))
    context = tuple(region for region in regions if not region.required and region.speaker is None)
    frame = (0, 0, *source_size)
    reaction_cache = {}
    if reaction is not None:
        face_ratio = max(max(part.box[axis] for part in reaction.track) /
                         min(part.box[axis] for part in face.track) for axis in (2, 3))
    for in_zone in (True, False):
        anchor = _face_anchor(face, main.output[2:], in_zone)
        best, best_score = None, None
        for slot in slots:
            obstacles = ui + slot.obstacles
            speech = tuple(item for item in slot.obstacles if item.object == "subtitles")
            for inset in insets if reaction is not None else (None,):
                small = ()
                blocked = obstacles
                if inset is not None:
                    if any(overlaps(cue.box, inset.output) for cue in speech):
                        continue
                    local = tuple(item for item in obstacles if overlaps(item.box, inset.output))
                    key = inset, local, 0
                    if key not in reaction_cache:
                        reaction_cache[key] = _crops((reaction,), (), required, inset, frame, local, face=reaction)
                    small = reaction_cache[key]
                    if not small:
                        continue
                    # The inset itself is opaque and must keep the main face clear.
                    blocked += (Obstacle("reaction", inset.output),)
                for panel in _crops(required, context, (reaction,) if reaction else (), main, frame, blocked,
                                    face=face, anchor=anchor):
                    inset_panels = small
                    if inset is not None:
                        # The reaction's face should also be smaller, even if
                        # the two faces have very different source sizes.
                        min_width = ceil(inset.output[2] * face_ratio * panel.crop[2] / (0.8 * main.output[2]))
                        if small[0].crop[2] < min_width:
                            key = inset, local, min_width
                            if key not in reaction_cache:
                                reaction_cache[key] = _crops((reaction,), (), required, inset, frame, local,
                                                             face=reaction, min_width=min_width)
                            inset_panels = reaction_cache[key]
                            if not inset_panels:
                                continue
                    below_face = True
                    for part in face.track:
                        _, top, _, height = project(part.box, panel.crop, main.output)
                        if any(conflict(part, cue) and cue.box[1] < top + height for cue in speech):
                            below_face = False
                            break
                    layout = Layout((panel, *inset_panels), slot)
                    score = (-panel.center_error, below_face, *_score(layout, face))
                    if best is None or score > best_score:
                        best, best_score = layout, score
        if best is not None:
            return best
    return None
