"""Unit tests for the NotebookLM integration layer.

These tests do NOT require the ``notebooklm-py`` library or internet access;
they validate the adapter logic, state-store serialization of NLM fields,
runtime-config persistence, and the MD builder reuse path.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from core_models import BatchContext, TaskItem, TaskStatus
from state_store import save_batch_state, task_from_state_row, _serialize_task
from runtime_config import RuntimeConfig, load_runtime_config, save_runtime_config
from subtitle_pipeline import build_md_content, build_md_header, build_md_body, render_notebooklm_title


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(seq: int = 1, **overrides) -> TaskItem:
    defaults = dict(
        seq=seq,
        raw_input=f"BV{seq:010d}",
        video_link=f"https://www.bilibili.com/video/BV{seq:010d}",
        bv=f"BV{seq:010d}",
        aid=seq,
        cid=seq * 10,
        owner="tester",
        source_type="single",
        title=f"TestTitle{seq}",
    )
    defaults.update(overrides)
    task = TaskItem(**{k: v for k, v in defaults.items() if k in TaskItem.__dataclass_fields__})
    for k, v in overrides.items():
        if k not in TaskItem.__dataclass_fields__:
            setattr(task, k, v)
    task.status = overrides.get("status", TaskStatus.COMPLETED_TRACK)
    task.subtitle_state = "已获取(轨道)"
    task.result_source = overrides.get("result_source", "api_track")
    task.selected_lang = overrides.get("selected_lang", "zh-CN")
    return task


def _make_batch(tasks=None) -> BatchContext:
    tasks = tasks or [_make_task(1)]
    return BatchContext(
        batch_id="test_batch",
        started_at=datetime.now(),
        model="small",
        tasks=tasks,
        total_count=len(tasks),
        done_count=len(tasks),
        success_count=len(tasks),
        failed_count=0,
        export_dir="",
        state_path="",
        io_workers=1,
        is_running=False,
        state_version="1",
        core_version="2.2.0",
    )


# ---------------------------------------------------------------------------
# State-store NLM field tests
# ---------------------------------------------------------------------------

class TestStateStoreNlmFields(unittest.TestCase):
    """Verify NLM fields survive serialization round-trip."""

    def test_serialize_nlm_fields(self):
        task = _make_task(1)
        task.nlm_source_id = "src_abc123"
        task.nlm_push_status = "pushed"
        row = _serialize_task(task)
        self.assertEqual(row["nlm_source_id"], "src_abc123")
        self.assertEqual(row["nlm_push_status"], "pushed")

    def test_deserialize_nlm_fields(self):
        row = {
            "seq": 1, "raw_input": "BV1", "video_link": "", "bv": "BV1",
            "title": "T", "status": "completed_track", "owner": "u",
            "nlm_source_id": "src_xyz", "nlm_push_status": "pushed",
        }
        task = task_from_state_row(row)
        self.assertEqual(task.nlm_source_id, "src_xyz")
        self.assertEqual(task.nlm_push_status, "pushed")

    def test_pushing_status_rollback_on_restore(self):
        row = {
            "seq": 1, "raw_input": "BV1", "video_link": "", "bv": "BV1",
            "title": "T", "status": "completed_track", "owner": "u",
            "nlm_push_status": "pushing",
        }
        task = task_from_state_row(row)
        self.assertEqual(task.nlm_push_status, "", "Should rollback 'pushing' to empty on restore")

    def test_missing_nlm_fields_default_empty(self):
        row = {
            "seq": 1, "raw_input": "BV1", "video_link": "", "bv": "BV1",
            "title": "T", "status": "queued", "owner": "u",
        }
        task = task_from_state_row(row)
        self.assertEqual(task.nlm_source_id, "")
        self.assertEqual(task.nlm_push_status, "")

    def test_round_trip_via_batch_state(self):
        task = _make_task(1)
        task.nlm_source_id = "src_roundtrip"
        task.nlm_push_status = "pushed"
        batch = _make_batch([task])
        with tempfile.TemporaryDirectory() as tmp:
            batch.state_path = os.path.join(tmp, "state.json")
            save_batch_state(batch, reason="nlm_test")
            with open(batch.state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            row = payload["tasks"][0]
            self.assertEqual(row["nlm_source_id"], "src_roundtrip")
            self.assertEqual(row["nlm_push_status"], "pushed")


# ---------------------------------------------------------------------------
# RuntimeConfig NLM field tests
# ---------------------------------------------------------------------------

class TestRuntimeConfigNlmFields(unittest.TestCase):

    def test_default_values(self):
        cfg = RuntimeConfig()
        self.assertTrue(cfg.notebooklm_enabled)
        self.assertEqual(cfg.notebooklm_notebook_id, "")
        self.assertTrue(cfg.notebooklm_auto_clean)

    def test_save_and_load_nlm_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "runtime.json")
            cfg = RuntimeConfig()
            cfg.notebooklm_enabled = False
            cfg.notebooklm_notebook_id = "nb_123"
            cfg.notebooklm_auto_clean = False
            save_runtime_config(cfg, path=path)
            loaded = load_runtime_config(path=path)
            self.assertFalse(loaded.notebooklm_enabled)
            self.assertEqual(loaded.notebooklm_notebook_id, "nb_123")
            self.assertFalse(loaded.notebooklm_auto_clean)


# ---------------------------------------------------------------------------
# MD builder tests (single source of truth)
# ---------------------------------------------------------------------------

class TestMdBuilders(unittest.TestCase):

    def test_build_md_header(self):
        task = _make_task(1)
        header = build_md_header(task, source="api_track", language="zh-CN")
        self.assertIn("# 视频字幕结果", header)
        self.assertIn(task.bv, header)
        self.assertIn("api_track", header)

    def test_build_md_body(self):
        segments = [{"text": "Hello"}, {"text": "World"}]
        body = build_md_body(segments)
        self.assertIn("Hello", body)
        self.assertIn("World", body)

    def test_build_md_content_combines_header_and_body(self):
        task = _make_task(1)
        segments = [{"text": "Line1"}, {"text": "Line2"}]
        md = build_md_content(task, segments, source="asr", language="en")
        self.assertIn("# 视频字幕结果", md)
        self.assertIn("Line1", md)
        self.assertIn("Line2", md)
        self.assertIn("asr", md)

    def test_render_notebooklm_title(self):
        task = _make_task(1)
        title = render_notebooklm_title(task)
        self.assertEqual(title, f"{task.title} ({task.bv})")


# ---------------------------------------------------------------------------
# notebooklm_client module tests (no real network)
# ---------------------------------------------------------------------------

class TestNlmClientModule(unittest.TestCase):
    """Test the adapter module can import and provides safe fallbacks."""

    def test_import_succeeds(self):
        import notebooklm_client as nc
        # AuthStatus enum should always be available
        self.assertTrue(hasattr(nc, "AuthStatus"))
        self.assertTrue(hasattr(nc, "is_nlm_available"))
        self.assertTrue(hasattr(nc, "check_auth_available"))

    def test_lib_missing_returns_correct_status(self):
        import notebooklm_client as nc
        if not nc.is_nlm_available():
            status = nc.check_auth_available()
            self.assertEqual(status, nc.AuthStatus.LIB_MISSING)

    def test_push_result_struct(self):
        import notebooklm_client as nc
        result = nc.NlmPushResult()
        self.assertEqual(result.pushed, 0)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.total, 0)
        self.assertIsInstance(result.errors, list)
        self.assertIsInstance(result.results, dict)


# ---------------------------------------------------------------------------
# core_models NLM field defaults
# ---------------------------------------------------------------------------

class TestCoreModelsNlmDefaults(unittest.TestCase):

    def test_task_nlm_defaults(self):
        task = TaskItem(
            seq=1, raw_input="BV1", video_link="", bv="BV1",
            title="T", owner="u",
        )
        self.assertEqual(task.nlm_source_id, "")
        self.assertEqual(task.nlm_push_status, "")


if __name__ == "__main__":
    unittest.main()
