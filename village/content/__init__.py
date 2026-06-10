"""Typed views over the JSON content registry (village/register.py).

Game code does ``from village.content import PRODUCTS, MACHINES`` and uses
``.get(id)`` / iteration; the definitions themselves live in ``content/`` as
JSON validated against the models in ``village/objects.py``.
"""

from __future__ import annotations

from typing import Generic, Iterator, List, TypeVar

from .. import register
from ..objects import MachineDef, ProductDef

T = TypeVar("T")


class ContentView(Generic[T]):
    """Read-only id-keyed view of one model's entries in the registry."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    @property
    def _entries(self) -> dict:
        try:
            return register.REGISTRY[self.model_name]
        except KeyError:
            raise RuntimeError(
                f"content not loaded (no {self.model_name!r} in registry); "
                "call village.content.load_all() first") from None

    def get(self, item_id: str) -> T:
        try:
            return self._entries[item_id]
        except KeyError:
            raise KeyError(
                f"unknown {self.model_name} id: {item_id!r}") from None

    def all(self) -> List[T]:
        return list(self._entries.values())

    def ids(self) -> List[str]:
        return list(self._entries.keys())

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._entries

    def __iter__(self) -> Iterator[T]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


PRODUCTS: ContentView[ProductDef] = ContentView("ProductDef")
MACHINES: ContentView[MachineDef] = ContentView("MachineDef")

_loaded = False


def load_all(force: bool = False) -> None:
    global _loaded
    if _loaded and not force:
        return
    register.load()
    _loaded = True


__all__ = ["load_all", "PRODUCTS", "MACHINES"]
