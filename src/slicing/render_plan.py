import hashlib
import json
import re
import tempfile
from bisect import bisect_right
from dataclasses import asdict, dataclass, replace
from itertools import accumulate
from math import ceil, floor
from pathlib import Path
from textwrap import wrap

from . import SlicingError
from . import framing as auto
from .media import Cue, Media, _run

FPS = 30
SAMPLE_RATE = 48_000
WIDTH, HEIGHT = auto.CANVAS
BACKGROUND = "0x0E1830"

Rect = auto.Rect


@dataclass(frozen=True)
class Panel:
    crop: Rect
    place: Rect
    ambient: bool = False


@dataclass(frozen=True)
class Header:
    label: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class SubtitleSpelling:
    replacements: dict[str, str]
    first_segment_joins: dict[str, str]


@dataclass(frozen=True)
class Caption:
    start_ms: int
    end_ms: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class DraftWord:
    id: str
    segment: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SubtitleReview:
    draft: Path
    edits: Path


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    framing: str = "full_frame"
    panels: tuple[Panel, ...] = ()
    captions: tuple[Caption, ...] | None = None
    masks: tuple[Rect, ...] = ()
    layered: bool = False
    regions: tuple[auto.Region, ...] = ()
    speaker_turns: tuple[auto.SpeakerTurn, ...] = ()

    @property
    def length_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class EditPlan:
    vod_id: str
    source: Path
    source_duration: float
    clip_id: str
    title: str
    segments: list[Segment]
    sha256: str
    header: Header | None = None
    subtitle_spelling: SubtitleSpelling | None = None
    subtitle_review: SubtitleReview | None = None
    subtitle_safe_area: bool = False
    safe_area: Rect | None = None
    export_size: tuple[int, int] = (WIDTH, HEIGHT)
    source_size: tuple[int, int] | None = None
    profiles: auto.Profiles | None = None

    @property
    def ends_ms(self) -> list[int]:
        return list(accumulate(segment.length_ms for segment in self.segments))


def _rect(value) -> Rect:
    if not (
        isinstance(value, list) and len(value) == 4
        and all(type(coordinate) is int and coordinate >= 0 for coordinate in value)
        and value[2] > 0 and value[3] > 0 and value[2] % 2 == value[3] % 2 == 0
    ):
        raise ValueError("Прямоугольник требует [x, y, ширина, высота] с целыми координатами и чётным ненулевым размером.")
    return tuple(value)


