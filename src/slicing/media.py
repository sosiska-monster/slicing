import io
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import SlicingError

CHUNK_SECONDS = 600


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def timecode(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    total_seconds, ms = divmod(total_ms, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{ms:03d}"


def _run(executable: Path, args: list[str], cwd: Path | None = None) -> bytes:
    try:
        return subprocess.run(
            [str(executable), *args], cwd=cwd, capture_output=True, check=True
        ).stdout
    except subprocess.CalledProcessError as error:
        diagnostic = error.stderr.decode("utf-8", errors="replace").strip()[-600:]
        raise SlicingError(f"{executable.stem}: код {error.returncode}. {diagnostic}") from None


def _segment_cues(segment, offset: int, limit: float):
    words = [
        word for word in (segment.words or [])
        if word.word.strip() and word.start is not None and word.end is not None
    ]
    if not words:
        text = " ".join(segment.text.split())
        if text:
            yield Cue(offset + segment.start, min(limit, offset + segment.end), text)
        return

    line = ""
    start = words[0].start
    end = start
    for word in words:
        token = word.word.strip()
        if line and (len(line) + len(token) > 62 or word.start - end > 0.65):
            yield Cue(offset + start, min(limit, offset + end), line)
            line = ""
            start = word.start
        line = f"{line} {token}" if line else token
        end = word.end
    yield Cue(offset + start, min(limit, offset + end), line)


def _load_whisper():
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        try:
            model_path = download_model("base", local_files_only=True, use_auth_token=False)
        except LocalEntryNotFoundError:
            model_path = download_model("base", use_auth_token=False)
        return WhisperModel(
            model_path, device="cpu", compute_type="int8",
            cpu_threads=min(8, os.cpu_count() or 1),
        )
    except Exception as error:
        raise SlicingError(f"Не удалось подготовить модель Whisper base ({type(error).__name__}).") from None


class Media:
    def __init__(self, ffmpeg: Path, ffprobe: Path):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    @classmethod
    def from_environment(cls):
        ffmpeg = shutil.which(os.environ.get("SLICING_FFMPEG") or "ffmpeg")
        if not ffmpeg:
            raise SlicingError("Укажите путь к полному ffmpeg.exe в SLICING_FFMPEG.")
        executable = Path(ffmpeg).resolve()
        probe = executable.with_name("ffprobe" + executable.suffix)
        if not probe.is_file():
            raise SlicingError("Положите ffprobe.exe рядом с ffmpeg.exe.")
        filters = _run(executable, ["-hide_banner", "-filters"])
        encoders = _run(executable, ["-hide_banner", "-encoders"])
        if not (
            re.search(rb"\bsubtitles\s+V->V", filters)
            and re.search(rb"^\s*[A-Z.]+\s+libx264\s", encoders, re.MULTILINE)
            and re.search(rb"^\s*[A-Z.]+\s+aac\s", encoders, re.MULTILINE)
        ):
            raise SlicingError("Нужна сборка FFmpeg с фильтром subtitles и кодеками libx264 и AAC.")
        return cls(executable, probe)

    def duration(self, source: Path) -> float:
        output = _run(self.ffprobe, [
            "-v", "error", "-show_entries", "format=duration:stream=codec_type",
            "-of", "json", str(source),
        ])
        info = json.loads(output)
        streams = {stream.get("codec_type") for stream in info.get("streams", [])}
        try:
            duration = float(info.get("format", {}).get("duration", 0))
        except (TypeError, ValueError):
            duration = 0
        if not {"video", "audio"} <= streams or not math.isfinite(duration) or duration <= 0:
            raise SlicingError(f"В исходнике нужны видео и звук: {source.name}.")
        return duration

    def transcribe(self, source: Path, duration: float) -> list[Cue]:
        from faster_whisper import BatchedInferencePipeline

        model = BatchedInferencePipeline(_load_whisper())
        cues = []
        for offset in range(0, math.ceil(duration), CHUNK_SECONDS):
            length = min(CHUNK_SECONDS, duration - offset)
            print(f"Распознавание {timecode(offset)} из {timecode(duration)}", flush=True)
            audio = _run(self.ffmpeg, [
                "-v", "error", "-nostdin", "-ss", str(offset), "-i", str(source),
                "-t", f"{length:.3f}", "-map", "0:a:0",
                "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1",
            ])
            segments, _ = model.transcribe(
                io.BytesIO(audio), language="ru", vad_filter=True,
                beam_size=1, word_timestamps=True, batch_size=8,
            )
            for segment in segments:
                cues.extend(_segment_cues(segment, offset, offset + length))
        return sorted((cue for cue in cues if cue.end > cue.start), key=lambda cue: cue.start)

    def transcribe_words(self, audio: Path) -> list[Cue]:
        segments, _ = _load_whisper().transcribe(
            str(audio), language="ru", beam_size=5, word_timestamps=True,
            condition_on_previous_text=False, no_repeat_ngram_size=3,
        )
        return [
            Cue(word.start, word.end, word.word.strip())
            for segment in segments for word in (segment.words or [])
            if word.word.strip() and word.start is not None and word.end is not None
        ]
