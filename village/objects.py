"""Pydantic models for all JSON-defined content (see village/register.py).

Each model class name corresponds to a folder under ``content/`` (and under
any mod folder in ``content_custom/``) holding one JSON file per definition.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict


class Modifiers(BaseModel):
    """Standard linear modifier block used across vehicle definitions:

        value = base + tick*T + tile*D + weight*W + space*S

    What T/D/W/S mean is set by the consumer of the value:
      * trip cost & fuel: T = travel ticks, D = total tiles driven,
        W/S = cargo weight/space x one-way distance (so the JSON reads as
        "$x per unit-weight per tile", matching the design notes)
      * speed: W/S = plain cargo weight/space (e.g. -0.1 tiles/hour per
        unit of weight); T and D are unused.
    Coefficients that don't make sense in a context are simply left 0.
    """
    model_config = ConfigDict(frozen=True)

    base: float = 0.0
    tick: float = 0.0
    tile: float = 0.0
    weight: float = 0.0
    space: float = 0.0

    def evaluate(self, ticks: float = 0.0, tiles: float = 0.0,
                 weight: float = 0.0, space: float = 0.0) -> float:
        return (self.base + self.tick * ticks + self.tile * tiles
                + self.weight * weight + self.space * space)


class Cargo(BaseModel):
    """A weight/space pair: vehicle capacity or building storage."""
    model_config = ConfigDict(frozen=True)

    weight: float
    space: float


class Fuel(BaseModel):
    """What a vehicle consumes to run: points of a demand type (e.g. a
    horse's hunger), fed from the owner's stock of fulfilling products."""
    model_config = ConfigDict(frozen=True)

    type: str          # demand id
    amount: Modifiers  # demand points per trip, same context as cost


class VehicleDef(BaseModel):
    """A means of moving goods between parcels.

    The cost structure is the heart of the retail economy: ``cost.base``
    (setup/setdown per trip) usually outweighs the per-weight terms, so
    moving 10 units costs nearly the same as moving 1 -- which is the
    margin retailers and warehouses chase.
    """
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    buy_cost: float
    cargo: Cargo       # max weight/space per trip
    drivers: int = 1   # crew needed per trip (owner or hired staff)
    cost: Modifiers    # coin per trip
    fuel: Fuel
    speed: Modifiers   # tiles per tick (tick = 1 hour)
    color: Tuple[int, int, int]


class ProductDef(BaseModel):
    """Anything that can sit in an inventory and be traded."""
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    base_price: int
    color: Tuple[int, int, int]  # placeholder asset: solid color swatch
    weight: float = 1.0
    space: float = 1.0


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


class AdvertisingDef(BaseModel):
    """A way for a seller to buy knowledge edges to themselves.

    Each run picks ``reach`` people at random and makes them hear about the
    seller. ``falloff`` controls locality: None means village-wide uniform;
    otherwise P(target) is proportional to exp(-distance / falloff) from the
    campaign's parcel, so small values are hyper-local flyers and big values
    are wide-area campaigns.

    Hearing about a seller is not free attention: every impression adds ad
    fatigue, and people who hear about you more than the fatigue threshold
    intentionally forget you (and stay deaf to your ads until the fatigue
    fades via the normal forget flow).
    """
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    cost: int
    reach: int
    falloff: Optional[float] = None
    cooldown_days: int = 1
    description: str = ""


class RecipeDef(BaseModel):
    """One way of turning inputs into outputs. Machines list which recipes
    they can run; the actual time depends on the machine too (its ``rate``
    and per-recipe overrides), so the same recipe can be faster on better
    equipment."""
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    inputs: Dict[str, int] = {}
    outputs: Dict[str, int]
    base_ticks: int


class MachineDef(BaseModel):
    """A building that can execute a chosen recipe from its list.

    Machines are themselves products: building one consumes a machine "kit"
    (the product with the same id) from the parcel's inventory -- nothing
    appears from thin air. ``build_cost`` remains the book value used for
    upgrade pricing and net worth.

    ``workers`` operators (the owner and/or hired citizens) must be free
    for the machine to run. Level L multiplies batch size by ``2**(L-1)``.
    """
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    build_cost: float
    color: Tuple[int, int, int]  # placeholder asset: solid color block
    footprint: int = 1  # plot slots occupied (uniform for now)
    recipes: List[str] = []
    rate: float = 1.0                    # general speed multiplier
    recipe_rates: Dict[str, float] = {}  # per-recipe speed overrides
    workers: int = 1                     # operators needed to run
    # Extra weight/space this building adds to its parcel's storage.
    storage: Optional[Cargo] = None
    # Reseller buildings (stores, warehouses) mark their parcel's stock as
    # for sale even if the owner didn't produce it.
    resells: bool = False
