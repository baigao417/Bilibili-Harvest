import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bili_subtitle_api import ApiDiscoveryMeta, ApiTrack
from subtitle_pipeline import DiscoveryMeta, TrackInfo
from window import MainWindow, TaskItem, TaskStatus


class DummySignal:
    def emit(self, *_args, **_kwargs):
        return None


class FakeWindow:
    _sanitize_prefetched_segments = MainWindow._sanitize_prefetched_segments
    _prepare_media_for_selected_task = MainWindow._prepare_media_for_selected_task

    def __init__(self, archive_root: str = ""):
        self._state_lock = threading.Lock()
        self._media_cache_lock = threading.Lock()
        self.table_refresh_signal = DummySignal()
        self._runtime_config = SimpleNamespace(archive_root=archive_root)

    def _current_cookie_mode(self):
        return "none"

    def _cookies_file_path(self):
        return None

    def _cookie_header_for_api(self):
        return "SESSDATA=ok"

    def _set_task_status(self, batch, task, status, state_text):
        task.status = status
        task.subtitle_state = state_text
        batch.current_task_seq = task.seq

    def _log(self, _msg, level="INFO", stage=None, task=None):
        return (level, stage, task)

    def _task_base_name(self, task):
        return f"{task.seq:03d}_{task.bv}_TestTitle"

    def _refresh_progress_bar(self):
        return None

    def _safe_title(self, title):
        return title or "Untitled"

    def _ensure_task_temp_path(self, task, path):
        if path and path not in task.temp_paths:
            task.temp_paths.append(path)


def _make_task():
    return TaskItem(
        seq=1,
        raw_input="BV1TEST",
        video_link="https://www.bilibili.com/video/BV1TEST",
        bv="BV1TEST",
        title="TestTitle",
        owner="TestUP",
    )


def _make_batch(tmp_dir):
    archive_root = os.path.join(tmp_dir, "archive")
    success_dir = os.path.join(tmp_dir, "success")
    success_srt_dir = os.path.join(success_dir, "srt")
    success_txt_dir = os.path.join(success_dir, "txt")
    success_md_dir = os.path.join(success_dir, "md")
    tmp_subtitle_dir = os.path.join(tmp_dir, "_tmp_subtitles")
    for path in (archive_root, success_dir, success_srt_dir, success_txt_dir, success_md_dir, tmp_subtitle_dir):
        os.makedirs(path, exist_ok=True)
    return SimpleNamespace(
        export_dir=archive_root,
        success_dir=success_dir,
        success_srt_dir=success_srt_dir,
        success_txt_dir=success_txt_dir,
        success_md_dir=success_md_dir,
        tmp_subtitle_dir=tmp_subtitle_dir,
        model="small",
        current_task_seq=None,
        media_cache={},
        is_running=True,
    )


