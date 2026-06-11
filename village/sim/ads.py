"""Advertising: sellers buy knowledge edges; audiences push back.

Each campaign run picks ``reach`` random people (optionally distance-biased
by ``falloff``) and makes them hear about the seller. Every impression adds
ad fatigue; past the threshold the listener *intentionally forgets* the
seller and stays deaf to their ads until the fatigue decays through the
normal forget flow (see world tick).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, List, Optional

from ..content import ADVERTS
from ..objects import AdvertisingDef
from . import config, trade

if TYPE_CHECKING:
    from .person import Person
    from .plot import Plot
    from .world import World


def ready(world: "World", person: "Person", addef: AdvertisingDef) -> bool:
    return world.day >= person.ad_cooldowns.get(addef.id, 0)


def run_ad(world: "World", person: "Person", addef: AdvertisingDef,
           center: "Plot") -> Optional[int]:
    """Run a campaign for ``person`` centered on one of their parcels.
    Returns the number of people who actually learned (or refreshed) an
    edge, or None if it couldn't run (coin/cooldown)."""
    if person.money < addef.cost or not ready(world, person, addef):
        return None
    person.money -= addef.cost
    world.treasury += addef.cost  # criers and printers get paid too
    person.ad_cooldowns[addef.id] = world.day + addef.cooldown_days
    world.stats.ads_run += 1

    targets = _pick_targets(world, person, addef, center)
    learned = 0
    for target in targets:
        if impress(world, target, person):
            learned += 1
    return learned


def _pick_targets(world: "World", person: "Person", addef: AdvertisingDef,
                  center: "Plot") -> List["Person"]:
    """reach distinct people; existing acquaintances are NOT excluded --
    hearing about someone you already know is how fatigue builds."""
    rng = world.rng
    others = [p for p in world.people.values() if p.id != person.id]
    if not others:
        return []
    if addef.falloff is None:
        rng.shuffle(others)
        return others[:addef.reach]
    weights = [math.exp(-p.home.distance_to(center) / addef.falloff)
               for p in others]
    picked: List["Person"] = []
    pool = list(zip(others, weights))
    for _ in range(min(addef.reach, len(pool))):
        total = sum(w for _, w in pool)
        if total <= 0:
            break
        r = rng.random() * total
        acc = 0.0
        for i, (p, w) in enumerate(pool):
            acc += w
            if r <= acc:
                picked.append(p)
                pool.pop(i)
                break
    return picked


def impress(world: "World", target: "Person", seller: "Person") -> bool:
    """One person hears one ad. Returns True if it produced/kept an edge,
    False if it bounced off (or backfired into an intentional forget)."""
    world.stats.ad_impressions += 1
    fatigue = target.ad_fatigue.get(seller.id, 0) + 1
    target.ad_fatigue[seller.id] = fatigue
    if fatigue > config.AD_FATIGUE_THRESHOLD:
        # Sick of hearing it: intentionally forget, ads bounce until the
        # fatigue counter decays back to zero.
        trade.remove_edge(world, target, seller)
        return False
    trade.add_edge(world, target, seller)
    return True


def npc_consider(world: "World", person: "Person") -> None:
    """Daily NPC decision: advertise when sellable stock sat unsold
    yesterday. Resellers prefer the most local campaign they can afford
    (their customers walk); producers prefer the widest."""
    if person.is_player:
        return
    if (world.day + person.id) % config.NPC_AD_PERIOD_DAYS != 0:
        return
    if world.day < person.ad_discouraged_until:
        return
    # Did the last campaign actually move product? If not, give up a while.
    if person.ad_watch is not None:
        ran_day, watched = person.ad_watch
        elapsed = world.day - ran_day
        if elapsed >= config.NPC_AD_PERIOD_DAYS:
            hist = list(person.stats_history.get(watched, ()))
            recent = sum(d.sold for d in hist[-elapsed:])
            person.ad_watch = None
            if recent == 0:
                person.ad_discouraged_until = (world.day
                                               + config.AD_DISCOURAGED_DAYS)
                return

    glut_pid = None
    for pid in person.sellable_products():
        day = person.yesterday(pid)
        if (day is not None and day.sold == 0
                and person.stock(pid) >= config.STOCK_TARGET_MIN):
            glut_pid = pid
            break
    if glut_pid is None:
        return

    affordable = [a for a in ADVERTS
                  if person.money >= a.cost * config.AD_BUDGET_FACTOR
                  and ready(world, person, a)]
    if not affordable:
        return
    store_plot = next((p for p in person.plots if p.resells()), None)
    if store_plot is not None:
        # most local first (None falloff sorts last)
        addef = min(affordable,
                    key=lambda a: a.falloff if a.falloff is not None
                    else float("inf"))
        run_ad(world, person, addef, store_plot)
    else:
        addef = max(affordable, key=lambda a: a.reach)
        run_ad(world, person, addef, person.home)
    person.ad_watch = (world.day, glut_pid)
