import hashlib
import json
import os
from datetime import datetime
from typing import Optional

from app_version import CORE_VERSION, STATE_SCHEMA_VERSION
from core_models import BatchContext, FailStage, TaskItem, TaskStatus


class StateStoreError(RuntimeError):
    pass


def _compute_checksum(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _serialize_task(task: TaskItem) -> dict:
    failed_stage = task.failed_stage.value if isinstance(task.failed_stage, FailStage) else (task.failed_stage or "")
    status_value = task.status.value if isinstance(task.status, TaskStatus) else str(task.status)

    return {
        "seq": int(task.seq),
        "raw_input": task.raw_input,
        "video_link": task.video_link,
        "bv": task.bv,
        "aid": task.aid,
        "cid": task.cid,
        "owner": task.owner,
        "source_type": task.source_type,
        "source_meta": dict(task.source_meta or {}),
        "page": task.page,
        "page_title": task.page_title,
        "title": task.title,
        "status": status_value,
        "failed_stage": failed_stage,
        "error": task.error or "",
        "retry_count": int(task.retry_count or 0),
        "save_selected": bool(task.save_selected),
        "result_source": task.result_source or "",
        "selected_lang": task.selected_lang or "",
        "cookie_hint": bool(task.cookie_hint),
        "nlm_source_id": task.nlm_source_id or "",
        "nlm_push_status": task.nlm_push_status or "",
    }


def serialize_batch_state(batch: BatchContext, reason: str = "") -> dict:
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "core_version": CORE_VERSION,
        "reason": reason,
        "batch": {
            "batch_id": batch.batch_id,
            "started_at": batch.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "model": batch.model,
            "io_workers": int(batch.io_workers or 2),
            "total_count": int(batch.total_count or 0),
            "done_count": int(batch.done_count or 0),
            "success_count": int(batch.success_count or 0),
            "failed_count": int(batch.failed_count or 0),
            "is_running": bool(batch.is_running),
            "resumed_from": batch.resumed_from or "",
            "state_version": batch.state_version or STATE_SCHEMA_VERSION,
            "exported_once": bool(batch.exported_once),
            "export_dir": batch.export_dir,
        },
        "tasks": [_serialize_task(task) for task in sorted(batch.tasks, key=lambda item: item.seq)],
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    payload["checksum"] = _compute_checksum(payload)
    return payload


def save_batch_state(batch: BatchContext, reason: str = "") -> str:
    path = batch.state_path
    if not path:
        raise StateStoreError("batch.state_path is empty")

    payload = serialize_batch_state(batch, reason=reason)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp, path)
    return path


def load_batch_state(path: str, *, expected_core_version: Optional[str] = None) -> dict:
    if not os.path.isfile(path):
        raise StateStoreError(f"state file not found: {path}")

    with open(path, "r", encoding="utf-8-sig") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise StateStoreError("invalid state payload")

    checksum = payload.get("checksum") or ""
    verify_payload = dict(payload)
    verify_payload.pop("checksum", None)
    verify_payload["checksum"] = _compute_checksum(verify_payload)
    if checksum and verify_payload["checksum"] != checksum:
        raise StateStoreError("state checksum mismatch")

    core_version = str(payload.get("core_version") or "")
    if expected_core_version and core_version and core_version != expected_core_version:
        raise StateStoreError(f"state core_version mismatch: {core_version} != {expected_core_version}")

    return payload


def find_latest_state_file(states_root: str = os.path.join("config", "batches")) -> Optional[str]:
    if not os.path.isdir(states_root):
        return None

    latest = None
    latest_mtime = -1.0
    for name in os.listdir(states_root):
        state_path = os.path.join(states_root, name, "state.json")
        if not os.path.isfile(state_path):
            continue
        try:
            mtime = os.path.getmtime(state_path)
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = state_path
    return latest


def task_from_state_row(row: dict) -> TaskItem:
    status_raw = str(row.get("status") or TaskStatus.QUEUED.value)
    try:
        status = TaskStatus(status_raw)
    except Exception:
        status = TaskStatus.QUEUED

    failed_stage_raw = str(row.get("failed_stage") or "").strip()
    failed_stage = None
    if failed_stage_raw:
        try:
            failed_stage = FailStage(failed_stage_raw)
        except Exception:
            failed_stage = None

    task = TaskItem(
        seq=int(row.get("seq") or 0),
        raw_input=str(row.get("raw_input") or ""),
        video_link=str(row.get("video_link") or ""),
        bv=str(row.get("bv") or ""),
        aid=row.get("aid"),
        cid=row.get("cid"),
        owner=str(row.get("owner") or "UnknownUP"),
        source_type=str(row.get("source_type") or "single"),
        source_meta=dict(row.get("source_meta") or {}),
        page=row.get("page"),
        page_title=str(row.get("page_title") or ""),
        status=status,
        title=str(row.get("title") or "UnknownTitle"),
    )
    task.failed_stage = failed_stage
    task.error = str(row.get("error") or "")
    task.retry_count = int(row.get("retry_count") or 0)
    task.save_selected = bool(row.get("save_selected"))
    task.result_source = str(row.get("result_source") or "")
    task.selected_lang = str(row.get("selected_lang") or "")
    task.cookie_hint = bool(row.get("cookie_hint"))
    task.nlm_source_id = str(row.get("nlm_source_id") or "")
    task.nlm_push_status = str(row.get("nlm_push_status") or "")

    # Rollback incomplete NLM push status on restore
    if task.nlm_push_status == "pushing":
        task.nlm_push_status = ""

    if task.status in (TaskStatus.RESOLVING_TRACKS, TaskStatus.DOWNLOADING_TRACK, TaskStatus.TRANSCRIBING_ASR):
        task.status = TaskStatus.QUEUED
        task.subtitle_state = "未获取"
        task.failed_stage = None
        task.error = ""
    elif task.status == TaskStatus.FAILED:
        task.subtitle_state = f"失败: {task.failed_stage.value if task.failed_stage else 'unknown'}"
    elif task.status == TaskStatus.COMPLETED_TRACK:
        task.subtitle_state = "已获取(轨道)"
    elif task.status == TaskStatus.COMPLETED_ASR:
        task.subtitle_state = "已获取(ASR)"
    else:
        task.subtitle_state = "未获取"

    return task
