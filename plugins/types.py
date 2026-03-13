from dataclasses import dataclass, field
from typing import Optional


SOURCE_META_REQUIRED_KEYS = (
    "container_type",
    "container_id",
    "container_title",
    "mid",
    "origin_url",
    "order",
    "page_num",
    "page_size",
)


@dataclass
class SourceResolveOptions:
    cookie_header: Optional[str] = None
    limit: Optional[int] = None
    order: str = "pubdate_desc"
    import_mode: str = "single"


@dataclass
class SourceItem:
    bvid: str
    aid: Optional[int] = None
    cid: Optional[int] = None
    title: str = "UnknownTitle"
    owner: str = "UnknownUP"
    source_type: str = "single"
    page: Optional[int] = None
    page_title: str = ""
    video_url: str = ""
    source_meta: dict = field(default_factory=dict)
