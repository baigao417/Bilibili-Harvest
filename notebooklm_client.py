"""NotebookLM integration adapter for BilibiliHarvest.

Encapsulates all interactions with the ``notebooklm-py`` library:
authentication, notebook management, and source pushing.

Design rules
~~~~~~~~~~~~
* **No hard-coded paths** – always defer to ``notebooklm.paths``/``notebooklm.auth``
  so ``NOTEBOOKLM_HOME`` / ``NOTEBOOKLM_AUTH_JSON`` are respected.
* All public helpers are *sync* wrappers around the library's async API; callers
  in the main GUI thread should invoke them via ``QThread`` / ``ThreadPoolExecutor``
  to avoid blocking.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import gate – the library is optional
# ---------------------------------------------------------------------------
_NLM_AVAILABLE: bool = False
_NLM_IMPORT_ERROR: Optional[str] = None

try:
    from notebooklm import NotebookLMClient, RPCError  # type: ignore[import-untyped]
    from notebooklm.auth import (  # type: ignore[import-untyped]
        fetch_tokens,
        load_auth_from_storage,
    )
    from notebooklm.paths import (  # type: ignore[import-untyped]
        get_browser_profile_dir,
        get_storage_path,
    )

    _NLM_AVAILABLE = True
except Exception as exc:
    _NLM_IMPORT_ERROR = str(exc)
    # Provide safe fallback symbols so the rest of the module can be imported
    NotebookLMClient = None  # type: ignore[assignment,misc]
    RPCError = Exception  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Auth status enum
# ---------------------------------------------------------------------------
class AuthStatus(Enum):
    """Result of :func:`check_auth_available`."""
    NOT_CONFIGURED = "not_configured"
    COOKIES_FOUND = "cookies_found"      # cookies loaded, but validity unknown (offline)
    VALID = "valid"                      # tokens fetched successfully
    EXPIRED = "expired"                  # cookie present but token fetch says expired
    LIB_MISSING = "lib_missing"          # notebooklm-py not installed


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def is_nlm_available() -> bool:
    """Return *True* when ``notebooklm-py`` can be imported."""
    return _NLM_AVAILABLE


def nlm_import_error() -> Optional[str]:
    return _NLM_IMPORT_ERROR


def check_auth_available() -> AuthStatus:
    """Probe the three-level auth precedence of *notebooklm-py*.

    1. ``load_auth_from_storage()`` (respects *NOTEBOOKLM_AUTH_JSON*, *NOTEBOOKLM_HOME*)
    2. ``fetch_tokens(cookies)`` for a lightweight liveness check.

    Returns an :class:`AuthStatus` member.
    """
    if not _NLM_AVAILABLE:
        return AuthStatus.LIB_MISSING

    try:
        cookies = load_auth_from_storage()
    except FileNotFoundError:
        return AuthStatus.NOT_CONFIGURED
    except (ValueError, Exception) as exc:
        logger.debug("load_auth_from_storage failed: %s", exc)
        return AuthStatus.NOT_CONFIGURED

    # Cookies loaded – now try a light-weight token fetch to verify validity.
    try:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(fetch_tokens(cookies))
        finally:
            loop.close()
        return AuthStatus.VALID
    except ValueError as exc:
        if "expired" in str(exc).lower() or "Authentication" in str(exc):
            return AuthStatus.EXPIRED
        logger.debug("fetch_tokens ValueError: %s", exc)
        return AuthStatus.EXPIRED
    except Exception as exc:
        # Network error – cookies exist, cannot verify.  Treat as usable.
        logger.debug("fetch_tokens network error: %s", exc)
        return AuthStatus.COOKIES_FOUND


def refresh_auth_from_browser_profile() -> bool:
    """Silently refresh ``storage_state.json`` from the persistent browser profile.

    Opens a **headless** Chromium with the same ``user_data_dir`` that
    :func:`run_browser_login` writes to, navigates to NotebookLM, and
    re-exports ``storage_state.json``.  Because Chrome's persistent
    profile keeps the Google session alive (auto-refreshed cookies),
    this typically succeeds without any user interaction.

    Returns ``True`` when the new ``storage_state.json`` passes the
    ``fetch_tokens`` liveness check.
    """
    if not _NLM_AVAILABLE:
        return False

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("playwright not installed, cannot refresh auth silently")
        return False

    storage_path = get_storage_path()
    browser_profile = get_browser_profile_dir()

    if not browser_profile.exists():
        logger.debug("browser profile does not exist, nothing to refresh from")
        return False

    logger.info("Attempting silent auth refresh from browser profile …")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(browser_profile),
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--password-store=basic",
                ],
                ignore_default_args=["--enable-automation"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto("https://notebooklm.google.com/", wait_until="networkidle", timeout=30000)
            except Exception:
                # Even on timeout, Chrome may have refreshed cookies
                pass

            context.storage_state(path=str(storage_path))
            try:
                storage_path.chmod(0o600)
            except Exception:
                pass
            context.close()
    except Exception as exc:
        logger.warning("Silent auth refresh failed: %s", exc)
        return False

    # Verify the refreshed state
    new_status = check_auth_available()
    success = new_status in (AuthStatus.VALID, AuthStatus.COOKIES_FOUND)
    logger.info("Silent auth refresh result: %s (status=%s)", success, new_status.value)
    return success


def ensure_auth_valid() -> AuthStatus:
    """High-level helper: check auth, auto-refresh if expired.

    Call this before any NLM operation.  Flow:

    1. ``check_auth_available()``
    2. If EXPIRED → ``refresh_auth_from_browser_profile()``
    3. Recheck and return final status.
    """
    status = check_auth_available()
    if status == AuthStatus.EXPIRED:
        logger.info("Auth expired, attempting silent refresh …")
        if refresh_auth_from_browser_profile():
            status = check_auth_available()
    return status


# ---------------------------------------------------------------------------
# Async helper: run coroutine in a fresh event loop (for worker threads)
# ---------------------------------------------------------------------------
def _run_async(coro):
    """Execute *coro* in a new event-loop (safe for non-main threads)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Notebook list / create (sync wrappers)
