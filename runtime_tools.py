import glob
import os
import shutil
import subprocess
from typing import Iterable, Optional


WINGET_PATTERNS = {
    "yt-dlp": [
        os.path.join("{root}", "yt-dlp.yt-dlp_*", "yt-dlp.exe"),
        os.path.join("{root}", "yt-dlp.yt-dlp_*", "**", "yt-dlp.exe"),
    ],
    "you-get": [
        os.path.join("{root}", "you-get.you-get_*", "**", "you-get.exe"),
    ],
    "ffmpeg": [
        os.path.join("{root}", "Gyan.FFmpeg.Essentials_*", "**", "ffmpeg.exe"),
        os.path.join("{root}", "yt-dlp.FFmpeg_*", "**", "ffmpeg.exe"),
    ],
    "ffprobe": [
        os.path.join("{root}", "Gyan.FFmpeg.Essentials_*", "**", "ffprobe.exe"),
        os.path.join("{root}", "yt-dlp.FFmpeg_*", "**", "ffprobe.exe"),
    ],
}


def run_command(cmd, timeout=1800, cwd=None):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
    )


def summarize_error(stderr: str, max_lines: int = 6) -> str:
    if not stderr:
        return "no stderr output"

    raw_lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not raw_lines:
        return "empty stderr output"

    filtered = []
    for line in raw_lines:
        lower = line.lower()
        if line.startswith("[download]"):
            continue
        if "%" in line and "download" in lower:
            continue
        filtered.append(line)

    lines = filtered if filtered else raw_lines
    keywords = (
        "error",
        "exception",
        "failed",
        "forbidden",
        "cookies",
        "traceback",
        "not found",
        "http",
        "timeout",
        "429",
        "5xx",
    )
    prioritized = [line for line in lines if any(keyword in line.lower() for keyword in keywords)]
    selected = prioritized if prioritized else lines

    unique = []
    seen = set()
    for line in selected:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)
        if len(unique) >= max_lines:
            break

    return " | ".join(unique)


def _winget_root() -> Optional[str]:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return None
    return os.path.join(local_appdata, "Microsoft", "WinGet", "Packages")


def find_executable(name: str) -> Optional[str]:
    resolved = shutil.which(name) or shutil.which(f"{name}.exe")
    if resolved:
        return resolved

    root = _winget_root()
    if not root:
        return None

    patterns = WINGET_PATTERNS.get(name.lower(), [])
    for pattern in patterns:
        matches = sorted(glob.glob(pattern.format(root=root), recursive=True))
        if matches:
            return matches[0]

    return None


def find_ffmpeg() -> str:
    ffmpeg_bin = find_executable("ffmpeg")
    if not ffmpeg_bin:
        raise FileNotFoundError("ffmpeg not found in PATH or WinGet package directory.")
    return ffmpeg_bin


def find_ffprobe() -> str:
    ffprobe_bin = find_executable("ffprobe")
    if not ffprobe_bin:
        raise FileNotFoundError("ffprobe not found in PATH or WinGet package directory.")
    return ffprobe_bin


def resolve_cookies_file(extra_candidates: Optional[Iterable[str]] = None) -> Optional[str]:
    candidates = [
        os.path.join(os.getcwd(), "cookies.txt"),
        os.path.join(os.path.dirname(__file__), "cookies.txt"),
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def should_retry_error(message: str) -> bool:
    if not message:
        return False

    lower = message.lower()
    non_retryable_markers = (
        "subtitles are only available when logged in",
        "login",
        "cookies",
        "unauthorized",
        "403",
    )
    if any(marker in lower for marker in non_retryable_markers):
        return False

    retryable_markers = (
        "timeout",
        "timed out",
        "temporarily",
        "connection reset",
        "connection aborted",
        "connection",
        "429",
        "500",
        "502",
        "503",
        "504",
        "network",
    )
    return any(marker in lower for marker in retryable_markers)
