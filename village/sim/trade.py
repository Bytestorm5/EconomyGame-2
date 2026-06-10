"""Trading through the knowledge graph.

A buyer first checks the people they know for the cheapest seller. If nobody
they know sells the product, they ask a random acquaintance to look; that
person runs the same check among *their* acquaintances, recursing onward with
a probability that decays with distance from the original buyer. A successful
referral creates a new knowledge edge between buyer and seller.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

from . import config

if TYPE_CHECKING:
    from .person import Person
    from .world import World


@dataclass
class TradeStats:
    trades: int = 0
    volume: int = 0          # total coins exchanged
    referrals_attempted: int = 0
    referrals_succeeded: int = 0
    edges_formed: int = 0


def find_known_seller(world: "World", buyer: "Person",
                      product_id: str) -> Optional["Person"]:
    """Cheapest seller of product_id among the people buyer knows.

    The player's unfair advantage: their auto-buy knows everybody, so they
    always see the whole market while NPCs only see their acquaintances.
    """
    candidates = world.people.keys() if buyer.is_player else buyer.knowledge
    best: Optional["Person"] = None
    for pid in candidates:
        p = world.people[pid]
        if p is buyer or not p.sells(product_id):
            continue
        if best is None or p.price_of(product_id) < best.price_of(product_id):
            best = p
    return best


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
        seller = find_known_seller(world, current, product_id)
        if seller is not None and seller.id != buyer.id:
            return seller
        # Recurse one hop further with decaying probability.
        if rng.random() > config.REFERRAL_CONTINUE_PROB ** depth:
            return None
        nxt = [pid for pid in current.knowledge if pid not in visited]
        if not nxt:
            return None
        current = world.people[rng.choice(nxt)]
    return None


def buy(world: "World", buyer: "Person", product_id: str, qty: int = 1) -> int:
    """Try to buy up to qty units. Returns the number of units bought."""
    seller = find_known_seller(world, buyer, product_id)
    if seller is None:
        if buyer.is_player:
            return 0  # the player already sees everyone; nobody sells it
        seller = referral_search(world, buyer, product_id)
        if seller is None:
            return 0
        world.stats.referrals_succeeded += 1
        if seller.id not in buyer.knowledge:
            buyer.knowledge.add(seller.id)
            seller.knowledge.add(buyer.id)
            world.stats.edges_formed += 1

    bought = 0
    price = seller.price_of(product_id)
    while (bought < qty and seller.sells(product_id)
           and buyer.money >= price):
        buyer.money -= price
        seller.money += price
        seller.remove_items(product_id, 1)
        buyer.add_items(product_id, 1)
        seller.stat(product_id).sold += 1
        seller.stat(product_id).revenue += price
        buyer.stat(product_id).spent += price
        world.stats.trades += 1
        world.stats.volume += price
        bought += 1
    return bought