# ---------------------------------------------------------------------------
def list_notebooks() -> list[dict[str, Any]]:
    """Return ``[{id, title}]`` for all notebooks visible to the logged-in user."""
    if not _NLM_AVAILABLE:
        raise RuntimeError("notebooklm-py is not installed")

    async def _list():
        async with await NotebookLMClient.from_storage() as client:
            notebooks = await client.notebooks.list()
            return [{"id": nb.id, "title": nb.title} for nb in notebooks]

    return _run_async(_list())


def create_notebook(title: str) -> dict[str, Any]:
    """Create a notebook and return ``{id, title}``."""
    if not _NLM_AVAILABLE:
        raise RuntimeError("notebooklm-py is not installed")

    async def _create():
        async with await NotebookLMClient.from_storage() as client:
            nb = await client.notebooks.create(title)
            return {"id": nb.id, "title": nb.title}

    return _run_async(_create())


# ---------------------------------------------------------------------------
# Push a single text source (with retry)
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_BASE_DELAY = 3.0        # seconds
_INTER_PUSH_DELAY = 1.5  # seconds between consecutive pushes


def _is_retryable(exc: Exception) -> bool:
    """Heuristic: HTTP 429/5xx or network errors are retryable."""
    msg = str(exc).lower()
    for keyword in ("429", "500", "502", "503", "504", "timeout", "connection", "network"):
        if keyword in msg:
            return True
    return False


