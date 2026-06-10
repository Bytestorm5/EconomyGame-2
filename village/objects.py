"""Pydantic models for all JSON-defined content (see village/register.py).

Each model class name corresponds to a folder under ``content/`` (and under
any mod folder in ``content_custom/``) holding one JSON file per definition.
"""

from __future__ import annotations

from typing import Dict, Tuple

from pydantic import BaseModel, ConfigDict


class ProductDef(BaseModel):
    """Anything that can sit in an inventory and be traded."""
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    base_price: int
    color: Tuple[int, int, int]  # placeholder asset: solid color swatch


class Urgency(BaseModel):
    """Cascading thresholds for consumer behaviour on a demand."""
    model_config = ConfigDict(frozen=True)

    want: int   # at this many points: fulfill from reserves or buy, but
                # only at a reasonable price (skip if too expensive)
    need: int   # at this many points: fulfill at any affordable cost,
                # asking around (referrals) if nobody known sells


class Loyalty(BaseModel):
    """Chance of skipping comparison shopping when fulfilling a demand.

    Loyalty only holds while it works: the customer zooms back out to full
    price comparison if the remembered seller/product has no stock or is
    too expensive for them right now.
    """
    model_config = ConfigDict(frozen=True)

    seller: float = 0.0   # P(go straight back to the last seller bought
                          # from for this demand, even for a different product)
    product: float = 0.0  # P(re-buy the same product as last time, even
                          # from a different seller)


class DemandDef(BaseModel):
    """A recurring consumer demand (e.g. hunger) and how it's satisfied.

    ``fulfilled_by`` maps product id -> points of this demand one unit
    fulfills. ``contributors`` maps source -> points added; supported
    sources: "tick" (every sim tick) and "daily" (once per sim day).
    """
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    fulfilled_by: Dict[str, int]
    contributors: Dict[str, float]
    urgency: Urgency
    loyalty: Loyalty = Loyalty()


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
