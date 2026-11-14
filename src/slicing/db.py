from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import SlicingError
from .twitch import Vod

if TYPE_CHECKING:
    from psycopg import Connection

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS public.vods (
    twitch_id text PRIMARY KEY CHECK (twitch_id ~ '^[0-9]+$'),
    published_at timestamptz NOT NULL,
    local_path text NOT NULL,
    status text NOT NULL CHECK (status IN ('downloaded', 'processed', 'no_moments'))
)
"""
LOCK_ID = 1936484707


@dataclass(frozen=True)
class StoredVod:
    vod: Vod
    path: Path
    status: str


class VodStore:
    def __init__(self, connection: "Connection"):
        if not connection.autocommit:
            raise ValueError("VodStore requires an autocommit connection")
        self.connection = connection

    def start(self) -> None:
        locked = self.connection.execute(
            "SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)
        ).fetchone()
        if not locked[0]:
            raise SlicingError("Другой запуск уже обрабатывает VOD в этой базе.")
        self.connection.execute(SCHEMA_SQL)

    def records(self) -> list[StoredVod]:
        rows = self.connection.execute(
            "SELECT twitch_id, published_at, local_path, status FROM public.vods "
            "ORDER BY published_at, twitch_id"
        ).fetchall()
        return [
            StoredVod(Vod(twitch_id, published_at), Path(local_path), status)
            for twitch_id, published_at, local_path, status in rows
        ]

    def save_download(self, vod: Vod, path: Path) -> None:
        self.connection.execute(
            """
            INSERT INTO public.vods (twitch_id, published_at, local_path, status)
            VALUES (%s, %s, %s, 'downloaded')
            ON CONFLICT (twitch_id) DO UPDATE SET local_path = EXCLUDED.local_path
            WHERE vods.status = 'downloaded'
            """,
            (vod.twitch_id, vod.published_at, str(path)),
        )
