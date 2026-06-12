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
from .money import cents

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


def maintain_stockpile(world: "World", person: "Person") -> None:
    """Hard constraint: a person will not let themselves starve if they can
    help it. Every day they top their home reserves of every demand back up
    to PERSONAL_STOCKPILE_DAYS of coverage -- *before* hunger bites, at a
    reasonable price when stocked, at any affordable price when the pantry
    is empty. (Businesses may misjudge their stockpiles; people don't.)"""
    for d in DEMANDS:
        per_day = daily_points(d)
        if per_day <= 0 or not d.stockpile:
            continue  # you can't bank sleep ahead
        have = sum((person.home.inventory.get(pid, 0)
                    + person.inbound_total(pid)) * pts
                   for pid, pts in d.fulfilled_by.items())
        target = per_day * config.PERSONAL_STOCKPILE_DAYS
        # Only go shopping when genuinely low: every trip costs someone's
        # working hours, so people buy several days at once.
        if have >= per_day * config.STOCKPILE_TRIGGER_DAYS:
            continue
        desperate = have <= 0
        gap = target - have
        # Best delivered value per demand point among fulfilling products.
        best = None  # (value, pid, qty)
        for pid, pts in d.fulfilled_by.items():
            qty = max(1, math.ceil(gap / pts))
            quote = trade.best_quote(world, person, pid, qty, person.home,
                                     respect_capacity=False)
            if quote is None:
                continue
            if not desperate and quote.unit_cost > _tolerance(pid):
                continue
            value = quote.unit_cost / pts
            if best is None or value < best[0]:
                best = (value, pid, qty)
        if best is not None:
            _, pid, qty = best
            trade.buy(world, person, pid, qty=qty, dest=person.home,
                      respect_capacity=False,
                      allow_referral=desperate)


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
    return cents(PRODUCTS.get(product_id).base_price) * config.WANT_PRICE_TOLERANCE


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
    #    (No loyalty to sellers they've since forgotten.)
    if (mem is not None and rng.random() < d.loyalty.seller
            and (mem[0] in person.knowledge or mem[0] == person.id)):
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
    # Only essential demands buy at literally any price -- nobody pays a
    # famine premium for a bed, so rents stay tethered to base prices.
    if urgent:
        for pid in sorted(d.fulfilled_by, key=lambda p: -d.fulfilled_by[p]):
            if trade.buy(world, person, pid, qty=buy_qty(d, pid),
                         dest=person.home, allow_referral=True,
                         respect_capacity=False,
                         max_unit_cost=None if d.essential
                         else _tolerance(pid)):
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
        if (not urgent or not d.essential) and quote.unit_cost > _tolerance(pid):
            continue  # non-essentials never pay a desperation premium
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
