import csv
import glob
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Callable, Optional

from http_utils import sanitize_cookie_header
from runtime_config import DEFAULT_ARCHIVE_ROOT
from runtime_tools import (
    find_executable,
    resolve_cookies_file,
    run_command,
    summarize_error,
)


@dataclass
class TrackInfo:
    lang: str
    track_type: str
    ext: str = "srt"


@dataclass
class Segment:
    start_sec: float
    end_sec: float
    text: str


@dataclass
class DiscoveryMeta:
    cookie_hint: bool = False
    stderr_summary: str = ""
    used_cookie_mode: str = "none"


@dataclass
class ExportSummary:
    exported_count: int
    normal_exported_count: int
    shape_saved_count: int
    skipped_count: int
    formats: list[str]
    target_dir: str
    zip_path: Optional[str] = None


class SubtitleError(RuntimeError):
    pass


DEFAULT_SHAPE_ROOT = DEFAULT_ARCHIVE_ROOT


def _find_yt_dlp() -> str:
    yt_dlp_bin = find_executable("yt-dlp")
    if not yt_dlp_bin:
        raise FileNotFoundError("yt-dlp not found. Install yt-dlp and ensure it is available in PATH.")
    return yt_dlp_bin


def _cookie_attempts(cookie_mode: str, cookies_file: Optional[str], cookie_header: Optional[str] = None):
    manual_cookie = sanitize_cookie_header(cookie_header)
    if manual_cookie:
        return [
            (
                "manual_header",
                [
                    "--add-header",
                    f"Cookie: {manual_cookie}",
                    "--add-header",
                    "Referer: https://www.bilibili.com/",
                ],
            )
        ]

    attempts = []
    if cookie_mode == "auto_chrome":
        attempts.append(("auto_chrome", ["--cookies-from-browser", "chrome"]))
        if cookies_file:
            attempts.append(("cookies_file", ["--cookies", cookies_file]))
        attempts.append(("none", []))
    elif cookie_mode == "cookies_file" and cookies_file:
        attempts.append(("cookies_file", ["--cookies", cookies_file]))
        attempts.append(("none", []))
    elif cookie_mode == "none":
        attempts.append(("none", []))
    else:
        if cookies_file:
            attempts.append(("cookies_file", ["--cookies", cookies_file]))
        attempts.append(("none", []))
    return attempts


def _run_yt_dlp_with_cookie_fallback(
    base_cmd,
    cookie_mode="auto_chrome",
    cookies_file=None,
    cookie_header=None,
    timeout=240,
):
    cookies_file = cookies_file or resolve_cookies_file()
    attempts = _cookie_attempts(cookie_mode, cookies_file, cookie_header=cookie_header)

    last = None
    for mode, cookie_args in attempts:
        cmd = list(base_cmd)
        cmd[1:1] = cookie_args
        result = run_command(cmd, timeout=timeout)
        last = (result, mode)
        if result.returncode == 0:
            return result, mode

        stderr = (result.stderr or "").lower()
        if mode == "auto_chrome" and "could not copy chrome cookie database" in stderr:
            continue
        if mode == "auto_chrome" and "cookies-from-browser" in stderr:
            continue

    if last is None:
        raise SubtitleError("yt-dlp command did not run")
    return last


def _extract_json(stdout: str):
    text = (stdout or "").strip()
    if not text:
        raise SubtitleError("yt-dlp produced empty JSON output")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    raise SubtitleError("failed to parse yt-dlp JSON output")


def _track_is_danmaku(lang: str, fmt_list: list) -> bool:
    if lang == "danmaku":
        return True

    exts = []
    for fmt in fmt_list:
        ext = (fmt or {}).get("ext")
        if ext:
            exts.append(ext.lower())

    return bool(exts) and all(ext == "xml" for ext in exts)


