from typing import Optional

from plugins.manager import PluginManagerError, SourcePluginManager
from plugins.types import SourceItem, SourceResolveOptions


class SourceResolveError(RuntimeError):
    pass


_MANAGER: Optional[SourcePluginManager] = None
_MANAGER_SCAN_ENABLED = False


def get_source_plugin_manager(enable_scan: Optional[bool] = None) -> SourcePluginManager:
    global _MANAGER, _MANAGER_SCAN_ENABLED
    if enable_scan is None:
        enable_scan = _MANAGER_SCAN_ENABLED

    if _MANAGER is None:
        _MANAGER_SCAN_ENABLED = bool(enable_scan)
        _MANAGER = SourcePluginManager(enable_scan=_MANAGER_SCAN_ENABLED)
        return _MANAGER

    if bool(enable_scan) != _MANAGER_SCAN_ENABLED:
        _MANAGER_SCAN_ENABLED = bool(enable_scan)
        _MANAGER = SourcePluginManager(enable_scan=_MANAGER_SCAN_ENABLED)
    return _MANAGER


def _resolve_with_plugin(plugin_id: str, text: str, options: SourceResolveOptions) -> list[SourceItem]:
    manager = get_source_plugin_manager()
    try:
        return manager.resolve_with_plugin(plugin_id, text, options)
    except PluginManagerError as exc:
        raise SourceResolveError(str(exc)) from exc
    except Exception as exc:
        raise SourceResolveError(str(exc)) from exc


def resolve_single_or_bv(
    input_text: str,
    import_mode: str = "single",
    cookie_header: Optional[str] = None,
) -> list[SourceItem]:
    return _resolve_with_plugin(
        "source.bv_video",
        input_text,
        SourceResolveOptions(
            cookie_header=cookie_header,
            import_mode=import_mode,
        ),
    )


def resolve_favorite(
    favorite_url: str,
    limit: int = 200,
    cookie_header: Optional[str] = None,
) -> list[SourceItem]:
    return _resolve_with_plugin(
        "source.favorite",
        favorite_url,
        SourceResolveOptions(
            cookie_header=cookie_header,
            limit=limit,
        ),
    )


def resolve_collection_series(
    input_text: str,
    cookie_header: Optional[str] = None,
) -> list[SourceItem]:
    return _resolve_with_plugin(
        "source.collection_series",
        input_text,
        SourceResolveOptions(cookie_header=cookie_header),
    )


def resolve_space_uploads(
    input_text: str,
    *,
    limit: int = 200,
    order: str = "pubdate_desc",
    cookie_header: Optional[str] = None,
) -> list[SourceItem]:
    return _resolve_with_plugin(
        "source.space_uploads",
        input_text,
        SourceResolveOptions(
            cookie_header=cookie_header,
            limit=limit,
            order=order,
        ),
    )


def resolve_source_auto(
    input_text: str,
    *,
    cookie_header: Optional[str] = None,
    limit: Optional[int] = None,
    order: str = "pubdate_desc",
    import_mode: str = "single",
) -> list[SourceItem]:
    manager = get_source_plugin_manager()
    options = SourceResolveOptions(
        cookie_header=cookie_header,
        limit=limit,
        order=order,
        import_mode=import_mode,
    )
    try:
        return manager.resolve(input_text, options)
    except PluginManagerError as exc:
        raise SourceResolveError(str(exc)) from exc


def reload_source_plugin_manager(enable_scan: Optional[bool] = None) -> SourcePluginManager:
    manager = get_source_plugin_manager(enable_scan=enable_scan)
    manager.reload(enable_scan=enable_scan)
    return manager
