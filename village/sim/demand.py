"""Data-driven consumer demands (content/DemandDef/*.json).

Each demand accumulates points from its contributors ("tick" every tick,
"daily" once a day). Urgency is a cascading threshold on those points:

  * below ``want``  -- ignored.
  * at ``want``     -- fulfill from home reserves, or buy from a known
                       seller, but only at a reasonable delivered price
                       (<= base price * WANT_PRICE_TOLERANCE).
  * at ``need``     -- fulfill at any affordable cost, asking around
                       (referral search) if nobody known sells.

Loyalty makes consumers sticky: per fulfillment there's a chance they skip
comparison shopping and go straight back to the last seller (even for a
different product) or re-buy the last product (even from a different
seller). They zoom back out to full price comparison whenever the
remembered option has no stock or is too expensive for them right now.
"""

from __future__ import annotations

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


def _consume(person: "Person", d: DemandDef, product_id: str) -> None:
    person.remove_items(product_id, 1)  # from home
    person.demands[d.id] = max(
        0.0, person.demands.get(d.id, 0.0) - d.fulfilled_by[product_id])


def _affordable(offer: trade.Offer, person: "Person", product_id: str,
                urgent: bool) -> bool:
    if offer.ceil_unit_cost() > person.money:
        return False
    if urgent:
        return True
    limit = PRODUCTS.get(product_id).base_price * config.WANT_PRICE_TOLERANCE
    return offer.unit_cost <= limit


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

    rng = world.rng

    # 2) Seller loyalty: go straight back to the last seller, taking their
    #    best fulfilling product, skipping the price comparison.
    if mem is not None and rng.random() < d.loyalty.seller:
        seller = world.people.get(mem[0])
        if seller is not None and _buy_from(world, person, d, [seller],
                                            list(d.fulfilled_by), urgent):
            return True
        # zoom out: loyalty failed (no stock / too expensive)

    # 3) Product loyalty: re-buy the last product, from whoever's cheapest.
    products = list(d.fulfilled_by)
    if mem is not None and mem[1] in products and rng.random() < d.loyalty.product:
        if _buy_from(world, person, d, None, [mem[1]], urgent):
            return True
        products = [p for p in products if p != mem[1]]  # zoom out

    # 4) Full comparison shopping over remaining fulfilling products.
    if _buy_from(world, person, d, None, products, urgent):
        return True

    # 5) Desperate: ask around for anything that fulfills, best points first.
    if urgent:
        for pid in sorted(d.fulfilled_by, key=lambda p: -d.fulfilled_by[p]):
            if trade.buy(world, person, pid, qty=1, dest=person.home,
                         allow_referral=True):
                person.demand_memory[d.id] = (person.id, pid)
                _consume(person, d, pid)
                return True
        person.unfulfilled[d.id] = person.unfulfilled.get(d.id, 0) + 1
    return False


def _buy_from(world: "World", person: "Person", d: DemandDef,
              sellers: Optional[List["Person"]], products: List[str],
              urgent: bool) -> bool:
    """Buy 1 unit of whichever product has the best delivered cost per
    demand point, restricted to the given sellers/products. Consumes it."""
    best = None  # (value, pid, offer)
    for pid in products:
        offer = trade.best_offer(world, person, pid, person.home, sellers)
        if offer is None or not _affordable(offer, person, pid, urgent):
            continue
        value = offer.unit_cost / d.fulfilled_by[pid]
        if best is None or value < best[0]:
            best = (value, pid, offer)
    if best is None:
        return False
    _, pid, offer = best
    if trade.execute(world, person, offer, pid, 1, person.home) == 0:
        return False
    person.demand_memory[d.id] = (offer.seller.id, pid)
    _consume(person, d, pid)
    return True
