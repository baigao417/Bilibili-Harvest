import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from subtitle_pipeline import (
    ExportSummary,
    Segment,
    TrackInfo,
    _run_yt_dlp_with_cookie_fallback,
    dump_segments_to_tmp_json,
    discover_tracks_with_meta,
    export_batch_selected,
    load_segments_from_tmp_json,
    parse_srt_to_segments,
    select_track,
    write_outputs,
)


class DummyTask:
    def __init__(self, seq=1, bv="BVTEST123", status=None):
        self.seq = seq
        self.bv = bv
        self.title = "Test Title"
        self.video_link = "https://www.bilibili.com/video/BVTEST123"
        self.status = status
        self.outputs = {}
        self.output_file = None
        self.result_source = "asr"
        self.selected_lang = "asr"
        self.segments_cache = []
        self.segments_tmp_json = ""
        self.video_file_path = ""
        self.audio_file_path = ""
        self.save_selected = False
        self.shape_folder_name = ""
        self.asset_prepare_error = ""
        self.cid = None
        self.cookie_hint = False
        self.failed_stage = None
        self.error = ""


class SubtitlePipelineUnitTests(unittest.TestCase):
    def test_select_track_zh_priority(self):
        tracks = [
            TrackInfo(lang="ai-en", track_type="ai"),
            TrackInfo(lang="ai-zh", track_type="ai"),
            TrackInfo(lang="zh-CN", track_type="uploader"),
        ]
        selected = select_track(tracks)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.lang, "zh-CN")

    def test_parse_srt_to_segments(self):
        content = """1
00:00:01,200 --> 00:00:03,500
hello world

2
00:00:04,000 --> 00:00:06,000
second line
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.srt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            segments = parse_srt_to_segments(path)
            self.assertEqual(len(segments), 2)
            self.assertAlmostEqual(segments[0].start_sec, 1.2)
            self.assertAlmostEqual(segments[1].end_sec, 6.0)
            self.assertEqual(segments[0].text, "hello world")

    def test_write_outputs_same_basename(self):
        segments = [
            Segment(start_sec=0.0, end_sec=1.0, text="line one"),
            Segment(start_sec=1.0, end_sec=2.0, text="line two"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            text_dir = os.path.join(tmp, "text")
            outputs = write_outputs(
                DummyTask(),
                segments,
                text_dir,
                metadata={"base_name": "001_BVTEST123_TestTitle", "source": "ai", "language": "ai-zh"},
            )
            self.assertTrue(os.path.isfile(outputs["srt"]))
            self.assertTrue(os.path.isfile(outputs["txt"]))
            self.assertTrue(os.path.isfile(outputs["md"]))

            stem_srt = os.path.splitext(os.path.basename(outputs["srt"]))[0]
            stem_txt = os.path.splitext(os.path.basename(outputs["txt"]))[0]
            stem_md = os.path.splitext(os.path.basename(outputs["md"]))[0]
            self.assertEqual(stem_srt, stem_txt)
            self.assertEqual(stem_txt, stem_md)

    def test_write_outputs_with_selected_formats(self):
        segments = [Segment(start_sec=0.0, end_sec=1.0, text="line one")]
        with tempfile.TemporaryDirectory() as tmp:
            text_dir = os.path.join(tmp, "text")
            outputs = write_outputs(
                DummyTask(),
                segments,
                text_dir,
                metadata={"base_name": "001_BVTEST123_TestTitle", "source": "ai", "language": "ai-zh"},
                formats={"txt"},
            )
            self.assertIn("txt", outputs)
            self.assertNotIn("srt", outputs)
            self.assertNotIn("md", outputs)
            self.assertTrue(os.path.isfile(outputs["txt"]))

    def test_dump_and_load_segments_tmp_json(self):
        payload = [
            Segment(start_sec=0.0, end_sec=1.0, text="hello"),
            {"start_sec": 1.0, "end_sec": 2.0, "text": "world"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "segments.json")
            dump_segments_to_tmp_json(path, payload)
            loaded = load_segments_from_tmp_json(path)
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["text"], "hello")
            self.assertEqual(loaded[1]["text"], "world")

    def test_export_batch_selected(self):
        from types import SimpleNamespace
        from window import TaskStatus

        with tempfile.TemporaryDirectory() as tmp:
            shape_root = os.path.join(tmp, "shape")
            os.makedirs(shape_root, exist_ok=True)
            video_file = os.path.join(tmp, "video.mp4")
            audio_file = os.path.join(tmp, "audio.mp3")
            with open(video_file, "w", encoding="utf-8") as f:
                f.write("video")
            with open(audio_file, "w", encoding="utf-8") as f:
                f.write("audio")

            task_ok = DummyTask(seq=1, bv="BVOK", status=TaskStatus.COMPLETED_ASR)
            task_ok.segments_cache = [{"start_sec": 0.0, "end_sec": 1.0, "text": "ok"}]
            task_ok.save_selected = False
            task_shape = DummyTask(seq=3, bv="BVSHAPE", status=TaskStatus.COMPLETED_TRACK)
            task_shape.segments_cache = [{"start_sec": 0.0, "end_sec": 1.0, "text": "shape"}]
            task_shape.save_selected = True
            task_shape.video_file_path = video_file
            task_shape.audio_file_path = audio_file
            task_fail = DummyTask(seq=2, bv="BVFAIL", status=TaskStatus.FAILED)
            batch = SimpleNamespace(
                batch_id="BATCH001",
                started_at=SimpleNamespace(strftime=lambda _fmt: "2026-02-24 00:00:00"),
                model="small",
                tasks=[task_ok, task_shape, task_fail],
                total_count=3,
                success_count=2,
                failed_count=1,
                failed_state_path=os.path.join(tmp, "failed.json"),
            )
            # Use a real datetime-like object for report generation.
            import datetime

            batch.started_at = datetime.datetime(2026, 2, 24, 0, 0, 0)
            summary = export_batch_selected(
                batch,
                selected_formats={"srt", "txt"},
                target_dir=tmp,
                export_zip=False,
                shape_root=shape_root,
                save_selector=lambda task: bool(getattr(task, "save_selected", False)),
                skip_selected_from_normal_export=True,
            )
            self.assertIsInstance(summary, ExportSummary)
            self.assertEqual(summary.exported_count, 1)
            self.assertEqual(summary.normal_exported_count, 0)
            self.assertEqual(summary.shape_saved_count, 1)
            self.assertEqual(summary.skipped_count, 1)
            self.assertTrue(os.path.isfile(batch.failed_state_path))
            shape_dir = os.path.join(shape_root, f"{task_shape.title}_{task_shape.bv}")
            self.assertTrue(os.path.isdir(shape_dir))
            self.assertTrue(os.path.isdir(os.path.join(shape_dir, "text")))
            self.assertTrue(os.path.isdir(os.path.join(shape_dir, "video")))
            self.assertTrue(os.path.isdir(os.path.join(shape_dir, "audio")))

    @patch("subtitle_pipeline.run_command")
    def test_manual_cookie_header_replaces_cookie_chain(self, mock_run_command):
        mock_run_command.return_value = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout="{}",
            stderr="",
        )

        _result, used_mode = _run_yt_dlp_with_cookie_fallback(
            ["yt-dlp", "--dump-single-json", "https://www.bilibili.com/video/BVTEST123"],
            cookie_mode="auto_chrome",
            cookies_file="cookies.txt",
            cookie_header="Cookie: SESSDATA=abc; bili_jct=def",
        )
        self.assertEqual(used_mode, "manual_header")
        self.assertEqual(mock_run_command.call_count, 1)

        called_cmd = mock_run_command.call_args.args[0]
        called_str = " ".join(called_cmd)
        self.assertIn("--add-header", called_cmd)
        self.assertIn("Cookie: SESSDATA=abc; bili_jct=def", called_str)
        self.assertNotIn("--cookies-from-browser", called_cmd)
        self.assertNotIn("--cookies", called_cmd)

    @patch("subtitle_pipeline.find_executable", return_value="yt-dlp")
    @patch("subtitle_pipeline.run_command")
    def test_discover_tracks_merges_automatic_captions(self, mock_run_command, _mock_find_exec):
        payload = {
            "subtitles": {
                "zh-CN": [{"ext": "srt"}],
                "danmaku": [{"ext": "xml"}],
            },
            "automatic_captions": {
                "ai-zh": [{"ext": "json3"}],
                "en": [{"ext": "json3"}],
            },
        }
        mock_run_command.return_value = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

        tracks, _meta = discover_tracks_with_meta(DummyTask(), cookie_mode="none", cookies_file=None)
        lang_map = {track.lang: track.track_type for track in tracks}
        self.assertEqual(lang_map["zh-CN"], "uploader")
        self.assertEqual(lang_map["ai-zh"], "ai")
        self.assertEqual(lang_map["en"], "ai")
        self.assertNotIn("danmaku", lang_map)


if __name__ == "__main__":
    unittest.main()
