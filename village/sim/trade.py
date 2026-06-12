"""Trading through the knowledge graph, with vehicles, transit time, and
per-parcel stock & storage.

Buying is now an *order*: goods leave the source parcel immediately (money
for the sale and the trip is paid up front), a vehicle of the buyer makes
the round trip, and the goods land in the destination parcel when it
returns. While the vehicle is out it can't serve other orders -- that's
throughput.

Trip cost is dominated by the vehicle's base + per-tile terms, with only
tiny weight/space modifiers, so hauling a full load costs nearly the same
as hauling one unit. Buyers compare *delivered* unit cost (price +
trip/qty), which is exactly the margin retailers and warehouses chase:
buy in bulk cheaply, sell nearby at a markup that still undercuts what a
single-unit fetch would cost the customer.

A buyer only sees offers from people they know (the player's auto-buy sees
everyone -- their unfair advantage). If nobody known sells a product, they
ask a random acquaintance to look; the search recurses outward with
decaying probability, and a successful referral forms a knowledge edge.
Trip costs go to the village treasury ("the carters") so money is conserved.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Tuple

from ..content import DEMANDS
from . import config
from .vehicle import Vehicle

if TYPE_CHECKING:
    from .person import Person
    from .plot import Plot
    from .world import World


@dataclass
class TradeStats:
    trades: int = 0
    volume: int = 0          # total coins exchanged in sales
    shipping_paid: int = 0   # total coins spent on trips
    trips: int = 0
    referrals_attempted: int = 0
    referrals_succeeded: int = 0
    edges_formed: int = 0
    edges_lost: int = 0
    ads_run: int = 0
    ad_impressions: int = 0
    spoiled: int = 0


@dataclass
class Shipment:
    """Goods in transit on a buyer's vehicle: parked -> src (empty leg),
    then src -> dest (loaded leg, where the vehicle stays parked). A trip
    carries a *manifest* -- several products from one source -- because the
    trip's base cost is the same either way (the warehouse advantage)."""
    buyer: "Person"
    seller: Optional["Person"]   # None for transfers between own parcels
    vehicle: Vehicle
    items: Dict[str, int]
    start: "Plot"                # where the vehicle was parked
    src: "Plot"
    dest: "Plot"
    depart: int
    arrive: int


@dataclass
class Offer:
    """One parcel's stock of a product (sale price; trip cost comes from
    whichever vehicle the buyer can put on the route)."""
    seller: "Person"
    plot: "Plot"
    price: int               # per unit; 0 when moving your own goods


@dataclass
class Quote:
    """An offer priced for delivery: a concrete vehicle, qty and cost."""
    offer: Offer
    vehicle: Vehicle
    qty: int                 # units this vehicle/storage/stock allows
    trip_cost: int           # whole-coin cost of the trip
    unit_cost: float         # price + trip_cost/qty

    @property
    def sale_cost(self) -> int:
        return self.offer.price * self.qty


def free_crew(world: "World", owner: "Person") -> List["Person"]:
    """People in the owner's workforce (themselves + staff) who aren't out
    driving right now. Owners drive their own carts when free."""
    members = [owner] + [world.people[i] for i in owner.staff
                         if i in world.people]
    return [m for m in members if not m.is_busy(world.tick_count)]


def _feeds(vehicle: Vehicle, product_id: str) -> bool:
    """Is this product feed for the vehicle's fuel demand? (Feed runs are
    exempt from the fuel block, so a hungry horse can still fetch its hay.)"""
    fuel = vehicle.definition.fuel
    return fuel.type in DEMANDS and product_id in DEMANDS.get(fuel.type).fulfilled_by


def iter_offers(world: "World", buyer: "Person", product_id: str,
                sellers: Optional[List["Person"]] = None,
                producers_only: bool = False,
                upstream_of: Optional["Plot"] = None) -> Iterator[Offer]:
    """All external offers visible to the buyer.

    ``upstream_of`` enforces the wholesale tier for reseller restock: a
    reseller only buys from producers or from reseller parcels with
    meaningfully more storage (stores buy from warehouses, warehouses from
    producers) -- strict ordering, so goods never ping-pong between shops."""
    if sellers is None:
        ids = world.people.keys() if buyer.is_player else buyer.knowledge
        # Knowledge can briefly reference people who emigrated (e.g. when
        # the buyer themselves left mid-shipment); skip the departed.
        sellers = [world.people[pid] for pid in ids if pid in world.people]
    for seller in sellers:
        if seller is buyer:
            continue
        produced = product_id in seller.produced_products()
        if producers_only and not produced:
            continue
        price = seller.price_of(product_id)
        for plot in seller.selling_plots(product_id):
            if (upstream_of is not None and not produced
                    and plot.capacity()[0]
                    < upstream_of.capacity()[0] * 1.5):
                continue  # not upstream enough in the wholesale chain
            yield Offer(seller, plot, price)


