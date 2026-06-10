"""Content registry system.

All game content (products, machines, ...) is defined as frozen dataclasses
and registered here by string id. Game code never hardcodes content; it looks
definitions up through the registry, so new content can be added purely by
adding definitions in ``village/content/``.

NOTE: This is a fresh implementation written to the spirit of the original
project's registry (the original file was not available). It is deliberately
small: typed categories, duplicate-id protection, and decorator registration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Generic, Iterator, List, Type, TypeVar


@dataclass(frozen=True)
class ContentDef:
    """Base class for all registrable content definitions."""

    id: str
    name: str


T = TypeVar("T", bound=ContentDef)


class Registry(Generic[T]):
    """A single category of content (e.g. all products), keyed by id."""

    def __init__(self, kind: str, base_type: Type[T] = ContentDef):
        self.kind = kind
        self.base_type = base_type
        self._items: Dict[str, T] = {}

    def register(self, item: T) -> T:
        if not isinstance(item, self.base_type):
            raise TypeError(
                f"{self.kind!r} registry expects {self.base_type.__name__}, "
                f"got {type(item).__name__}"
            )
        if item.id in self._items:
            raise ValueError(f"duplicate {self.kind} id: {item.id!r}")
        self._items[item.id] = item
        return item

    def get(self, item_id: str) -> T:
        try:
            return self._items[item_id]
        except KeyError:
            raise KeyError(f"unknown {self.kind} id: {item_id!r}") from None

    def all(self) -> List[T]:
        return list(self._items.values())

    def ids(self) -> List[str]:
        return list(self._items.keys())

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def __iter__(self) -> Iterator[T]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


class ContentRegistry:
    """Umbrella over all content categories."""

    def __init__(self) -> None:
        self._categories: Dict[str, Registry] = {}

    def category(self, kind: str, base_type: Type[T] = ContentDef) -> Registry[T]:
        if kind not in self._categories:
            self._categories[kind] = Registry(kind, base_type)
        return self._categories[kind]

    def clear(self) -> None:
        for reg in self._categories.values():
            reg.clear()


#: The global registry instance used by the whole game.
REGISTRY = ContentRegistry()
