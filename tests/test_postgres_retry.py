import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from slicing import SlicingError
from slicing.db import VodStore
from slicing.media import Cue, Media
from slicing.pipeline import run_one
from slicing.twitch import CUTOFF, Vod


@unittest.skipUnless(os.environ.get("SLICING_TEST_DATABASE_URL"), "requires a disposable PostgreSQL database")
class PostgresRetryTest(unittest.TestCase):
    def test_empty_database_then_transcript_failure_and_retry(self):
        import psycopg

        media = Media.from_environment()
        dsn = os.environ["SLICING_TEST_DATABASE_URL"]
        oldest = Vod("900001", CUTOFF + timedelta(days=1))
        newer = Vod("900002", CUTOFF + timedelta(days=2))

        with tempfile.TemporaryDirectory(prefix="slicing-test-") as temporary:
            root = Path(temporary)
            fixture = root / "fixture.mp4"
            subprocess.run([
                str(media.ffmpeg), "-v", "error", "-nostdin",
                "-f", "lavfi", "-i", "color=c=navy:s=160x90:r=6:d=4",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(fixture),
            ], check=True)
            data = root / "data"
            original = data / "vods" / "900001.mp4"
            output = data / "review" / "transcript_900001.json"
            cue = Cue(1.0, 2.25, "Реплика для расшифровки.")

            twitch = Mock()
            twitch.public_vods.return_value = [oldest, newer]
            twitch.download.side_effect = lambda vod, path: bool(shutil.copyfile(fixture, path))
            media.transcribe = Mock(side_effect=[SlicingError("Сбой распознавания"), [cue], [cue]])

            with psycopg.connect(dsn, autocommit=True) as first:
                self.assertEqual(first.info.dbname, "slicing_test")
                self.assertIsNone(first.execute("SELECT to_regclass('public.vods')").fetchone()[0])
                store = VodStore(first)
                store.start()
                self.assertEqual(store.records(), [])
                with self.assertRaisesRegex(SlicingError, "Сбой распознавания"):
                    run_one(store, twitch, media, data)
                self.assertTrue(original.is_file())
                self.assertFalse(output.exists())
                original_stamp = original.stat().st_mtime_ns

            with psycopg.connect(dsn, autocommit=True) as retry:
                store = VodStore(retry)
                store.start()
                self.assertEqual(
                    [(row.vod, row.status, row.path) for row in store.records()],
                    [(oldest, "downloaded", original)],
                )
                print("DB after transcription failure: 900001 downloaded")
                twitch.public_vods.side_effect = AssertionError("Retry must use the stored VOD")
                self.assertEqual(run_one(store, twitch, media, data), output)
                twitch.public_vods.assert_called_once_with(set())
                twitch.download.assert_called_once_with(oldest, original.with_name(".900001.download.mp4"))
                self.assertEqual(store.records()[0].status, "downloaded")
                self.assertEqual(store.records()[0].path, original)
                self.assertEqual(original.stat().st_mtime_ns, original_stamp)
                self.assertEqual([call.args[0] for call in media.transcribe.call_args_list], [original, original])

                transcript = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(transcript, {
                    "vod_id": "900001", "duration_seconds": media.duration(original),
                    "cues": [{"start": cue.start, "end": cue.end, "text": cue.text}],
                })
                output_stamp = output.stat().st_mtime_ns
                print("DB after retry: 900001 downloaded, original reused, transcript exported")

                twitch.public_vods.side_effect = None
                twitch.public_vods.return_value = [newer]
                newer_source = original.with_name("900002.mp4")
                shutil.copyfile(fixture, newer_source)
                self.assertEqual(run_one(store, twitch, media, data), output.with_name("transcript_900002.json"))
                twitch.public_vods.assert_called_with({"900001"})
                twitch.download.assert_called_once()
                self.assertEqual(media.transcribe.call_args.args[0], newer_source)
                self.assertEqual(output.stat().st_mtime_ns, output_stamp)
                self.assertEqual(store.records()[1].status, "downloaded")
                self.assertFalse((data / "clips").exists())
