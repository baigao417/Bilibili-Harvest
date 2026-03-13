import socket
import threading
import time
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    _FASTAPI_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - environment dependent
    FastAPI = Any  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = RuntimeError  # type: ignore[assignment]
    Request = Any  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]
    _FASTAPI_IMPORT_ERROR = exc

from app_version import CORE_VERSION

EXTENSION_ORIGIN_PATTERN = re.compile(r"^chrome-extension://[a-p]{32}$")


@dataclass
class LocalApiStartResult:
    ok: bool
    message: str
    port: int


class LocalApiServer:
    def __init__(
        self,
        *,
        command_handler: Callable[[str, dict], dict],
        runtime_state_provider: Callable[[], dict],
    ):
        self._command_handler = command_handler
        self._runtime_state_provider = runtime_state_provider
        self._app: Optional[FastAPI] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._token = ""
        self._host = "127.0.0.1"
        self._port = 0
        self._origins: list[str] = []
        self._allow_extension_origin_regex: Optional[str] = None

    @property
    def port(self) -> int:
        return int(self._port or 0)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server and getattr(self._server, "started", False))

    def _build_app(self) -> FastAPI:
        if _FASTAPI_IMPORT_ERROR is not None:
            raise RuntimeError(f"fastapi unavailable: {_FASTAPI_IMPORT_ERROR}")
        app = FastAPI(title="BilibiliHarvest local api", version=CORE_VERSION)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self._origins,
            allow_origin_regex=self._allow_extension_origin_regex,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

        def _check_token(x_bili2text_token: Optional[str]):
            if not self._token:
                raise HTTPException(status_code=503, detail="server token unavailable")
            if x_bili2text_token != self._token:
                raise HTTPException(status_code=401, detail="invalid token")

        def _check_origin(request: Request):
            origin = str(request.headers.get("origin") or "").strip()
            if not origin:
                return
            if origin in self._origins:
                return
            if self._allow_extension_origin_regex and EXTENSION_ORIGIN_PATTERN.match(origin):
                return
            if self._allow_extension_origin_regex:
                raise HTTPException(
                    status_code=403,
                    detail="origin not allowed: only localhost and chrome-extension origins are accepted",
                )
            raise HTTPException(
                status_code=403,
                detail='extension_id 未登记，请在应用“服务设置”中添加扩展 ID',
            )

        def _check_pairing_origin(request: Request):
            origin = str(request.headers.get("origin") or "").strip()
            if not origin:
                return
            if origin in {"http://localhost", "http://127.0.0.1"}:
                return
            if EXTENSION_ORIGIN_PATTERN.match(origin):
                return
            raise HTTPException(
                status_code=403,
                detail="pairing only accepts localhost and chrome-extension origins",
            )

        @app.get("/v1/pairing/info")
        def pairing_info(request: Request):
            _check_pairing_origin(request)
            state = self._command_handler("pairing_info", {})
            state.setdefault("ok", True)
            state.setdefault("core_version", CORE_VERSION)
            state.setdefault("port", self._port)
            return state

        @app.post("/v1/pairing/claim")
        def pairing_claim(payload: dict, request: Request):
            _check_pairing_origin(request)
            result = self._command_handler("pairing_claim", payload or {})
            return result

        @app.get("/v1/health")
        def health(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            state = dict(self._runtime_state_provider() or {})
            state.setdefault("ok", True)
            state.setdefault("core_version", CORE_VERSION)
            state.setdefault("port", self._port)
            return state

        @app.post("/v1/tasks/add")
        def add_task(
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            result = self._command_handler("add", payload or {})
            return result

        @app.post("/v1/tasks/add_prefetched")
        def add_task_prefetched(
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            result = self._command_handler("add_prefetched", payload or {})
            return result

        @app.post("/v1/tasks/bulk_add")
        def bulk_add(
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            result = self._command_handler("bulk_add", payload or {})
            return result

        # ── Task list ──

        @app.get("/v1/tasks")
        def list_tasks(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("list_tasks", {})

        # ── Batch operations ──

        @app.get("/v1/batch/status")
        def batch_status(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("batch_status", {})

        @app.post("/v1/batch/start")
        def batch_start(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("start_batch", {})

        @app.post("/v1/batch/stop")
        def batch_stop(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("stop_batch", {})

        @app.post("/v1/batch/export")
        def batch_export(
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("export_batch", payload or {})

        @app.post("/v1/tasks/bind_prefetched")
        def bind_prefetched(
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            result = self._command_handler("bind_prefetched", payload or {})
            return result

        @app.get("/v1/config")
        def get_config(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("get_config", {})

        @app.patch("/v1/config")
        def patch_config(
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("patch_config", payload or {})

        @app.post("/v1/window/show")
        def show_window(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("show_window", {})

        # ── Single-task operations (clear BEFORE {seq} to prevent route swallowing) ──

        @app.delete("/v1/tasks/clear")
        def clear_tasks(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("clear_tasks", {})

        @app.delete("/v1/tasks/{seq}")
        def delete_task(
            seq: int,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("delete_task", {"seq": seq})

        @app.post("/v1/tasks/{seq}/retry")
        def retry_task(
            seq: int,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("retry_task", {"seq": seq})

        @app.post("/v1/tasks/{seq}/update_flag")
        def update_task_flag(
            seq: int,
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("update_task_flag", {"seq": seq, **(payload or {})})

        # ── NotebookLM endpoints ──

        @app.get("/v1/notebooklm/status")
        def nlm_status(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("nlm_auth_status", {})

        @app.get("/v1/notebooklm/notebooks")
        def nlm_notebooks(
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("nlm_list_notebooks", {})

        @app.post("/v1/notebooklm/notebooks")
        def nlm_create_notebook(
            payload: dict,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("nlm_create_notebook", payload or {})

        @app.get("/v1/notebooklm/push/{job_id}")
        def nlm_push_status(
            job_id: str,
            request: Request,
            x_bili2text_token: Optional[str] = Header(default=None, alias="X-BilibiliHarvest-Token"),
        ):
            _check_origin(request)
            _check_token(x_bili2text_token)
            return self._command_handler("nlm_push_status", {"job_id": job_id})

        return app

    def _find_available_port(self, host: str, start_port: int, window: int) -> int:
        for port in range(start_port, start_port + max(1, window) + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind((host, port))
                except OSError:
                    continue
                return port
        return 0

    def start(
        self,
        *,
        host: str,
        port: int,
        port_scan_window: int,
        token: str,
        extension_ids: list[str],
    ) -> LocalApiStartResult:
        if self.is_running:
            return LocalApiStartResult(ok=True, message="already running", port=self._port)
        if _FASTAPI_IMPORT_ERROR is not None:
            return LocalApiStartResult(
                ok=False,
                message=f"fastapi import failed: {_FASTAPI_IMPORT_ERROR}",
                port=0,
            )

        chosen_port = self._find_available_port(host, int(port), int(port_scan_window))
        if chosen_port <= 0:
            return LocalApiStartResult(ok=False, message="no available port", port=0)

        origins = ["http://localhost", "http://127.0.0.1"]
        cleaned_extension_ids: list[str] = []
        for ext_id in extension_ids:
            ext_id = str(ext_id or "").strip()
            if not ext_id:
                continue
            cleaned_extension_ids.append(ext_id)

        allow_extension_origin_regex = None
        if cleaned_extension_ids:
            for ext_id in cleaned_extension_ids:
                origins.append(f"chrome-extension://{ext_id}")
        else:
            allow_extension_origin_regex = r"^chrome-extension://[a-p]{32}$"

        self._host = host
        self._port = chosen_port
        self._token = token
        self._origins = sorted(set(origins))
        self._allow_extension_origin_regex = allow_extension_origin_regex

        self._app = self._build_app()

        try:
            import uvicorn
        except Exception as exc:
            return LocalApiStartResult(ok=False, message=f"uvicorn import failed: {exc}", port=0)

        config = uvicorn.Config(self._app, host=self._host, port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)

        def _run():
            self._server.run()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        for _ in range(40):
            if getattr(self._server, "started", False):
                return LocalApiStartResult(ok=True, message="started", port=self._port)
            if self._thread and (not self._thread.is_alive()):
                break
            time.sleep(0.1)

        self.stop()
        return LocalApiStartResult(ok=False, message="failed to start uvicorn server", port=0)

    def stop(self):
        if self._server is not None:
            try:
                self._server.should_exit = True
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._server = None
        self._thread = None
        self._app = None
        self._port = 0