def internal_offers(buyer: "Person", product_id: str,
                    dest: "Plot") -> Iterator[Offer]:
    """The buyer's own other parcels: free goods, but the trip still costs."""
    for plot in buyer.plots:
        if plot is not dest and plot.inventory.get(product_id, 0) > 0:
            yield Offer(buyer, plot, 0)


def make_quote(world: "World", buyer: "Person", offer: Offer,
               product_id: str, qty: int, dest: "Plot",
               feed_run: bool = False,
               respect_capacity: bool = True) -> Optional[Quote]:
    """Pick the buyer's best idle vehicle for this offer and price the trip.
    Returns None if no vehicle can run it or nothing fits/remains.

    ``respect_capacity=False`` is for goods bound for immediate consumption
    (meals, vehicle feed): the pantry isn't the warehouse, so a full parcel
    can still receive them."""
    qty = min(qty, offer.plot.inventory.get(product_id, 0))
    if respect_capacity:
        qty = min(qty, dest.max_fit(product_id))
    if qty <= 0:
        return None
    d_loaded = offer.plot.distance_to(dest)
    crew = free_crew(world, buyer)
    best: Optional[Quote] = None
    for vehicle in buyer.vehicles:
        if not vehicle.idle(world.tick_count):
            continue
        if vehicle.definition.drivers > len(crew):
            continue  # nobody free to drive it
        if vehicle.blocked and not (feed_run and _feeds(vehicle, product_id)):
            continue
        q = min(qty, vehicle.max_qty(product_id))
        if q <= 0:
            continue
        # Positioning leg from wherever this vehicle is parked: a cart
        # already near the seller quotes cheaper than one across town.
        d_empty = vehicle.plot.distance_to(offer.plot)
        cost = math.ceil(
            vehicle.trip_cost(d_empty, d_loaded, product_id, q) * 100)
        unit = offer.price + cost / q
        if best is None or unit < best.unit_cost:
            best = Quote(offer, vehicle, q, cost, unit)
    return best


def best_quote(world: "World", buyer: "Person", product_id: str, qty: int,
               dest: "Plot", sellers: Optional[List["Person"]] = None,
               producers_only: bool = False, feed_run: bool = False,
               respect_capacity: bool = True,
               upstream_of: Optional["Plot"] = None,
               basket: Optional[Dict[str, int]] = None) -> Optional[Quote]:
    """Cheapest *delivered* option: external sellers and the buyer's own
    parcels compete on price + trip cost per unit.

    With a ``basket`` (the rest of today's shopping list), one-stop
    sourcing applies: a source that also stocks more of the basket wins
    over a slightly cheaper single-product source, because it saves whole
    trips."""
    candidates = list(iter_offers(world, buyer, product_id, sellers,
                                  producers_only, upstream_of))
    candidates.extend(internal_offers(buyer, product_id, dest))
    quotes = []
    for offer in candidates:
        quote = make_quote(world, buyer, offer, product_id, qty, dest,
                           feed_run, respect_capacity)
        if quote is not None:
            quotes.append(quote)
    if not quotes:
        return None
    cheapest = min(q.unit_cost for q in quotes)
    if not basket:
        return min(quotes, key=lambda q: q.unit_cost)

    def coverage(q: Quote) -> int:
        src, seller = q.offer.plot, q.offer.seller
        internal = seller is buyer
        n = 0
        for pid in basket:
            if pid == product_id:
                continue
            if src.inventory.get(pid, 0) > 0 and (
                    internal or pid in seller.sellable_products()):
                n += 1
        return n

    eligible = [q for q in quotes
                if q.unit_cost <= cheapest * (1 + config.ONE_STOP_TOLERANCE)]
    return max(eligible, key=lambda q: (coverage(q), -q.unit_cost))


