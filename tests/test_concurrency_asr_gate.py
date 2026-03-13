import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bili_subtitle_api import ApiDiscoveryMeta
from subtitle_pipeline import DiscoveryMeta
from window import MainWindow, TaskItem, TaskStatus


class _DummySignal:
    def emit(self, *_args, **_kwargs):
        return None


class _FakeAsrWindow:
    _process_task_once = MainWindow._process_task_once
    _sanitize_prefetched_segments = MainWindow._sanitize_prefetched_segments

    def __init__(self):
        self._state_lock = threading.Lock()
        self._media_cache_lock = threading.Lock()
        self._asr_semaphore = threading.Semaphore(1)
        self.table_refresh_signal = _DummySignal()

    def _current_cookie_mode(self):
        return "none"

    def _cookies_file_path(self):
        return None

    def _cookie_header_for_api(self):
        return None

    def _set_task_status(self, batch, task, status, state_text):
        task.status = status
        task.subtitle_state = state_text
        batch.current_task_seq = task.seq

    def _log(self, _msg, **_kwargs):
        return None

    def _task_base_name(self, task):
        return f"{task.seq:03d}_{task.bv}_X"

    def _refresh_progress_bar(self):
        return None

    def _safe_title(self, title):
        return title or "Untitled"

    def _ensure_task_temp_path(self, task, path):
        if path and path not in task.temp_paths:
            task.temp_paths.append(path)


def _make_task(seq: int) -> TaskItem:
    return TaskItem(
        seq=seq,
        raw_input=f"BV{seq}",
        video_link=f"https://www.bilibili.com/video/BV{seq}",
        bv=f"BV{seq}",
        title=f"T{seq}",
        owner="UP",
    )


class ConcurrencyAsrGateTests(unittest.TestCase):
    @patch("window.dump_segments_to_tmp_json")
    @patch("window.s2t.transcribe_to_segments")
    @patch("window.process_audio_split")
    @patch("window.infer_download_title")
    @patch("window.download_video")
    @patch("window.discover_tracks_with_meta")
    @patch("window.discover_bili_tracks")
    @patch("window.ensure_task_identifiers")
    def test_asr_gate_is_serialized(
        self,
        _mock_ensure_task_identifiers,
        mock_discover_bili_tracks,
        mock_discover_tracks_with_meta,
        mock_download_video,
        mock_infer_download_title,
        mock_process_audio_split,
        mock_transcribe_to_segments,
        mock_dump_segments,
    ):
        mock_discover_bili_tracks.return_value = ([], ApiDiscoveryMeta(cookie_hint=False, endpoint_used="none", warnings=[]))
        mock_discover_tracks_with_meta.return_value = ([], DiscoveryMeta(cookie_hint=False, stderr_summary="", used_cookie_mode="none"))
        mock_download_video.side_effect = lambda suffix: f"dl_{suffix}"
        mock_infer_download_title.side_effect = lambda _bv: "AnyTitle"
        mock_process_audio_split.side_effect = lambda identifier: f"slice_{identifier}"
        def _dump(path, _segments):
            with open(path, "w", encoding="utf-8") as f:
                f.write("[]")

        mock_dump_segments.side_effect = _dump

        active = 0
        max_active = 0
        lock = threading.Lock()

        def transcribe_side_effect(*_args, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return [{"start_sec": 0.0, "end_sec": 1.0, "text": "ok"}]

        mock_transcribe_to_segments.side_effect = transcribe_side_effect

        fake = _FakeAsrWindow()
        with tempfile.TemporaryDirectory() as tmp:
            batch = SimpleNamespace(
                tmp_subtitle_dir=tmp,
                model="small",
                current_task_seq=None,
                media_cache={},
            )
            tasks = [_make_task(1), _make_task(2)]
            errors = []

            def runner(task):
                try:
                    fake._process_task_once(batch, task)
                except Exception as exc:  # pragma: no cover - diagnostic path
                    errors.append(exc)

            threads = [threading.Thread(target=runner, args=(task,)) for task in tasks]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        self.assertFalse(errors)
        self.assertEqual(max_active, 1)
        self.assertTrue(all(task.status == TaskStatus.COMPLETED_ASR for task in tasks))


if __name__ == "__main__":
    unittest.main()
