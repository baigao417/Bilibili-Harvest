import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

from bili_wbi import WbiSigningError, sign_wbi_params
from http_utils import HttpRequestError, request_json_with_retry, sanitize_cookie_header
from plugins.types import SourceItem, SourceResolveOptions
from runtime_tools import find_executable, run_command, summarize_error


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
DEFAULT_PAGE_SIZE = 30
DEFAULT_SPACE_LIMIT = 200


def _headers(video_url: Optional[str] = None, cookie_header: Optional[str] = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Referer": video_url or "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    }
    clean_cookie = sanitize_cookie_header(cookie_header)
    if clean_cookie:
        headers["Cookie"] = clean_cookie
    return headers


def _request_bili_json(url: str, *, params=None, headers=None) -> dict:
    payload = request_json_with_retry(url, params=params, headers=headers)
    code = payload.get("code", 0)
    if code != 0:
        message = payload.get("message") or payload.get("msg") or "unknown"
        raise RuntimeError(f"Bilibili API failed: code={code}, message={message}")
    return payload


def _extract_bv(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"BV([A-Za-z0-9]+)", text, re.IGNORECASE)
    if not match:
        return None
    return f"BV{match.group(1)}"


def _extract_json(stdout: str) -> dict:
    text = (stdout or "").strip()
    if not text:
        raise RuntimeError("yt-dlp produced empty output")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    raise RuntimeError("failed to parse yt-dlp JSON output")


def _parse_favorite_id(text: str) -> Optional[int]:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)

    for pattern in (r"[?&](?:fid|media_id)=([0-9]+)", r"/favlist\?fid=([0-9]+)"):
        hit = re.search(pattern, raw)
        if hit:
            return int(hit.group(1))

    return None


def _to_video_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"


def _build_source_meta(
    *,
    container_type: str,
    container_id: str,
    container_title: str = "",
    mid: Optional[int] = None,
    origin_url: str = "",
    order: str = "",
    page_num: int = 0,
    page_size: int = 0,
) -> dict:
    return {
        "container_type": container_type,
        "container_id": str(container_id or ""),
        "container_title": container_title or "",
        "mid": int(mid) if mid is not None else None,
        "origin_url": origin_url or "",
        "order": order or "",
        "page_num": int(page_num) if page_num else 0,
        "page_size": int(page_size) if page_size else 0,
    }


