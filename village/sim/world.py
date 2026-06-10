"""The world: people, parcels, the land market, and the tick loop."""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from ..content import MACHINES, PRODUCTS
from . import config, demand, trade
from .machine import Machine
from .person import Person
from .plot import Plot
from .trade import TradeStats


class World:
    def __init__(self, width: int, height: int, seed: int = 0):
        self.width = width    # map size in tiles
        self.height = height
        self.rng = random.Random(seed)
        self.people: Dict[int, Person] = {}
        self.plots: Dict[int, Plot] = {}
        self.roads: List[Tuple[int, int, int, int]] = []  # tile rects
        self.tick_count = 0
        self.stats = TradeStats()
        self.player_id: Optional[int] = None
        # Coin spent on building/upgrading/shipping/unowned land lands here
        # ("paid to village labor") and is redistributed with the daily
        # tithe, so the total money supply is exactly conserved.
        self.treasury = 0

    # --- convenience -------------------------------------------------------
    @property
    def day(self) -> int:
        return self.tick_count // config.TICKS_PER_DAY + 1

    @property
    def player(self) -> Person:
        assert self.player_id is not None
        return self.people[self.player_id]

    def add_person(self, person: Person) -> Person:
        self.people[person.id] = person
        return person

    def add_plot(self, plot: Plot) -> Plot:
        self.plots[plot.id] = plot
        return plot

    def assign_plot(self, person: Person, plot: Plot) -> None:
        plot.owner_id = person.id
        plot.for_sale_price = None
        plot.acquired_day = self.day
        person.plots.append(plot)

    # --- the land market -----------------------------------------------------
    def plot_sale_price(self, plot: Plot) -> Optional[int]:
        """What buying this parcel costs right now, if it's available."""
        if plot.owner_id is None:
            return config.PARCEL_PRICE
        return plot.for_sale_price

    def buy_plot(self, person: Person, plot: Plot) -> bool:
        price = self.plot_sale_price(plot)
        if price is None or plot.owner_id == person.id:
            return False
        if person.money < price or plot.machines():
            return False
        person.money -= price
        if plot.owner_id is None:
            self.treasury += price  # village common land
        else:
            seller = self.people[plot.owner_id]
            seller.money += price
            seller.plots.remove(plot)
        self.assign_plot(person, plot)
        return True

    def list_plot(self, person: Person, plot: Plot) -> bool:
        """Offer an owned parcel for sale. Home (first) parcels and parcels
        with machines on them can't be listed."""
        if plot not in person.plots or plot is person.home or plot.machines():
            return False
        plot.for_sale_price = config.PARCEL_PRICE
        return True

    def unlist_plot(self, person: Person, plot: Plot) -> bool:
        if plot not in person.plots or plot.for_sale_price is None:
            return False
        plot.for_sale_price = None
        return True

    # --- player/NPC build actions -------------------------------------------
    def build_machine(self, person: Person, plot: Plot, def_id: str,
                      free: bool = False) -> Optional[Machine]:
        d = MACHINES.get(def_id)
        slot = plot.free_slot()
        if slot is None or plot.owner_id != person.id:
            return None
        if not free:
            if person.money < d.build_cost:
                return None
            person.money -= d.build_cost
            self.treasury += d.build_cost
        machine = Machine(def_id, plot=plot)
        plot.slots[slot] = machine
        plot.for_sale_price = None  # developed parcels come off the market
        person.machines.append(machine)
        return machine

    def upgrade_machine(self, person: Person, machine: Machine) -> bool:
        cost = machine.upgrade_cost
        if not machine.can_upgrade or person.money < cost:
            return False
        person.money -= cost
        self.treasury += cost
        machine.level += 1
        return True

    def demolish_machine(self, person: Person, plot: Plot, slot: int) -> bool:
        machine = plot.slots[slot]
        if machine is None:
            return False
        plot.slots[slot] = None
        person.machines.remove(machine)
        refund = int(machine.definition.build_cost * config.DEMOLISH_REFUND)
        person.money += refund
        self.treasury -= refund  # may dip negative; repaid by future builds
        return True

    # --- simulation ---------------------------------------------------------
    def tick(self) -> None:
        order = list(self.people.values())
        self.rng.shuffle(order)

        for person in order:
            for machine in person.machines:
                machine.tick(person)

        for person in order:
            demand.tick(self, person)

        self.tick_count += 1
        if self.tick_count % config.TICKS_PER_DAY == 0:
            self._daily_update(order)

    def _daily_update(self, order: List[Person]) -> None:
        for person in order:
            demand.daily(self, person)
            self._update_production_pauses(person)
            # Restock machine inputs up to the buffer, delivered to each
            # machine's own parcel (player included, so machines "run
            # automatically" for everyone). The buy logic compares external
            # sellers against the owner's other parcels (free goods, paid
            # shipping) by delivered cost. Paused machines don't restock.
            need: Dict[Tuple[int, str], int] = {}
            for machine in person.machines:
                if machine.paused:
                    continue
                for pid, qty in machine.daily_input_need().items():
                    key = (machine.plot.id, pid)
                    need[key] = need.get(key, 0) + qty
            for (plot_id, pid), qty in need.items():
                dest = self.plots[plot_id]
                shortfall = qty - dest.inventory.get(pid, 0)
                if shortfall > 0:
                    trade.buy(self, person, pid, qty=shortfall, dest=dest)
            person.adjust_prices_daily()
            self._consider_investment(person)
        for person in order:
            person.end_of_day()
        self._collect_tithe(order)

    def _update_production_pauses(self, person: Person) -> None:
        """Make-to-stock throttle: an NPC machine pauses while every one of
        its outputs already has several days of (observed) sales in stock."""
        for machine in person.machines:
            if person.is_player:
                machine.paused = False  # the player manages their own plots
                continue
            def target(pid: str) -> int:
                hist = person.stats_history.get(pid)
                avg_sales = (sum(d.sold for d in hist) / len(hist)
                             if hist else 0.0)
                return max(config.STOCK_TARGET_MIN,
                           int(avg_sales * config.STOCK_TARGET_DAYS))
            outputs = machine.definition.outputs
            # Pause when every output is at target, or any output is grossly
            # overstocked (a by-product in demand mustn't justify producing
            # mountains of the main product nobody buys).
            machine.paused = (
                all(person.stock(pid) >= target(pid) for pid in outputs)
                or any(person.stock(pid)
                       >= config.STOCK_HARD_CAP_FACTOR * target(pid)
                       for pid in outputs)
            )

    def _consider_investment(self, person: Person) -> None:
        """Low-frequency NPC growth heuristic: each person, every
        INVEST_PERIOD_DAYS (staggered by id), makes at most one move.

        1. Upgrade: a machine that actually runs (uptime) and whose output
           kept selling out this week -- demand is outstripping supply.
        2. Build: the machine def with the best estimated daily margin,
           priced from what this person *knows* -- but only if its primary
           output has a visible supply gap. If they're out of room, buy the
           nearest available parcel instead and build next time.
        3. Divest: list an empty extra parcel they've been too broke to
           develop for a while.
        """
        if person.is_player or not person.plots:
            return
        if (self.day + person.id) % config.INVEST_PERIOD_DAYS != 0:
            return

        # 1) Upgrade where demand keeps outstripping supply.
        candidates = [
            m for m in person.machines
            if m.can_upgrade
            and person.money >= m.upgrade_cost * config.INVEST_RESERVE_FACTOR
            and m.uptime() >= config.INVEST_MIN_UPTIME
            and max((person.sellout_days(pid) for pid in m.definition.outputs),
                    default=0) >= config.INVEST_SELLOUT_DAYS
        ]
        if candidates:
            machine = min(candidates, key=lambda m: m.upgrade_cost)
            self.upgrade_machine(person, machine)
            return

        # 2) Build the best-margin machine with a visible supply gap.
        def known_price(pid: str) -> int:
            offer = trade.best_offer(self, person, pid, person.home)
            return offer.price if offer is not None else PRODUCTS.get(pid).base_price

        def supply_gap(mdef) -> bool:
            # The machine's primary output (first listed; by-products don't
            # justify a build) has no in-stock seller among the people they
            # know, themselves included -- as far as this person can tell,
            # demand for it is going unmet.
            pid = next(iter(mdef.outputs))
            circle = [self.people[k] for k in person.knowledge] + [person]
            return not any(p.sells(pid) for p in circle)

        best_def, best_margin = None, 0
        for mdef in MACHINES:
            if person.money < mdef.build_cost * config.INVEST_RESERVE_FACTOR:
                continue
            if not supply_gap(mdef):
                continue
            per_cycle = (sum(known_price(p) * q for p, q in mdef.outputs.items())
                         - sum(known_price(p) * q for p, q in mdef.inputs.items()))
            cycles = max(1, config.TICKS_PER_DAY // mdef.cycle_ticks)
            margin = per_cycle * cycles
            if margin > best_margin:
                best_def, best_margin = mdef, margin

        if best_def is not None:
            build_site = next((p for p in person.plots
                               if p.free_slot() is not None), None)
            if build_site is not None:
                self.build_machine(person, build_site, best_def.id)
            else:
                self._buy_expansion_plot(person, best_def.build_cost)
            return

        # 3) Divest parcels they can't afford to develop.
        cheapest_build = min(m.build_cost for m in MACHINES)
        for plot in person.plots[1:]:
            if (not plot.machines() and plot.for_sale_price is None
                    and self.day - plot.acquired_day >= config.PARCEL_IDLE_DAYS
                    and person.money <
                    cheapest_build * config.INVEST_RESERVE_FACTOR):
                self.list_plot(person, plot)
                return

    def _buy_expansion_plot(self, person: Person, build_cost: int) -> bool:
        """Buy the nearest purchasable parcel, keeping enough coin to still
        afford the machine that motivated the expansion."""
        available = [p for p in self.plots.values()
                     if self.plot_sale_price(p) is not None
                     and p.owner_id != person.id]
        available = [p for p in available
                     if person.money >= self.plot_sale_price(p) + build_cost]
        if not available:
            return False
        plot = min(available, key=lambda p: p.distance_to(person.home))
        return self.buy_plot(person, plot)

    def _collect_tithe(self, order: List[Person]) -> None:
        """Pool a % of everyone's coin plus the building treasury and share
        it back equally (conserves total money; remainder to the poorest)."""
        pool = max(0, self.treasury)
        self.treasury = min(0, self.treasury)
        for person in order:
            tax = int(person.money * config.TITHE_RATE)
            person.money -= tax
            pool += tax
        share, remainder = divmod(pool, len(order))
        for person in order:
            person.money += share
        min(order, key=lambda p: p.money).money += remainder

    def run_days(self, days: int) -> None:
        for _ in range(days * config.TICKS_PER_DAY):
            self.tick()
