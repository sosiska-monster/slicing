import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import SlicingError

CHANNEL = "evelone2004"
ARCHIVES_URL = f"https://www.twitch.tv/{CHANNEL}/videos?filter=archives&sort=time"
CUTOFF = datetime(2026, 7, 11, tzinfo=timezone(timedelta(hours=3)))
DOWNLOAD_FORMAT = "b[ext=mp4][height<=480]/b[ext=mp4]"


@dataclass(frozen=True)
class Vod:
    twitch_id: str
    published_at: datetime

    @property
    def url(self) -> str:
        return f"https://www.twitch.tv/videos/{self.twitch_id}"


class _QuietLog:
    def debug(self, message):
        pass

    warning = debug
    error = debug


def _unavailable(error) -> bool:
    message = str(error).lower()
    return any(
        marker in message
        for marker in (
            "does not exist",
            "subscriber-only",
            "vod_manifest_restricted",
            "unauthorized_entitlements",
            "http error 404",
            "http error 410",
            "requested format is not available",
        )
    )


def _network_error(action: str, error) -> SlicingError:
    # yt-dlp diagnostics may include signed playback URLs.
    message = str(error)
    http = re.search(r"HTTP Error \d{3}", message)
    detail = f" ({http.group(0)})" if http else ""
    if not http and "proxy" in message.lower():
        detail = " (ошибка подключения к прокси)"
    return SlicingError(f"Twitch: не удалось {action}{detail}.")


class TwitchArchive:
    def __init__(self, ffmpeg: Path | None = None):
        self.ffmpeg = ffmpeg

    def _open(self, **options):
        from yt_dlp import YoutubeDL

        defaults = {
            "logger": _QuietLog(),
            "quiet": True,
            "noprogress": True,
            "cachedir": False,
            "socket_timeout": 20,
            "retries": 2,
            "fragment_retries": 3,
        }
        if self.ffmpeg is not None:
            defaults["ffmpeg_location"] = str(self.ffmpeg)
        return YoutubeDL(defaults | options)

    def public_vods(self, excluded: set[str] | None = None) -> list[Vod]:
        from yt_dlp.utils import DownloadError

        seen = set(excluded or ())
        try:
            with self._open(extract_flat="in_playlist") as ydl:
                playlist = ydl.extract_info(ARCHIVES_URL, download=False)
        except DownloadError as error:
            raise _network_error("получить список архивов", error) from None
        if not playlist or "entries" not in playlist:
            raise SlicingError("Twitch: ответ не содержит списка архивов.")

        candidates = []
        with self._open(format=DOWNLOAD_FORMAT) as ydl:
            for entry in playlist["entries"]:
                # The flat archive listing provides IDs but no publication dates.
                twitch_id = str((entry or {}).get("id", "")).removeprefix("v")
                if not re.fullmatch(r"[0-9]+", twitch_id) or twitch_id in seen:
                    continue
                seen.add(twitch_id)
                url = f"https://www.twitch.tv/videos/{twitch_id}"
                try:
                    info = ydl.extract_info(url, download=False)
                except DownloadError as error:
                    if _unavailable(error):
                        continue
                    raise _network_error(f"проверить VOD {twitch_id}", error) from None
                if info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
                    continue
                if (info.get("uploader_id") or "").lower() != CHANNEL:
                    raise SlicingError(f"Twitch: не подтверждён канал для VOD {twitch_id}.")
                timestamp = info.get("timestamp")
                if not isinstance(timestamp, (int, float)) or timestamp <= 0:
                    raise SlicingError(f"Twitch: неизвестна дата публикации VOD {twitch_id}.")
                published_at = datetime.fromtimestamp(timestamp, timezone.utc)
                if published_at >= CUTOFF:
                    candidates.append(Vod(twitch_id, published_at))
        return sorted(candidates, key=lambda vod: (vod.published_at, vod.twitch_id))

    def download(self, vod: Vod, target: Path) -> bool:
        from yt_dlp.utils import DownloadError

        last_report = time.monotonic() - 20

        def report_progress(event):
            nonlocal last_report
            now = time.monotonic()
            if event["status"] == "downloading" and now - last_report >= 20:
                last_report = now
                received = (event.get("downloaded_bytes") or 0) // (1024 * 1024)
                fragment = event.get("fragment_index")
                count = event.get("fragment_count")
                progress = f", фрагмент {fragment}/{count}" if fragment and count else ""
                print(f"VOD {vod.twitch_id}: {received} МиБ{progress}", flush=True)

        try:
            with self._open(
                format=DOWNLOAD_FORMAT,
                outtmpl=str(target).replace("%", "%%"),
                continuedl=True,
                skip_unavailable_fragments=False,
                concurrent_fragment_downloads=4,
                progress_hooks=[report_progress],
                noplaylist=True,
            ) as ydl:
                result = ydl.download([vod.url])
        except DownloadError as error:
            if _unavailable(error):
                return False
            raise _network_error(f"скачать VOD {vod.twitch_id}", error) from None
        if result != 0 or not target.is_file() or not target.stat().st_size:
            raise SlicingError(f"Twitch: загрузка VOD {vod.twitch_id} не завершилась.")
        return True