def discover_tracks_with_meta(task, cookie_mode="auto_chrome", cookies_file=None, cookie_header=None):
    yt_dlp_bin = _find_yt_dlp()
    base_cmd = [
        yt_dlp_bin,
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--dump-single-json",
        task.video_link,
    ]

    result, used_mode = _run_yt_dlp_with_cookie_fallback(
        base_cmd,
        cookie_mode=cookie_mode,
        cookies_file=cookies_file,
        cookie_header=cookie_header,
        timeout=300,
    )

    stderr_summary = summarize_error(result.stderr)
    if result.returncode != 0:
        raise SubtitleError(f"subtitle discovery failed: {stderr_summary}")

    payload = _extract_json(result.stdout)
    subtitles = payload.get("subtitles") or {}
    automatic_captions = payload.get("automatic_captions") or {}

    dedup = {}

    def _add_tracks(track_dict: dict, forced_type: Optional[str] = None):
        for lang, fmt_list in track_dict.items():
            fmt_list = fmt_list or []
            if _track_is_danmaku(lang, fmt_list):
                continue

            has_srt = any((fmt or {}).get("ext", "").lower() == "srt" for fmt in fmt_list)
            track_type = forced_type or ("ai" if lang.lower().startswith("ai-") else "uploader")
            ext = "srt" if has_srt else (fmt_list[0].get("ext") if fmt_list else "srt")
            track = TrackInfo(lang=lang, track_type=track_type, ext=ext)

            key = lang.lower()
            existing = dedup.get(key)
            if existing is None:
                dedup[key] = track
                continue
            if existing.track_type == "ai" and track.track_type == "uploader":
                dedup[key] = track

    _add_tracks(subtitles)
    _add_tracks(automatic_captions, forced_type="ai")
    tracks = list(dedup.values())

    stderr_text = (result.stderr or "")
    lower_stderr = stderr_text.lower()
    cookie_hint = (
        (not tracks and "subtitles are only available when logged in" in lower_stderr)
        or (not tracks and "cookies" in lower_stderr)
        or (not tracks and "danmaku" in (payload.get("subtitles") or {}))
    )

    return tracks, DiscoveryMeta(
        cookie_hint=cookie_hint,
        stderr_summary=stderr_summary,
        used_cookie_mode=used_mode,
    )


def discover_tracks(task, cookie_mode="auto_chrome", cookies_file=None, cookie_header=None):
    tracks, _meta = discover_tracks_with_meta(
        task,
        cookie_mode=cookie_mode,
        cookies_file=cookies_file,
        cookie_header=cookie_header,
    )
    return tracks


def select_track(tracks, policy="zh_first"):
    if not tracks:
        return None

    def _track_rank(track: TrackInfo):
        source_rank = 0 if track.track_type == "uploader" else 1
        return source_rank, track.lang.lower()

    if policy != "zh_first":
        return sorted(tracks, key=_track_rank)[0]

    priority = ["zh-CN", "zh-Hans", "zh", "ai-zh"]
    lower_map = {track.lang.lower(): track for track in tracks}

    for lang in priority:
        hit = lower_map.get(lang.lower())
        if hit:
            return hit

    zh_like = [track for track in tracks if track.lang.lower().startswith("zh") or track.lang.lower().startswith("ai-zh")]
    if zh_like:
        return sorted(zh_like, key=_track_rank)[0]

    return sorted(tracks, key=_track_rank)[0]


def download_track_srt(task, track: TrackInfo, cookie_mode="auto_chrome", out_dir=".", cookies_file=None, cookie_header=None):
    yt_dlp_bin = _find_yt_dlp()
    os.makedirs(out_dir, exist_ok=True)

    output_tpl = f"{task.seq:03d}_{task.bv}.%(ext)s"
    base_cmd = [
        yt_dlp_bin,
        "--skip-download",
        "--write-subs",
        "--sub-langs",
        track.lang,
        "--sub-format",
        "srt",
        "--no-part",
        "--force-overwrites",
        "--output",
        output_tpl,
        "--paths",
        out_dir,
        task.video_link,
    ]

    before = set(glob.glob(os.path.join(out_dir, "*.srt")))
    result, _used_mode = _run_yt_dlp_with_cookie_fallback(
        base_cmd,
        cookie_mode=cookie_mode,
        cookies_file=cookies_file,
        cookie_header=cookie_header,
        timeout=300,
    )
    if result.returncode != 0:
        raise SubtitleError(f"subtitle download failed: {summarize_error(result.stderr)}")

    after = set(glob.glob(os.path.join(out_dir, "*.srt")))
    new_files = list(after - before)

    if not new_files:
        candidates = sorted(glob.glob(os.path.join(out_dir, f"*{track.lang}*.srt")), key=os.path.getmtime, reverse=True)
        if candidates:
            return candidates[0]
        candidates = sorted(glob.glob(os.path.join(out_dir, "*.srt")), key=os.path.getmtime, reverse=True)
        if candidates:
            return candidates[0]
        raise SubtitleError("subtitle download succeeded but no srt file was generated")

    new_files.sort(key=os.path.getmtime, reverse=True)
    return new_files[0]


