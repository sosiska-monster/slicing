import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from slicing import SlicingError
from slicing import framing
from slicing.media import Cue, Media
from slicing.render_plan import (
    EditPlan, Segment, _draft_words, _read_subtitle_review, _resolve_layout, _tile_sets, load_plan, make_ass,
)


class RenderPlanTest(unittest.TestCase):
    def test_speaker_cut_swaps_main_camera_and_holds_an_interjection(self):
        profile = {"top": 240, "bottom": 380, "left": 65, "right": 65, "rail_top": 780, "rail_right": 200}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "plan.json"
            path.write_text(json.dumps({
                "schema_version": 1, "source": {"vod_id": "123", "file": "data/vods/123.mp4"},
                "auto_layout": {"source": "test", "kind": "estimate", "reference_size_px": [1080, 1920],
                                "platforms": {"TikTok": profile, "Shorts": profile}},
                "clips": [{"id": "test", "export_size": [1080, 1920], "segments": [{
                    "start_ms": 2000, "end_ms": 5200,
                    "captions": [{"start_ms": 3400, "end_ms": 3800, "lines": ["Через склейку"]}],
                    "framing": {"name": "conversation", "regions": [
                        {"name": "left camera", "speaker": "A", "priority": "required",
                         "box": [350, 338, 168, 164], "viewport": [20, 40, 610, 850]},
                        {"name": "right camera", "speaker": "B", "priority": "required",
                         "box": [1338, 326, 168, 160], "viewport": [1260, 40, 610, 850]},
                    ], "speaker_turns": [
                        {"start_ms": 2000, "end_ms": 3200, "speaker": "A", "reaction": "B"},
                        {"start_ms": 3200, "end_ms": 3500, "speaker": "B", "hold": True},
                        {"start_ms": 3500, "end_ms": 5200, "speaker": "B", "reaction": "A"},
                    ]},
                }]}],
            }), encoding="utf-8")
            media = Mock(spec=Media)
            media.duration.return_value = 10
            media.ffprobe = root / "ffprobe.exe"
            with patch("slicing.render_plan._run", return_value=b'{"streams":[{"width":1920,"height":1080}]}'):
                plan = load_plan(path, "test", root, media)
            ass = make_ass([], plan.ends_ms, segments=tuple(plan.segments), safe_area=plan.safe_area)
            with patch("slicing.render_plan._measure_ass", return_value={0: (400, 899, 280, 65)}):
                picture, ass, entries = _resolve_layout(plan, ass, media, root)

        self.assertEqual([(part.start_ms, part.end_ms) for part in plan.segments], [(2000, 5200)])
        self.assertEqual([(part.start_ms, part.end_ms) for part in picture.segments], [(2000, 3500), (3500, 5200)])
        for index, (speaker, main, reaction) in enumerate((("A", "left camera", "right camera"),
                                                            ("B", "right camera", "left camera"))):
            entry = entries[index]
            self.assertEqual(entry["active_speaker"], speaker)
            self.assertTrue(picture.segments[index].layered)
            primary, inset = entry["panels"]
            self.assertEqual(primary["distinct_required_regions"], [main])
            self.assertEqual(inset["distinct_required_regions"], [reaction])
            self.assertEqual(primary["output_place"], (0, 0, 1080, 1920))
            self.assertLess(inset["output_place"][2], 1080 // 2)
            cx, cy = entry["face_centers"][0]["center_percent"]
            self.assertTrue(45 <= cx <= 55 and 35 <= cy <= 45)
            for region in entry["regions"]:
                self.assertFalse(region["track"][0]["ui_overlaps"])
                self.assertFalse(region["track"][0]["overlay_overlaps"])
            main_box = next(region for region in entry["regions"] if region["name"] == main)["track"][0]["output_box"]
            self.assertFalse(framing.overlaps(main_box, inset["output_place"]))
        self.assertIn("0:00:01.40,0:00:01.50,Speech", ass)
        self.assertIn("0:00:01.50,0:00:01.80,Speech", ass)
        self.assertEqual(ass.count("Через склейку"), 2)

    def test_auto_crop_rejects_clipped_edge_even_with_visible_center(self):
        source_size = (420, 320)
        tiles = _tile_sets((720, 1280))[:1]
        interval = (1000, 1500)
        wide = (70, 120, 182, 60)
        center = (wide[0] + wide[2] // 2, wide[1] + wide[3] // 2, 1, 1)
        slots = (framing.TextSlot(None),)
        for box, fits in ((center, True), (wide, False), ((70, 120, 180, 60), True)):
            with self.subTest(box=box):
                region = framing.Region("phone", True, (framing.TimedBox(interval, box),))
                layout = framing.solve((region,), source_size, tiles, (), slots)
                self.assertEqual(layout is not None, fits)
                if layout is not None:
                    self.assertTrue(framing.contains(layout.panels[0].crop, box))
                    if box == center:
                        self.assertFalse(framing.contains(layout.panels[0].crop, wide))

    def test_auto_layout_moves_subtitles_away_from_a_required_object(self):
        region = framing.Region("board", True, (framing.TimedBox((0, 1000), (0, 100, 180, 100)),))
        blocking = framing.TextSlot((360, 400), (framing.Obstacle("subtitles", (200, 480, 300, 75), (0, 1000)),))
        available = framing.TextSlot((360, 950), (framing.Obstacle("subtitles", (200, 860, 300, 75), (0, 1000)),))
        layout = framing.solve((region,), (180, 320), _tile_sets((720, 1280)), (), (blocking, available))
        self.assertIsNotNone(layout)
        self.assertEqual(layout.speech, available)

    def test_auto_layout_uses_a_wider_crop_for_a_visible_reaction(self):
        interval = (1000, 2000)
        speaker = framing.Region("speaker", True, (framing.TimedBox(interval, (100, 132, 40, 40)),))
        reaction = framing.Region("reaction", False, (framing.TimedBox(interval, (200, 132, 42, 40)),))
        size, tiles, slots = (420, 320), _tile_sets((720, 1280)), (framing.TextSlot(None),)
        tight = framing.solve((speaker,), size, tiles, (), slots)
        wider = framing.solve((speaker, reaction), size, tiles, (), slots)
        self.assertIsNotNone(wider)
        self.assertEqual(len(wider.panels), 1)
        self.assertGreater(wider.panels[0].crop[2], tight.panels[0].crop[2])
        self.assertTrue(framing.contains(wider.panels[0].crop, reaction.envelope))
        self.assertEqual(wider.panels[0].secondary, {"reaction"})

        blocked = (framing.Obstacle("UI", (400, 0, 320, 1280)),)
        hidden = framing.solve((speaker, reaction), size, tiles, blocked, slots)
        self.assertEqual(hidden, framing.solve((speaker,), size, tiles, blocked, slots))
        self.assertFalse(hidden.panels[0].secondary)

    def test_auto_layout_reports_a_duplicated_required_region(self):
        interval = (1000, 1500)
        separate = (
            framing.Region("face", True, (framing.TimedBox(interval, (100, 100, 32, 120)),)),
            framing.Region("screen", True, (framing.TimedBox(interval, (156, 105, 36, 105)),)),
        )
        halves = tuple(framing.Tile(rect, rect) for rect in ((0, 0, 720, 640), (0, 640, 720, 640)))
        layout = framing.solve(separate, (420, 320), (halves,), (), (framing.TextSlot(None),))
        self.assertIsNotNone(layout)
        self.assertEqual(len(layout.panels), 2)
        self.assertEqual(list(framing.duplicated_regions(layout)), [])

        box = (110, 130, 200, 70)
        regions = tuple(framing.Region(name, True, (framing.TimedBox(interval, box),))
                        for name in ("phone", "preview"))
        size, tiles, slots = (420, 320), _tile_sets((720, 1280)), (framing.TextSlot(None),)
        repeated = framing.solve(regions, size, tiles, (), slots, allow_duplicates=True)
        self.assertEqual(len(repeated.panels), 2)
        self.assertTrue(all(framing.contains(panel.crop, box) for panel in repeated.panels))
        self.assertIsNone(framing.solve(regions, size, tiles, (), slots))

        segment = Segment(*interval, captions=(), regions=regions)
        plan = EditPlan(
            "123", Path("123.mp4"), 5.0, "test", "Test", [segment], "",
            source_size=size, profiles=framing.Profiles("estimate", "test", ()),
        )
        ass = make_ass([], plan.ends_ms, segments=(segment,))
        with self.assertRaises(SlicingError) as caught:
            _resolve_layout(plan, ass, Mock(spec=Media), Path("."))
        result = json.loads(str(caught.exception))
        self.assertEqual(result["status"], "needs_review")
        issues = result["scenes"][0]["issues"]
        self.assertEqual({item["object"] for item in issues}, {"phone", "preview"})
        self.assertTrue(all(item["reason"] == "duplicate_required_region" and item["interval_ms"] == list(interval)
                            for item in issues))

    def test_auto_layout_reports_object_and_source_interval_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "plan.json"
            profile = {"top": 100, "bottom": 100, "left": 20, "right": 20, "rail_top": 800, "rail_right": 80}
            path.write_text(json.dumps({
                "schema_version": 1, "source": {"vod_id": "123", "file": "data/vods/123.mp4"},
                "auto_layout": {"source": "test", "kind": "estimate", "reference_size_px": [720, 1280],
                                "platforms": {"TikTok": profile, "Shorts": profile}},
                "clips": [{"id": "test", "segments": [{
                    "start_ms": 1000, "end_ms": 1500, "captions": [],
                    "framing": {"name": "board", "regions": [
                        {"name": "board", "priority": "required", "box": [50, 80, 182, 100]},
                    ]},
                }]}],
            }), encoding="utf-8")
            media = Mock(spec=Media)
            media.duration.return_value = 5
            media.ffprobe = root / "ffprobe.exe"
            with patch("slicing.render_plan._run", return_value=b'{"streams":[{"width":420,"height":320}]}'):
                plan = load_plan(path, "test", root, media)
            ass = make_ass([], plan.ends_ms, segments=tuple(plan.segments))
            with self.assertRaises(SlicingError) as caught:
                _resolve_layout(plan, ass, media, root)
            result = json.loads(str(caught.exception))
            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(result["scenes"][0]["issues"][0], {
                "object": "board", "interval_ms": [1000, 1500], "source_box": [50, 80, 182, 100],
                "reason": "cannot_fit_edges",
            })

    def test_auto_layout_keeps_motion_and_uses_two_undistorted_panels(self):
        regions = framing.load_regions([
            {"name": "speaker", "priority": "required", "viewport": [0, 0, 600, 540], "track": [
                {"start_ms": 1000, "end_ms": 1200, "box": [170, 230, 130, 100]},
                {"start_ms": 1200, "end_ms": 1500, "box": [200, 260, 160, 100]},
            ]},
            {"name": "reaction", "priority": "required", "viewport": [1300, 0, 620, 540],
             "box": [1450, 230, 150, 110]},
        ], (1000, 1500))
        profiles = framing.load_profiles({
            "kind": "estimate", "source": "test", "reference_size_px": [1080, 1920],
            "platforms": {
                "TikTok": {"top": 240, "bottom": 380, "left": 65, "right": 65, "rail_top": 780, "rail_right": 200},
                "Shorts": {"top": 240, "bottom": 320, "left": 70, "right": 70, "rail_top": 1130, "rail_right": 230},
            },
        }, (1080, 1920))
        layout = framing.solve(regions, (1920, 1080), _tile_sets((1080, 1920)),
                               profiles.obstacles, (framing.TextSlot(None),))
        self.assertIsNotNone(layout)
        self.assertEqual(len(layout.panels), 2)
        first, second = (panel.tile.output for panel in layout.panels)
        self.assertFalse(framing.overlaps(first, second))
        self.assertEqual(first[2] * first[3] + second[2] * second[3], 1080 * 1920)
        for panel in layout.panels:
            crop, out = panel.crop, panel.tile.output
            self.assertEqual(crop[2] * out[3], crop[3] * out[2])
            for region in panel.regions:
                for part in region.track:
                    self.assertTrue(framing.contains(crop, part.box))
                    output_box = framing.project(part.box, crop, out)
                    self.assertFalse(any(framing.overlaps(output_box, ui.box) for ui in profiles.obstacles))

    def test_probe_source_and_keep_segment_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "plan.json"
            document = {
                "schema_version": 1,
                "source": {"vod_id": "123", "file": "data/vods/123.mp4", "duration_ms": 60_000},
                "clips": [{"id": "test", "segments": [
                    {"start_ms": 3000, "end_ms": 4200},
                    {"start_ms": 200, "end_ms": 1100},
                    {"start_ms": 3000, "end_ms": 4100},
                ]}],
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            media = Mock(spec=Media)
            media.duration.return_value = 4.205
            plan = load_plan(path, "test", root, media)
            media.duration.assert_called_once_with(root / "data/vods/123.mp4")
            self.assertEqual([part.start_ms for part in plan.segments], [3000, 200, 3000])
            self.assertEqual(plan.ends_ms, [1200, 2100, 3200])
            self.assertEqual([part.framing for part in plan.segments], ["full_frame"] * 3)
            self.assertIsNone(plan.header)
            self.assertTrue(all(part.captions is None for part in plan.segments))

            for end in (4206, 0, True):
                with self.subTest(end=end):
                    document["clips"][0]["segments"][0]["end_ms"] = end
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(SlicingError, "Отрезок 1"):
                        load_plan(path, "test", root, media)

    def test_word_highlights_respect_both_cuts_and_caption_line_limit(self):
        words = [
            Cue(12.90, 13.05, "Прочитать"),
            Cue(13.05, 13.30, "правильный"),
            Cue(13.30, 13.42, "вариант"),
            Cue(13.42, 13.55, "ответа"),
            Cue(13.55, 13.75, "сейчас"),
            Cue(13.75, 13.91, "Давай"),
            Cue(19.42, 19.64, "Fnatic."),
            Cue(19.70, 19.84, "Верно!"),
        ]
        ass = make_ass(words, [13_650, 19_580, 29_580])
        events = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
        self.assertIn(r"0:00:13.55,0:00:13.65,Speech", ass)
        self.assertIn(r"0:00:13.75,0:00:13.91,Speech", ass)
        self.assertIn(r"0:00:19.42,0:00:19.58,Speech", ass)
        self.assertIn(r"0:00:19.70,0:00:19.84,Speech", ass)
        self.assertEqual(len(events), len(words))
        self.assertTrue(any(r"\N" in event for event in events))
        for event in events:
            self.assertLessEqual(event.count(r"\N"), 1)
            self.assertEqual(event.count(r"{\1c&H38DDFF&}"), 1)

    def test_plan_supplies_header_panels_and_captions_for_arbitrary_clip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "plan.json"
            panel = {"crop": [10, 12, 240, 100], "place": [21, 300, 600, 250]}
            document = {
                "schema_version": 1,
                "source": {"vod_id": "123", "file": "data/vods/123.mp4"},
                "clips": [{
                    "id": "custom",
                    "header": {"label": "ВОПРОС", "lines": ["Паста {C}", "50 000 ₽"]},
                    "segments": [
                        {"start_ms": 3000, "end_ms": 4400,
                         "framing": {"name": "board", "panels": [panel]},
                         "captions": [{"start_ms": 3080, "end_ms": 4300, "lines": ["Первый"]}]},
                        {"start_ms": 500, "end_ms": 2000,
                         "captions": [{"start_ms": 700, "end_ms": 1500, "lines": ["Второй", "ответ"]}]},
                    ],
                }],
            }
            media = Mock(spec=Media)
            media.duration.return_value = 5.0
            media.ffprobe = root / "ffprobe.exe"
            with patch("slicing.render_plan._run", return_value=b'{"streams":[{"width":852,"height":480}]}'):
                path.write_text(json.dumps(document), encoding="utf-8")
                plan = load_plan(path, "custom", root, media)
                self.assertEqual(plan.segments[0].framing, "board")
                self.assertEqual(plan.segments[0].panels[0].place, (21, 300, 600, 250))
                ass = make_ass([], plan.ends_ms, plan.header, tuple(plan.segments))
                self.assertIn(r"Паста （C）\N50 000 ₽", ass)
                self.assertIn("0:00:00.08,0:00:01.30,Speech,,0,0,0,,Первый", ass)
                self.assertIn(r"0:00:01.60,0:00:02.40,Speech,,0,0,0,,Второй\Nответ", ass)

                panel["place"][0] = 122
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(SlicingError, "за границы холста"):
                    load_plan(path, "custom", root, media)

                panel["place"][0] = 21
                panel["crop"][0] = 614
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(SlicingError, "за границы исходного кадра"):
                    load_plan(path, "custom", root, media)

    def test_reviewed_subtitles_keep_word_timing_and_use_plain_phrases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "plan.json"
            draft_path, edits_path = root / "words.json", root / "edits.json"
            intervals = [[1000, 2407], [4000, 5000]]
            plan_path.write_text(json.dumps({
                "schema_version": 1,
                "source": {"vod_id": "123", "file": "data/vods/123.mp4"},
                "clips": [{
                    "id": "reviewed",
                    "subtitle_review": {"draft": draft_path.name, "edits": edits_path.name},
                    "segments": [{"start_ms": start, "end_ms": end} for start, end in intervals],
                }],
            }), encoding="utf-8")
            media = Mock(spec=Media)
            media.duration.return_value = 10.0
            plan = load_plan(plan_path, "reviewed", root, media)
            words = _draft_words([
                Cue(1.31, 1.45, "мясо"),
                Cue(1.407, 1.62, "альдента"),
                Cue(1.63, 1.70, "от"),
                Cue(1.70, 1.92, "варки"),
            ], plan.ends_ms)
            self.assertEqual([(w.id, w.segment, w.start_ms, w.end_ms) for w in words], [
                ("w001", 1, 1310, 1407), ("w002", 2, 1407, 1620),
                ("w003", 2, 1630, 1700), ("w004", 2, 1700, 1920),
            ])
            draft = {
                "schema_version": 1, "vod_id": "123", "clip_id": "reviewed", "source_segments_ms": intervals,
                "words": [vars(word) for word in words],
            }
            raw = json.dumps(draft).encode("utf-8")
            draft_path.write_bytes(raw)
            edits = {
                "schema_version": 1, "draft_sha256": hashlib.sha256(raw).hexdigest(),
                "edits": [
                    {"word_ids": ["w001"], "text": "мяса."},
                    {"word_ids": ["w002"], "text": "аль денте"},
                    {"word_ids": ["w003", "w004"], "text": "отварки"},
                ],
            }
            edits_path.write_text(json.dumps(edits), encoding="utf-8")
            reviewed, _ = _read_subtitle_review(plan, plan.subtitle_review)
            ass = make_ass([], plan.ends_ms, reviewed=reviewed)
            self.assertIn(r"0:00:01.31,0:00:01.40,Speech,,0,0,0,,{\1c&H38DDFF&}мяса.", ass)
            self.assertIn("0:00:01.41,0:00:01.62,Speech,,0,0,0,,аль денте", ass)
            self.assertIn("0:00:01.63,0:00:01.92,Speech,,0,0,0,,отварки", ass)
            self.assertEqual(ass.count(r"{\1c&H38DDFF&}"), 1)

            draft_path.write_bytes(raw + b"\n")
            with self.assertRaisesRegex(SlicingError, "SHA-256"):
                _read_subtitle_review(plan, plan.subtitle_review)
            draft_path.write_bytes(raw)
            edits["edits"] = [{"word_ids": ["w001", "w002"], "text": "через склейку"}]
            edits_path.write_text(json.dumps(edits), encoding="utf-8")
            with self.assertRaisesRegex(SlicingError, "одного отрезка"):
                _read_subtitle_review(plan, plan.subtitle_review)