async def _push_one_source(
    client,
    notebook_id: str,
    title: str,
    content: str,
) -> str:
    """Push a single text source with exponential-backoff retry.

    Returns the source id on success; raises on final failure.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            source = await client.sources.add_text(notebook_id, title, content)
            return source.id
        except Exception as exc:
            last_exc = exc
            # Try auth refresh once on auth errors
            if attempt == 0 and ("expired" in str(exc).lower() or "authentication" in str(exc).lower()):
                try:
                    await client.refresh_auth()
                except Exception:
                    pass

            if not _is_retryable(exc) and "expired" not in str(exc).lower():
                raise  # non-retryable → fail fast

            delay = _BASE_DELAY * (2 ** attempt)
            # Respect retry_after hint when present
            retry_after = getattr(exc, "retry_after", None)
            if retry_after and isinstance(retry_after, (int, float)):
                delay = max(delay, float(retry_after))
            logger.info("Retryable error (attempt %d/%d): %s – waiting %.1fs", attempt + 1, _MAX_RETRIES, exc, delay)
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Push Job – designed to be run inside a QThread
# ---------------------------------------------------------------------------
class NlmPushResult:
    """Immutable result returned by :func:`run_push_job`."""

    def __init__(self):
        self.pushed: int = 0
        self.failed: int = 0
        self.total: int = 0
        self.errors: list[dict[str, Any]] = []   # [{seq, error}]
        self.results: dict[int, str] = {}         # {seq: source_id}


def run_push_job(
    notebook_id: str,
    task_items: list[Any],            # list[TaskItem] – avoid import cycle
    *,
    build_md_func,                    # Callable[[task, segments], str]
    load_segments_func,               # Callable[[task], list[dict]]
    render_title_func,                # Callable[[task], str]
    progress_cb=None,                 # Optional[Callable[[int, int, str], None]]
    task_pushed_cb=None,              # Optional[Callable[[int, str], None]]
    task_failed_cb=None,              # Optional[Callable[[int, str], None]]
    cancel_flag=None,                 # Optional[Callable[[], bool]]
) -> NlmPushResult:
    """Synchronous entry-point (meant for a worker thread).

    Iterates *task_items*, generates MD in-memory, and pushes each one as a
    text source to *notebook_id*.  Inter-push delay avoids rate-limits.

    Parameters
    ----------
    build_md_func:
        ``(task, segments) -> str`` – returns full Markdown text.
    load_segments_func:
        ``(task) -> list[dict]`` – loads subtitle segments for a task.
    render_title_func:
        ``(task) -> str`` – produces the NotebookLM source title.
    progress_cb:
        ``(pushed_so_far, total, current_title)`` – progress feedback.
    task_pushed_cb:
        ``(seq, source_id)`` – fired after each successful push.
    task_failed_cb:
        ``(seq, error_message)`` – fired after each failed push.
    cancel_flag:
        ``() -> bool`` – checked before each iteration; *True* aborts.
    """
    if not _NLM_AVAILABLE:
        raise RuntimeError("notebooklm-py is not installed")

    result = NlmPushResult()
    result.total = len(task_items)

    async def _run():
        async with await NotebookLMClient.from_storage() as client:
            for idx, task in enumerate(task_items):
                if cancel_flag and cancel_flag():
                    logger.info("NLM push cancelled after %d/%d", idx, result.total)
                    break

                segments = load_segments_func(task)
                if not segments:
                    result.failed += 1
                    err = "no segments"
                    result.errors.append({"seq": task.seq, "error": err})
                    if task_failed_cb:
                        task_failed_cb(task.seq, err)
                    continue

                md_content = build_md_func(task, segments)
                nlm_title = render_title_func(task)

                if progress_cb:
                    progress_cb(result.pushed, result.total, task.title)

                try:
                    source_id = await _push_one_source(client, notebook_id, nlm_title, md_content)
                    result.pushed += 1
                    result.results[task.seq] = source_id
                    if task_pushed_cb:
                        task_pushed_cb(task.seq, source_id)
                except Exception as exc:
                    result.failed += 1
                    err_msg = str(exc)
                    result.errors.append({"seq": task.seq, "error": err_msg})
                    logger.warning("push failed for seq=%d: %s", task.seq, err_msg)
                    if task_failed_cb:
                        task_failed_cb(task.seq, err_msg)

                # Inter-push delay to honour rate limits
                if idx < len(task_items) - 1:
                    await asyncio.sleep(_INTER_PUSH_DELAY)

    _run_async(_run())
    return result


# ---------------------------------------------------------------------------
# Playwright login helper (for GUI integration, NOT CLI)
# ---------------------------------------------------------------------------
def run_browser_login(
    on_status=None,     # Optional[Callable[[str], None]]  status messages
    cancel_flag=None,   # Optional[Callable[[], bool]]
    timeout: int = 300, # seconds to wait for user to log in
) -> bool:
    """Open a Chromium window for the user to log into Google/NotebookLM.

    Uses the same Playwright persistent-context approach as the
    ``notebooklm login`` CLI but **without** ``input()`` blocking.
    Instead we poll ``page.url`` until the user reaches the NotebookLM
    homepage, then automatically save the storage state.

    Returns ``True`` on success.
    """
    if not _NLM_AVAILABLE:
        raise RuntimeError("notebooklm-py is not installed")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run:\n"
            "  pip install 'notebooklm-py[browser]'\n"
            "  playwright install chromium"
        )

    storage_path = get_storage_path()
    browser_profile = get_browser_profile_dir()
    storage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    browser_profile.mkdir(parents=True, exist_ok=True, mode=0o700)

    if on_status:
        on_status("正在启动 Chromium 浏览器...")

    # Windows event-loop fix (mirrors notebooklm-py session.py #89)
    import contextlib

    @contextlib.contextmanager
    def _windows_event_loop():
        if sys.platform == "win32":
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    yield
                    return
            except RuntimeError:
                pass
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                yield
            finally:
                asyncio.set_event_loop(None)
                loop.close()
        else:
            yield

    success = False
    with _windows_event_loop(), sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(browser_profile),
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--password-store=basic",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://notebooklm.google.com/")

        if on_status:
            on_status("请在浏览器中完成 Google 登录，登录后将自动保存...")

        def _try_save_state() -> bool:
            """Attempt to persist the browser storage state. Returns True on success."""
            nonlocal success
            try:
                context.storage_state(path=str(storage_path))
                try:
                    storage_path.chmod(0o600)
                except Exception:
                    pass
                success = True
                return True
            except Exception as exc:
                logger.error("Failed to save storage state: %s", exc)
                return False

        def _looks_logged_in(url: str) -> bool:
            """Heuristic: the user has reached a logged-in NotebookLM page."""
            url_lower = url.lower()
            if "notebooklm.google.com" not in url_lower:
                return False
            # Any of these patterns indicate a logged-in state
            if "/notebook" in url_lower:
                return True
            if "mynotebooks" in url_lower:
                return True
            # The bare landing page after login (no accounts.google redirect)
            if "accounts.google" not in url_lower:
                try:
                    # Check for app-shell elements that only appear after login
                    if page.query_selector('[data-notebook-id]') is not None:
                        return True
                    if page.query_selector('a[aria-label="NotebookLM"]') is not None:
                        return True
                    # Generic check: presence of a "New notebook" button or similar
                    if page.query_selector('button[aria-label]') is not None:
                        return True
                except Exception:
                    pass
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel_flag and cancel_flag():
                break
            try:
                current_url = page.url
            except Exception:
                # Browser closed by user — try to save what we have
                break

            if _looks_logged_in(current_url):
                _try_save_state()
                break

            time.sleep(2)

        # Fallback: even if URL heuristics didn't trigger, save the state
        # when the browser is being closed.  The persistent Chromium profile
        # already holds the Google cookies; the storage_state.json lets
        # notebooklm-py's ``load_auth_from_storage()`` pick them up directly.
        if not success:
            _try_save_state()

        try:
            context.close()
        except Exception:
            pass

    if on_status:
        on_status("登录成功 ✓" if success else "登录未完成")

    return success
