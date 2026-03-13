from typing import Protocol

from plugins.types import SourceItem, SourceResolveOptions


class SourcePlugin(Protocol):
    id: str
    version: str

    def can_handle(self, text: str, options: SourceResolveOptions) -> bool:
        ...

    def resolve(self, text: str, options: SourceResolveOptions) -> list[SourceItem]:
        ...
