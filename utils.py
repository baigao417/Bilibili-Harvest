import glob
import os
import re
import sys

from typing import Optional

from http_utils import sanitize_cookie_header
from runtime_tools import (
    find_executable,
    resolve_cookies_file,
    run_command,
    summarize_error,
)


VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".flv", ".avi", ".mov")
TITLE_MEDIA_EXTENSIONS = (".mp4", ".m4a", ".flv", ".mkv", ".webm", ".avi", ".mov")


def ensure_folders_exist(output_dir):
    os.makedirs("bilibili_video", exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)


def _find_downloaded_video_files(output_dir):
    found = []
    for root, _dirs, files in os.walk(output_dir):
        for file_name in files:
            if file_name.lower().endswith(VIDEO_EXTENSIONS):
                found.append(os.path.join(root, file_name))
    return sorted(found)


def find_primary_media_file(output_dir: str) -> str:
    files = _find_downloaded_video_files(output_dir)
    if not files:
        return ""

    def _size(path: str):
        try:
            return os.path.getsize(path)
        except OSError:
            return -1

    files.sort(key=_size, reverse=True)
    return files[0]


def infer_download_title(bv):
    if not bv:
        return "UnknownTitle"

    normalized_bv = bv if str(bv).startswith("BV") else f"BV{bv}"
    target_dir = os.path.join("bilibili_video", normalized_bv)
    if not os.path.isdir(target_dir):
        return "UnknownTitle"

    temp_suffixes = (".part", ".tmp", ".temp", ".download", ".ytdl")
    candidates = []
    for root, _dirs, files in os.walk(target_dir):
        for file_name in files:
            lower_name = file_name.lower()
            _, ext = os.path.splitext(lower_name)
            if ext not in TITLE_MEDIA_EXTENSIONS:
                continue
            if lower_name.endswith(temp_suffixes):
                continue

            full_path = os.path.join(root, file_name)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            candidates.append((size, full_path))

    if not candidates:
        return "UnknownTitle"

    candidates.sort(key=lambda item: item[0], reverse=True)
    best_path = candidates[0][1]
    stem = os.path.splitext(os.path.basename(best_path))[0].strip()
    return stem if stem else "UnknownTitle"


def _run_you_get(video_url, output_dir, cookies_file):
    module_cmd = [sys.executable, "-m", "you_get", "-o", output_dir]
    if cookies_file:
        module_cmd.extend(["--cookies", cookies_file])
    module_cmd.append(video_url)

    result = run_command(module_cmd)
    if result.returncode == 0:
        return result

    you_get_bin = find_executable("you-get")
    if not you_get_bin:
        return result

    bin_cmd = [you_get_bin, "-o", output_dir]
    if cookies_file:
        bin_cmd.extend(["--cookies", cookies_file])
    bin_cmd.append(video_url)
    return run_command(bin_cmd)


def _run_yt_dlp(video_url, output_dir, cookies_file):
    yt_dlp_bin = find_executable("yt-dlp")
    if not yt_dlp_bin:
        raise FileNotFoundError("yt-dlp not found. Install with pip/winget or ensure yt-dlp is in PATH.")

    output_tpl = os.path.join(output_dir, "%(title)s.%(ext)s")
    cmd = [yt_dlp_bin, "--no-playlist", "--newline", "-o", output_tpl]
    if cookies_file:
        cmd.extend(["--cookies", cookies_file])
    cmd.append(video_url)
    return run_command(cmd)


