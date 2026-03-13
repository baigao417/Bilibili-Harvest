import unittest

from core_models import TaskItem, TaskStatus
from state_store import task_from_state_row
from window import MainWindow


class _FakeResumeWindow:
    _next_seq = MainWindow._next_seq
    _task_key = MainWindow._task_key
    _merge_task_from_source_item = MainWindow._merge_task_from_source_item
    _add_task = MainWindow._add_task
    _clone_task_for_restore = MainWindow._clone_task_for_restore
    _restore_task_runtime_fields = MainWindow._restore_task_runtime_fields

    def __init__(self):
        self._seq_counter = 0
        self._tasks = []
        self._task_key_set = set()


def _apply_restored_tasks(fake: _FakeResumeWindow, restored_rows: list[dict]):
    accepted = 0
    for row in restored_rows:
        restored = task_from_state_row(row)
        source = fake._clone_task_for_restore(restored)
        if fake._add_task(source, restored.raw_input):
            accepted += 1
            target = next(
                (t for t in reversed(fake._tasks) if t.bv.upper() == restored.bv.upper() and t.cid == restored.cid),
                None,
            )
            if target is None:
                target = next((t for t in reversed(fake._tasks) if t.bv.upper() == restored.bv.upper()), None)
            if target is not None:
                fake._restore_task_runtime_fields(target, restored)
    return accepted


class ResumeFlowTests(unittest.TestCase):
    def test_merge_restore_keeps_existing_and_adds_new(self):
        fake = _FakeResumeWindow()
        existing = TaskItem(
            seq=1,
            raw_input="BV_EXIST",
            video_link="https://www.bilibili.com/video/BV_EXIST",
            bv="BV_EXIST",
            cid=100,
            title="E",
            owner="UP",
            source_type="single",
        )
        existing.status = TaskStatus.COMPLETED_TRACK
        fake._tasks.append(existing)
        fake._task_key_set.add(("BV_EXIST", 100))
        fake._seq_counter = 1

        restored_rows = [
            {
                "seq": 2,
                "raw_input": "BV_NEW",
                "video_link": "https://www.bilibili.com/video/BV_NEW",
                "bv": "BV_NEW",
                "cid": 200,
                "title": "N",
                "owner": "UP",
                "source_type": "single",
                "status": TaskStatus.FAILED.value,
                "failed_stage": "download",
            }
        ]
        accepted = _apply_restored_tasks(fake, restored_rows)
        self.assertEqual(accepted, 1)
        self.assertEqual(len(fake._tasks), 2)
        restored_task = next(t for t in fake._tasks if t.bv == "BV_NEW")
        self.assertEqual(restored_task.status, TaskStatus.FAILED)

    def test_restore_in_progress_row_becomes_queued(self):
        fake = _FakeResumeWindow()
        restored_rows = [
            {
                "seq": 1,
                "raw_input": "BV_Q",
                "video_link": "https://www.bilibili.com/video/BV_Q",
                "bv": "BV_Q",
                "cid": None,
                "title": "Q",
                "owner": "UP",
                "source_type": "space_uploads",
                "status": TaskStatus.TRANSCRIBING_ASR.value,
            }
        ]
        accepted = _apply_restored_tasks(fake, restored_rows)
        self.assertEqual(accepted, 1)
        self.assertEqual(fake._tasks[0].status, TaskStatus.QUEUED)
        self.assertEqual(fake._tasks[0].subtitle_state, "未获取")


if __name__ == "__main__":
    unittest.main()
