#!/usr/bin/env python3
"""Run the simulation without the UI and print economy health stats.

Usage: python run_headless.py [--days N] [--seed N] [--blocks WxH] [--npcs N]
                              [--csv out.csv]

--csv writes a per-day time series (population, money, prices, stocks,
unfulfilled demand, knowledge edges, trade volume) for balance tuning.
"""

from __future__ import annotations

import argparse
from collections import Counter

from village.content import DEMANDS, PRODUCTS, load_all
from village.sim.worldgen import generate


def report(world) -> None:
    print(f"\n=== Day {world.day} (tick {world.tick_count}) ===")
    print(f"trades: {world.stats.trades}  volume: ${world.stats.volume}  "
          f"shipping: ${world.stats.shipping_paid}  "
          f"referrals: {world.stats.referrals_succeeded}/"
          f"{world.stats.referrals_attempted} ok  "
          f"new edges: {world.stats.edges_formed}")

    monies = sorted(p.money for p in world.people.values())
    print(f"money: min ${monies[0]}  median ${monies[len(monies) // 2]}  "
          f"max ${monies[-1]}  total ${sum(monies) + world.treasury}")

    for d in DEMANDS:
        unmet = sum(p.unfulfilled.get(d.id, 0) for p in world.people.values())
        print(f"unfulfilled {d.name} (person-ticks at need with no option): "
              f"{unmet}")

    for prod in PRODUCTS:
        prices = [p.price_of(prod.id) for p in world.people.values()
                  if prod.id in p.produced_products()]
        stock = sum(pl.inventory.get(prod.id, 0)
                    for pl in world.plots.values())
        if prices:
            print(f"  {prod.name:<6} price {min(prices)}-{max(prices)}  "
                  f"stock {stock}")

    edges = sum(len(p.knowledge) for p in world.people.values()) // 2
    print(f"knowledge edges: {edges}")
    biz = Counter(m.def_id for p in world.people.values() for m in p.machines)
    paused = sum(m.paused for p in world.people.values() for m in p.machines)
    print(f"machines: {dict(biz)}  ({paused} paused)")
    unowned = sum(1 for p in world.plots.values() if p.owner_id is None)
    listed = sum(1 for p in world.plots.values()
                 if p.for_sale_price is not None)
    multi = sum(1 for p in world.people.values() if len(p.plots) > 1)
    print(f"land: {unowned} unowned, {listed} listed, "
          f"{multi} multi-parcel owners")
    print(f"population: {len(world.people)}  (+{world.immigrants} settled, "
          f"-{world.emigrants} left)  ads: {world.stats.ads_run} run, "
          f"{world.stats.ad_impressions} impressions")


def snapshot(world) -> dict:
    monies = sorted(p.money for p in world.people.values())
    row = {
        "day": world.day - 1,
        "population": len(world.people),
        "total_money": sum(monies) + world.treasury,
        "median_money": monies[len(monies) // 2],
        "player_money": world.player.money,
        "edges": sum(len(p.knowledge) for p in world.people.values()) // 2,
        "trades": world.stats.trades,
        "trips": world.stats.trips,
        "ads_run": world.stats.ads_run,
        "unfulfilled": sum(sum(p.unfulfilled.values())
                           for p in world.people.values()),
        "machines": sum(len(p.machines) for p in world.people.values()),
    }
    for prod in PRODUCTS:
        prices = [p.price_of(prod.id) for p in world.people.values()
                  if prod.id in p.sellable_products()]
        row[f"price_{prod.id}"] = (sum(prices) / len(prices)) if prices else ""
        row[f"stock_{prod.id}"] = sum(pl.inventory.get(prod.id, 0)
                                      for pl in world.plots.values())
    return row


def write_csv(path: str, rows: list) -> None:
    import csv
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--blocks", type=str, default=None,
                        help="village size in blocks, e.g. 4x3")
    parser.add_argument("--npcs", type=int, default=None)
    parser.add_argument("--csv", type=str, default=None)
    args = parser.parse_args()
    blocks = None
    if args.blocks:
        w, _, h = args.blocks.lower().partition("x")
        blocks = (int(w), int(h))

    load_all()
    world = generate(seed=args.seed, blocks=blocks, npcs=args.npcs)
    print(f"Generated village: {len(world.people)} people, "
          f"{len(world.plots)} parcels ({world.width}x{world.height} tiles), "
          f"seed {args.seed}")
    biz = Counter(m.def_id for p in world.people.values() for m in p.machines)
    print(f"businesses: {dict(biz)}")

    rows = []
    for _ in range(args.days):
        world.run_days(1)
        if args.csv:
            rows.append(snapshot(world))
        if world.day % 10 == 1:
            report(world)
    report(world)
    if args.csv:
        write_csv(args.csv, rows)
        print(f"wrote {len(rows)} rows to {args.csv}")


if __name__ == "__main__":
    main()
