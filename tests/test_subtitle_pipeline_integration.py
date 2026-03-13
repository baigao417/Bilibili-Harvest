import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from subtitle_pipeline import TrackInfo, discover_tracks_with_meta, download_track_srt


class DummyTask:
    def __init__(self, link="https://www.bilibili.com/video/BV1TEST"):
        self.video_link = link
        self.bv = "BV1TEST"
        self.seq = 1


class SubtitlePipelineIntegrationTests(unittest.TestCase):
    @patch("subtitle_pipeline.find_executable", return_value="yt-dlp")
    @patch("subtitle_pipeline.run_command")
    def test_discover_tracks_filters_danmaku(self, mock_run_command, _mock_find_exec):
        payload = {
            "subtitles": {
                "danmaku": [{"ext": "xml"}],
                "ai-zh": [{"ext": "srt"}],
                "ai-en": [{"ext": "srt"}],
            }
        }
        mock_run_command.return_value = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

        tracks, meta = discover_tracks_with_meta(DummyTask(), cookie_mode="none", cookies_file=None)
        langs = sorted([t.lang for t in tracks])
        self.assertEqual(langs, ["ai-en", "ai-zh"])
        self.assertFalse(meta.cookie_hint)

    @patch("subtitle_pipeline.find_executable", return_value="yt-dlp")
    @patch("subtitle_pipeline.run_command")
    def test_discover_tracks_sets_cookie_hint(self, mock_run_command, _mock_find_exec):
        payload = {"subtitles": {"danmaku": [{"ext": "xml"}]}}
        mock_run_command.return_value = subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(payload),
            stderr="WARNING: Subtitles are only available when logged in",
        )

        tracks, meta = discover_tracks_with_meta(DummyTask(), cookie_mode="none", cookies_file=None)
        self.assertEqual(tracks, [])
        self.assertTrue(meta.cookie_hint)

    @patch("subtitle_pipeline.find_executable", return_value="yt-dlp")
    @patch("subtitle_pipeline.run_command")
    def test_download_track_uses_manual_cookie_header(self, mock_run_command, _mock_find_exec):
        with tempfile.TemporaryDirectory() as tmp:
            task = DummyTask()
            track = TrackInfo(lang="zh-CN", track_type="uploader")

            def _fake_run(cmd, timeout=1800, cwd=None):
                path = os.path.join(tmp, "001_BV1TEST.zh-CN.srt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            mock_run_command.side_effect = _fake_run
            out_path = download_track_srt(
                task,
                track,
                cookie_mode="auto_chrome",
                cookies_file="cookies.txt",
                cookie_header="SESSDATA=abc; bili_jct=def",
                out_dir=tmp,
            )
            self.assertTrue(os.path.isfile(out_path))

            called_cmd = mock_run_command.call_args.args[0]
            joined = " ".join(called_cmd)
            self.assertIn("--add-header", called_cmd)
            self.assertIn("Cookie: SESSDATA=abc; bili_jct=def", joined)
            self.assertNotIn("--cookies-from-browser", called_cmd)
            self.assertNotIn("--cookies", called_cmd)


if __name__ == "__main__":
    unittest.main()
