import json
import math
import tempfile
from dataclasses import asdict
from pathlib import Path

from . import SlicingError
from .db import VodStore
from .media import Media
from .twitch import CUTOFF, TwitchArchive, Vod


def run_one(store: VodStore, twitch: TwitchArchive, media: Media, data: Path) -> Path | None:
    data = data.resolve()
    vod_dir = data / "vods"
    records = store.records()
    prepared = {record.vod.twitch_id for record in records if record.status != "downloaded"}
    for record in records:
        if (
            record.status == "downloaded"
            and record.vod.published_at >= CUTOFF
            and record.path.resolve().is_relative_to(vod_dir)
            and record.path.is_file()
        ):
            vod_id = record.vod.twitch_id
            duration = media.duration(record.path)
            output = data / "review" / f"transcript_{vod_id}.json"
            if _has_transcript(output, vod_id, duration):
                prepared.add(vod_id)
                continue
            print(f"VOD {vod_id}: использую исходник {record.path}", flush=True)
            return _export(media, record.vod, record.path, duration, output)

    print("Проверяю публичные архивы evelone2004", flush=True)
    for vod in twitch.public_vods(prepared):
        print(f"VOD {vod.twitch_id} опубликован {vod.published_at.isoformat()} — {vod.url}", flush=True)
        vod_dir.mkdir(parents=True, exist_ok=True)
        source = vod_dir / f"{vod.twitch_id}.mp4"
        if source.is_file():
            print(f"VOD {vod.twitch_id}: использую исходник {source}", flush=True)
            duration = media.duration(source)
        else:
            stage = vod_dir / f".{vod.twitch_id}.download.mp4"
            if not twitch.download(vod, stage):
                print(f"VOD {vod.twitch_id} больше недоступен", flush=True)
                continue
            duration = media.duration(stage)
            stage.rename(source)
        store.save_download(vod, source)
        print(f"VOD {vod.twitch_id}: downloaded, файл {source}", flush=True)
        output = data / "review" / f"transcript_{vod.twitch_id}.json"
        if not _has_transcript(output, vod.twitch_id, duration):
            return _export(media, vod, source, duration, output)

    print("Подходящих VOD без расшифровки нет.", flush=True)
    return None


def _has_transcript(output: Path, vod_id: str, duration: float) -> bool:
    if not output.exists():
        return False
    try:
        document = json.loads(output.read_text(encoding="utf-8"))
        cues = document["cues"]
        if (
            document["vod_id"] == vod_id
            and math.isclose(document["duration_seconds"], duration, rel_tol=0, abs_tol=0.001)
            and isinstance(cues, list)
            and all(
                type(cue["start"]) in (int, float) and type(cue["end"]) in (int, float)
                and 0 <= cue["start"] < cue["end"] <= duration
                and isinstance(cue["text"], str)
                for cue in cues
            )
        ):
            return True
    except (ValueError, KeyError, TypeError, OverflowError):
        pass
    raise SlicingError(f"Расшифровка {output} не соответствует исходнику. Проверьте файл.")


def _export(media: Media, vod: Vod, source: Path, duration: float, output: Path) -> Path:
    cues = media.transcribe(source, duration)
    document = {
        "vod_id": vod.twitch_id, "duration_seconds": duration, "cues": [asdict(cue) for cue in cues],
    }
    staging = output.parent / "mvp"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".transcript-", dir=staging) as temporary:
        stage = Path(temporary) / output.name
        stage.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage.rename(output)
    print(f"VOD {vod.twitch_id}: {len(cues)} реплик, {output}", flush=True)
    return output
