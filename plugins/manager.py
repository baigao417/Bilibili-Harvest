import importlib
import json
import os
from dataclasses import dataclass
from typing import Optional

from plugins.sources.builtin_sources import get_builtin_source_plugins
from plugins.types import SourceItem, SourceResolveOptions


class PluginManagerError(RuntimeError):
    pass


@dataclass
class PluginRecord:
    manifest: dict
    plugin: object
    enabled: bool = True


class SourcePluginManager:
    def __init__(
        self,
        *,
        plugins_dir: Optional[str] = None,
        enabled_file: Optional[str] = None,
        enable_scan: bool = False,
    ):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.plugins_dir = plugins_dir or base_dir
        self.enabled_file = enabled_file or os.path.join(base_dir, "enabled.json")
        self.enable_scan = enable_scan
        self._records: dict[str, PluginRecord] = {}

        self.reload(enable_scan=self.enable_scan)

    def _register_builtins(self):
        for manifest, plugin in get_builtin_source_plugins():
            self.register(plugin, manifest)

    def _register_from_directory(self):
        for name in sorted(os.listdir(self.plugins_dir)):
            plugin_dir = os.path.join(self.plugins_dir, name)
            if not os.path.isdir(plugin_dir):
                continue

            manifest_path = os.path.join(plugin_dir, "plugin.json")
            if not os.path.isfile(manifest_path):
                continue

            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            if manifest.get("type") != "source":
                continue

            entry = manifest.get("entry")
            if not entry or ":" not in entry:
                raise PluginManagerError(f"invalid entry in manifest: {manifest_path}")

            module_name, symbol_name = entry.split(":", 1)
            module = importlib.import_module(module_name)
            symbol = getattr(module, symbol_name)
            plugin = symbol() if isinstance(symbol, type) else symbol
            self.register(plugin, manifest)

    def _load_enabled_config(self) -> dict[str, bool]:
        if not os.path.isfile(self.enabled_file):
            return {}

        with open(self.enabled_file, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)

        if not isinstance(payload, dict):
            return {}

        normalized = {}
        for key, value in payload.items():
            if isinstance(key, str):
                normalized[key] = bool(value)
        return normalized

    def save_enabled_config(self, payload: dict[str, bool]):
        normalized = {}
        for key, value in (payload or {}).items():
            if not isinstance(key, str):
                continue
            normalized[key] = bool(value)

        os.makedirs(os.path.dirname(self.enabled_file), exist_ok=True)
        temp = f"{self.enabled_file}.tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
        os.replace(temp, self.enabled_file)

    def _apply_enabled_flags(self):
        enabled_cfg = self._load_enabled_config()
        for plugin_id, record in self._records.items():
            manifest = record.manifest
            if manifest.get("builtin") and manifest.get("required"):
                record.enabled = True
                continue

            if plugin_id not in enabled_cfg:
                record.enabled = True
                continue

            record.enabled = bool(enabled_cfg.get(plugin_id))

    def register(self, plugin, manifest: Optional[dict] = None):
        if not getattr(plugin, "id", ""):
            raise PluginManagerError("source plugin requires id")

        plugin_id = plugin.id
        if plugin_id in self._records:
            raise PluginManagerError(f"duplicate source plugin id: {plugin_id}")

        if manifest is None:
            manifest = {
                "id": plugin_id,
                "type": "source",
                "version": getattr(plugin, "version", "0.0.0"),
                "entry": "",
                "builtin": False,
                "required": False,
                "min_core_version": "0.0.0",
            }
        self._records[plugin_id] = PluginRecord(manifest=manifest, plugin=plugin, enabled=True)

    def reload(self, enable_scan: Optional[bool] = None):
        if enable_scan is not None:
            self.enable_scan = bool(enable_scan)
        self._records.clear()
        self._register_builtins()
        if self.enable_scan:
            self._register_from_directory()
        self._apply_enabled_flags()

    def get_plugin(self, plugin_id: str):
        record = self._records.get(plugin_id)
        if not record:
            raise PluginManagerError(f"source plugin not found: {plugin_id}")
        if not record.enabled:
            raise PluginManagerError(f"source plugin disabled: {plugin_id}")
        return record.plugin

    def list_plugins(self) -> list[dict]:
        entries = []
        for plugin_id, record in sorted(self._records.items()):
            entries.append(
                {
                    "id": plugin_id,
                    "enabled": bool(record.enabled),
                    "version": record.manifest.get("version", ""),
                    "builtin": bool(record.manifest.get("builtin")),
                    "required": bool(record.manifest.get("required")),
                }
            )
        return entries

    def resolve_with_plugin(self, plugin_id: str, text: str, options: SourceResolveOptions) -> list[SourceItem]:
        plugin = self.get_plugin(plugin_id)
        items = plugin.resolve(text, options)
        if not isinstance(items, list):
            raise PluginManagerError(f"plugin {plugin_id} returned invalid payload")
        return items

    def resolve(self, text: str, options: SourceResolveOptions) -> list[SourceItem]:
        candidates = []
        for plugin_id, record in self._records.items():
            if not record.enabled:
                continue
            plugin = record.plugin
            try:
                if plugin.can_handle(text, options):
                    candidates.append(plugin)
            except Exception:
                continue

        if not candidates:
            raise PluginManagerError("no source plugin matched input")

        errors = []
        for plugin in candidates:
            try:
                items = plugin.resolve(text, options)
            except Exception as exc:
                errors.append(f"{plugin.id}: {exc}")
                continue

            if items:
                return items

        if errors:
            raise PluginManagerError("; ".join(errors))
        raise PluginManagerError("all source plugins returned empty result")
