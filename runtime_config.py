import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from typing import Any


RUNTIME_CONFIG_PATH = os.path.join("config", "runtime.json")
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 16780
DEFAULT_PORT_SCAN_WINDOW = 20
DEFAULT_API_TOKEN = "bili2text_local_default_token"
DEFAULT_ARCHIVE_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "BilibiliHarvest Library")


@dataclass
class RuntimeConfig:
    http_enabled: bool = True
    http_host: str = DEFAULT_HTTP_HOST
    http_port: int = DEFAULT_HTTP_PORT
    http_port_scan_window: int = DEFAULT_PORT_SCAN_WINDOW
    api_token: str = DEFAULT_API_TOKEN
    extension_ids: list[str] = field(default_factory=list)
    io_workers: int = 2
    plugin_scan_enabled: bool = False
    notebooklm_enabled: bool = True
    notebooklm_notebook_id: str = ""
    notebooklm_auto_clean: bool = True
    archive_root: str = DEFAULT_ARCHIVE_ROOT

    def normalized(self) -> "RuntimeConfig":
        self.http_host = (self.http_host or DEFAULT_HTTP_HOST).strip() or DEFAULT_HTTP_HOST
        self.http_port = int(self.http_port or DEFAULT_HTTP_PORT)
        self.http_port_scan_window = int(self.http_port_scan_window or DEFAULT_PORT_SCAN_WINDOW)
        self.io_workers = max(1, min(int(self.io_workers or 2), 4))
        self.extension_ids = [item.strip() for item in self.extension_ids if str(item).strip()]
        token = str(self.api_token or "").strip()
        if (not token) or token == DEFAULT_API_TOKEN:
            token = generate_api_token()
        self.api_token = token
        archive_root = os.path.abspath(os.path.expanduser(str(self.archive_root or DEFAULT_ARCHIVE_ROOT)))
        self.archive_root = archive_root or DEFAULT_ARCHIVE_ROOT
        return self


def generate_api_token() -> str:
    return secrets.token_urlsafe(24)


def _ensure_config_dir(path: str):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _atomic_write_json(path: str, payload: dict[str, Any]):
    _ensure_config_dir(path)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def load_runtime_config(path: str = RUNTIME_CONFIG_PATH) -> RuntimeConfig:
    if not os.path.isfile(path):
        cfg = RuntimeConfig().normalized()
        save_runtime_config(cfg, path=path)
        return cfg

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
    except Exception:
        cfg = RuntimeConfig().normalized()
        save_runtime_config(cfg, path=path)
        return cfg

    if not isinstance(payload, dict):
        cfg = RuntimeConfig().normalized()
        save_runtime_config(cfg, path=path)
        return cfg

    cfg = RuntimeConfig(
        http_enabled=bool(payload.get("http_enabled", True)),
        http_host=str(payload.get("http_host", DEFAULT_HTTP_HOST)),
        http_port=int(payload.get("http_port", DEFAULT_HTTP_PORT)),
        http_port_scan_window=int(payload.get("http_port_scan_window", DEFAULT_PORT_SCAN_WINDOW)),
        api_token=str(payload.get("api_token", DEFAULT_API_TOKEN) or ""),
        extension_ids=list(payload.get("extension_ids") or []),
        io_workers=int(payload.get("io_workers", 2)),
        plugin_scan_enabled=bool(payload.get("plugin_scan_enabled", False)),
        notebooklm_enabled=bool(payload.get("notebooklm_enabled", True)),
        notebooklm_notebook_id=str(payload.get("notebooklm_notebook_id", "") or ""),
        notebooklm_auto_clean=bool(payload.get("notebooklm_auto_clean", True)),
        archive_root=str(
            payload.get("archive_root", payload.get("shape_root", DEFAULT_ARCHIVE_ROOT)) or DEFAULT_ARCHIVE_ROOT
        ),
    ).normalized()
    save_runtime_config(cfg, path=path)
    return cfg


def save_runtime_config(config: RuntimeConfig, path: str = RUNTIME_CONFIG_PATH):
    normalized = config.normalized()
    _atomic_write_json(path, asdict(normalized))


def reset_api_token(config: RuntimeConfig, path: str = RUNTIME_CONFIG_PATH) -> str:
    config.api_token = generate_api_token()
    save_runtime_config(config, path=path)
    return config.api_token
