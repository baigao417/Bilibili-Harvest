import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from http_utils import (
    HttpRequestError,
    cookie_key_set,
    request_json_with_retry,
    sanitize_cookie_header,
)


DEFAULT_TIMEOUT = 20
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"


class BiliSubtitleAPIError(RuntimeError):
    pass


@dataclass
class ApiTrack:
    lang: str
    track_type: str
    subtitle_url: str
    raw_lang: str
    endpoint: str


@dataclass
class ApiDiscoveryMeta:
    cookie_hint: bool = False
    endpoint_used: str = "none"
    warnings: list[str] = field(default_factory=list)


def _headers(video_link: str, cookie_header: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Referer": video_link or "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "X-Wbi-UA": "Win32.Chrome.109.0.0.0",
    }
    clean_cookie = sanitize_cookie_header(cookie_header)
    if clean_cookie:
        headers["Cookie"] = clean_cookie
    return headers


def _request_json(url: str, *, params=None, headers=None, timeout=DEFAULT_TIMEOUT) -> dict:
    try:
        return request_json_with_retry(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )
    except HttpRequestError as exc:
        raise BiliSubtitleAPIError(f"request failed: {url} ({exc})") from exc


def validate_cookie_login(cookie_header: Optional[str], timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    clean_cookie = sanitize_cookie_header(cookie_header)
    if not clean_cookie:
        return False, "cookie is empty"

    keys = cookie_key_set(clean_cookie)
    if "SESSDATA" not in keys:
        return False, "cookie missing SESSDATA (likely from document.cookie without HttpOnly auth cookie)"

    try:
        payload = _request_json(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=_headers("https://www.bilibili.com/", clean_cookie),
            timeout=timeout,
        )
    except BiliSubtitleAPIError as exc:
        return False, str(exc)

    code = payload.get("code", 0)
    if code != 0:
        msg = payload.get("message") or payload.get("msg") or "unknown"
        return False, f"code={code}, message={msg}"

    data = payload.get("data") or {}
    is_login = bool(data.get("isLogin"))
    if not is_login:
        return False, "isLogin=false"

    uname = (data.get("uname") or "").strip()
    return True, (f"isLogin=true, uname={uname}" if uname else "isLogin=true")


def _format_subtitle_url(raw_url: str) -> str:
    text = (raw_url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if text.startswith("/"):
        return f"https://api.bilibili.com{text}"
    return f"https://{text.lstrip('/')}"


def _normalize_lang(raw_lang: Optional[str]) -> str:
    raw = (raw_lang or "").strip()
    if not raw:
        return "unknown"

    lower = raw.lower()
    mapping = {
        "zh-cn": "zh-CN",
        "zh-hans": "zh-Hans",
        "zh-hant": "zh-Hant",
        "zh-tw": "zh-Hant",
        "zh-hk": "zh-Hant",
        "zh": "zh",
        "ai-zh": "ai-zh",
    }
    if lower in mapping:
        return mapping[lower]
    if lower.startswith("ai-zh"):
        return "ai-zh"
    if lower.startswith("zh-cn"):
        return "zh-CN"
    if lower.startswith("zh-hans"):
        return "zh-Hans"
    if lower.startswith("zh"):
        return "zh"
    return raw


def _is_danmaku_track(raw_lang: str, subtitle_url: str) -> bool:
    lang = (raw_lang or "").strip().lower()
    if lang == "danmaku":
        return True

    url = _format_subtitle_url(subtitle_url)
    if not url:
        return False

    path = urlparse(url).path.lower()
    return path.endswith(".xml")


def _extract_tracks(payload: dict, endpoint: str) -> list[ApiTrack]:
    subtitle_root = (payload.get("data") or {}).get("subtitle") or {}
    subtitle_items = subtitle_root.get("subtitles") or []

    dedup: dict[str, ApiTrack] = {}
    for item in subtitle_items:
        raw_lang = (item or {}).get("lan") or ""
        subtitle_url = (item or {}).get("subtitle_url") or ""
        if _is_danmaku_track(raw_lang, subtitle_url):
            continue

        lang = _normalize_lang(raw_lang)
        lower_lang = lang.lower()

        track_type = "ai" if raw_lang.lower().startswith("ai-") or bool((item or {}).get("ai_type")) else "uploader"
        track = ApiTrack(
            lang=lang,
            track_type=track_type,
            subtitle_url=_format_subtitle_url(subtitle_url),
            raw_lang=raw_lang,
            endpoint=endpoint,
        )

        existing = dedup.get(lower_lang)
        if existing is None:
            dedup[lower_lang] = track
            continue

        # Prefer uploader track over AI when lang key is the same.
        if existing.track_type == "ai" and track.track_type == "uploader":
            dedup[lower_lang] = track

    return list(dedup.values())


def ensure_task_identifiers(task, cookie_header: Optional[str] = None) -> None:
    bvid = (getattr(task, "bv", "") or "").strip()
    if not bvid:
        raise BiliSubtitleAPIError("task missing bv")

    if getattr(task, "aid", None) and getattr(task, "cid", None):
        return

    video_link = getattr(task, "video_link", "") or f"https://www.bilibili.com/video/{bvid}"
    payload = _request_json(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        headers=_headers(video_link, cookie_header),
    )

    code = payload.get("code", 0)
    if code != 0:
        msg = payload.get("message") or payload.get("msg") or "unknown"
        raise BiliSubtitleAPIError(f"view api failed: code={code}, message={msg}")

    data = payload.get("data") or {}
    task.aid = data.get("aid") or task.aid
    task.cid = data.get("cid") or task.cid

    title = data.get("title")
    if title and getattr(task, "title", "") in ("", "UnknownTitle"):
        task.title = title

    owner_name = (data.get("owner") or {}).get("name")
    if owner_name and getattr(task, "owner", "") in ("", "UnknownUP"):
        task.owner = owner_name

    if not getattr(task, "video_link", None):
        task.video_link = video_link


def discover_bili_tracks(
    task, cookie_header: Optional[str] = None, max_retries: int = 3, retry_interval: float = 3.0
) -> tuple[list[ApiTrack], ApiDiscoveryMeta]:
    bvid = (getattr(task, "bv", "") or "").strip()
    if not bvid:
        raise BiliSubtitleAPIError("task missing bv")

    if not getattr(task, "cid", None):
        ensure_task_identifiers(task, cookie_header=cookie_header)

    cid = getattr(task, "cid", None)
    aid = getattr(task, "aid", None)
    if not cid:
        raise BiliSubtitleAPIError("task missing cid")

    video_link = getattr(task, "video_link", "") or f"https://www.bilibili.com/video/{bvid}"
    headers = _headers(video_link, cookie_header)

    attempts = []
    if aid:
        attempts.append(
            (
                "wbi_v2",
                "https://api.bilibili.com/x/player/wbi/v2",
                {"aid": aid, "cid": cid},
            )
        )
    attempts.append(
        (
            "v2",
            "https://api.bilibili.com/x/player/v2",
            {"cid": cid, "bvid": bvid},
        )
    )

    warnings: list[str] = []
    # 重试循环：B站 AI 字幕异步就绪，服务端局部重试 max_retries 次
    for _retry in range(max(1, max_retries)):
        if _retry > 0:
            time.sleep(retry_interval)

        for endpoint, url, params in attempts:
            try:
                payload = _request_json(url, params=params, headers=headers)
            except BiliSubtitleAPIError as exc:
                warnings.append(f"{endpoint}: {exc}")
                continue

            code = payload.get("code", 0)
            if code != 0:
                msg = payload.get("message") or payload.get("msg") or "unknown"
                warnings.append(f"{endpoint}: code={code}, message={msg}")
                continue

            tracks = _extract_tracks(payload, endpoint=endpoint)
            if tracks:
                return tracks, ApiDiscoveryMeta(
                    cookie_hint=False,
                    endpoint_used=endpoint,
                    warnings=warnings,
                )

            warnings.append(f"{endpoint}: no subtitle tracks")

        # 如果所有 endpoint 均没有字幕，且不是最后一次，继续重试
        if _retry < max(1, max_retries) - 1:
            # 清洗重试警告中重复的 "no subtitle tracks" 信息
            warnings = [w for w in warnings if "no subtitle tracks" not in w]


    no_cookie = not sanitize_cookie_header(cookie_header)
    cookie_hint = no_cookie and bool(warnings)
    return [], ApiDiscoveryMeta(
        cookie_hint=cookie_hint,
        endpoint_used="none",
        warnings=warnings,
    )


def _extract_segments_from_payload(payload: dict) -> list[dict]:
    body = payload.get("body")
    if not isinstance(body, list):
        return []

    segments = []
    for item in body:
        if not isinstance(item, dict):
            continue

        start = item.get("from", item.get("start"))
        end = item.get("to", item.get("end", start))
        text = (item.get("content") or item.get("text") or "").strip()

        if start is None or end is None or not text:
            continue

        try:
            start_sec = float(start)
            end_sec = float(end)
        except (TypeError, ValueError):
            continue

        if end_sec < start_sec:
            end_sec = start_sec

        segments.append(
            {
                "start_sec": start_sec,
                "end_sec": end_sec,
                "text": text,
            }
        )

    return segments


def _resolve_ai_subtitle_url(task, cookie_header: Optional[str]) -> str:
    aid = getattr(task, "aid", None)
    cid = getattr(task, "cid", None)
    if not aid or not cid:
        return ""

    video_link = getattr(task, "video_link", "") or f"https://www.bilibili.com/video/{task.bv}"
    payload = _request_json(
        "https://api.bilibili.com/x/player/v2/ai/subtitle/search/stat",
        params={"aid": aid, "cid": cid},
        headers=_headers(video_link, cookie_header),
    )
    if payload.get("code", 0) != 0:
        return ""

    subtitle_url = ((payload.get("data") or {}).get("subtitle_url") or "").strip()
    return _format_subtitle_url(subtitle_url)


def fetch_bili_track_segments(task, track: ApiTrack, cookie_header: Optional[str] = None) -> list[dict]:
    video_link = getattr(task, "video_link", "") or f"https://www.bilibili.com/video/{task.bv}"
    headers = _headers(video_link, cookie_header)

    subtitle_url = _format_subtitle_url(track.subtitle_url)
    if not subtitle_url and track.track_type == "ai":
        subtitle_url = _resolve_ai_subtitle_url(task, cookie_header)

    if not subtitle_url:
        raise BiliSubtitleAPIError("subtitle url is empty")

    payload = _request_json(subtitle_url, headers=headers)
    segments = _extract_segments_from_payload(payload)
    if not segments:
        raise BiliSubtitleAPIError("subtitle payload has no usable segments")
    return segments
