import glob
import os
from datetime import datetime
from typing import Callable, Optional

import whisper

from runtime_config import DEFAULT_ARCHIVE_ROOT

from runtime_tools import find_ffmpeg, find_ffprobe, run_command


whisper_model = None


def is_cuda_available():
    return whisper.torch.cuda.is_available()


def _ensure_ffmpeg_in_path():
    ffmpeg_bin = find_ffmpeg()
    ffmpeg_dir = os.path.dirname(ffmpeg_bin)
    current_path = os.environ.get("PATH", "")
    path_entries = current_path.split(os.pathsep) if current_path else []
    normalized_target = os.path.normcase(os.path.normpath(ffmpeg_dir))

    has_path = any(
        os.path.normcase(os.path.normpath(entry)) == normalized_target
        for entry in path_entries
        if entry
    )

    if not has_path:
        os.environ["PATH"] = f"{ffmpeg_dir}{os.pathsep}{current_path}" if current_path else ffmpeg_dir
        print(f"ffmpeg path injected for Whisper: {ffmpeg_dir}")

    return ffmpeg_bin


def load_whisper(model="tiny"):
    global whisper_model
    _ensure_ffmpeg_in_path()
    whisper_model = whisper.load_model(model, device="cuda" if is_cuda_available() else "cpu")
    print(f"Whisper model loaded: {model}")


def _slice_sort_key(file_name):
    stem = os.path.splitext(file_name)[0]
    if stem.isdigit():
        return (0, int(stem))
    return (1, stem)


def _resolve_slice_dir(filename: str) -> str:
    if os.path.isdir(filename):
        return filename

    maybe_dir = os.path.join("audio", "slice", filename)
    if os.path.isdir(maybe_dir):
        return maybe_dir

    raise FileNotFoundError(f"Slice folder not found: {filename}")


def _probe_audio_duration_seconds(file_path: str) -> Optional[float]:
    ffprobe_bin = find_ffprobe()
    result = run_command(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        timeout=120,
    )
    if result.returncode != 0:
        return None

    text = (result.stdout or "").strip()
    if not text:
        return None

    try:
        value = float(text)
    except ValueError:
        return None

    if value <= 0:
        return None
    return value


def _build_markdown_header(metadata, model_name):
    safe_meta = metadata or {}
    lines = ["# 视频转写结果", ""]

    bv = safe_meta.get("bv")
    title = safe_meta.get("title")
    model = safe_meta.get("model") or f"whisper-{model_name}"

    if bv:
        lines.append(f"- BV号: {bv}")
    if title:
        lines.append(f"- 标题: {title}")
    if model:
        lines.append(f"- 模型: {model}")
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.extend(["", "---", ""])
    return "\n".join(lines)


def transcribe_to_segments(
    slice_folder,
    model="small",
    prompt="以下是普通话句子。",
    fallback_slice_seconds=45.0,
    progress_callback: Optional[Callable[[int, int], None]] = None,
):
    global whisper_model

    _ensure_ffmpeg_in_path()
    if whisper_model is None:
        print("Whisper model is not loaded, loading now...")
        load_whisper(model=model)

    slice_dir = _resolve_slice_dir(slice_folder)
    audio_files = sorted(
        [
            item
            for item in os.listdir(slice_dir)
            if item.lower().endswith((".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"))
        ],
        key=_slice_sort_key,
    )
    if not audio_files:
        raise FileNotFoundError(f"No audio slices found in: {slice_dir}")

    preview = ", ".join(audio_files[:5])
    if len(audio_files) > 5:
        preview += ", ..."
    print(f"Detected {len(audio_files)} audio slices: {preview}")

    segments = []
    global_offset = 0.0

    for index, audio_file in enumerate(audio_files, start=1):
        if progress_callback:
            progress_callback(index, len(audio_files))

        full_path = os.path.join(slice_dir, audio_file)
        print(f"Transcribing {index}/{len(audio_files)}: {audio_file}")
        result = whisper_model.transcribe(full_path, initial_prompt=prompt)

        for seg in result.get("segments", []) or []:
            if seg is None:
                continue
            text = (seg.get("text") or "").strip()
            if not text:
                continue

            start = float(seg.get("start", 0.0)) + global_offset
            end = float(seg.get("end", seg.get("start", 0.0))) + global_offset
            if end < start:
                end = start

            segments.append(
                {
                    "start_sec": start,
                    "end_sec": end,
                    "text": text,
                }
            )

        duration = _probe_audio_duration_seconds(full_path)
        global_offset += duration if duration is not None else fallback_slice_seconds

    return segments


def run_analysis(
    filename,
    model="tiny",
    prompt="以下是普通话句子。",
    output_path=None,
    output_format="txt",
    metadata=None,
    overwrite=True,
):
    segments = transcribe_to_segments(
        filename,
        model=model,
        prompt=prompt,
    )

    if output_path is None:
        os.makedirs(DEFAULT_ARCHIVE_ROOT, exist_ok=True)
        final_output_path = os.path.join(DEFAULT_ARCHIVE_ROOT, f"{os.path.basename(str(filename))}.txt")
    else:
        final_output_path = output_path
        output_dir = os.path.dirname(final_output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

    normalized_format = (output_format or "txt").lower()
    if normalized_format not in ("txt", "md"):
        raise ValueError(f"Unsupported output_format: {output_format}")

    if overwrite and os.path.exists(final_output_path):
        os.remove(final_output_path)

    if normalized_format == "md" and (overwrite or not os.path.exists(final_output_path)):
        with open(final_output_path, "w", encoding="utf-8") as output_file:
            output_file.write(_build_markdown_header(metadata, model))

    with open(final_output_path, "a", encoding="utf-8") as output_file:
        for seg in segments:
            text = seg["text"].strip()
            if not text:
                continue
            if normalized_format == "md":
                output_file.write(text)
                output_file.write("\n\n")
            else:
                output_file.write(text)
                output_file.write("\n")

    return final_output_path
