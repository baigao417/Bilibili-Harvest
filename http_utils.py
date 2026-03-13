import re
import time
from dataclasses import dataclass
from typing import Optional

import requests


DEFAULT_TIMEOUT = 20
DEFAULT_RETRY_COUNT = 2
DEFAULT_BACKOFF_SECONDS = 0.6


class HttpRequestError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass
class RetryPolicy:
    retries: int = DEFAULT_RETRY_COUNT
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


def sanitize_cookie_header(cookie_header: Optional[str]) -> Optional[str]:
    if not cookie_header:
        return None

    text = cookie_header.strip()
    if not text:
        return None

    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()

    text = text.replace("\r", "; ").replace("\n", "; ")
    text = re.sub(r"\s*;\s*", "; ", text)
    text = re.sub(r"\s+", " ", text).strip(" ;")
    return text or None


def cookie_key_set(cookie_header: Optional[str]) -> set[str]:
    clean = sanitize_cookie_header(cookie_header)
    if not clean:
        return set()

    keys: set[str] = set()
    for chunk in clean.split(";"):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        key = item.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def request_json_with_retry(
    url: str,
    *,
    params=None,
    headers=None,
    timeout: int = DEFAULT_TIMEOUT,
    retry_policy: Optional[RetryPolicy] = None,
):
    policy = retry_policy or RetryPolicy()
    last_error = None

    for attempt in range(policy.retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            last_error = HttpRequestError(
                f"request failed: {url} ({exc})",
                retryable=True,
            )
            should_retry = attempt < policy.retries
            if should_retry:
                time.sleep(policy.backoff_seconds * (2 ** attempt))
                continue
            raise last_error from exc

        if response.status_code in policy.retry_statuses and attempt < policy.retries:
            time.sleep(policy.backoff_seconds * (2 ** attempt))
            continue

        if response.status_code >= 400:
            raise HttpRequestError(
                f"http {response.status_code} for {url}",
                status_code=response.status_code,
                retryable=response.status_code in policy.retry_statuses,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise HttpRequestError(f"invalid json response from {url}", retryable=False) from exc

    if last_error is not None:
        raise last_error
    raise HttpRequestError(f"request failed: {url}", retryable=False)