def place_order(world: "World", buyer: "Person", quote: Quote,
                product_id: str, dest: "Plot", wanted: int = None,
                extras: Optional[Dict[str, int]] = None) -> int:
    """Commit a quote: pay, load, and dispatch the vehicle. ``extras`` are
    additional wants that ride along from the same source parcel while
    cargo room, stock, storage, and coin allow -- one trip, one base cost,
    many products. Returns units of the primary product ordered."""
    offer, vehicle = quote.offer, quote.vehicle
    internal = offer.seller is buyer
    d_empty = vehicle.plot.distance_to(offer.plot)
    d_loaded = offer.plot.distance_to(dest)

    def price_of(pid: str) -> int:
        if internal:
            return 0
        return offer.seller.price_of(pid)

    def available(pid: str) -> int:
        if internal:
            return offer.plot.inventory.get(pid, 0)
        return (offer.plot.inventory.get(pid, 0)
                if pid in offer.seller.sellable_products() else 0)

    # Manifest fill: share the cart between the lead product and the
    # ride-alongs, round-robin with the lead getting a double share --
    # otherwise the lead fills the cart and extras never ride.
    requests: Dict[str, int] = {product_id: quote.qty}
    for pid, q in (extras or {}).items():
        if pid != product_id and q > 0:
            q = min(q, available(pid), dest.max_fit(pid))
            if q > 0:
                requests[pid] = q
    items: Dict[str, int] = {}
    rotation = [product_id, product_id] + [p for p in requests
                                           if p != product_id]
    stalled_rounds = 0
    while stalled_rounds < 1:
        stalled_rounds = 1
        for pid in rotation:
            if requests.get(pid, 0) <= items.get(pid, 0):
                continue
            trial = {**items, pid: items.get(pid, 0) + 1}
            if vehicle.fits(trial):
                items = trial
                stalled_rounds = 0
    if items.get(product_id, 0) <= 0:
        return 0

    def totals(man: Dict[str, int]) -> Tuple[int, int]:
        sale = sum(price_of(pid) * q for pid, q in man.items())
        cost = math.ceil(vehicle.trip_cost(
            d_empty, d_loaded, cargo=Vehicle.manifest_cargo(man)) * 100)
        return sale, cost

    # Affordability: shed extras first, then shrink the primary load.
    while True:
        sale, cost = totals(items)
        if sale + cost <= buyer.money:
            break
        shed = next((pid for pid in items if pid != product_id), None)
        if shed is not None:
            items[shed] -= 1
            if items[shed] <= 0:
                del items[shed]
        elif items[product_id] > 1:
            items[product_id] -= 1
        else:
            return 0

    sale, cost = totals(items)
    ticks = vehicle.trip_ticks(d_empty, d_loaded,
                               cargo=Vehicle.manifest_cargo(items))

    buyer.money -= sale + cost
    if not internal:
        buyer.last_bought[offer.seller.id] = world.tick_count
    world.treasury += cost  # the carters' wages, recirculated via tithe
    world.stats.shipping_paid += cost
    world.stats.trips += 1
    for pid, q in items.items():
        line = price_of(pid) * q
        buyer.stat(pid).spent += line
        if not internal and q > 0:
            unit = line / q
            old = buyer.cost_basis.get(pid)
            buyer.cost_basis[pid] = (unit if old is None
                                     else 0.7 * old + 0.3 * unit)
            # Resellers anchor their asking price to a markup over cost
            # the moment goods arrive -- wholesale lives on the spread.
            if (pid not in buyer.produced_products()
                    and not buyer.is_player):
                anchor = int(buyer.cost_basis[pid] * config.RESALE_MARKUP)
                if buyer.prices.get(pid, 0) < anchor or pid not in buyer.prices:
                    buyer.prices[pid] = max(buyer.prices.get(pid, 0), anchor)
        if not internal:
            offer.seller.money += line
            offer.seller.stat(pid).sold += q
            offer.seller.stat(pid).revenue += line
            world.stats.trades += 1
            world.stats.volume += line
            units, value = world.market_today.get(pid, (0, 0))
            world.market_today[pid] = (units + q, value + line)
        offer.plot.inventory[pid] -= q
        dest.reserve(pid, q)
        key = (dest.id, pid)
        buyer.inbound[key] = buyer.inbound.get(key, 0) + q

    # The trip itself is a cost of doing business on the primary product.
    buyer.stat(product_id).spent += cost
    vehicle.busy_until = world.tick_count + ticks
    vehicle.fuel_due += vehicle.trip_fuel(
        d_empty, d_loaded, cargo=Vehicle.manifest_cargo(items))
    vehicle.trips += 1
    # Crew rides along: employees first so the owner can keep working.
    if vehicle.definition.drivers > 0:
        crew = free_crew(world, buyer)
        crew.sort(key=lambda c: c is buyer)
        for driver in crew[:vehicle.definition.drivers]:
            driver.busy_until = world.tick_count + ticks
    world.shipments.append(Shipment(
        buyer, None if internal else offer.seller, vehicle,
        dict(items), vehicle.plot, offer.plot, dest,
        world.tick_count, world.tick_count + ticks))
    vehicle.plot = dest  # it will be parked there when the trip ends

    qty = items.get(product_id, 0)
    # Wanted more, stock and storage allowed more, but the vehicle didn't:
    # signal that a bigger vehicle would pay off.
    if wanted is not None and qty < wanted:
        more = min(wanted, available(product_id) + qty,
                   dest.max_fit(product_id) + qty)
        if more > qty and not vehicle.fits(
                {**items, product_id: qty + 1}):
            buyer.capped_trips += 1
    return qty


