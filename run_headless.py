#!/usr/bin/env python3
"""Run the simulation without the UI and print economy health stats.

Usage: python run_headless.py [days] [seed]
"""

from __future__ import annotations

import sys
from collections import Counter

from village.content import load_all
from village.content.products import PRODUCTS
from village.sim import config
from village.sim.worldgen import generate


def report(world) -> None:
    print(f"\n=== Day {world.day} (tick {world.tick_count}) ===")
    print(f"trades: {world.stats.trades}  volume: ${world.stats.volume}  "
          f"referrals: {world.stats.referrals_succeeded}/"
          f"{world.stats.referrals_attempted} ok  "
          f"new edges: {world.stats.edges_formed}")

    monies = sorted(p.money for p in world.people.values())
    print(f"money: min ${monies[0]}  median ${monies[len(monies) // 2]}  "
          f"max ${monies[-1]}  total ${sum(monies)}")

    missed = sum(p.missed_meals for p in world.people.values())
    print(f"missed meals (person-ticks hungry with no food): {missed}")

    for prod in PRODUCTS:
        prices = [p.price_of(prod.id) for p in world.people.values()
                  if prod.id in p.produced_products()]
        stock = sum(p.inventory.get(prod.id, 0) for p in world.people.values())
        if prices:
            print(f"  {prod.name:<6} price {min(prices)}-{max(prices)}  "
                  f"stock {stock}")

    edges = sum(len(p.knowledge) for p in world.people.values()) // 2
    print(f"knowledge edges: {edges}")


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    load_all()
    world = generate(seed=seed)
    print(f"Generated village: {len(world.people)} people, "
          f"{len(world.plots)} plots, seed {seed}")
    biz = Counter(m.def_id for p in world.people.values() for m in p.machines)
    print(f"businesses: {dict(biz)}")

    for chunk in range(days // 10 or 1):
        world.run_days(min(10, days - chunk * 10))
        report(world)


if __name__ == "__main__":
    main()