def _parse_srt_timestamp(raw: str) -> float:
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})$", raw.strip())
    if not match:
        raise SubtitleError(f"invalid srt timestamp: {raw}")

    hour, minute, second, milli = match.groups()
    total = int(hour) * 3600 + int(minute) * 60 + int(second)
    ms = int(milli.ljust(3, "0")[:3])
    return total + ms / 1000.0


def parse_srt_to_segments(path: str):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"srt file not found: {path}")

    text = ""
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            with open(path, "r", encoding=encoding) as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue

    if not text:
        return []

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        time_line_idx = 1 if "-->" in lines[1] else 0
        if "-->" not in lines[time_line_idx]:
            continue

        time_line = lines[time_line_idx]
        parts = [item.strip() for item in time_line.split("-->")]
        if len(parts) != 2:
            continue

        try:
            start_sec = _parse_srt_timestamp(parts[0])
            end_sec = _parse_srt_timestamp(parts[1])
        except SubtitleError:
            continue

        text_lines = lines[time_line_idx + 1 :]
        body = " ".join(text_lines).strip()
        if not body:
            continue

        segments.append(Segment(start_sec=start_sec, end_sec=end_sec, text=body))

    return segments


def _format_srt_timestamp(seconds: float) -> str:
    value = max(0.0, float(seconds))
    total_ms = int(round(value * 1000))

    hours = total_ms // 3_600_000
    total_ms %= 3_600_000
    minutes = total_ms // 60_000
    total_ms %= 60_000
    secs = total_ms // 1000
    ms = total_ms % 1000

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _segment_to_dict(seg):
    if isinstance(seg, Segment):
        return {
            "start_sec": float(seg.start_sec),
            "end_sec": float(seg.end_sec),
            "text": str(seg.text),
        }
    return {
        "start_sec": float(seg["start_sec"]),
        "end_sec": float(seg["end_sec"]),
        "text": str(seg["text"]),
    }


def dump_segments_to_tmp_json(path: str, segments):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalized = [_segment_to_dict(seg) for seg in (segments or [])]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    return path


def load_segments_from_tmp_json(path: str):
    if not path or not os.path.isfile(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, list):
        return []

    segments = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if "start_sec" not in item or "end_sec" not in item or "text" not in item:
            continue
        segments.append(
            {
                "start_sec": float(item["start_sec"]),
                "end_sec": float(item["end_sec"]),
                "text": str(item["text"]),
            }
        )
    return segments


# ---------------------------------------------------------------------------
# Pure in-memory MD generation (no file I/O)
# ---------------------------------------------------------------------------

