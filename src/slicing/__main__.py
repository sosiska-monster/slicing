import argparse
import os
import sys
from pathlib import Path

from . import SlicingError
from .media import Media
from .twitch import TwitchArchive


def main() -> int:
    parser = argparse.ArgumentParser(description="Подготовка VOD evelone2004 или монтаж клипа по JSON-плану")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list-vods", action="store_true", help="Только список доступных VOD")
    mode.add_argument("--edit-plan", type=Path, help="JSON-план монтажа")
    parser.add_argument("--clip", help="ID клипа в плане")
    parser.add_argument("--music", type=Path, help="Необязательная локальная инструментальная дорожка")
    parser.add_argument("--draft-subtitles", action="store_true", help="Сохранить метки Whisper по склеенному звуку")
    args = parser.parse_args()
    if args.edit_plan is not None and not args.clip:
        parser.error("--edit-plan требует --clip")
    if args.edit_plan is None and (args.clip is not None or args.music is not None or args.draft_subtitles):
        parser.error("--clip, --music и --draft-subtitles требуют --edit-plan")
    if args.draft_subtitles and args.music is not None:
        parser.error("--draft-subtitles использует исходный звук без --music")

    try:
        if args.edit_plan is not None:
            from .render_plan import prepare_subtitle_draft, render_plan

            root = Path.cwd().resolve()
            media = Media.from_environment()
            if args.draft_subtitles:
                output = prepare_subtitle_draft(args.edit_plan, args.clip, root, media)
            else:
                output = render_plan(args.edit_plan, args.clip, args.music, root, media)
            print(output)
            return 0

        if args.list_vods:
            vods = TwitchArchive().public_vods()
            for vod in vods:
                print(f"{vod.twitch_id}\t{vod.published_at.isoformat()}\t{vod.url}")
            print(f"Доступных VOD после 10 июля 2026 года: {len(vods)}")
            return 0

        dsn = os.environ.get("SLICING_DATABASE_URL")
        if not dsn:
            raise SlicingError("Задайте SLICING_DATABASE_URL для отдельной базы slicing. См. README.")

        import psycopg
        from .db import VodStore
        from .pipeline import run_one

        media = Media.from_environment()
        try:
            with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as connection:
                store = VodStore(connection)
                store.start()
                run_one(store, TwitchArchive(media.ffmpeg), media, Path("data"))
        except psycopg.Error as error:
            reason = error.sqlstate or type(error).__name__
            raise SlicingError(
                f"PostgreSQL ({reason}). Проверьте адрес, порт, права и существование базы slicing."
            ) from None
    except ImportError:
        print("Установите зависимости из pyproject.toml. См. README.", file=sys.stderr)
        return 1
    except (SlicingError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Запуск прерван.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
