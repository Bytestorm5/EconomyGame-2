"""The world: people, plots, and the tick loop."""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from ..content.machines import MACHINES
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
        machine = Machine(def_id)
        plot.slots[slot] = machine
        person.machines.append(machine)
        return machine

    def upgrade_machine(self, person: Person, machine: Machine) -> bool:
        cost = machine.upgrade_cost
        if not machine.can_upgrade or person.money < cost:
            return False
        person.money -= cost
        machine.level += 1
        return True

    def demolish_machine(self, person: Person, plot: Plot, slot: int) -> bool:
        machine = plot.slots[slot]
        if machine is None:
            return False
        plot.slots[slot] = None
        person.machines.remove(machine)
        person.money += int(machine.definition.build_cost * config.DEMOLISH_REFUND)
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
        from ..content.products import PRODUCTS
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
            # Restock machine inputs up to the buffer (player included, so
            # machines "run automatically" for everyone).
            need: Dict[str, int] = {}
            for machine in person.machines:
                for pid, qty in machine.daily_input_need().items():
                    need[pid] = need.get(pid, 0) + qty
            for pid, qty in need.items():
                shortfall = qty - person.inventory.get(pid, 0)
                if shortfall > 0:
                    trade.buy(self, person, pid, qty=shortfall)
            person.adjust_prices_daily()
        self._collect_tithe(order)

    def _collect_tithe(self, order: List[Person]) -> None:
        """Pool a % of everyone's coin and share it back equally (conserves
        total money; the remainder goes to the poorest)."""
        pool = 0
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
