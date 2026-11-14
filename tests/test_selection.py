import unittest
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock, patch

from slicing.twitch import ARCHIVES_URL, CUTOFF, TwitchArchive


class SelectionTest(unittest.TestCase):
    def test_oldest_playable_archive_after_cutoff_excludes_completed_and_live(self):
        from yt_dlp.utils import DownloadError

        archive = TwitchArchive()
        playlist = Mock()
        playlist.extract_info.return_value = {
            "entries": [{"id": f"v{id_}"} for id_ in (8, 7, 6, 5, 4, 3, 2, 1)]
        }
        detail = Mock()

        def get_detail(url, download):
            twitch_id = int(url.rsplit("/", 1)[1])
            if twitch_id == 4:
                raise DownloadError("This is subscriber-only content")
            published_at = CUTOFF + timedelta(seconds={8: 40, 6: 20, 5: 10, 3: 0, 2: -1}[twitch_id])
            return {
                "timestamp": published_at.timestamp(),
                "live_status": "is_live" if twitch_id == 5 else "was_live",
                "uploader_id": "evelone2004",
            }

        detail.extract_info.side_effect = get_detail
        with patch.object(archive, "_open", side_effect=[nullcontext(playlist), nullcontext(detail)]):
            result = archive.public_vods({"7", "1"})
        playlist.extract_info.assert_called_once_with(ARCHIVES_URL, download=False)
        self.assertEqual([vod.twitch_id for vod in result], ["3", "6", "8"])
