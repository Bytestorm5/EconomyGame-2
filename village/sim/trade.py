"""Trading through the knowledge graph, with per-parcel stock and shipping.

A buyer first checks the people they know (the player's auto-buy checks
everyone -- their unfair advantage) and picks the offer with the lowest
*delivered* cost: sale price plus shipping per tile of manhattan distance
between the seller's parcel and the destination parcel. Moving goods
between two parcels of the same owner has no sale price, but shipping is
still paid. Shipping coin goes to the village treasury ("the carters") so
total money is conserved.

If nobody known sells the product, the buyer asks a random acquaintance to
look; the search recurses outward with a probability that decays with
distance from the original buyer. A successful referral forms a permanent
new knowledge edge.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, List, Optional

from . import config

if TYPE_CHECKING:
    from .person import Person
    from .plot import Plot
    from .world import World


@dataclass
class TradeStats:
    trades: int = 0
    volume: int = 0          # total coins exchanged in sales
    shipping_paid: int = 0   # total coins spent on shipping
    referrals_attempted: int = 0
    referrals_succeeded: int = 0
    edges_formed: int = 0


@dataclass
class Offer:
    """One parcel's stock of a product, priced for a specific destination."""
    seller: "Person"
    plot: "Plot"
    price: int               # sale price per unit (0 for own parcels)
    ship_per_unit: float     # shipping per unit to the destination

    @property
    def unit_cost(self) -> float:
        return self.price + self.ship_per_unit

    def ceil_unit_cost(self) -> int:
        """Worst-case whole-coin cost of a single unit."""
        return self.price + math.ceil(self.ship_per_unit)


def ship_cost(plot_a: "Plot", plot_b: "Plot", qty: int) -> int:
    if plot_a is plot_b:
        return 0
    dist = plot_a.distance_to(plot_b)
    return math.ceil(qty * dist * config.SHIPPING_PER_TILE)


def _ship_per_unit(plot_a: "Plot", plot_b: "Plot") -> float:
    if plot_a is plot_b:
        return 0.0
    return plot_a.distance_to(plot_b) * config.SHIPPING_PER_TILE


def iter_offers(world: "World", buyer: "Person", product_id: str,
                dest: "Plot",
                sellers: Optional[List["Person"]] = None) -> Iterator[Offer]:
    """All external offers visible to the buyer, priced for delivery."""
    if sellers is None:
        ids = world.people.keys() if buyer.is_player else buyer.knowledge
        sellers = [world.people[pid] for pid in ids]
    for seller in sellers:
        if seller is buyer or not seller.sells(product_id):
            continue
        price = seller.price_of(product_id)
        for plot in seller.plots:
            if plot.inventory.get(product_id, 0) > 0:
                yield Offer(seller, plot, price, _ship_per_unit(plot, dest))


def best_offer(world: "World", buyer: "Person", product_id: str,
               dest: "Plot",
               sellers: Optional[List["Person"]] = None) -> Optional[Offer]:
    """The cheapest *delivered* offer: a $3 product one tile away beats a
    $2 product thirty tiles away."""
    offers = list(iter_offers(world, buyer, product_id, dest, sellers))
    return min(offers, key=lambda o: o.unit_cost) if offers else None


def best_internal_source(buyer: "Person", product_id: str,
                         dest: "Plot") -> Optional[Offer]:
    """Cheapest of the buyer's own other parcels holding the product
    (price 0, shipping still applies)."""
    best: Optional[Offer] = None
    for plot in buyer.plots:
        if plot is dest or plot.inventory.get(product_id, 0) <= 0:
            continue
        offer = Offer(buyer, plot, 0, _ship_per_unit(plot, dest))
        if best is None or offer.unit_cost < best.unit_cost:
            best = offer
    return best


def execute(world: "World", buyer: "Person", offer: Offer, product_id: str,
            qty: int, dest: "Plot") -> int:
    """Move up to qty units along an offer. Returns units transferred."""
    units = min(qty, offer.plot.inventory.get(product_id, 0))
    internal = offer.seller is buyer
    while units > 0:
        total = offer.price * units + ship_cost(offer.plot, dest, units)
        if total <= buyer.money:
            break
        units -= 1
    if units <= 0:
        return 0

    shipping = ship_cost(offer.plot, dest, units)
    sale = offer.price * units
    buyer.money -= sale + shipping
    world.treasury += shipping  # the carters' wages, recirculated via tithe
    world.stats.shipping_paid += shipping
    offer.plot.inventory[product_id] -= units
    dest.inventory[product_id] += units
    buyer.stat(product_id).spent += sale + shipping
    if not internal:
        offer.seller.money += sale
        offer.seller.stat(product_id).sold += units
        offer.seller.stat(product_id).revenue += sale
        world.stats.trades += 1
        world.stats.volume += sale
    return units


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
        dest: Optional["Plot"] = None, allow_referral: bool = True) -> int:
    """Acquire up to qty units delivered to dest (default: buyer's home),
    always taking the cheapest delivered source first -- the buyer's own
    parcels (free goods, paid shipping) compete with external sellers.
    Returns units acquired."""
    dest = dest or buyer.home
    bought = 0
    while bought < qty:
        sources = []
        internal = best_internal_source(buyer, product_id, dest)
        if internal is not None:
            sources.append(internal)
        external = best_offer(world, buyer, product_id, dest)
        if external is not None:
            sources.append(external)
        if not sources:
            break
        offer = min(sources, key=lambda o: o.unit_cost)
        got = execute(world, buyer, offer, product_id, qty - bought, dest)
        if got == 0:
            break
        bought += got

    if bought == 0 and allow_referral and not buyer.is_player:
        # Nobody this person knows sells it: ask around.
        seller = referral_search(world, buyer, product_id)
        if seller is not None:
            world.stats.referrals_succeeded += 1
            add_edge(world, buyer, seller)
            offer = best_offer(world, buyer, product_id, dest, [seller])
            if offer is not None:
                bought = execute(world, buyer, offer, product_id, qty, dest)
    return bought
