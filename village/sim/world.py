"""The world: people, plots, and the tick loop."""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from ..content import MACHINES
from . import config, trade
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
        self.tick_count = 0
        self.stats = TradeStats()
        self.player_id: Optional[int] = None
        # Coin spent on building/upgrading lands here ("paid to village
        # labor") and is redistributed with the daily tithe, so the total
        # money supply is exactly conserved.
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
        person.plot_id = plot.id

    # --- player/NPC build actions -------------------------------------------
    def build_machine(self, person: Person, plot: Plot, def_id: str,
                      free: bool = False) -> Optional[Machine]:
        d = MACHINES.get(def_id)
        slot = plot.free_slot()
        if slot is None:
            return None
        if not free:
            if person.money < d.build_cost:
                return None
            person.money -= d.build_cost
            self.treasury += d.build_cost
        machine = Machine(def_id)
        plot.slots[slot] = machine
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
            self._tick_needs(person)

        self.tick_count += 1
        if self.tick_count % config.TICKS_PER_DAY == 0:
            self._daily_update(order)

    def _tick_needs(self, person: Person) -> None:
        person.hunger = min(config.HUNGER_MAX,
                            person.hunger + config.HUNGER_PER_TICK)
        if person.hunger < config.EAT_THRESHOLD:
            return
        if person.eat_from_inventory():
            return
        # No food on hand: buy the best-value food a known seller offers
        # (price per point of food value), affordably.
        from ..content import PRODUCTS
        best_pid, best_value = None, None
        for pid in config.FOOD_PREFERENCE:
            seller = trade.find_known_seller(self, person, pid)
            if seller is None or seller.price_of(pid) > person.money:
                continue
            value = seller.price_of(pid) / PRODUCTS.get(pid).food_value
            if best_value is None or value < best_value:
                best_pid, best_value = pid, value
        if best_pid is None:
            # Nobody known sells affordable food: ask around (referral),
            # best food first.
            for pid in config.FOOD_PREFERENCE:
                if trade.buy(self, person, pid, qty=1):
                    person.eat_from_inventory()
                    return
            person.missed_meals += 1
            return
        if trade.buy(self, person, best_pid, qty=1):
            person.eat_from_inventory()
        else:
            person.missed_meals += 1

    def _daily_update(self, order: List[Person]) -> None:
        for person in order:
            self._update_production_pauses(person)
            # Restock machine inputs up to the buffer (player included, so
            # machines "run automatically" for everyone). Paused machines
            # don't restock -- no point buying inputs nobody's output needs.
            need: Dict[str, int] = {}
            for machine in person.machines:
                if machine.paused:
                    continue
                for pid, qty in machine.daily_input_need().items():
                    need[pid] = need.get(pid, 0) + qty
            for pid, qty in need.items():
                shortfall = qty - person.inventory.get(pid, 0)
                if shortfall > 0:
                    trade.buy(self, person, pid, qty=shortfall)
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
                machine.paused = False  # the player manages their own plot
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
                all(person.inventory.get(pid, 0) >= target(pid)
                    for pid in outputs)
                or any(person.inventory.get(pid, 0)
                       >= config.STOCK_HARD_CAP_FACTOR * target(pid)
                       for pid in outputs)
            )

    def _consider_investment(self, person: Person) -> None:
        """Low-frequency NPC growth heuristic: each person, every
        INVEST_PERIOD_DAYS (staggered by id), makes at most one move.

        1. Upgrade: a machine that actually runs (uptime) and whose output
           kept selling out this week -- demand is outstripping supply.
        2. Build: otherwise, the machine def with the best estimated daily
           margin, priced from what this person *knows* (their market view
           is limited to their acquaintances, unlike the player's).
        """
        if person.is_player or person.plot_id is None:
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

        # 2) Build the best-margin machine they can afford, if there's room
        #    AND the market this person can see actually looks under-supplied.
        plot = self.plots[person.plot_id]
        if plot.free_slot() is None:
            return

        def known_price(pid: str) -> int:
            seller = trade.find_known_seller(self, person, pid)
            from ..content import PRODUCTS
            return (seller.price_of(pid) if seller is not None
                    else PRODUCTS.get(pid).base_price)

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
            self.build_machine(person, plot, best_def.id)

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
