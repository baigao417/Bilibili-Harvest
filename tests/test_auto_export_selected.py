import threading
import unittest
from types import SimpleNamespace

from window import MainWindow, TaskStatus


class _DummySignal:
    def __init__(self):
        self.calls = []

    def emit(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _DummyButton:
    def __init__(self):
        self.enabled = False

    def setEnabled(self, value):
        self.enabled = bool(value)


class _FakeBatchFinishWindow:
    _should_auto_export_selected_batch = MainWindow._should_auto_export_selected_batch
    _maybe_auto_export_selected_batch = MainWindow._maybe_auto_export_selected_batch
    _on_batch_finished = MainWindow._on_batch_finished

    def __init__(self, export_result=None):
        self._state_lock = threading.Lock()
        self._last_batch = None
        self._current_batch = None
        self._current_stage_text = ""
        self._worker_thread = object()
        self._stop_requested = False
        self.btn_submit = _DummyButton()
        self.progress_signal = _DummySignal()
        self.table_refresh_signal = _DummySignal()
        self.export_calls = []
        self.logs = []
        self._export_result = export_result or {"ok": True, "shape_saved_count": 1}

    def _svc_export_batch(self, formats=None, export_zip=False, target_dir=None, notebook_id="", nlm_auto_clean=True):
        self.export_calls.append(
            {
                "formats": list(formats or []),
                "export_zip": export_zip,
                "target_dir": target_dir,
                "notebook_id": notebook_id,
                "nlm_auto_clean": nlm_auto_clean,
            }
        )
        return dict(self._export_result)

    def _log(self, message, level="INFO", stage=None, task=None):
        self.logs.append({"message": message, "level": level, "stage": stage, "task": task})


def _make_batch(*, save_selected: bool, status=TaskStatus.COMPLETED_ASR, success_count=1, exported_once=False):
    task = SimpleNamespace(save_selected=save_selected, status=status)
    return SimpleNamespace(
        tasks=[task],
        success_count=success_count,
        failed_count=0,
        done_count=1,
        total_count=1,
        exported_once=exported_once,
    )


class AutoExportSelectedBatchTests(unittest.TestCase):
    def test_should_auto_export_only_for_selected_success_tasks(self):
        fake = _FakeBatchFinishWindow()
        self.assertTrue(fake._should_auto_export_selected_batch(_make_batch(save_selected=True), stopped=False))
        self.assertFalse(fake._should_auto_export_selected_batch(_make_batch(save_selected=False), stopped=False))
        self.assertFalse(
            fake._should_auto_export_selected_batch(
                _make_batch(save_selected=True, status=TaskStatus.FAILED, success_count=0),
                stopped=False,
            )
        )
        self.assertFalse(fake._should_auto_export_selected_batch(_make_batch(save_selected=True), stopped=True))
        self.assertFalse(
            fake._should_auto_export_selected_batch(_make_batch(save_selected=True, exported_once=True), stopped=False)
        )

    def test_on_batch_finished_auto_exports_selected_tasks(self):
        fake = _FakeBatchFinishWindow()
        batch = _make_batch(save_selected=True)

        fake._on_batch_finished(batch)

        self.assertEqual(len(fake.export_calls), 1)
        self.assertEqual(fake.export_calls[0]["formats"], ["srt", "txt", "md"])
        self.assertTrue(fake.btn_submit.enabled)

    def test_on_batch_finished_skips_auto_export_for_plain_batches(self):
        fake = _FakeBatchFinishWindow()
        batch = _make_batch(save_selected=False)

        fake._on_batch_finished(batch)

        self.assertEqual(fake.export_calls, [])


if __name__ == "__main__":
    unittest.main()
