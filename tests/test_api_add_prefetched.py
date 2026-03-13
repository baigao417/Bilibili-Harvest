import threading
import unittest

from plugins.types import SourceItem
from window import MainWindow, TaskStatus


class _FakePrefetchWindow:
    _normalize_api_options = MainWindow._normalize_api_options
    _sanitize_prefetched_segments = MainWindow._sanitize_prefetched_segments
    _normalize_prefetched_subtitle = MainWindow._normalize_prefetched_subtitle
    _prefetch_status_bindable = MainWindow._prefetch_status_bindable
    _apply_prefetched_to_task = MainWindow._apply_prefetched_to_task
    _upsert_task_from_source_item = MainWindow._upsert_task_from_source_item
    _select_prefetch_source_item = MainWindow._select_prefetch_source_item
    _handle_api_add_prefetched = MainWindow._handle_api_add_prefetched
    _task_key = MainWindow._task_key
    _merge_task_from_source_item = MainWindow._merge_task_from_source_item
    _next_seq = MainWindow._next_seq

    def __init__(self):
        self._state_lock = threading.Lock()
        self._tasks = []
        self._task_key_set = set()
        self._seq_counter = 0
        self._warnings = []

    def _resolve_source_items(self, text, source_type, import_mode, limit, order, cookie_header):
        _ = (text, source_type, import_mode, limit, order, cookie_header)
        return [
            SourceItem(
                bvid="BV1TEST12345",
                aid=11,
                cid=22,
                title="T",
                owner="UP",
                source_type="single",
                page=1,
                page_title="P1",
                video_url="https://www.bilibili.com/video/BV1TEST12345",
                source_meta={},
            )
        ]

    def _refresh_table(self):
        return None

    def _log(self, msg, **_kwargs):
        self._warnings.append(msg)


class ApiAddPrefetchedTests(unittest.TestCase):
    def test_validator_filters_invalid_segments(self):
        fake = _FakePrefetchWindow()
        cleaned = fake._sanitize_prefetched_segments(
            [
                {"start_sec": -1, "end_sec": 1, "text": "neg"},
                {"start_sec": 2, "end_sec": 1, "text": "reverse"},
                {"start_sec": 0, "end_sec": 1, "text": ""},
                {"start_sec": 0.0, "end_sec": 1.5, "text": "ok"},
            ]
        )
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["text"], "ok")

    def test_add_prefetched_binds_for_new_task(self):
        fake = _FakePrefetchWindow()
        resp = fake._handle_api_add_prefetched(
            {
                "source_type": "single",
                "input": "https://www.bilibili.com/video/BV1TEST12345",
                "options": {"import_mode": "single", "cookie_header": "SESSDATA=abc"},
                "prefetched_subtitle": {
                    "aid": 11,
                    "cid": 22,
                    "lang": "zh-CN",
                    "track_type": "uploader",
                    "segments": [{"start_sec": 0.0, "end_sec": 1.0, "text": "hello"}],
                },
            }
        )

        self.assertTrue(resp["ok"])
        self.assertEqual(resp["accepted"], 1)
        self.assertTrue(resp["prefetch_bound"])
        self.assertEqual(resp["prefetch_reason"], "bound")
        self.assertEqual(len(fake._tasks), 1)
        task = fake._tasks[0]
        self.assertEqual(task.prefetched_segments[0]["text"], "hello")
        self.assertEqual(task.prefetched_meta["lang"], "zh-CN")
        self.assertEqual(task.request_cookie_header, "SESSDATA=abc")

    def test_duplicate_queued_task_allows_prefetch_override(self):
        fake = _FakePrefetchWindow()
        first = fake._handle_api_add_prefetched(
            {
                "source_type": "single",
                "input": "https://www.bilibili.com/video/BV1TEST12345",
                "prefetched_subtitle": {
                    "aid": 11,
                    "cid": 22,
                    "lang": "zh-CN",
                    "track_type": "uploader",
                    "segments": [{"start_sec": 0.0, "end_sec": 1.0, "text": "first"}],
                },
            }
        )
        self.assertTrue(first["prefetch_bound"])

        second = fake._handle_api_add_prefetched(
            {
                "source_type": "single",
                "input": "https://www.bilibili.com/video/BV1TEST12345",
                "prefetched_subtitle": {
                    "aid": 11,
                    "cid": 22,
                    "lang": "zh-CN",
                    "track_type": "uploader",
                    "segments": [{"start_sec": 0.0, "end_sec": 1.0, "text": "second"}],
                },
            }
        )
        self.assertTrue(second["ok"])
        self.assertEqual(second["accepted"], 0)
        self.assertEqual(second["duplicates"], 1)
        self.assertTrue(second["prefetch_bound"])
        self.assertEqual(fake._tasks[0].prefetched_segments[0]["text"], "second")

    def test_duplicate_non_bindable_status_rejects_prefetch(self):
        fake = _FakePrefetchWindow()
        fake._handle_api_add_prefetched(
            {
                "source_type": "single",
                "input": "https://www.bilibili.com/video/BV1TEST12345",
                "prefetched_subtitle": {
                    "aid": 11,
                    "cid": 22,
                    "lang": "zh-CN",
                    "track_type": "uploader",
                    "segments": [{"start_sec": 0.0, "end_sec": 1.0, "text": "first"}],
                },
            }
        )
        fake._tasks[0].status = TaskStatus.COMPLETED_TRACK
        fake._tasks[0].prefetched_segments = []
        fake._tasks[0].prefetched_meta = {}

        second = fake._handle_api_add_prefetched(
            {
                "source_type": "single",
                "input": "https://www.bilibili.com/video/BV1TEST12345",
                "prefetched_subtitle": {
                    "aid": 11,
                    "cid": 22,
                    "lang": "zh-CN",
                    "track_type": "uploader",
                    "segments": [{"start_sec": 0.0, "end_sec": 1.0, "text": "second"}],
                },
            }
        )
        self.assertTrue(second["ok"])
        self.assertFalse(second["prefetch_bound"])
        self.assertTrue(str(second["prefetch_reason"]).startswith("status_not_bindable"))
        self.assertEqual(fake._tasks[0].prefetched_segments, [])

    def test_invalid_prefetch_segments_still_adds_task(self):
        fake = _FakePrefetchWindow()
        resp = fake._handle_api_add_prefetched(
            {
                "source_type": "single",
                "input": "https://www.bilibili.com/video/BV1TEST12345",
                "prefetched_subtitle": {
                    "aid": 11,
                    "cid": 22,
                    "segments": [{"start_sec": -1.0, "end_sec": 1.0, "text": "bad"}],
                },
            }
        )
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["accepted"], 1)
        self.assertFalse(resp["prefetch_bound"])
        self.assertEqual(resp["prefetch_reason"], "prefetched_segments_empty")
        self.assertEqual(len(fake._tasks), 1)


if __name__ == "__main__":
    unittest.main()
