import unittest

from plugins.types import SourceItem
from window import MainWindow, TaskStatus


class _FakeWindow:
    _next_seq = MainWindow._next_seq
    _task_key = MainWindow._task_key
    _merge_task_from_source_item = MainWindow._merge_task_from_source_item
    _add_task = MainWindow._add_task

    def __init__(self):
        self._seq_counter = 0
        self._tasks = []
        self._task_key_set = set()


class DedupePolicyTests(unittest.TestCase):
    def test_weak_key_upgraded_by_strong_key(self):
        fake = _FakeWindow()
        weak = SourceItem(
            bvid="BV1TEST",
            cid=None,
            title="Weak",
            source_type="space_uploads",
            video_url="https://www.bilibili.com/video/BV1TEST",
        )
        strong = SourceItem(
            bvid="BV1TEST",
            cid=123,
            title="Strong",
            source_type="multi_p",
            video_url="https://www.bilibili.com/video/BV1TEST",
        )

        self.assertTrue(fake._add_task(weak, "space"))
        self.assertTrue(fake._add_task(strong, "pages"))
        self.assertEqual(len(fake._tasks), 1)
        self.assertEqual(fake._tasks[0].cid, 123)
        self.assertEqual(fake._tasks[0].status, TaskStatus.QUEUED)

    def test_reject_weak_if_strong_exists(self):
        fake = _FakeWindow()
        strong = SourceItem(
            bvid="BV1TEST",
            cid=123,
            title="Strong",
            source_type="single",
            video_url="https://www.bilibili.com/video/BV1TEST",
        )
        weak = SourceItem(
            bvid="BV1TEST",
            cid=None,
            title="Weak",
            source_type="space_uploads",
            video_url="https://www.bilibili.com/video/BV1TEST",
        )

        self.assertTrue(fake._add_task(strong, "single"))
        self.assertFalse(fake._add_task(weak, "space"))
        self.assertEqual(len(fake._tasks), 1)

    def test_allow_multiple_strong_keys_for_same_bv(self):
        fake = _FakeWindow()
        p1 = SourceItem(
            bvid="BV1TEST",
            cid=111,
            title="P1",
            source_type="multi_p",
            video_url="https://www.bilibili.com/video/BV1TEST",
        )
        p2 = SourceItem(
            bvid="BV1TEST",
            cid=222,
            title="P2",
            source_type="multi_p",
            video_url="https://www.bilibili.com/video/BV1TEST",
        )

        self.assertTrue(fake._add_task(p1, "p1"))
        self.assertTrue(fake._add_task(p2, "p2"))
        self.assertEqual(len(fake._tasks), 2)


if __name__ == "__main__":
    unittest.main()
