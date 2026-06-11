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
from typing import TYPE_CHECKING, Iterator, List, Optional, Tuple

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


@dataclass
class Shipment:
    """Goods in transit on a buyer's vehicle."""
    buyer: "Person"
    seller: Optional["Person"]   # None for transfers between own parcels
    vehicle: Vehicle
    product_id: str
    qty: int
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


def _feeds(vehicle: Vehicle, product_id: str) -> bool:
    """Is this product feed for the vehicle's fuel demand? (Feed runs are
    exempt from the fuel block, so a hungry horse can still fetch its hay.)"""
    fuel = vehicle.definition.fuel
    return fuel.type in DEMANDS and product_id in DEMANDS.get(fuel.type).fulfilled_by


def iter_offers(world: "World", buyer: "Person", product_id: str,
                sellers: Optional[List["Person"]] = None,
                producers_only: bool = False) -> Iterator[Offer]:
    """All external offers visible to the buyer."""
    if sellers is None:
        ids = world.people.keys() if buyer.is_player else buyer.knowledge
        sellers = [world.people[pid] for pid in ids]
    for seller in sellers:
        if seller is buyer:
            continue
        if producers_only and product_id not in seller.produced_products():
            continue
        price = seller.price_of(product_id)
        for plot in seller.selling_plots(product_id):
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
    dist = offer.plot.distance_to(dest)
    best: Optional[Quote] = None
    for vehicle in buyer.vehicles:
        if not vehicle.idle(world.tick_count):
            continue
        if vehicle.blocked and not (feed_run and _feeds(vehicle, product_id)):
            continue
        q = min(qty, vehicle.max_qty(product_id))
        if q <= 0:
            continue
        cost = math.ceil(vehicle.trip_cost(dist, product_id, q))
        unit = offer.price + cost / q
        if best is None or unit < best.unit_cost:
            best = Quote(offer, vehicle, q, cost, unit)
    return best


def best_quote(world: "World", buyer: "Person", product_id: str, qty: int,
               dest: "Plot", sellers: Optional[List["Person"]] = None,
               producers_only: bool = False, feed_run: bool = False,
               respect_capacity: bool = True) -> Optional[Quote]:
    """Cheapest *delivered* option: external sellers and the buyer's own
    parcels compete on price + trip cost per unit."""
    candidates = list(iter_offers(world, buyer, product_id, sellers,
                                  producers_only))
    candidates.extend(internal_offers(buyer, product_id, dest))
    best: Optional[Quote] = None
    for offer in candidates:
        quote = make_quote(world, buyer, offer, product_id, qty, dest,
                           feed_run, respect_capacity)
        if quote is not None and (best is None
                                  or quote.unit_cost < best.unit_cost):
            best = quote
    return best


def place_order(world: "World", buyer: "Person", quote: Quote,
                product_id: str, dest: "Plot",
                wanted: int = None) -> int:
    """Commit a quote: pay, load, and dispatch the vehicle. Returns units."""
    offer, vehicle = quote.offer, quote.vehicle
    qty = quote.qty
    internal = offer.seller is buyer
    dist = offer.plot.distance_to(dest)
    # Affordability: shrink the load until sale + trip fits the wallet.
    while qty > 0:
        cost = math.ceil(vehicle.trip_cost(dist, product_id, qty))
        if offer.price * qty + cost <= buyer.money:
            break
        qty -= 1
    if qty <= 0:
        return 0

    cost = math.ceil(vehicle.trip_cost(dist, product_id, qty))
    sale = offer.price * qty
    ticks = vehicle.trip_ticks(dist, product_id, qty)

    buyer.money -= sale + cost
    world.treasury += cost  # the carters' wages, recirculated via tithe
    world.stats.shipping_paid += cost
    world.stats.trips += 1
    buyer.stat(product_id).spent += sale + cost
    if not internal:
        offer.seller.money += sale
        offer.seller.stat(product_id).sold += qty
        offer.seller.stat(product_id).revenue += sale
        world.stats.trades += 1
        world.stats.volume += sale

    offer.plot.inventory[product_id] -= qty
    dest.reserve(product_id, qty)
    key = (dest.id, product_id)
    buyer.inbound[key] = buyer.inbound.get(key, 0) + qty

    vehicle.busy_until = world.tick_count + ticks
    vehicle.fuel_due += vehicle.trip_fuel(dist, product_id, qty)
    vehicle.trips += 1
    world.shipments.append(Shipment(
        buyer, None if internal else offer.seller, vehicle,
        product_id, qty, offer.plot, dest,
        world.tick_count, world.tick_count + ticks))

    # Wanted more, stock and storage allowed more, but the vehicle didn't:
    # signal that a bigger vehicle would pay off.
    if wanted is not None and qty < wanted:
        more_possible = min(wanted,
                            offer.plot.inventory.get(product_id, 0) + qty,
                            dest.max_fit(product_id) + qty)
        if more_possible > qty and qty == vehicle.max_qty(product_id):
            buyer.capped_trips += 1
    return qty


def deliver(world: "World", shipment: Shipment) -> None:
    dest, pid, qty = shipment.dest, shipment.product_id, shipment.qty
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
    candidates = [pid for pid in buyer.knowledge if pid not in visited]
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
                 if pid != buyer.id]
        sellers = [p for p in known if p.sells(product_id)]
        if sellers:
            return min(sellers, key=lambda p: p.price_of(product_id))
        # Recurse one hop further with decaying probability.
        if rng.random() > config.REFERRAL_CONTINUE_PROB ** depth:
            return None
        nxt = [pid for pid in current.knowledge if pid not in visited]
        if not nxt:
            return None
        current = world.people[rng.choice(nxt)]
    return None


def add_edge(world: "World", a: "Person", b: "Person") -> None:
    if b.id not in a.knowledge:
        a.knowledge.add(b.id)
        b.knowledge.add(a.id)
        world.stats.edges_formed += 1


def buy(world: "World", buyer: "Person", product_id: str, qty: int = 1,
        dest: Optional["Plot"] = None, allow_referral: bool = True,
        producers_only: bool = False, feed_run: bool = False,
        respect_capacity: bool = True,
        max_unit_cost: Optional[float] = None) -> int:
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
                           respect_capacity=respect_capacity)
        if quote is None:
            break
        if max_unit_cost is not None and quote.unit_cost > max_unit_cost:
            break
        got = place_order(world, buyer, quote, product_id, dest,
                          wanted=qty - ordered)
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
            if quote is not None:
                ordered = place_order(world, buyer, quote, product_id, dest)
    return ordered
