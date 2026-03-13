import hashlib
import re
import threading
import time
from os.path import basename, splitext
from typing import Optional
from urllib.parse import urlencode

from http_utils import request_json_with_retry, sanitize_cookie_header


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
WBI_KEY_TTL_SECONDS = 12 * 60 * 60

MIXIN_KEY_ENC_TAB = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]

_INVALID_WBI_VALUE = re.compile(r"[!'()*]")

_cache_lock = threading.Lock()
_cached_img_key = ""
_cached_sub_key = ""
_cached_at = 0.0


class WbiSigningError(RuntimeError):
    pass


def _headers(cookie_header: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    }
    clean_cookie = sanitize_cookie_header(cookie_header)
    if clean_cookie:
        headers["Cookie"] = clean_cookie
    return headers


def _extract_wbi_keys(payload: dict) -> tuple[str, str]:
    data = payload.get("data") or {}
    wbi_img = data.get("wbi_img") or {}
    img_url = (wbi_img.get("img_url") or "").strip()
    sub_url = (wbi_img.get("sub_url") or "").strip()
    img_key = splitext(basename(img_url))[0]
    sub_key = splitext(basename(sub_url))[0]
    if not img_key or not sub_key:
        raise WbiSigningError("failed to resolve WBI image keys from nav response")
    return img_key, sub_key


def _is_cache_valid(now: float) -> bool:
    if not _cached_img_key or not _cached_sub_key:
        return False
    return now - _cached_at <= WBI_KEY_TTL_SECONDS


def _refresh_wbi_keys(cookie_header: Optional[str] = None) -> tuple[str, str]:
    payload = request_json_with_retry(
        "https://api.bilibili.com/x/web-interface/nav",
        headers=_headers(cookie_header),
    )
    code = payload.get("code", 0)
    if code != 0:
        message = payload.get("message") or payload.get("msg") or "unknown"
        raise WbiSigningError(f"nav api failed: code={code}, message={message}")

    return _extract_wbi_keys(payload)


def get_wbi_keys(cookie_header: Optional[str] = None, force_refresh: bool = False) -> tuple[str, str]:
    global _cached_at, _cached_img_key, _cached_sub_key

    now = time.time()
    with _cache_lock:
        if (not force_refresh) and _is_cache_valid(now):
            return _cached_img_key, _cached_sub_key

        img_key, sub_key = _refresh_wbi_keys(cookie_header)
        _cached_img_key = img_key
        _cached_sub_key = sub_key
        _cached_at = now
        return img_key, sub_key


def _mixin_key(img_key: str, sub_key: str) -> str:
    src = f"{img_key}{sub_key}"
    mixed = "".join(src[index] for index in MIXIN_KEY_ENC_TAB if index < len(src))
    return mixed[:32]


def _normalize_wbi_value(value) -> str:
    text = str(value)
    return _INVALID_WBI_VALUE.sub("", text)


def sign_wbi_params(params: dict, cookie_header: Optional[str] = None, force_refresh: bool = False) -> dict:
    if params is None:
        params = {}

    img_key, sub_key = get_wbi_keys(cookie_header=cookie_header, force_refresh=force_refresh)
    mixin = _mixin_key(img_key, sub_key)

    signed = {str(key): _normalize_wbi_value(value) for key, value in params.items() if value is not None}
    signed["wts"] = str(int(time.time()))

    query = urlencode(sorted(signed.items()), safe="")
    signed["w_rid"] = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()
    return signed
