import json
import os
import tempfile
import unittest
from datetime import datetime

from core_models import BatchContext, FailStage, TaskItem, TaskStatus
from state_store import StateStoreError, load_batch_state, save_batch_state, task_from_state_row


def _make_task(seq: int, status: TaskStatus) -> TaskItem:
    task = TaskItem(
        seq=seq,
        raw_input=f"BV{seq}",
        video_link=f"https://www.bilibili.com/video/BV{seq}",
        bv=f"BV{seq}",
        aid=seq,
        cid=seq * 10,
        owner="tester",
        source_type="single",
        title=f"Title{seq}",
    )
    task.status = status
    task.subtitle_state = "已获取(轨道)" if status == TaskStatus.COMPLETED_TRACK else "未获取"
    task.temp_paths = ["tmp1", "tmp2"]
    task.segments_cache = [{"start_sec": 0.0, "end_sec": 1.0, "text": "hello"}]
    task.outputs = {"txt": "x.txt"}
    task.video_file_path = "video.mp4"
    task.audio_file_path = "audio.mp3"
    return task


class StateStoreTests(unittest.TestCase):
    def test_save_and_load_state_with_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = BatchContext(
                batch_id="batch1",
                started_at=datetime.now(),
                model="small",
                tasks=[_make_task(1, TaskStatus.COMPLETED_TRACK), _make_task(2, TaskStatus.QUEUED)],
                total_count=2,
                done_count=1,
                success_count=1,
                failed_count=0,
                export_dir=tmp,
                state_path=os.path.join(tmp, "state.json"),
                io_workers=2,
                is_running=True,
                state_version="1",
                core_version="2.2.0",
            )

            path = save_batch_state(batch, reason="unit_test")
            self.assertTrue(os.path.isfile(path))
            payload = load_batch_state(path, expected_core_version=batch.core_version)
            self.assertEqual(payload["batch"]["batch_id"], "batch1")
            self.assertEqual(len(payload["tasks"]), 2)

            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            first = saved["tasks"][0]
            self.assertNotIn("temp_paths", first)
            self.assertNotIn("segments_cache", first)
            self.assertNotIn("video_file_path", first)
            self.assertNotIn("audio_file_path", first)

    def test_checksum_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            payload = {
                "schema_version": "1",
                "core_version": "2.2.0",
                "batch": {"batch_id": "x"},
                "tasks": [],
                "checksum": "broken",
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            with self.assertRaises(StateStoreError):
                load_batch_state(path)

    def test_task_from_state_row_normalizes_in_progress_to_queued(self):
        row = {
            "seq": 1,
            "raw_input": "BV1",
            "video_link": "https://www.bilibili.com/video/BV1",
            "bv": "BV1",
            "status": TaskStatus.TRANSCRIBING_ASR.value,
            "source_type": "single",
            "title": "T",
        }
        task = task_from_state_row(row)
        self.assertEqual(task.status, TaskStatus.QUEUED)
        self.assertEqual(task.subtitle_state, "未获取")

    def test_task_from_state_row_preserves_failed_terminal(self):
        row = {
            "seq": 2,
            "raw_input": "BV2",
            "video_link": "https://www.bilibili.com/video/BV2",
            "bv": "BV2",
            "status": TaskStatus.FAILED.value,
            "failed_stage": FailStage.TRANSCRIBE.value,
            "error": "boom",
            "source_type": "single",
            "title": "T2",
        }
        task = task_from_state_row(row)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.failed_stage, FailStage.TRANSCRIBE)
        self.assertIn("失败", task.subtitle_state)


if __name__ == "__main__":
    unittest.main()