def download_video_prefer_1080(bv_or_url, output_dir=None, cookie_header=None, cookies_file=None) -> str:
    """
    Download using yt-dlp only, preferring 1080p then fallback to best available.
    Returns the primary downloaded media path or empty string on failure.
    """
    yt_dlp_bin = find_executable("yt-dlp")
    if not yt_dlp_bin:
        print("yt-dlp not found for 1080p-preferred download.")
        return ""

    raw = (bv_or_url or "").strip()
    normalized_bv = _normalize_bv(raw)
    if raw.lower().startswith("http://") or raw.lower().startswith("https://"):
        video_url = raw
    else:
        video_url = f"https://www.bilibili.com/video/{normalized_bv}"

    output_dir = output_dir or os.path.join("bilibili_video", normalized_bv)
    ensure_folders_exist(output_dir)
    cookies_file = cookies_file or resolve_cookies_file()
    manual_cookie = sanitize_cookie_header(cookie_header)

    def _run_with_format(format_spec: str):
        output_tpl = os.path.join(output_dir, "%(title)s.%(ext)s")
        cmd = [
            yt_dlp_bin,
            "--no-playlist",
            "--newline",
            "--merge-output-format",
            "mp4",
            "-f",
            format_spec,
            "-o",
            output_tpl,
        ]
        if manual_cookie:
            cmd.extend(
                [
                    "--add-header",
                    f"Cookie: {manual_cookie}",
                    "--add-header",
                    "Referer: https://www.bilibili.com/",
                ]
            )
        elif cookies_file:
            cmd.extend(["--cookies", cookies_file])
        cmd.append(video_url)
        return run_command(cmd)

    result = _run_with_format("bestvideo[height<=1080]+bestaudio/best[height<=1080]/best")
    if result.returncode != 0:
        print(f"1080p-preferred download failed (summary): {summarize_error(result.stderr)}")
        result = _run_with_format("best")
        if result.returncode != 0:
            print(f"fallback best download failed (summary): {summarize_error(result.stderr)}")
            return ""

    media_path = find_primary_media_file(output_dir)
    if not media_path:
        print("Download succeeded but no playable media file found.")
        return ""
    return media_path


def _normalize_bv(bv_number: str) -> str:
    text = (bv_number or "").strip()
    match = re.search(r"BV([A-Za-z0-9]+)", text, re.IGNORECASE)
    if match:
        return f"BV{match.group(1)}"
    if text.startswith("BV"):
        return text
    return f"BV{text}"


def download_video(bv_number):
    """
    Download Bilibili video with automatic downloader fallback.
    Returns BV id with "BV" prefix on success, empty string on failure.
    """
    bv_number = _normalize_bv(str(bv_number))
    video_url = f"https://www.bilibili.com/video/{bv_number}"
    output_dir = f"bilibili_video/{bv_number}"
    ensure_folders_exist(output_dir)

    cookies_file = resolve_cookies_file()
    print(f"Using you-get to download: {video_url}")
    if cookies_file:
        print("cookies.txt detected, using authenticated download mode.")
    else:
        print("cookies.txt not found. Some videos may require login cookies.")

    downloader_used = "you-get"
    try:
        result = _run_you_get(video_url, output_dir, cookies_file)
    except Exception as exc:
        print(f"you-get failed with exception: {exc}")
        result = None

    if result is None or result.returncode != 0:
        stderr = result.stderr if result else ""
        print(f"you-get failed (summary): {summarize_error(stderr)}")
        print("Falling back to yt-dlp...")
        downloader_used = "yt-dlp"
        try:
            result = _run_yt_dlp(video_url, output_dir, cookies_file)
        except Exception as exc:
            print(f"yt-dlp failed with exception: {exc}")
            return ""
        if result.returncode != 0:
            print(f"yt-dlp failed (summary): {summarize_error(result.stderr)}")
            return ""

    video_files = _find_downloaded_video_files(output_dir)
    if not video_files:
        print("Download failed: no playable video file found in output directory.")
        return ""

    xml_files = glob.glob(os.path.join(output_dir, "*.xml"))
    for xml_file in xml_files:
        try:
            os.remove(xml_file)
        except OSError:
            pass

    print(f"Downloader used: {downloader_used}")
    print(f"Video downloaded to: {output_dir}")
    print(f"Detected media files: {len(video_files)}")
    print(f"Primary media file: {os.path.basename(video_files[0])}")
    return bv_number
