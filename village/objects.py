"""Pydantic models for all JSON-defined content (see village/register.py).

Each model class name corresponds to a folder under ``content/`` (and under
any mod folder in ``content_custom/``) holding one JSON file per definition.
"""

from __future__ import annotations

from typing import Dict, Tuple

from pydantic import BaseModel, ConfigDict


class ProductDef(BaseModel):
    """Anything that can sit in an inventory and be traded.

    ``food_value > 0`` means a hungry person can eat one unit to reduce
    hunger by ``food_value * HUNGER_PER_FOOD_VALUE`` (see sim.config).
    """
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    base_price: int
    color: Tuple[int, int, int]  # placeholder asset: solid color swatch
    food_value: int = 0


class MachineDef(BaseModel):
    """A machine recipe: consumes ``inputs`` from the owner's inventory over
    ``cycle_ticks`` ticks, then adds ``outputs``. Level L multiplies batch
    size by ``2 ** (L - 1)``; upgrade costs grow exponentially (sim.machine).

    All machines occupy exactly one plot slot for now.
    """
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    inputs: Dict[str, int] = {}
    outputs: Dict[str, int]
    cycle_ticks: int
    build_cost: int
    color: Tuple[int, int, int]  # placeholder asset: solid color block
    footprint: int = 1  # plot slots occupied (uniform for now)