def deliver(world: "World", shipment: Shipment) -> None:
    dest = shipment.dest
    for pid, qty in shipment.items.items():
        dest.release(pid, qty)
        dest.inventory[pid] += qty
        key = (dest.id, pid)
        left = shipment.buyer.inbound.get(key, 0) - qty
        if left > 0:
            shipment.buyer.inbound[key] = left
        else:
            shipment.buyer.inbound.pop(key, None)


def referral_search(world: "World", buyer: "Person",
                    product_id: str) -> Optional["Person"]:
    """Walk the knowledge graph looking for a seller on buyer's behalf."""
    rng = world.rng
    world.stats.referrals_attempted += 1
    visited = {buyer.id}
    candidates = [pid for pid in buyer.knowledge
                  if pid not in visited and pid in world.people]
    if not candidates:
        return None
    current = world.people[rng.choice(candidates)]

    for depth in range(1, config.REFERRAL_MAX_DEPTH + 1):
        visited.add(current.id)
        # The person asked might sell it themself...
        if current.sells(product_id):
            return current
        # ...or know someone who does.
        known = [world.people[pid] for pid in current.knowledge
                 if pid != buyer.id and pid in world.people]
        sellers = [p for p in known if p.sells(product_id)]
        if sellers:
            return min(sellers, key=lambda p: p.price_of(product_id))
        # Recurse one hop further with decaying probability.
        if rng.random() > config.REFERRAL_CONTINUE_PROB ** depth:
            return None
        nxt = [pid for pid in current.knowledge
               if pid not in visited and pid in world.people]
        if not nxt:
            return None
        current = world.people[rng.choice(nxt)]
    return None


def add_edge(world: "World", a: "Person", b: "Person") -> None:
    if b.id not in a.knowledge:
        a.knowledge.add(b.id)
        b.knowledge.add(a.id)
        world.stats.edges_formed += 1


def remove_edge(world: "World", a: "Person", b: "Person") -> None:
    if b.id in a.knowledge:
        a.knowledge.discard(b.id)
        b.knowledge.discard(a.id)
        world.stats.edges_lost += 1


def buy(world: "World", buyer: "Person", product_id: str, qty: int = 1,
        dest: Optional["Plot"] = None, allow_referral: bool = True,
        producers_only: bool = False, feed_run: bool = False,
        respect_capacity: bool = True,
        max_unit_cost: Optional[float] = None,
        upstream_of: Optional["Plot"] = None,
        extras: Optional[Dict[str, int]] = None) -> int:
    """Order up to qty units delivered to dest (default: buyer's home),
    taking the cheapest delivered source first. Each order occupies one
    vehicle for the duration of its round trip, so large wants may take
    several vehicles or several days. Returns units ordered (not yet
    arrived)."""
    dest = dest or buyer.home
    ordered = 0
    while ordered < qty:
        quote = best_quote(world, buyer, product_id, qty - ordered, dest,
                           producers_only=producers_only, feed_run=feed_run,
                           respect_capacity=respect_capacity,
                           upstream_of=upstream_of, basket=extras)
        if quote is None:
            break
        if max_unit_cost is not None and quote.unit_cost > max_unit_cost:
            break
        got = place_order(world, buyer, quote, product_id, dest,
                          wanted=qty - ordered, extras=extras)
        extras = None  # ride-alongs only on the first trip
        if got == 0:
            break
        ordered += got

    if ordered == 0 and allow_referral and not buyer.is_player:
        # Nobody this person knows sells it: ask around.
        seller = referral_search(world, buyer, product_id)
        if seller is not None:
            world.stats.referrals_succeeded += 1
            add_edge(world, buyer, seller)
            quote = best_quote(world, buyer, product_id, qty, dest,
                               sellers=[seller], feed_run=feed_run,
                               respect_capacity=respect_capacity)
            if quote is not None and (max_unit_cost is None
                                      or quote.unit_cost <= max_unit_cost):
                ordered = place_order(world, buyer, quote, product_id, dest)
    if ordered < qty:
        # Record the shortfall: producers watch unmet demand to decide
        # what to make (a failed kit order is the workshop's cue).
        world.unmet_today[product_id] = (world.unmet_today.get(product_id, 0)
                                         + qty - ordered)
    return ordered