def _load_segment(data) -> Segment:
    segment = Segment(data["start_ms"], data["end_ms"])
    if "captions" in data:
        segment = replace(segment, captions=_load_captions(data["captions"], segment))
    if "framing" not in data:
        return segment

    framing = data["framing"]
    name = framing["name"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError("framing требует имя name.")
    masks = tuple(map(_rect, framing.get("masks", [])))
    if any(x + w > WIDTH or y + h > HEIGHT for x, y, w, h in masks):
        raise ValueError("Маска выходит за границы холста.")
    if "regions" in framing:
        if "panels" in framing or "layered" in framing:
            raise ValueError("framing.regions используется отдельно от panels и layered.")
        interval = segment.start_ms, segment.end_ms
        regions = auto.load_regions(framing["regions"], interval)
        turns = auto.load_speaker_turns(framing.get("speaker_turns"), interval, regions)
        return replace(segment, framing=name, masks=masks, regions=regions, speaker_turns=turns)
    if "speaker_turns" in framing:
        raise ValueError("speaker_turns требует framing.regions с областями лица.")
    panels = framing["panels"]
    if not isinstance(panels, list) or not panels:
        raise ValueError("framing требует непустой список panels.")
    panels = tuple(Panel(_rect(panel["crop"]), _rect(panel["place"]), panel.get("ambient", False)) for panel in panels)
    for panel in panels:
        if type(panel.ambient) is not bool:
            raise ValueError("ambient должен быть логическим значением.")
        if panel.crop[0] % 2 or panel.crop[1] % 2:
            raise ValueError(f"Панель {name} требует чётные x и y в crop.")
        x, y, width, height = panel.place
        if x + width > WIDTH or y + height > HEIGHT:
            raise ValueError(f"Панель {name} выходит за границы холста {WIDTH} × {HEIGHT}.")
    layered = framing.get("layered", False)
    if type(layered) is not bool or (layered and panels[0].place != (0, 0, WIDTH, HEIGHT)):
        raise ValueError("Для layered первая панель должна покрывать весь холст.")
    return replace(segment, framing=name, panels=panels, masks=masks, layered=layered)


def _load_export_size(size) -> tuple[int, int]:
    if not (isinstance(size, list) and len(size) == 2 and
            all(type(value) is int and value > 0 and value % 2 == 0 for value in size) and
            size[0] >= WIDTH and size[0] * 16 == size[1] * 9):
        raise ValueError("export_size требует чётное разрешение 9:16 шириной не менее 720.")
    return size[0], size[1]


def _output_rect(rect: Rect, size: tuple[int, int], *, cover: bool = False) -> Rect:
    if size == (WIDTH, HEIGHT):
        return rect
    # Round shared panel edges together and masks outward on the chroma grid.
    x, y, w, h = rect
    half_scale = size[0] / (2 * WIDTH)
    start, end = (floor, ceil) if cover else (round, round)
    left, top = (2 * start(edge * half_scale) for edge in (x, y))
    right, bottom = (2 * end(edge * half_scale) for edge in (x + w, y + h))
    return left, top, right - left, bottom - top


def _load_safe_area(margins) -> Rect:
    left, top, right, bottom = (margins[key] for key in ("left", "top", "right", "bottom"))
    if not all(type(value) in (int, float) and 0 <= value < 1 for value in (left, top, right, bottom)):
        raise ValueError("Отступы safe_margins должны быть долями кадра от 0 до 1.")
    x, y = ceil(WIDTH * left), ceil(HEIGHT * top)
    w, h = WIDTH - x - ceil(WIDTH * right), HEIGHT - y - ceil(HEIGHT * bottom)
    if w < 160 or h < 240:
        raise ValueError("В безопасной области недостаточно места для текста.")
    return x, y, w, h


def _text_line(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\n" not in value and "\r" not in value


def _text_lines(value) -> bool:
    return isinstance(value, list) and 1 <= len(value) <= 2 and all(map(_text_line, value))


def _load_header(data) -> Header:
    label, lines = data["label"], data["lines"]
    if not (_text_line(label) and _text_lines(lines)):
        raise ValueError("header требует строку label и одну или две строки lines.")
    return Header(label, tuple(lines))


def _load_captions(data, segment: Segment) -> tuple[Caption, ...]:
    if not isinstance(data, list):
        raise ValueError("captions должен быть списком.")
    captions = []
    previous_end = segment.start_ms
    for cue in data:
        start, end, lines = cue["start_ms"], cue["end_ms"], cue["lines"]
        if not (
            type(start) is int and type(end) is int and previous_end <= start < end <= segment.end_ms
            and _text_lines(lines)
        ):
            raise ValueError("Реплики captions должны идти по порядку внутри отрезка и иметь одну или две строки.")
        captions.append(Caption(start, end, tuple(lines)))
        previous_end = end
    return tuple(captions)


def _load_spelling(data) -> SubtitleSpelling:
    if not isinstance(data, dict):
        raise ValueError("subtitle_spelling должен быть объектом.")
    replacements = data.get("replacements", {})
    joins = data.get("first_segment_joins", {})
    for mapping in (replacements, joins):
        if not isinstance(mapping, dict) or not all(_text_line(key) and _text_line(value) for key, value in mapping.items()):
            raise ValueError("Замены в субтитрах требуют строковых ключей и значений.")
    return SubtitleSpelling(replacements, joins)


def _load_review_paths(data, directory: Path) -> SubtitleReview:
    draft, edits = data["draft"], data["edits"]
    if not all(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+\.json", name) for name in (draft, edits)):
        raise ValueError("subtitle_review требует имена двух JSON-файлов рядом с планом.")
    if draft.casefold() == edits.casefold():
        raise ValueError("Черновик и правки должны быть разными файлами.")
    return SubtitleReview(directory / draft, directory / edits)


def _check_source_framing(media: Media, source: Path, segments: list[Segment]) -> tuple[int, int] | None:
    annotated = any(segment.regions for segment in segments)
    if not annotated and not any(segment.panels for segment in segments):
        return None
    fields = "stream=width,height,sample_aspect_ratio" if annotated else "stream=width,height"
    raw = _run(media.ffprobe, [
        "-v", "error", "-select_streams", "v:0", "-show_entries", fields, "-of", "json", str(source),
    ])
    stream = json.loads(raw)["streams"][0]
    if annotated and stream.get("sample_aspect_ratio") not in (None, "N/A", "0:1", "1:1"):
        raise SlicingError("Автокомпоновка требует исходник с квадратными пикселями.")
    size = stream["width"], stream["height"]
    frame = (0, 0, *size)
    for number, segment in enumerate(segments, 1):
        for panel in segment.panels:
            if not auto.contains(frame, panel.crop):
                raise SlicingError(f"Панель отрезка {number} выходит за границы исходного кадра.")
        for region in segment.regions:
            if not auto.contains(frame, region.envelope) or (
                region.viewport is not None and not auto.contains(frame, region.viewport)
            ):
                raise SlicingError(f"Область {region.name} отрезка {number} выходит за границы исходного кадра.")
    return size


def load_plan(path: Path, clip_id: str, root: Path, media: Media) -> EditPlan:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", clip_id):
        raise SlicingError("Недопустимый ID клипа.")
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
        if type(document["schema_version"]) is not int or document["schema_version"] != 1:
            raise ValueError("Поддерживается схема плана версии 1.")
        source = document["source"]
        vod_id = source["vod_id"]
        if not isinstance(vod_id, str) or not re.fullmatch(r"[0-9]+", vod_id):
            raise ValueError("Ожидается числовой ID Twitch VOD.")
        vod_dir = (root / "data" / "vods").resolve()
        vod_file = (root / source["file"]).resolve()
        if vod_file != vod_dir / f"{vod_id}.mp4":
            raise ValueError(f"Ожидается локальный исходник data/vods/{vod_id}.mp4.")
        if not isinstance(document["clips"], list):
            raise ValueError("Ожидается список clips.")
        matches = [clip for clip in document["clips"] if clip["id"] == clip_id]
        if len(matches) != 1:
            raise ValueError(f"В clips должна быть одна запись {clip_id}.")
        clip = matches[0]
        if not isinstance(clip["segments"], list) or not clip["segments"]:
            raise ValueError("Клип должен содержать непустой список segments.")
        segments = [_load_segment(segment) for segment in clip["segments"]]
        if any(segment.captions is not None for segment in segments) and any(segment.captions is None for segment in segments):
            raise ValueError("Для ручных субтитров укажите captions у каждого отрезка, включая пустые списки.")
        title = clip.get("title", clip_id)
        if not isinstance(title, str):
            raise ValueError("Название клипа должно быть строкой.")
        header = _load_header(clip["header"]) if "header" in clip else None
        spelling = _load_spelling(clip["subtitle_spelling"]) if "subtitle_spelling" in clip else None
        review = _load_review_paths(clip["subtitle_review"], path.parent) if "subtitle_review" in clip else None
        subtitle_safe_area = clip.get("subtitle_safe_area", False)
        if type(subtitle_safe_area) is not bool:
            raise ValueError("subtitle_safe_area должен быть логическим значением.")
        safe_area = _load_safe_area(clip["safe_margins"]) if "safe_margins" in clip else None
        export_size = _load_export_size(clip["export_size"]) if "export_size" in clip else (WIDTH, HEIGHT)
        profiles = None
        if any(segment.regions for segment in segments):
            profiles = auto.load_profiles(document["auto_layout"], export_size)
            if safe_area is None:
                x, y, w, h = profiles.text_area()
                left, top = ceil(x * WIDTH / export_size[0]), ceil(y * HEIGHT / export_size[1])
                right = floor((x + w) * WIDTH / export_size[0])
                bottom = floor((y + h) * HEIGHT / export_size[1])
                safe_area = left, top, right - left, bottom - top
        if review is not None and (segments[0].captions is not None or spelling is not None):
            raise ValueError("subtitle_review используется отдельно от captions и subtitle_spelling.")
    except (KeyError, TypeError, ValueError) as error:
        raise SlicingError(f"Некорректный план {path.name}. {error}") from None

    duration = media.duration(vod_file)
    for number, segment in enumerate(segments, 1):
        if not (
            type(segment.start_ms) is int
            and type(segment.end_ms) is int
            and 0 <= segment.start_ms < segment.end_ms <= duration * 1000
        ):
            raise SlicingError(f"Отрезок {number} выходит за границы исходника ({duration:.6f} с) или задан неверно.")
    source_size = _check_source_framing(media, vod_file, segments)
    return EditPlan(
        vod_id, vod_file, duration, clip_id, title, segments, hashlib.sha256(raw).hexdigest(), header, spelling, review,
        subtitle_safe_area=subtitle_safe_area, safe_area=safe_area, export_size=export_size,
        source_size=source_size, profiles=profiles,
    )


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def _inputs(plan: EditPlan) -> list[str]:
    return [
        option for part in plan.segments
        for option in ("-ss", _seconds(part.start_ms), "-t", _seconds(part.length_ms), "-i", str(plan.source))
    ]


def _join_audio(media: Media, plan: EditPlan, audio: Path) -> None:
    filters = [
        f"[{index}:a:0]aresample={SAMPLE_RATE}:first_pts=0,aformat=channel_layouts=stereo,"
        f"apad,atrim=end_sample={part.length_ms * (SAMPLE_RATE // 1000)},asetpts=N/SR/TB[a{index}]"
        for index, part in enumerate(plan.segments)
    ]
    inputs = "".join(f"[a{index}]" for index in range(len(plan.segments)))
    filters.append(f"{inputs}concat=n={len(plan.segments)}:v=0:a=1[audio]")
    _run(media.ffmpeg, [
        "-hide_banner", "-v", "error", "-nostdin", "-n", *_inputs(plan),
        "-filter_complex", ";".join(filters), "-map", "[audio]", "-c:a", "pcm_s16le", str(audio),
    ])


def _draft_words(cues: list[Cue], ends_ms: list[int]) -> list[DraftWord]:
    words = []
    previous_end = 0
    for cue in sorted(cues, key=lambda cue: cue.start):
        start = max(0, round(cue.start * 1000))
        part = bisect_right(ends_ms, start)
        if part == len(ends_ms):
            break
        start = max(start, previous_end)
        end = min(round(cue.end * 1000), ends_ms[part])
        text = " ".join(cue.text.split())
        if text and end > start:
            words.append(DraftWord(f"w{len(words) + 1:03d}", part + 1, start, end, text))
            previous_end = end
    return words


def _draft_context(plan: EditPlan) -> dict:
    return {
        "schema_version": 1, "vod_id": plan.vod_id, "clip_id": plan.clip_id,
        "source_segments_ms": [[part.start_ms, part.end_ms] for part in plan.segments],
    }


def prepare_subtitle_draft(path: Path, clip_id: str, root: Path, media: Media) -> Path:
    plan = load_plan(path, clip_id, root, media)
    if plan.subtitle_review is None:
        raise SlicingError("Для черновика задайте subtitle_review в плане.")
    output = plan.subtitle_review.draft
    if output.exists():
        raise SlicingError(f"Черновик уже существует: {output}.")
    with tempfile.TemporaryDirectory(prefix=".subtitle-draft-", dir=output.parent) as temporary:
        audio = Path(temporary) / "joined.wav"
        _join_audio(media, plan, audio)
        print(f"{clip_id}: получаю метки Whisper по склеенному звуку.", flush=True)
        words = _draft_words(media.transcribe_words(audio), plan.ends_ms)
    document = {**_draft_context(plan), "words": [asdict(word) for word in words]}
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return output


def _read_draft_words(entries, ends_ms: list[int]) -> list[DraftWord]:
    if not isinstance(entries, list):
        raise ValueError("words должен быть списком.")
    words = []
    previous_end = 0
    for entry in entries:
        word = DraftWord(**entry)
        if not (
            word.id == f"w{len(words) + 1:03d}" and type(word.segment) is int
            and type(word.start_ms) is int and type(word.end_ms) is int
            and 1 <= word.segment <= len(ends_ms) and _text_line(word.text)
        ):
            raise ValueError("Некорректное слово черновика.")
        start = ends_ms[word.segment - 2] if word.segment > 1 else 0
        if not max(start, previous_end) <= word.start_ms < word.end_ms <= ends_ms[word.segment - 1]:
            raise ValueError(f"Метка {word.id} пересекает склейку или другую метку.")
        words.append(word)
        previous_end = word.end_ms
    return words


def _apply_subtitle_edits(words: list[DraftWord], edits) -> list[DraftWord | Caption]:
    if not isinstance(edits, list):
        raise ValueError("edits должен быть списком.")
    positions = {word.id: index for index, word in enumerate(words)}
    result = []
    cursor = 0
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"word_ids", "text"}:
            raise ValueError("У правки должны быть только word_ids и text.")
        ids, text = edit["word_ids"], edit["text"]
        if not isinstance(ids, list) or not ids or not (text == "" or _text_line(text)):
            raise ValueError("Правка требует список ID и строку text.")
        indexes = [positions[word_id] for word_id in ids]
        first, last = indexes[0], indexes[-1]
        if first < cursor or indexes != list(range(first, last + 1)) or words[first].segment != words[last].segment:
            raise ValueError("Правка должна охватывать соседние слова одного отрезка без пересечений и по порядку.")
        result.extend(words[cursor:first])
        if text:
            word = words[first]
            if first == last and len(text.split()) == len(word.text.split()) == 1:
                result.append(replace(word, text=text.strip()))
            else:
                lines = wrap(text, width=24, break_long_words=False, break_on_hyphens=False)
                if len(lines) > 2:
                    raise ValueError("Фраза правки должна помещаться в две строки.")
                result.append(Caption(word.start_ms, words[last].end_ms, tuple(lines)))
        cursor = last + 1
    result.extend(words[cursor:])
    return result


def _read_subtitle_review(plan: EditPlan, paths: SubtitleReview) -> tuple[list[DraftWord | Caption], dict]:
    draft_raw = paths.draft.read_bytes()
    edits_raw = paths.edits.read_bytes()
    draft_sha256 = hashlib.sha256(draft_raw).hexdigest()
    try:
        draft, edits = json.loads(draft_raw), json.loads(edits_raw)
        if type(draft["schema_version"]) is not int or any(draft[key] != value for key, value in _draft_context(plan).items()):
            raise ValueError("Черновик относится к другому клипу или набору отрезков.")
        if type(edits["schema_version"]) is not int or edits["schema_version"] != 1 or edits["draft_sha256"] != draft_sha256:
            raise ValueError("Правки должны ссылаться на SHA-256 этого черновика и иметь schema_version 1.")
        words = _read_draft_words(draft["words"], plan.ends_ms)
        reviewed = _apply_subtitle_edits(words, edits["edits"])
    except (KeyError, TypeError, ValueError) as error:
        raise SlicingError(f"Некорректная вычитка {paths.draft.name} / {paths.edits.name}. {error}") from None
    return reviewed, {
        "draft": paths.draft.name, "draft_sha256": draft_sha256,
        "edits": paths.edits.name, "edits_sha256": hashlib.sha256(edits_raw).hexdigest(),
    }


def _ass_time(centiseconds: int) -> str:
    seconds, fraction = divmod(centiseconds, 100)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _ass_text(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "（").replace("}", "）")


def _correct_spelling(words: list[Cue], spelling: SubtitleSpelling, first_segment_end: float) -> list[Cue]:
    corrected = []
    for word in words:
        token = re.match(r"(\w+)(.*)", word.text)
        if not token:
            corrected.append(word)
            continue
        stem, suffix = token.groups()
        key = stem.casefold()
        name = None
        if corrected and word.start < first_segment_end and word.start - corrected[-1].end < 0.1:
            name = spelling.first_segment_joins.get(f"{corrected[-1].text.casefold()} {key}")
        if name:
            # Whisper sometimes splits one team name into two tokens.
            corrected[-1] = Cue(corrected[-1].start, word.end, name + suffix)
        else:
            corrected.append(replace(word, text=spelling.replacements.get(key, stem) + suffix))
    return corrected


def _timed_phrases(words: list[Cue], ends_ms: list[int], *, split_clauses: bool = False):
    # ASS uses centiseconds. Stop a word that straddles a cut at that cut.
    bounds = [round(end / 10) for end in ends_ms]
    phrase = []
    previous_end = 0
    for word in sorted(words, key=lambda cue: cue.start):
        start = max(0, previous_end, round(word.start * 100))
        part = bisect_right(bounds, start)
        if part == len(bounds):
            break
        end = min(bounds[part], round(word.end * 100))
        if end <= start:
            continue
        if phrase and (
            len(phrase) == 5 or part != phrase[-1][3] or start - previous_end > 48
            or phrase[-1][2].endswith((".", "!", "?"))
            or (split_clauses and len(phrase) > 1 and phrase[-1][2].endswith(","))
        ):
            yield phrase
            phrase = []
        phrase.append((start, end, _ass_text(word.text), part))
        previous_end = end
    if phrase:
        yield phrase


def _lines(phrase, max_chars=24):
    # Wrap on word boundaries and split a long group into more captions if needed.
    lines = [[]]
    length = 0
    for word in phrase:
        width = len(word[2])
        if lines[-1] and length + 1 + width > max_chars:
            if len(lines) == 2:
                yield lines
                lines = [[]]
            else:
                lines.append([])
            length = 0
        length += width + bool(lines[-1])
        lines[-1].append(word)
    yield lines


def _merge_short_phrases(phrases, max_chars):
    pending = []
    for phrase in phrases:
        if pending:
            short = min(pending[-1][1] - pending[0][0], phrase[-1][1] - phrase[0][0]) < 40
            if short and pending[-1][3] == phrase[0][3] and phrase[0][0] - pending[-1][1] <= 28:
                combined = pending + phrase
                if len(list(_lines(combined, max_chars))) == 1:
                    pending = combined
                    continue
            yield pending
        pending = phrase
    if pending:
        yield pending


def make_ass(
    words: list[Cue], ends_ms: list[int], header: Header | None = None, segments: tuple[Segment, ...] = (),
    *, reviewed: list[DraftWord | Caption] | None = None, subtitle_safe_area: bool = False,
    safe_area: Rect | None = None,
) -> str:
    # Bottom-center alignment leaves room for the outline below y=800.
    speech_placement = "2,32,148,480" if subtitle_safe_area else "8,32,32,1038"
    speech_size, question_size, max_chars = 46, 40, 24
    question_placement, label_placement = "8,32,32,88", "8,32,32,47"
    if safe_area is not None:
        x, y, w, h = safe_area
        left, right = x + 8, WIDTH - x - w + 8
        speech_placement = f"2,{left},{right},{HEIGHT - y - h + 18}"
        question_placement = f"8,{left},{right},{y + 36}"
        label_placement = f"8,{left},{right},{y + 7}"
        speech_size, question_size = 42, 36
        max_chars = min(24, (w - 18) // 22)
    styles = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Speech,Arial,{speech_size},&H00FFFFFF,&H000000FF,&H00101824,&H70000000,-1,0,0,0,100,100,0,0,1,3.5,1,{speech_placement},1
Style: Question,Arial,{question_size},&H00FFFFFF,&H000000FF,&H00101824,&H70000000,-1,0,0,0,100,100,0,0,1,0,0,{question_placement},1
Style: Label,Arial,23,&H00E8BE85,&H000000FF,&H00101824,&H70000000,-1,0,0,0,100,100,2,0,1,0,0,{label_placement},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []

    def add(start, end, style, text):
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{text}")

    if header is not None:
        end = round(ends_ms[-1] / 10)
        add(0, end, "Label", _ass_text(header.label))
        add(0, end, "Question", r"\N".join(map(_ass_text, header.lines)))

    output_start = 0
    for segment, output_end in zip(segments, ends_ms):
        shift = output_start - segment.start_ms
        for caption in segment.captions or ():
            start = round((caption.start_ms + shift) / 10)
            end = round((caption.end_ms + shift) / 10)
            if end > start:
                add(start, end, "Speech", r"\N".join(map(_ass_text, caption.lines)))
        output_start = output_end

    def add_words(batch: list[Cue], plain=frozenset()) -> None:
        phrases = _timed_phrases(batch, ends_ms, split_clauses=safe_area is not None)
        if safe_area is not None:
            phrases = _merge_short_phrases(phrases, max_chars)
        for phrase in phrases:
            for lines in _lines(phrase, max_chars):
                flat = [word for line in lines for word in line]
                for index, word in enumerate(flat):
                    start, end, _, _ = word
                    highlighted = r"\N".join(
                        " ".join(r"{\1c&H38DDFF&}" + token[2] + r"{\1c}"
                                 if token is word and (start, end) not in plain else token[2] for token in line)
                        for line in lines
                    )
                    add(start, end, "Speech", highlighted)
                    if index + 1 < len(flat) and end < flat[index + 1][0]:
                        neutral = r"\N".join(" ".join(token[2] for token in line) for line in lines)
                        add(end, flat[index + 1][0], "Speech", neutral)

    if reviewed is None:
        add_words(words)
    else:
        batch = []
        plain = set()
        for item in reviewed:
            # Round inward so ASS centiseconds cannot cross a millisecond cut.
            start, end = (item.start_ms + 9) // 10, item.end_ms // 10
            if isinstance(item, Caption):
                text = " ".join(item.lines)
                if safe_area is not None and end > start and len(text) <= max_chars:
                    batch.append(Cue(start / 100, end / 100, text))
                    plain.add((start, end))
                    continue
                add_words(batch, plain)
                batch.clear()
                plain.clear()
                if end > start:
                    add(start, end, "Speech", r"\N".join(map(_ass_text, item.lines)))
            elif end > start:
                batch.append(Cue(start / 100, end / 100, item.text))
        add_words(batch, plain)
    return styles + "\n".join(events) + "\n"


def _header_box(safe_area: Rect | None) -> Rect:
    return (24, 38, 672, 157) if safe_area is None else (*safe_area[:3], 126)


def _tile_sets(size: tuple[int, int]) -> tuple[tuple[auto.Tile, ...], ...]:
    def tiles(*rects):
        return tuple(auto.Tile(rect, _output_rect(rect, size)) for rect in rects)

    return (
        tiles((0, 0, WIDTH, HEIGHT)),
        *(tiles((0, 0, WIDTH, y), (0, y, WIDTH, HEIGHT - y)) for y in range(384, 897, 32)),
        *(tiles((0, 0, x, HEIGHT), (x, 0, WIDTH - x, HEIGHT)) for x in range(288, 433, 36)),
    )


def _reaction_tiles(size: tuple[int, int]) -> tuple[auto.Tile, ...]:
    return tuple(auto.Tile(rect, _output_rect(rect, size)) for rect in (
        (52, 752, 248, 248), (300, 752, 248, 248),
        (52, 800, 224, 208), (320, 800, 224, 208),
        (52, 680, 224, 208), (320, 680, 224, 208),
        (52, 866, 154, 154), (378, 866, 154, 154),
    ))


def _read_ass_time(value: str) -> int:
    hours, minutes, seconds, fraction = map(int, re.split(r"[:.]", value))
    return ((hours * 60 + minutes) * 60 + seconds) * 100 + fraction


def _position(anchor: tuple[int, int]) -> str:
    return rf"{{\an2\pos({anchor[0]},{anchor[1]})}}"


_PROBE_ANCHOR = (WIDTH // 2, HEIGHT // 2)


def _measure_ass(media: Media, work: Path, size: tuple[int, int], styles: list[str],
                 frames: list[list[list[str]]]) -> dict[int, Rect]:
    if not frames:
        return {}
    events = []
    for index, rows in enumerate(frames):
        for row in rows:
            fields = row.copy()
            fields[1:3] = [_ass_time(100 * index), _ass_time(100 * (index + 1))]
            events.append(",".join(fields))
    (work / "layout_probe.ass").write_text("\n".join(styles + events) + "\n", encoding="utf-8")
    w, h = size
    # Paint the same libass styles at the actual export size and detect every
    # changed luma pixel, including the dark outline on a flat mid-gray field.
    raw = _run(media.ffmpeg, [
        "-v", "error", "-nostdin", "-filter_threads", "1", "-f", "lavfi",
        "-i", f"color=s={w}x{h}:r=1,format=yuv420p,lutyuv=y=128",
        "-vf", "subtitles=layout_probe.ass,lutyuv=y='255*(1-eq(val,128))',bbox=min_val=1,metadata=mode=print:file=-",
        "-frames:v", str(len(frames)), "-f", "null", "-",
    ], cwd=work).decode("ascii")
    result = {}
    for match in re.finditer(
        r"frame:(\d+)[^\n]*\s+lavfi\.bbox\.x1=(\d+)\s+lavfi\.bbox\.x2=(\d+)"
        r"\s+lavfi\.bbox\.y1=(\d+)\s+lavfi\.bbox\.y2=(\d+)", raw,
    ):
        number, left, right, top, bottom = map(int, match.groups())
        if number < len(frames):
            result[number] = left, top, right - left + 1, bottom - top + 1
    return result


def _text_slots(probes: list[tuple[auto.Interval, Rect]], fixed: tuple[auto.Obstacle, ...],
                safe: Rect, size: tuple[int, int], ui: tuple[auto.Obstacle, ...]) -> tuple[auto.TextSlot, ...]:
    if not probes:
        return (auto.TextSlot(None, fixed),)
    w, h = size
    if any(x <= 0 or y <= 0 or x + bw >= w or y + bh >= h for _, (x, y, bw, bh) in probes):
        return ()  # The probe itself clipped the text.
    _, top, _, bh = auto.bounds(box for _, box in probes)
    x, y, width, height = safe
    y_min = _PROBE_ANCHOR[1] + ceil((y * h / HEIGHT - top + 2) * HEIGHT / h)
    y_max = _PROBE_ANCHOR[1] + floor(((y + height) * h / HEIGHT - top - bh - 2) * HEIGHT / h)
    anchors_y = dict.fromkeys([*range(y_max, y_min - 1, -32), y_min]) if y_max >= y_min else {}
    anchors_x = dict.fromkeys((x + width // 2, WIDTH // 2, x + width // 2 - 44, x + width // 2 + 44))
    slots = []
    for ay in anchors_y:
        for ax in anchors_x:
            # Extra pixels cover sub-pixel rasterisation after repositioning.
            dx = round((ax - _PROBE_ANCHOR[0]) * w / WIDTH)
            dy = round((ay - _PROBE_ANCHOR[1]) * h / HEIGHT)
            speech = tuple(auto.Obstacle("subtitles", (sx + dx - 2, sy + dy - 2, sw + 4, sh + 4), interval)
                           for interval, (sx, sy, sw, sh) in probes)
            if all(auto.contains((0, 0, w, h), cue.box) and
                   not any(auto.overlaps(cue.box, obstacle.box) for obstacle in ui + fixed) for cue in speech):
                slots.append(auto.TextSlot((ax, ay), fixed + speech))
    return tuple(slots)


def _layout_issues(segment: Segment, layout: auto.Layout | None, obstacles: tuple[auto.Obstacle, ...],
                   reason: str) -> list[dict]:
    if layout is None:
        return [
            {"object": region.name, "interval_ms": (segment.start_ms, segment.end_ms),
             "source_box": region.envelope, "reason": reason}
            for region in segment.regions if region.required
        ]
    hits = {}
    for panel in layout.panels:
        for region in panel.regions:
            for part in region.track:
                box = auto.project(part.box, panel.crop, panel.tile.output)
                for obstacle in obstacles:
                    if auto.conflict(part, obstacle) and auto.overlaps(box, obstacle.box):
                        start, end = obstacle.interval or part.interval
                        hits.setdefault((region.name, obstacle.object, obstacle.platform), []).append(
                            (max(start, part.interval[0]), min(end, part.interval[1]))
                        )
    issues = []
    for (name, blocked_by, platform), intervals in hits.items():
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(merged[-1][1], end)
            else:
                merged.append((start, end))
        issues.extend({
            "object": name, "interval_ms": interval, "reason": reason, "blocked_by": blocked_by,
            **({"platform": platform} if platform else {}),
        } for interval in merged)
    return issues


def _layout_entry(segment: Segment, layout: auto.Layout, ui: tuple[auto.Obstacle, ...]) -> dict:
    regions = []
    for region in segment.regions:
        panel = next((panel for panel in layout.panels
                      if region in panel.regions or region.name in panel.secondary), None)
        if panel is None:
            panel = next((panel for panel in layout.panels if auto.contains(panel.crop, region.envelope)), None)
        parts = []
        for part in region.track:
            entry = {"source_interval_ms": part.interval, "source_box": part.box}
            if panel is not None:
                box = auto.project(part.box, panel.crop, panel.tile.output)
                entry.update(output_box=box, ui_overlaps=[
                    {"platform": obstacle.platform, "element": obstacle.object} for obstacle in ui
                    if auto.overlaps(box, obstacle.box)
                ], overlay_overlaps=sorted({obstacle.object for obstacle in layout.speech.obstacles
                    if auto.conflict(part, obstacle) and auto.overlaps(box, obstacle.box)}))
            parts.append(entry)
        regions.append({
            "name": region.name, "priority": "required" if region.required else "secondary",
            "fully_in_crop": panel is not None, "track": parts,
        })
    result = {
        "status": "ok", "mode": "single_crop" if len(layout.panels) == 1 else "two_panels",
        "panels": [
            {"crop": panel.crop, "place": panel.tile.place, "output_place": panel.tile.output,
             "distinct_required_regions": [region.name for region in panel.regions],
             "visible_secondary_regions": sorted(panel.secondary)}
            for panel in layout.panels
        ],
        "regions": regions, "subtitle_anchor_720x1280": layout.speech.anchor,
        "overlays": [asdict(item) for item in layout.speech.obstacles],
    }
    if segment.speaker_turns:
        turn = segment.speaker_turns[0]
        main = layout.panels[0]
        face = next(region for region in main.regions if region.speaker == turn.speaker)
        centers = []
        for part in face.track:
            x, y, w, h = auto.project(part.box, main.crop, main.tile.output)
            cx = (x + w / 2) * 100 / main.tile.output[2]
            cy = (y + h / 2) * 100 / main.tile.output[3]
            centers.append({"source_interval_ms": part.interval, "center_percent": [round(cx, 2), round(cy, 2)]})
        result.update(active_speaker=turn.speaker, reaction_speaker=turn.reaction, layered=len(layout.panels) > 1,
                      face_centers=centers, face_center_zone_percent=auto.SPEAKER_ZONE,
                      face_center_in_zone=all(lo <= value <= hi for part in centers
                                             for value, (lo, hi) in zip(part["center_percent"], auto.SPEAKER_ZONE)))
    return result


def _speaker_picture(plan: EditPlan) -> tuple[EditPlan, set[int]]:
    """Split the video after audio and speech events have been built."""
    if not any(segment.speaker_turns for segment in plan.segments):
        return plan, set()
    picture, cuts = [], set()
    position = 0
    for segment in plan.segments:
        if not segment.speaker_turns:
            picture.append(segment)
            position += segment.length_ms
            continue
        for number, turn in enumerate(segment.speaker_turns):
            start, end = turn.interval
            if number:
                cuts.add(position)
            regions = []
            for region in segment.regions:
                track = tuple(auto.TimedBox((max(start, lo), min(end, hi)), part.box)
                              for part in region.track for lo, hi in (part.interval,)
                              if max(start, lo) < min(end, hi))
                required = region.required if region.speaker is None else region.speaker in (turn.speaker, turn.reaction)
                regions.append(replace(region, track=track, required=required))
            picture.append(replace(segment, start_ms=start, end_ms=end, captions=None,
                                   regions=tuple(regions), speaker_turns=(turn,)))
            position += end - start
    return replace(plan, segments=picture), cuts


def _split_picture_cues(events, cuts):
    # The same text and highlight continue when a picture cut falls inside an ASS event.
    for row in events:
        if row[3] != "Speech":
            yield row
            continue
        start, end = map(_read_ass_time, row[1:3])
        bounds = [start, *(cut for cut in cuts if start < cut < end), end]
        for a, b in zip(bounds, bounds[1:]):
            yield [row[0], _ass_time(a), _ass_time(b), *row[3:]]


def _video_frame(milliseconds):
    return (milliseconds * FPS + 500) // 1000


def _resolve_layout(plan: EditPlan, ass: str, media: Media, work: Path) -> tuple[EditPlan, str, dict]:
    plan, picture_cuts = _speaker_picture(plan)
    ui = plan.profiles.obstacles
    lines = ass.splitlines()
    events = [line.split(",", 9) for line in lines if line.startswith("Dialogue:")]
    styles = [line for line in lines if not line.startswith("Dialogue:")]
    headings = [row for row in events if row[3] in ("Label", "Question")]
    probes = [headings] if headings else []
    keys = {}
    scene_cues = [[] for _ in plan.segments]
    bounds = [0, *plan.ends_ms]
    cuts = [_video_frame(end) * 100 // FPS if end in picture_cuts else round(end / 10) for end in bounds]
    if picture_cuts:
        events = list(_split_picture_cues(events, sorted({_video_frame(ms) * 100 // FPS for ms in picture_cuts})))
    for index, row in enumerate(events):
        if row[3] != "Speech":
            continue
        start, end = map(_read_ass_time, row[1:3])
        scene = bisect_right(cuts, start) - 1
        if scene >= len(plan.segments) or not plan.segments[scene].regions:
            continue
        segment = plan.segments[scene]
        first_frame, after_frame = map(_video_frame, bounds[scene:scene + 2])
        start = max(start, (first_frame - 1) * 100 // FPS + 1)
        end = min(end, after_frame * 100 // FPS)
        if start >= end:
            events[index] = None
            continue
        row[1:3] = [_ass_time(start), _ass_time(end)]
        clean = re.sub(r"\{\\1c(?:&H[0-9A-F]+&)?\}", "", row[9])
        if clean not in keys:
            sample = row.copy()
            sample[9] = _position(_PROBE_ANCHOR) + clean
            keys[clean] = len(probes)
            probes.append([sample])
        # Video cuts quantise to frames. Widen the protection interval for the
        # adjacent source samples and keep it within the annotated scene.
        shift = segment.start_ms - bounds[scene]
        guard = ceil(1000 / FPS) + 1
        interval = (max(segment.start_ms, start * 10 + shift - guard),
                    min(segment.end_ms, end * 10 + shift + guard))
        scene_cues[scene].append((index, keys[clean], interval))
    measured = _measure_ass(media, work, plan.export_size, styles, probes)
    header = ()
    if headings:
        header = (auto.Obstacle("header_box", _output_rect(_header_box(plan.safe_area), plan.export_size)),)
        if 0 in measured:
            header += (auto.Obstacle("header_text", measured[0]),)
    tile_sets = _tile_sets(plan.export_size)
    insets = _reaction_tiles(plan.export_size)
    segments = list(plan.segments)
    entries, failures = {}, []
    for index, segment in enumerate(segments):
        if not segment.regions:
            continue
        interval = (segment.start_ms, segment.end_ms)
        fixed = header + tuple(auto.Obstacle("mask", _output_rect(mask, plan.export_size, cover=True))
                               for mask in segment.masks)
        issues = [
            {"object": "header", "interval_ms": interval, "reason": "overlay_ui",
             "platform": zone.platform, "blocked_by": zone.object}
            for item in header for zone in ui if auto.overlaps(item.box, zone.box)
        ]
        cues = scene_cues[index]
        slots = ()
        if not issues and all(number in measured for _, number, _ in cues):
            slots = _text_slots([(time, measured[number]) for _, number, time in cues],
                                fixed, plan.safe_area, plan.export_size, ui)
        if not slots and not issues:
            issues = [{"object": "subtitles", "interval_ms": interval, "reason": "no_safe_text_position"}]
        if not issues:
            turn = segment.speaker_turns[0] if segment.speaker_turns else None
            if turn is not None:
                layout = auto.solve_speaker(segment.regions, turn, plan.source_size, tile_sets[0][0], insets, ui, slots)
            else:
                layout = auto.solve(segment.regions, plan.source_size, tile_sets, ui, slots)
            if layout is not None:
                segments[index] = replace(segment, panels=tuple(Panel(p.crop, p.tile.place) for p in layout.panels),
                                          layered=turn is not None and len(layout.panels) > 1)
                for row, _, _ in cues:
                    events[row][9] = _position(layout.speech.anchor) + events[row][9]
                entries[index] = _layout_entry(segment, layout, ui)
                continue
            if turn is not None:
                face = next(region for region in segment.regions if region.speaker == turn.speaker)
                failures.append({"scene": index + 1, "source_interval_ms": interval, "issues": [
                    {"object": face.name, "interval_ms": interval, "source_box": face.envelope,
                     "speaker": turn.speaker, "reaction": turn.reaction, "reason": "no_clear_speaker_layout"},
                ]})
                continue
            repeated = auto.solve(segment.regions, plan.source_size, tile_sets, ui, slots, allow_duplicates=True)
            if repeated is not None:
                issues = [
                    {"object": region.name, "interval_ms": part.interval, "source_box": part.box,
                     "reason": "duplicate_required_region", "panel": panel, "also_in_panel": other}
                    for region, part, panel, other in auto.duplicated_regions(repeated)
                ]
            else:
                clear = (auto.TextSlot(None),)
                without_text = auto.solve(segment.regions, plan.source_size, tile_sets, ui, clear, allow_duplicates=True)
                if without_text is not None:
                    issues = _layout_issues(segment, without_text, slots[0].obstacles, "overlay_overlap")
                else:
                    geometric = auto.solve(segment.regions, plan.source_size, tile_sets, (), clear, allow_duplicates=True)
                    issues = _layout_issues(segment, geometric, ui, "ui_overlap" if geometric else "cannot_fit_edges")
        failures.append({"scene": index + 1, "source_interval_ms": interval, "issues": issues})
    if failures:
        raise SlicingError(json.dumps({"status": "needs_review", "clip": plan.clip_id, "scenes": failures},
                                      ensure_ascii=False))
    ass = "\n".join(styles + [",".join(row) for row in events if row is not None]) + "\n"
    return replace(plan, segments=segments), ass, entries


def _portrait(
    index: int, segment: Segment, frames: int, has_header: bool, safe_area: Rect | None = None,
    export_size: tuple[int, int] = (WIDTH, HEIGHT),
) -> list[str]:
    timing = (
        f"trim=duration={_seconds(segment.length_ms)},setpts=PTS-STARTPTS,fps={FPS}:start_time=0,"
        f"tpad=stop_mode=clone:stop_duration=0.067,trim=end_frame={frames}"
    )
    panels = segment.panels
    out_w, out_h = export_size
    masks = (_output_rect(rect, export_size, cover=True) for rect in segment.masks)
    overlays = "".join(f",drawbox={x}:{y}:{w}:{h}:{BACKGROUND}:fill" for x, y, w, h in masks)
    if has_header:
        header = _header_box(safe_area)
        x, y, w, h = _output_rect(header, export_size)
        overlays += f",drawbox={x}:{y}:{w}:{h}:0x17294C:fill"
    if not panels:
        return [(
            f"[{index}:v:0]{timing},scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:"
            f"force_divisible_by=2,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:{BACKGROUND},setsar=1{overlays}[v{index}]"
        )]

    labels = "".join(f"[s{index}_{panel}]" for panel in range(len(panels)))
    split = f",split={len(panels)}" if len(panels) > 1 else ""
    filters = [f"[{index}:v:0]{timing}{split}{labels}"]
    positions = []
    labels = []
    for number, panel in enumerate(panels):
        x, y, w, h = panel.crop
        left, top, width, height = _output_rect(panel.place, export_size)
        label = f"[p{index}_{number}]"
        preview_height = 128 if segment.layered and number == 0 else 46
        soften = (
            f"scale=72:{preview_height}:flags=area,gblur=sigma=5:steps=2,eq=brightness=-0.12:saturation=0.75,"
            if panel.ambient else ""
        )
        filters.append(f"[s{index}_{number}]crop={w}:{h}:{x}:{y},{soften}scale={width}:{height}:flags=lanczos,setsar=1{label}")
        labels.append(label)
        positions.append((left, top))
    if segment.layered:
        base = labels[0]
        for number, (label, (left, top)) in enumerate(zip(labels[1:], positions[1:]), 1):
            next_base = f"[l{index}_{number}]"
            filters.append(f"{base}{label}overlay={left}:{top}:shortest=1{next_base}")
            base = next_base
        filters.append(f"{base}null{overlays}[v{index}]")
        return filters
    inputs = "".join(labels)
    if len(panels) > 1:
        layout = "|".join(f"{left}_{top}" for left, top in positions)
        inputs += f"xstack=inputs={len(panels)}:layout={layout}:fill={BACKGROUND},"
        left, top = 0, 0
    else:
        left, top = positions[0]
    filters.append(f"{inputs}pad={out_w}:{out_h}:{left}:{top}:{BACKGROUND}{overlays}[v{index}]")
    return filters


def _music_mix(voice: int, end_ms: int) -> str:
    fade_ms = min(850, end_ms)
    return (
        f"[{voice}:a:0]asplit=2[voice][key];"
        f"[{voice + 1}:a:0]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
        f"atrim=duration={_seconds(end_ms)},volume=0.13,"
        f"afade=t=out:st={_seconds(end_ms - fade_ms)}:d={_seconds(fade_ms)}[bed];"
        "[bed][key]sidechaincompress=threshold=0.025:ratio=7:attack=12:release=230[ducked];"
        "[voice][ducked]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.95:level=false:latency=true[audio]"
    )


def _encode(media: Media, plan: EditPlan, audio: Path, out: Path, music: Path | None) -> list[dict]:
    filters = []
    entries = []
    start_ms = start_frame = 0
    for index, (segment, end_ms) in enumerate(zip(plan.segments, plan.ends_ms)):
        end_frame = _video_frame(end_ms)
        if end_frame <= start_frame:
            raise SlicingError(f"Отрезок {index + 1} слишком короткий для {FPS} кадров/с.")
        filters.extend(_portrait(index, segment, end_frame - start_frame, plan.header is not None,
                                 plan.safe_area, plan.export_size))
        entries.append({
            "source_start_ms": segment.start_ms, "source_end_ms": segment.end_ms,
            "output_start_ms": start_ms, "output_end_ms": end_ms,
            "video_start_frame": start_frame, "video_end_frame": end_frame, "framing": segment.framing,
        })
        if segment.masks:
            entries[-1]["masks"] = [_output_rect(rect, plan.export_size, cover=True) for rect in segment.masks]
        start_ms, start_frame = end_ms, end_frame

    inputs = "".join(f"[v{index}]" for index in range(len(entries)))
    # libass scales the reference PlayRes, including font sizes and outlines, to the canvas.
    filters.append(
        f"{inputs}concat=n={len(entries)}:v=1:a=0,settb=1/{FPS},setpts=N,setsar=1,"
        f"subtitles={plan.clip_id}.ass[video]"
    )
    audio_input = len(entries)
    music_args = []
    audio_map = f"{audio_input}:a:0"
    if music is not None:
        music_args = ["-stream_loop", "-1", "-i", str(music)]
        filters.append(_music_mix(audio_input, start_ms))
        audio_map = "[audio]"
    _run(media.ffmpeg, [
        "-hide_banner", "-v", "error", "-nostdin", "-n", "-filter_complex_threads", "2",
        *_inputs(plan), "-i", str(audio), *music_args, "-filter_complex", ";".join(filters),
        "-map", "[video]", "-map", audio_map, "-c:v", "libx264", "-preset", "fast", "-crf", "19",
        "-r", str(FPS), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-map_metadata", "-1", f"{plan.clip_id}.mp4",
    ], cwd=out)
    return entries


def render_plan(
    path: Path, clip_id: str, music: Path | None, root: Path, media: Media, *, work_directory: Path | None = None,
) -> Path:
    plan = load_plan(path, clip_id, root, media)
    if music is not None:
        music = music.resolve()
        if not music.is_file():
            raise SlicingError(f"Локальная дорожка не найдена: {music}.")

    output = root / "data" / "review" / "mvp" / plan.vod_id / clip_id
    if output.exists():
        raise SlicingError(f"Клип уже существует: {output}.")
    reviewed = review_manifest = None
    if plan.subtitle_review is not None:
        reviewed, review_manifest = _read_subtitle_review(plan, plan.subtitle_review)
    elif plan.profiles is not None and plan.segments[0].captions is None:
        raise SlicingError("Для автокомпоновки укажите сохранённый subtitle_review или captions у каждого отрезка.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{clip_id}-", dir=work_directory or output.parent) as temporary:
        work = Path(temporary)
        audio = work / "joined.wav"
        stage = work / "publish"
        stage.mkdir()
        print(f"{clip_id}: склеиваю звук по плану ({_seconds(plan.ends_ms[-1])} с).", flush=True)
        _join_audio(media, plan, audio)
        audio_ranges = [(segment.start_ms, segment.end_ms) for segment in plan.segments] if any(
            segment.speaker_turns for segment in plan.segments
        ) else None
        subtitle_source = "whisper"
        words = []
        if reviewed is not None:
            subtitle_source = "review"
        elif plan.segments[0].captions is not None:
            subtitle_source = "plan"
        else:
            print(f"{clip_id}: распознаю слова Whisper по склеенному звуку.", flush=True)
            words = media.transcribe_words(audio)
        captions = words
        if plan.subtitle_spelling is not None:
            captions = _correct_spelling(words, plan.subtitle_spelling, plan.ends_ms[0] / 1000)
        ass = f"{clip_id}.ass"
        ass_text = make_ass(
            captions, plan.ends_ms, plan.header, tuple(plan.segments), reviewed=reviewed,
            subtitle_safe_area=plan.subtitle_safe_area, safe_area=plan.safe_area,
        )
        layouts = {}
        if plan.profiles is not None:
            plan, ass_text, layouts = _resolve_layout(plan, ass_text, media, work)
        (stage / ass).write_text(ass_text, encoding="utf-8")
        width, height = plan.export_size
        print(f"{clip_id}: рендерю {width} × {height} с ASS.", flush=True)
        entries = _encode(media, plan, audio, stage, music)
        for index, layout in layouts.items():
            entries[index]["auto_layout"] = layout
        video = f"{clip_id}.mp4"
        actual_duration = media.duration(stage / video)
        if abs(actual_duration - plan.ends_ms[-1] / 1000) > 1 / FPS:
            raise SlicingError(f"Рендер {clip_id} вышел неверной длительности ({actual_duration:.3f} с).")
        manifest = {
            "vod_id": plan.vod_id, "clip_id": clip_id, "title": plan.title,
            "source": plan.source.relative_to(root).as_posix(), "source_duration_seconds": plan.source_duration,
            "edit_plan_sha256": plan.sha256, "duration_ms": plan.ends_ms[-1],
            "render_duration_seconds": actual_duration, "fps": FPS,
            "export_size": plan.export_size,
            "segments": entries, "video": video, "subtitles": ass,
            "audio": {"speech": "original", "music": music.name if music is not None else None},
            "subtitle_source": subtitle_source,
            "whisper_words": [asdict(word) for word in words],
        }
        if review_manifest is not None:
            manifest["subtitle_review"] = review_manifest
        if audio_ranges is not None:
            manifest["audio"]["source_intervals_ms"] = audio_ranges
        if plan.safe_area is not None:
            manifest["safe_area_px"] = _output_rect(plan.safe_area, plan.export_size)
        if plan.profiles is not None:
            manifest["auto_layout_profiles"] = asdict(plan.profiles)
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        stage.rename(output)
    return output / video