class ProcessFallbackOrderTests(unittest.TestCase):
    @patch("window.discover_tracks_with_meta")
    @patch("window.discover_bili_tracks")
    @patch("window.ensure_task_identifiers")
    @patch("window.download_video")
    def test_prefetch_success_short_circuits_all_backends(
        self,
        mock_download_video,
        mock_ensure_task_identifiers,
        mock_discover_bili_tracks,
        mock_discover_tracks_with_meta,
    ):
        fake_window = FakeWindow()
        with tempfile.TemporaryDirectory() as tmp:
            batch = _make_batch(tmp)
            task = _make_task()
            task.prefetched_segments = [
                {"start_sec": 0.0, "end_sec": 1.0, "text": "prefetch"},
            ]
            task.prefetched_meta = {"lang": "zh-CN", "track_type": "uploader"}
            MainWindow._process_task_once(fake_window, batch, task)

        self.assertEqual(task.status, TaskStatus.COMPLETED_TRACK)
        self.assertEqual(task.result_source, "browser_prefetch_uploader")
        self.assertEqual(task.selected_lang, "zh-CN")
        self.assertFalse(mock_ensure_task_identifiers.called)
        self.assertFalse(mock_discover_bili_tracks.called)
        self.assertFalse(mock_discover_tracks_with_meta.called)
        self.assertFalse(mock_download_video.called)
        self.assertEqual(task.prefetched_segments, [])
        self.assertEqual(task.prefetched_meta, {})

    @patch("window.discover_tracks_with_meta")
    @patch("window.discover_bili_tracks")
    @patch("window.ensure_task_identifiers")
    @patch("window.convert_flv_to_mp3", return_value="audio.mp3")
    @patch("window.download_video_prefer_1080", return_value="video.mp4")
    def test_prefetch_save_selected_prepares_archive_media(
        self,
        mock_download_video_prefer_1080,
        mock_convert_flv_to_mp3,
        mock_ensure_task_identifiers,
        mock_discover_bili_tracks,
        mock_discover_tracks_with_meta,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            batch = _make_batch(tmp)
            archive_root = batch.export_dir
            fake_window = FakeWindow(archive_root=archive_root)
            task = _make_task()
            task.save_selected = True
            task.prefetched_segments = [
                {"start_sec": 0.0, "end_sec": 1.0, "text": "prefetch"},
            ]
            task.prefetched_meta = {"lang": "zh-CN", "track_type": "ai"}
            MainWindow._process_task_once(fake_window, batch, task)

        self.assertEqual(task.status, TaskStatus.COMPLETED_TRACK)
        self.assertEqual(task.result_source, "browser_prefetch_ai")
        self.assertEqual(task.video_file_path, "video.mp4")
        self.assertEqual(task.audio_file_path, "audio.mp3")
        self.assertFalse(mock_ensure_task_identifiers.called)
        self.assertFalse(mock_discover_bili_tracks.called)
        self.assertFalse(mock_discover_tracks_with_meta.called)
        self.assertTrue(mock_download_video_prefer_1080.called)
        self.assertTrue(mock_convert_flv_to_mp3.called)

        video_output_dir = mock_download_video_prefer_1080.call_args.kwargs["output_dir"]
        self.assertTrue(video_output_dir.startswith(batch.tmp_subtitle_dir))
        self.assertFalse(video_output_dir.startswith(archive_root))

        convert_folder = mock_convert_flv_to_mp3.call_args.kwargs["folder"]
        self.assertTrue(convert_folder.startswith(batch.tmp_subtitle_dir))
        self.assertFalse(convert_folder.startswith(archive_root))

    @patch("window.discover_tracks_with_meta")
    @patch("window.fetch_bili_track_segments")
    @patch("window.discover_bili_tracks")
    @patch("window.ensure_task_identifiers")
    @patch("window.download_video")
    def test_bili_api_success_short_circuits_other_backends(
        self,
        mock_download_video,
        _mock_ensure_task_identifiers,
        mock_discover_bili_tracks,
        mock_fetch_bili_track_segments,
        mock_discover_tracks_with_meta,
    ):
        mock_discover_bili_tracks.return_value = (
            [ApiTrack(lang="zh-CN", track_type="uploader", subtitle_url="https://x/sub.json", raw_lang="zh-CN", endpoint="v2")],
            ApiDiscoveryMeta(cookie_hint=False, endpoint_used="v2", warnings=[]),
        )
        mock_fetch_bili_track_segments.return_value = [
            {"start_sec": 0.0, "end_sec": 1.0, "text": "hello"},
        ]

        fake_window = FakeWindow()
        with tempfile.TemporaryDirectory() as tmp:
            batch = _make_batch(tmp)
            task = _make_task()
            MainWindow._process_task_once(fake_window, batch, task)

        self.assertEqual(task.status, TaskStatus.COMPLETED_TRACK)
        self.assertEqual(task.result_source, "bili_api_uploader")
        self.assertFalse(mock_discover_tracks_with_meta.called)
        self.assertFalse(mock_download_video.called)

    @patch("window.parse_srt_to_segments")
    @patch("window.download_track_srt")
    @patch("window.discover_tracks_with_meta")
    @patch("window.discover_bili_tracks")
    @patch("window.ensure_task_identifiers")
    @patch("window.download_video")
    def test_yt_dlp_success_after_bili_api_no_track(
        self,
        mock_download_video,
        _mock_ensure_task_identifiers,
        mock_discover_bili_tracks,
        mock_discover_tracks_with_meta,
        mock_download_track_srt,
        mock_parse_srt,
    ):
        mock_discover_bili_tracks.return_value = ([], ApiDiscoveryMeta(cookie_hint=False, endpoint_used="none", warnings=[]))
        mock_discover_tracks_with_meta.return_value = (
            [TrackInfo(lang="ai-zh", track_type="ai")],
            DiscoveryMeta(cookie_hint=False, stderr_summary="", used_cookie_mode="none"),
        )
        mock_download_track_srt.return_value = "dummy.srt"
        mock_parse_srt.return_value = [{"start_sec": 0.0, "end_sec": 1.0, "text": "hello"}]

        fake_window = FakeWindow()
        with tempfile.TemporaryDirectory() as tmp:
            batch = _make_batch(tmp)
            task = _make_task()
            MainWindow._process_task_once(fake_window, batch, task)

        self.assertEqual(task.status, TaskStatus.COMPLETED_TRACK)
        self.assertEqual(task.result_source, "yt_dlp_ai")
        self.assertFalse(mock_download_video.called)

    @patch("window.s2t.transcribe_to_segments")
    @patch("window.process_audio_split")
    @patch("window.infer_download_title")
    @patch("window.download_video_prefer_1080", return_value="E:/archive/.bilibili_harvest_work/BV1TEST/video/test.mp4")
    @patch("window.download_video")
    @patch("window.discover_tracks_with_meta")
    @patch("window.discover_bili_tracks")
    @patch("window.ensure_task_identifiers")
    def test_asr_used_after_all_track_backends_fail(
        self,
        _mock_ensure_task_identifiers,
        mock_discover_bili_tracks,
        mock_discover_tracks_with_meta,
        mock_download_video,
        _mock_download_video_prefer_1080,
        mock_infer_download_title,
        mock_process_audio_split,
        mock_transcribe_to_segments,
    ):
        mock_discover_bili_tracks.return_value = ([], ApiDiscoveryMeta(cookie_hint=False, endpoint_used="none", warnings=[]))
        mock_discover_tracks_with_meta.return_value = (
            [],
            DiscoveryMeta(cookie_hint=False, stderr_summary="", used_cookie_mode="none"),
        )
        mock_download_video.return_value = "download_id"
        mock_infer_download_title.return_value = "InferredTitle"
        mock_process_audio_split.return_value = "slice_dir"
        mock_transcribe_to_segments.return_value = [{"start_sec": 0.0, "end_sec": 1.0, "text": "fallback"}]

        fake_window = FakeWindow()
        with tempfile.TemporaryDirectory() as tmp:
            batch = _make_batch(tmp)
            task = _make_task()
            MainWindow._process_task_once(fake_window, batch, task)

        self.assertEqual(task.status, TaskStatus.COMPLETED_ASR)
        self.assertEqual(task.result_source, "asr")
        self.assertEqual(task.selected_lang, "asr")
        self.assertTrue(mock_download_video.called)

    @patch("window.s2t.transcribe_to_segments")
    @patch("window.process_audio_split")
    @patch("window.infer_download_title")
    @patch("window.download_video_prefer_1080", return_value="video.mp4")
    @patch("window.download_video")
    @patch("window.discover_tracks_with_meta")
    @patch("window.discover_bili_tracks")
    @patch("window.ensure_task_identifiers")
    def test_asr_save_selected_uses_archive_work_dir(
        self,
        _mock_ensure_task_identifiers,
        mock_discover_bili_tracks,
        mock_discover_tracks_with_meta,
        mock_download_video,
        mock_download_video_prefer_1080,
        mock_infer_download_title,
        mock_process_audio_split,
        mock_transcribe_to_segments,
    ):
        mock_discover_bili_tracks.return_value = ([], ApiDiscoveryMeta(cookie_hint=False, endpoint_used="none", warnings=[]))
        mock_discover_tracks_with_meta.return_value = (
            [],
            DiscoveryMeta(cookie_hint=False, stderr_summary="", used_cookie_mode="none"),
        )
        mock_infer_download_title.return_value = "IgnoredForSelected"
        mock_process_audio_split.return_value = "slice_dir"
        mock_transcribe_to_segments.return_value = [{"start_sec": 0.0, "end_sec": 1.0, "text": "fallback"}]

        with tempfile.TemporaryDirectory() as tmp:
            batch = _make_batch(tmp)
            archive_root = batch.export_dir
            fake_window = FakeWindow(archive_root=archive_root)
            task = _make_task()
            task.save_selected = True
            MainWindow._process_task_once(fake_window, batch, task)

        self.assertEqual(task.status, TaskStatus.COMPLETED_ASR)
        self.assertEqual(task.result_source, "asr")
        self.assertEqual(task.selected_lang, "asr")
        self.assertFalse(mock_download_video.called)
        self.assertTrue(mock_download_video_prefer_1080.called)
        self.assertTrue(mock_process_audio_split.called)

        video_output_dir = mock_download_video_prefer_1080.call_args.kwargs["output_dir"]
        self.assertTrue(video_output_dir.startswith(batch.tmp_subtitle_dir))
        self.assertFalse(video_output_dir.startswith(archive_root))

        process_kwargs = mock_process_audio_split.call_args.kwargs
        self.assertTrue(process_kwargs["media_folder"].startswith(batch.tmp_subtitle_dir))
        self.assertTrue(process_kwargs["conv_target_dir"].startswith(batch.tmp_subtitle_dir))
        self.assertTrue(process_kwargs["slice_target_root"].startswith(batch.tmp_subtitle_dir))
        self.assertFalse(process_kwargs["media_folder"].startswith(archive_root))


if __name__ == "__main__":
    unittest.main()