def build_md_header(task, *, source: str = "unknown", language: str = "unknown") -> str:
    """Return the Markdown metadata header block for a task (no trailing body)."""
    lines = [
        "# 视频字幕结果",
        "",
        f"- BV号: {task.bv}",
        f"- 标题: {task.title}",
        f"- 来源: {source}",
        f"- 语言: {language}",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def build_md_body(segments) -> str:
    """Return the body text from *segments* (list[dict] or list[Segment])."""
    parts: list[str] = []
    for seg in segments:
        text = seg.text if isinstance(seg, Segment) else seg["text"]
        line = text.strip()
        if line:
            parts.append(line)
    return "\n\n".join(parts) + ("\n" if parts else "")


def build_md_content(task, segments, *, source: str = "unknown", language: str = "unknown") -> str:
    """Build a complete Markdown document for *task* and *segments* **in memory**.

    This is the single source-of-truth for the MD format; both local export
    (``write_outputs``) and NotebookLM push share this function.
    """
    header = build_md_header(task, source=source, language=language)
    body = build_md_body(segments)
    return header + body


def render_notebooklm_title(task) -> str:
    """Produce a human-readable title for a NotebookLM text source."""
    return f"{task.title} ({task.bv})"


def write_outputs(task, segments, text_dir: str, metadata=None, formats: Optional[set[str]] = None):
    metadata = metadata or {}
    base_name = metadata.get("base_name")
    if not base_name:
        raise SubtitleError("write_outputs requires metadata.base_name")

    selected = {"srt", "txt", "md"} if formats is None else {fmt.lower() for fmt in formats if fmt}
    if not selected:
        raise SubtitleError("write_outputs requires at least one format")

    outputs = {}

    if isinstance(text_dir, dict):
        srt_dir = text_dir.get("srt") or text_dir.get("txt") or text_dir.get("md")
        txt_dir = text_dir.get("txt") or srt_dir
        md_dir = text_dir.get("md") or srt_dir
    else:
        srt_dir = txt_dir = md_dir = text_dir

    for path in {srt_dir, txt_dir, md_dir}:
        if path:
            os.makedirs(path, exist_ok=True)

    if "srt" in selected:
        srt_path = os.path.join(srt_dir, f"{base_name}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for idx, seg in enumerate(segments, start=1):
                start = _format_srt_timestamp(seg.start_sec if isinstance(seg, Segment) else seg["start_sec"])
                end = _format_srt_timestamp(seg.end_sec if isinstance(seg, Segment) else seg["end_sec"])
                text = seg.text if isinstance(seg, Segment) else seg["text"]
                f.write(f"{idx}\n{start} --> {end}\n{text}\n\n")
        outputs["srt"] = srt_path

    if "txt" in selected:
        txt_path = os.path.join(txt_dir, f"{base_name}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            for seg in segments:
                text = seg.text if isinstance(seg, Segment) else seg["text"]
                line = text.strip()
                if line:
                    f.write(line)
                    f.write("\n")
        outputs["txt"] = txt_path

    if "md" in selected:
        md_path = os.path.join(md_dir, f"{base_name}.md")
        source = metadata.get("source") or "unknown"
        language = metadata.get("language") or "unknown"
        md_text = build_md_content(task, segments, source=source, language=language)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        outputs["md"] = md_path

    return outputs


def _is_success(task) -> bool:
    status = getattr(task, "status", None)
    if status is None:
        return False
    value = status.value if hasattr(status, "value") else str(status)
    return value in ("completed_track", "completed_asr", "success")


def _copy_path_to_dir(src_path: str, target_dir: str):
    if not src_path or not os.path.exists(src_path):
        return

    os.makedirs(target_dir, exist_ok=True)
    if os.path.isdir(src_path):
        dst = os.path.join(target_dir, os.path.basename(src_path))
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src_path, dst)
        return

    shutil.copy2(src_path, os.path.join(target_dir, os.path.basename(src_path)))


def write_failed_tasks_json(path: str, tasks: list) -> str:
    if not path:
        raise SubtitleError("failed-state path is required")

    failed_rows = []
    for task in sorted(tasks, key=lambda item: item.seq):
        if _is_success(task):
            continue
        failed_stage = getattr(task, "failed_stage", None)
        failed_rows.append(
            {
                "seq": int(getattr(task, "seq", 0) or 0),
                "bv": str(getattr(task, "bv", "") or ""),
                "cid": getattr(task, "cid", None),
                "title": str(getattr(task, "title", "") or ""),
                "video_link": str(getattr(task, "video_link", "") or ""),
                "status": getattr(task.status, "value", str(task.status)) if getattr(task, "status", None) is not None else "",
                "result_source": str(getattr(task, "result_source", "") or ""),
                "selected_lang": str(getattr(task, "selected_lang", "") or ""),
                "failed_stage": getattr(failed_stage, "value", failed_stage or ""),
                "error": str(getattr(task, "error", "") or ""),
                "cookie_hint": bool(getattr(task, "cookie_hint", False)),
            }
        )

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(failed_rows, f, ensure_ascii=False, indent=2)
    return path


def _safe_title_for_folder(title: str):
    text = (title or "").strip()
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_()[]")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "Untitled"
    return text[:80].rstrip() or "Untitled"


def _load_task_segments(task):
    cache = getattr(task, "segments_cache", None) or []
    if cache:
        return [_segment_to_dict(seg) for seg in cache]

    tmp_json = getattr(task, "segments_tmp_json", "") or ""
    if tmp_json:
        return load_segments_from_tmp_json(tmp_json)
    return []


def export_batch_selected(
    batch,
    selected_formats,
    target_dir,
    export_zip=False,
    shape_root: str = DEFAULT_SHAPE_ROOT,
    save_selector: Optional[Callable[[object], bool]] = None,
    skip_selected_from_normal_export: bool = True,
    nlm_mode: bool = False,
):
    selected = {fmt.lower() for fmt in (selected_formats or {"srt", "txt", "md"}) if fmt}
    selected = selected & {"srt", "txt", "md"}
    if not selected:
        selected = {"srt", "txt", "md"}

    save_selector = save_selector or (lambda _task: False)
    archive_root = os.path.abspath(os.path.expanduser(shape_root or DEFAULT_SHAPE_ROOT))
    os.makedirs(archive_root, exist_ok=True)

    archive_saved_count = 0
    skipped_count = 0

    for task in sorted(batch.tasks, key=lambda item: item.seq):
        if not _is_success(task):
            continue

        segments = _load_task_segments(task)
        if not segments:
            task.outputs = {}
            task.output_file = None
            setattr(task, "export_route", "skipped")
            skipped_count += 1
            continue

        should_save_archive = bool(save_selector(task))
        if nlm_mode and not should_save_archive:
            setattr(task, "export_route", "nlm")
            skipped_count += 1
            continue
        if (not nlm_mode) and (not should_save_archive):
            setattr(task, "export_route", "unselected")
            skipped_count += 1
            continue

        safe_title = _safe_title_for_folder(task.title)
        folder_name = f"{safe_title}_{task.bv}"
        base_name = folder_name
        task_root = os.path.join(archive_root, folder_name)
        text_dir = os.path.join(task_root, "text")
        setattr(task, "shape_folder_name", folder_name)

        outputs = write_outputs(
            task,
            segments,
            text_dir=text_dir,
            metadata={
                "base_name": base_name,
                "source": task.result_source or "unknown",
                "language": task.selected_lang or "unknown",
            },
            formats=selected,
        )

        video_src = getattr(task, "video_file_path", "")
        audio_src = getattr(task, "audio_file_path", "")
        _copy_path_to_dir(video_src, os.path.join(task_root, "video"))
        _copy_path_to_dir(audio_src, os.path.join(task_root, "audio"))

        archive_error = getattr(task, "asset_prepare_error", "") or ""
        if not video_src or not os.path.exists(video_src):
            archive_error = (archive_error + "; " if archive_error else "") + "video missing"
        if not audio_src or not os.path.exists(audio_src):
            archive_error = (archive_error + "; " if archive_error else "") + "audio missing"

        setattr(task, "shape_save_error", archive_error)
        setattr(task, "export_route", "archive_failed" if archive_error else "archive")
        task.outputs = outputs
        task.output_file = outputs.get("md")
        archive_saved_count += 1

    failed_state_path = getattr(batch, "failed_state_path", "") or ""
    if failed_state_path:
        write_failed_tasks_json(failed_state_path, batch.tasks)

    return ExportSummary(
        exported_count=archive_saved_count,
        normal_exported_count=0,
        shape_saved_count=archive_saved_count,
        skipped_count=skipped_count,
        formats=sorted(selected),
        target_dir=archive_root,
        zip_path=None,
    )
