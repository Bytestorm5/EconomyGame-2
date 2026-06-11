"""Data-driven consumer demands (content/DemandDef/*.json).

Each demand accumulates points from its contributors ("tick" every tick,
"daily" once a day). Urgency is a cascading threshold on those points:

  * below ``want``  -- ignored.
  * at ``want``     -- fulfill from home reserves, or order from a known
                       seller at a reasonable *delivered* price
                       (<= base price * WANT_PRICE_TOLERANCE incl. the trip).
  * at ``need``     -- fulfill at any affordable cost, asking around
                       (referral search) if nobody known sells.

Purchases are vehicle trips that take time: a person orders a couple of
days' worth at once (amortizing the trip's base cost), then eats from home
stock as it arrives. While an order is en route they wait instead of
re-ordering.

Loyalty makes consumers sticky: per fulfillment there's a chance they skip
comparison shopping and go straight back to the last seller (even for a
different product) or re-buy the last product (even from a different
seller). They zoom back out whenever the remembered option has no stock or
is too expensive for them right now.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, List, Optional

from ..content import DEMANDS, PRODUCTS
from ..objects import DemandDef
from . import config, trade

if TYPE_CHECKING:
    from .person import Person
    from .world import World


def tick(world: "World", person: "Person") -> None:
    for d in DEMANDS:
        pts = person.demands.get(d.id, 0.0) + d.contributors.get("tick", 0.0)
        person.demands[d.id] = min(pts, d.urgency.need * config.DEMAND_CAP_FACTOR)
        if pts >= d.urgency.want:
            fulfill(world, person, d, urgent=pts >= d.urgency.need)


def daily(world: "World", person: "Person") -> None:
    for d in DEMANDS:
        daily_pts = d.contributors.get("daily", 0.0)
        if daily_pts:
            pts = person.demands.get(d.id, 0.0) + daily_pts
            person.demands[d.id] = min(pts,
                                       d.urgency.need * config.DEMAND_CAP_FACTOR)


def daily_points(d: DemandDef) -> float:
    return (d.contributors.get("tick", 0.0) * config.TICKS_PER_DAY
            + d.contributors.get("daily", 0.0))


def buy_qty(d: DemandDef, product_id: str) -> int:
    """Units per order: a couple of days' worth, so the trip's base cost is
    spread over several units (a single loaf rarely justifies the cart)."""
    per_unit = d.fulfilled_by[product_id]
    need = daily_points(d) * config.DEMAND_BUY_DAYS
    return max(1, math.ceil(need / per_unit))


def _consume(person: "Person", d: DemandDef, product_id: str) -> None:
    person.remove_items(product_id, 1)  # from home
    person.demands[d.id] = max(
        0.0, person.demands.get(d.id, 0.0) - d.fulfilled_by[product_id])


def _tolerance(product_id: str) -> float:
    return PRODUCTS.get(product_id).base_price * config.WANT_PRICE_TOLERANCE


def fulfill(world: "World", person: "Person", d: DemandDef,
            urgent: bool) -> bool:
    # 1) Home reserves first (loyalty product preferred, else best points).
    mem = person.demand_memory.get(d.id)
    on_hand = [pid for pid in d.fulfilled_by
               if person.home.inventory.get(pid, 0) > 0]
    if on_hand:
        if mem and mem[1] in on_hand:
            pid = mem[1]
        else:
            pid = max(on_hand, key=lambda p: d.fulfilled_by[p])
        _consume(person, d, pid)
        return True

    # An order is already on its way: wait for the cart, don't double-buy.
    if any(person.inbound_total(pid) > 0 for pid in d.fulfilled_by):
        return False

    rng = world.rng

    # 2) Seller loyalty: go straight back to the last seller, taking their
    #    best fulfilling product, skipping the wider price comparison.
    if mem is not None and rng.random() < d.loyalty.seller:
        seller = world.people.get(mem[0])
        if seller is not None and _order(world, person, d, [seller],
                                         list(d.fulfilled_by), urgent):
            return True
        # zoom out: loyalty failed (no stock / too expensive / no vehicle)

    # 3) Product loyalty: re-buy the last product, from whoever's cheapest.
    products = list(d.fulfilled_by)
    if mem is not None and mem[1] in products and rng.random() < d.loyalty.product:
        if _order(world, person, d, None, [mem[1]], urgent):
            return True
        products = [p for p in products if p != mem[1]]  # zoom out

    # 4) Full comparison shopping over remaining fulfilling products.
    if _order(world, person, d, None, products, urgent):
        return True

    # 5) Desperate: ask around for anything that fulfills, best points first.
    if urgent:
        for pid in sorted(d.fulfilled_by, key=lambda p: -d.fulfilled_by[p]):
            if trade.buy(world, person, pid, qty=buy_qty(d, pid),
                         dest=person.home, allow_referral=True,
                         respect_capacity=False):
                person.demand_memory[d.id] = (person.id, pid)
                return True
        person.unfulfilled[d.id] = person.unfulfilled.get(d.id, 0) + 1
    return False


def _order(world: "World", person: "Person", d: DemandDef,
           sellers: Optional[List["Person"]], products: List[str],
           urgent: bool) -> bool:
    """Order whichever product has the best delivered cost per demand
    point, restricted to the given sellers/products."""
    best = None  # (value, pid, quote)
    for pid in products:
        quote = trade.best_quote(world, person, pid, buy_qty(d, pid),
                                 person.home, sellers=sellers,
                                 respect_capacity=False)
        if quote is None:
            continue
        if not urgent and quote.unit_cost > _tolerance(pid):
            continue
        value = quote.unit_cost / d.fulfilled_by[pid]
        if best is None or value < best[0]:
            best = (value, pid, quote)
    if best is None:
        return False
    _, pid, quote = best
    if trade.place_order(world, person, quote, pid, person.home) == 0:
        return False
    person.demand_memory[d.id] = (quote.offer.seller.id, pid)
    return True