def _parse_collection_or_series_target(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise RuntimeError("empty collection/series input")

    season_pref = re.match(r"^season:([0-9]+)$", raw, re.IGNORECASE)
    if season_pref:
        season_id = int(season_pref.group(1))
        return {
            "kind": "collection",
            "season_id": season_id,
            "series_id": None,
            "media_id": None,
            "mid": None,
            "origin_url": f"https://space.bilibili.com/0/channel/collectiondetail?sid={season_id}",
        }

    series_pref = re.match(r"^series:([0-9]+)$", raw, re.IGNORECASE)
    if series_pref:
        series_id = int(series_pref.group(1))
        return {
            "kind": "series",
            "season_id": None,
            "series_id": series_id,
            "media_id": None,
            "mid": None,
            "origin_url": f"https://space.bilibili.com/0/channel/seriesdetail?sid={series_id}",
        }

    ml_pref = re.match(r"^ml([0-9]+)$", raw, re.IGNORECASE)
    if ml_pref:
        return {
            "kind": "ml",
            "season_id": None,
            "series_id": None,
            "media_id": int(ml_pref.group(1)),
            "mid": None,
            "origin_url": f"https://www.bilibili.com/medialist/detail/ml{ml_pref.group(1)}",
        }

    parsed = urlparse(raw)
    if not parsed.scheme:
        raise RuntimeError("unsupported collection/series input, expected url or season:/series:/ml")

    path = parsed.path or ""
    query = parse_qs(parsed.query)

    mid = None
    mid_match = re.search(r"space\.bilibili\.com/([0-9]+)", raw)
    if mid_match:
        mid = int(mid_match.group(1))

    if "collectiondetail" in path or "channel/collectiondetail" in raw:
        sid = query.get("sid", [""])[0]
        if sid.isdigit():
            return {
                "kind": "collection",
                "season_id": int(sid),
                "series_id": None,
                "media_id": None,
                "mid": mid,
                "origin_url": raw,
            }

    lists_hit = re.search(r"/lists/([0-9]+)", path)
    if lists_hit:
        list_id = lists_hit.group(1)
        list_type = str((query.get("type", [""])[0] or "")).strip().lower()
        if list_type == "season":
            return {
                "kind": "collection",
                "season_id": int(list_id),
                "series_id": None,
                "media_id": None,
                "mid": mid,
                "origin_url": raw,
            }
        return {
            "kind": "series",
            "season_id": None,
            "series_id": int(list_id),
            "media_id": None,
            "mid": mid,
            "origin_url": raw,
        }

    if "seriesdetail" in path or "channel/seriesdetail" in raw or re.search(r"/lists/([0-9]+)", path):
        sid = query.get("sid", [""])[0]
        if not sid:
            hit = re.search(r"/lists/([0-9]+)", path)
            sid = hit.group(1) if hit else ""
        if sid.isdigit():
            return {
                "kind": "series",
                "season_id": None,
                "series_id": int(sid),
                "media_id": None,
                "mid": mid,
                "origin_url": raw,
            }

    ml_match = re.search(r"/medialist/detail/ml([0-9]+)", raw)
    if ml_match:
        media_id = int(ml_match.group(1))
        return {
            "kind": "ml",
            "season_id": None,
            "series_id": None,
            "media_id": media_id,
            "mid": mid,
            "origin_url": raw,
        }

    raise RuntimeError("unsupported collection/series url")


def _parse_space_mid(text: str) -> int:
    raw = (text or "").strip()
    if not raw:
        raise RuntimeError("empty space input")

    if raw.isdigit():
        return int(raw)

    hit = re.search(r"space\.bilibili\.com/([0-9]+)", raw)
    if hit:
        return int(hit.group(1))

    raise RuntimeError(f"invalid space input: {text}")


def _resolve_mid_for_series(series_id: int, cookie_header: Optional[str]) -> Optional[int]:
    try:
        payload = _request_bili_json(
            "https://api.bilibili.com/x/series/series",
            params={"series_id": series_id},
            headers=_headers(None, cookie_header),
        )
    except Exception:
        return None

    data = payload.get("data") or {}
    if isinstance(data, dict):
        if str(data.get("mid", "")).isdigit():
            return int(data["mid"])
        meta = data.get("meta") or {}
        if str(meta.get("mid", "")).isdigit():
            return int(meta["mid"])
    return None


def _resolve_collection_archives(
    season_id: int,
    mid: Optional[int],
    cookie_header: Optional[str],
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[dict], Optional[int], str]:
    page_num = 1
    archives: list[dict] = []
    resolved_mid = mid
    container_title = ""

    while True:
        params = {
            "season_id": season_id,
            "page_num": page_num,
            "page_size": page_size,
        }
        if resolved_mid is not None:
            params["mid"] = resolved_mid

        payload = _request_bili_json(
            "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list",
            params=params,
            headers=_headers(None, cookie_header),
        )
        data = payload.get("data") or {}
        meta = data.get("meta") or {}
        if not container_title:
            container_title = meta.get("name") or meta.get("title") or ""

        if resolved_mid is None:
            candidate_mid = meta.get("mid") or data.get("mid")
            if str(candidate_mid or "").isdigit():
                resolved_mid = int(candidate_mid)

        page_items = data.get("archives") or data.get("items") or []
        if not page_items:
            break

        archives.extend(page_items)
        if len(page_items) < page_size:
            break
        page_num += 1

    return archives, resolved_mid, container_title


def _resolve_series_archives(
    series_id: int,
    mid: Optional[int],
    cookie_header: Optional[str],
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[dict], Optional[int], str]:
    pn = 1
    archives: list[dict] = []
    resolved_mid = mid or _resolve_mid_for_series(series_id, cookie_header)
    container_title = ""

    while True:
        params = {
            "series_id": series_id,
            "pn": pn,
            "ps": page_size,
            "sort": "desc",
            "only_normal": "true",
        }
        if resolved_mid is not None:
            params["mid"] = resolved_mid

        payload = _request_bili_json(
            "https://api.bilibili.com/x/series/archives",
            params=params,
            headers=_headers(None, cookie_header),
        )
        data = payload.get("data") or {}
        if not container_title:
            meta = data.get("meta") or {}
            container_title = meta.get("name") or meta.get("title") or ""

        if resolved_mid is None:
            candidate_mid = data.get("mid") or (data.get("meta") or {}).get("mid")
            if str(candidate_mid or "").isdigit():
                resolved_mid = int(candidate_mid)

        page_items = data.get("archives") or data.get("items") or []
        if not page_items:
            break

        archives.extend(page_items)
        if len(page_items) < page_size:
            break
        pn += 1

    return archives, resolved_mid, container_title


def _resolve_favorite_items(media_id: int, cookie_header: Optional[str], limit: int) -> tuple[list[dict], str]:
    ps = 20
    pn = 1
    medias: list[dict] = []
    title = ""

    while len(medias) < limit:
        payload = _request_bili_json(
            "https://api.bilibili.com/x/v3/fav/resource/list",
            params={
                "media_id": media_id,
                "pn": pn,
                "ps": ps,
                "platform": "web",
            },
            headers=_headers(None, cookie_header),
        )
        data = payload.get("data") or {}
        title = title or (data.get("info") or {}).get("title") or ""
        page_items = data.get("medias") or []
        if not page_items:
            break

        for media in page_items:
            if len(medias) >= limit:
                break
            medias.append(media)

        if len(page_items) < ps:
            break
        pn += 1

    return medias, title


def _resolve_space_upload_archives(
    mid: int,
    cookie_header: Optional[str],
    *,
    limit: int,
    order: str,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[dict]:
    pn = 1
    archives: list[dict] = []

    while len(archives) < limit:
        params = sign_wbi_params(
            {
                "mid": str(mid),
                "pn": str(pn),
                "ps": str(page_size),
                "order": order,
                "platform": "web",
                "web_location": "1550101",
            },
            cookie_header=cookie_header,
        )
        payload = request_json_with_retry(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            params=params,
            headers=_headers(None, cookie_header),
        )

        code = payload.get("code", 0)
        if code != 0:
            message = payload.get("message") or payload.get("msg") or "unknown"
            raise RuntimeError(f"space api failed: code={code}, message={message}")

        data = payload.get("data") or {}
        page_items = (((data.get("list") or {}).get("vlist")) or [])
        if not page_items:
            break

        for item in page_items:
            if len(archives) >= limit:
                break
            archives.append(item)

        if len(page_items) < page_size:
            break
        pn += 1

    return archives


def _resolve_via_ytdlp_flat(
    input_url: str,
    *,
    source_type: str,
    source_meta: dict,
    limit: Optional[int],
) -> list[SourceItem]:
    yt_dlp_bin = find_executable("yt-dlp")
    if not yt_dlp_bin:
        raise RuntimeError("yt-dlp not found for fallback resolution")

    cmd = [
        yt_dlp_bin,
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        input_url,
    ]
    result = run_command(cmd, timeout=420)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp flat playlist failed: {summarize_error(result.stderr)}")

    payload = _extract_json(result.stdout)
    title = payload.get("title") or source_meta.get("container_title") or ""
    entries = payload.get("entries") or []

    items: list[SourceItem] = []
    for idx, entry in enumerate(entries, start=1):
        if limit is not None and len(items) >= limit:
            break

        if not isinstance(entry, dict):
            continue
        bvid = _extract_bv(str(entry.get("id") or "")) or _extract_bv(str(entry.get("url") or ""))
        if not bvid:
            continue

        entry_meta = dict(source_meta)
        entry_meta["container_title"] = title or entry_meta.get("container_title") or ""
        entry_meta["page_num"] = idx
        entry_meta["page_size"] = len(entries)

        items.append(
            SourceItem(
                bvid=bvid,
                cid=None,
                title=entry.get("title") or "UnknownTitle",
                owner=entry.get("uploader") or entry.get("channel") or "UnknownUP",
                source_type=source_type,
                page=idx,
                page_title=entry.get("title") or "",
                video_url=_to_video_url(bvid),
                source_meta=entry_meta,
            )
        )

    return items


@dataclass
class BvVideoSourcePlugin:
    id: str = "source.bv_video"
    version: str = "2.0.0"

    def can_handle(self, text: str, options: SourceResolveOptions) -> bool:
        return _extract_bv(text or "") is not None

    def resolve(self, text: str, options: SourceResolveOptions) -> list[SourceItem]:
        bvid = _extract_bv(text or "")
        if not bvid:
            raise RuntimeError(f"invalid video input: {text}")

        video_url = _to_video_url(bvid)
        view = _request_bili_json(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers=_headers(video_url, options.cookie_header),
        )

        data = view.get("data") or {}
        title = data.get("title") or "UnknownTitle"
        owner = (data.get("owner") or {}).get("name") or "UnknownUP"
        aid = data.get("aid")

        if options.import_mode == "all_pages":
            pagelist = _request_bili_json(
                "https://api.bilibili.com/x/player/pagelist",
                params={"bvid": bvid},
                headers=_headers(video_url, options.cookie_header),
            )
            pages = pagelist.get("data") or []
            return [
                SourceItem(
                    bvid=bvid,
                    aid=aid,
                    cid=page_item.get("cid"),
                    title=title,
                    owner=owner,
                    source_type="multi_p",
                    page=page_item.get("page"),
                    page_title=page_item.get("part") or "",
                    video_url=video_url,
                    source_meta=_build_source_meta(
                        container_type="multi_p",
                        container_id=bvid,
                        container_title=title,
                        origin_url=text,
                        page_num=int(page_item.get("page") or 0),
                        page_size=len(pages),
                    ),
                )
                for page_item in pages
            ]

        return [
            SourceItem(
                bvid=bvid,
                aid=aid,
                cid=data.get("cid"),
                title=title,
                owner=owner,
                source_type="single",
                page=1,
                page_title=data.get("title") or "",
                video_url=video_url,
                source_meta=_build_source_meta(
                    container_type="single",
                    container_id=bvid,
                    container_title=title,
                    origin_url=text,
                    page_num=1,
                    page_size=1,
                ),
            )
        ]


@dataclass
class FavoriteSourcePlugin:
    id: str = "source.favorite"
    version: str = "2.0.0"

    def can_handle(self, text: str, options: SourceResolveOptions) -> bool:
        raw = (text or "").strip()
        return bool(_parse_favorite_id(raw)) or "favlist" in raw

    def resolve(self, text: str, options: SourceResolveOptions) -> list[SourceItem]:
        media_id = _parse_favorite_id(text)
        if not media_id:
            raise RuntimeError(f"invalid favorite url or media_id: {text}")

        limit = options.limit or DEFAULT_SPACE_LIMIT
        medias, list_title = _resolve_favorite_items(media_id, options.cookie_header, limit)

        items: list[SourceItem] = []
        for idx, media in enumerate(medias, start=1):
            bvid = media.get("bvid") or media.get("bv_id")
            if not bvid:
                continue

            upper = media.get("upper") or {}
            ugc = media.get("ugc") or {}
            title = media.get("title") or "UnknownTitle"

            items.append(
                SourceItem(
                    bvid=bvid,
                    aid=None,
                    cid=ugc.get("first_cid"),
                    title=title,
                    owner=upper.get("name") or "UnknownUP",
                    source_type="favorite",
                    page=media.get("page") or idx,
                    page_title=title,
                    video_url=_to_video_url(bvid),
                    source_meta=_build_source_meta(
                        container_type="favorite",
                        container_id=str(media_id),
                        container_title=list_title,
                        origin_url=text,
                        order=options.order,
                        page_num=idx,
                        page_size=len(medias),
                    ),
                )
            )

        return items


@dataclass
class CollectionSeriesSourcePlugin:
    id: str = "source.collection_series"
    version: str = "2.0.0"

    def can_handle(self, text: str, options: SourceResolveOptions) -> bool:
        raw = (text or "").strip().lower()
        return bool(
            re.match(r"^(season:[0-9]+|series:[0-9]+|ml[0-9]+)$", raw)
            or "collectiondetail" in raw
            or "seriesdetail" in raw
            or "/medialist/detail/ml" in raw
            or "/lists/" in raw
        )

    def resolve(self, text: str, options: SourceResolveOptions) -> list[SourceItem]:
        target = _parse_collection_or_series_target(text)
        kind = target["kind"]

        if kind == "ml":
            medias, container_title = _resolve_favorite_items(
                target["media_id"],
                options.cookie_header,
                options.limit or 2000,
            )
            items: list[SourceItem] = []
            for idx, media in enumerate(medias, start=1):
                bvid = media.get("bvid") or media.get("bv_id")
                if not bvid:
                    continue
                upper = media.get("upper") or {}
                ugc = media.get("ugc") or {}
                title = media.get("title") or "UnknownTitle"
                items.append(
                    SourceItem(
                        bvid=bvid,
                        cid=ugc.get("first_cid"),
                        title=title,
                        owner=upper.get("name") or "UnknownUP",
                        source_type="collection",
                        page=idx,
                        page_title=title,
                        video_url=_to_video_url(bvid),
                        source_meta=_build_source_meta(
                            container_type="collection",
                            container_id=f"ml{target['media_id']}",
                            container_title=container_title,
                            mid=target.get("mid"),
                            origin_url=target.get("origin_url") or text,
                            order=options.order,
                            page_num=idx,
                            page_size=len(medias),
                        ),
                    )
                )
            return items

        source_type = "collection" if kind == "collection" else "series"

        try:
            if kind == "collection":
                archives, resolved_mid, container_title = _resolve_collection_archives(
                    target["season_id"],
                    target.get("mid"),
                    options.cookie_header,
                )
                container_id = f"season:{target['season_id']}"
            else:
                archives, resolved_mid, container_title = _resolve_series_archives(
                    target["series_id"],
                    target.get("mid"),
                    options.cookie_header,
                )
                container_id = f"series:{target['series_id']}"

            items: list[SourceItem] = []
            for idx, archive in enumerate(archives, start=1):
                bvid = archive.get("bvid") or archive.get("bv_id") or archive.get("bvid_str")
                if not bvid:
                    continue

                owner = (
                    archive.get("author")
                    or archive.get("owner")
                    or ((archive.get("upper") or {}).get("name"))
                    or "UnknownUP"
                )
                cid = archive.get("cid")
                if cid is None:
                    cid = archive.get("first_cid")

                title = archive.get("title") or "UnknownTitle"
                items.append(
                    SourceItem(
                        bvid=bvid,
                        cid=cid,
                        title=title,
                        owner=owner,
                        source_type=source_type,
                        page=idx,
                        page_title=title,
                        video_url=_to_video_url(bvid),
                        source_meta=_build_source_meta(
                            container_type=source_type,
                            container_id=container_id,
                            container_title=container_title,
                            mid=resolved_mid,
                            origin_url=target.get("origin_url") or text,
                            order=options.order,
                            page_num=idx,
                            page_size=len(archives),
                        ),
                    )
                )
            if items:
                return items
        except Exception:
            pass

        origin_url = target.get("origin_url") or text
        if not origin_url:
            raise RuntimeError("collection/series api failed and no url for yt-dlp fallback")

        return _resolve_via_ytdlp_flat(
            origin_url,
            source_type=source_type,
            source_meta=_build_source_meta(
                container_type=source_type,
                container_id=str(target.get("series_id") or target.get("season_id") or ""),
                origin_url=origin_url,
                order=options.order,
            ),
            limit=options.limit,
        )


@dataclass
class SpaceUploadsSourcePlugin:
    id: str = "source.space_uploads"
    version: str = "2.0.0"

    def can_handle(self, text: str, options: SourceResolveOptions) -> bool:
        raw = (text or "").strip()
        return raw.isdigit() or "space.bilibili.com" in raw

    def resolve(self, text: str, options: SourceResolveOptions) -> list[SourceItem]:
        mid = _parse_space_mid(text)
        limit = options.limit if options.limit is not None else DEFAULT_SPACE_LIMIT
        limit = max(1, int(limit))

        try:
            archives = _resolve_space_upload_archives(
                mid,
                options.cookie_header,
                limit=limit,
                order=options.order or "pubdate_desc",
            )
        except (WbiSigningError, HttpRequestError, RuntimeError):
            origin_url = text if text.startswith("http") else f"https://space.bilibili.com/{mid}/video"
            return _resolve_via_ytdlp_flat(
                origin_url,
                source_type="space_uploads",
                source_meta=_build_source_meta(
                    container_type="space_uploads",
                    container_id=str(mid),
                    mid=mid,
                    origin_url=origin_url,
                    order=options.order,
                ),
                limit=limit,
            )

        items: list[SourceItem] = []
        for idx, arc in enumerate(archives, start=1):
            bvid = arc.get("bvid") or _extract_bv(str(arc.get("aid") or ""))
            if not bvid:
                continue

            title = arc.get("title") or "UnknownTitle"
            owner = arc.get("author") or arc.get("name") or "UnknownUP"
            items.append(
                SourceItem(
                    bvid=bvid,
                    aid=arc.get("aid"),
                    cid=arc.get("cid"),
                    title=title,
                    owner=owner,
                    source_type="space_uploads",
                    page=idx,
                    page_title=title,
                    video_url=_to_video_url(bvid),
                    source_meta=_build_source_meta(
                        container_type="space_uploads",
                        container_id=str(mid),
                        mid=mid,
                        origin_url=text,
                        order=options.order,
                        page_num=idx,
                        page_size=len(archives),
                    ),
                )
            )

        return items


def get_builtin_source_plugins() -> list[tuple[dict, object]]:
    return [
        (
            {
                "id": "source.bv_video",
                "type": "source",
                "version": "2.0.0",
                "entry": "plugins.sources.builtin_sources:BvVideoSourcePlugin",
                "builtin": True,
                "required": True,
                "min_core_version": "2.0.0",
            },
            BvVideoSourcePlugin(),
        ),
        (
            {
                "id": "source.favorite",
                "type": "source",
                "version": "2.0.0",
                "entry": "plugins.sources.builtin_sources:FavoriteSourcePlugin",
                "builtin": True,
                "required": True,
                "min_core_version": "2.0.0",
            },
            FavoriteSourcePlugin(),
        ),
        (
            {
                "id": "source.collection_series",
                "type": "source",
                "version": "2.0.0",
                "entry": "plugins.sources.builtin_sources:CollectionSeriesSourcePlugin",
                "builtin": True,
                "required": False,
                "min_core_version": "2.0.0",
            },
            CollectionSeriesSourcePlugin(),
        ),
        (
            {
                "id": "source.space_uploads",
                "type": "source",
                "version": "2.0.0",
                "entry": "plugins.sources.builtin_sources:SpaceUploadsSourcePlugin",
                "builtin": True,
                "required": False,
                "min_core_version": "2.0.0",
            },
            SpaceUploadsSourcePlugin(),
        ),
    ]
