"""The world: people, parcels, the land market, logistics, and the tick loop."""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

from ..content import DEMANDS, MACHINES, PRODUCTS, VEHICLES
from . import ads, config, demand, trade
from .machine import Machine
from .person import Person
from .plot import Plot
from .money import cents
from .trade import Shipment, TradeStats
from .vehicle import Vehicle


class World:
    def __init__(self, width: int, height: int, seed: int = 0):
        self.width = width    # map size in tiles
        self.height = height
        self.rng = random.Random(seed)
        self.people: Dict[int, Person] = {}
        self.plots: Dict[int, Plot] = {}
        self.roads: List[Tuple[int, int, int, int]] = []  # tile rects
        self.shipments: List[Shipment] = []
        self.tick_count = 0
        self.stats = TradeStats()
        self.player_id: Optional[int] = None
        # Coin spent on building/upgrading/trips/unowned land lands here
        # ("paid to village labor") and is redistributed with the daily
        # tithe, so the total money supply is exactly conserved...
        self.treasury = 0
        # ...except for migration: settlers bring minted coin, emigrants'
        # coin leaves with them. Tracked so audits still balance.
        self.minted = 0
        self.evaporated = 0
        self.immigrants = 0
        self.emigrants = 0

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
            cost = cents(d.build_cost)
            if person.money < cost:
                return None
            person.money -= cost
            self.treasury += cost
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
        refund = int(cents(machine.definition.build_cost)
                     * config.DEMOLISH_REFUND)
        person.money += refund
        self.treasury -= refund  # may dip negative; repaid by future builds
        return True

    def buy_vehicle(self, person: Person, def_id: str,
                    plot: Optional[Plot] = None) -> Optional[Vehicle]:
        plot = plot or person.home
        d = VEHICLES.get(def_id)
        cost = cents(d.buy_cost)
        if person.money < cost or plot.owner_id != person.id:
            return None
        person.money -= cost
        self.treasury += cost
        vehicle = Vehicle(def_id, plot=plot)
        person.vehicles.append(vehicle)
        return vehicle

    # --- simulation ---------------------------------------------------------
    def tick(self) -> None:
        self._process_arrivals()

        order = list(self.people.values())
        self.rng.shuffle(order)

        for person in order:
            for machine in person.machines:
                machine.tick(person)

        for person in order:
            demand.tick(self, person)

        self._tick_forgetting(order)

        self.tick_count += 1
        if self.tick_count % config.TICKS_PER_DAY == 0:
            self._daily_update(order)

    def _tick_forgetting(self, order: List[Person]) -> None:
        """Knowledge decays: each tick (= 1 hour) every edge to a *seller*
        has a small chance of being forgotten -- unless the person bought
        from that seller this very tick. Ad fatigue rides the same event:
        each fire decrements the counter until it clears."""
        sellers = {p.id for p in order if p.sellable_products()}
        for person in order:
            for sid in list(person.knowledge):
                if sid not in sellers:
                    continue  # purely social edges don't fade
                if person.last_bought.get(sid) == self.tick_count:
                    continue  # bought from them this turn
                if self.rng.random() < config.FORGET_PROB:
                    if len(person.knowledge) > config.MIN_KNOWLEDGE:
                        trade.remove_edge(self, person, self.people[sid])
            for sid in list(person.ad_fatigue):
                if self.rng.random() < config.FORGET_PROB:
                    person.ad_fatigue[sid] -= 1
                    if person.ad_fatigue[sid] <= 0:
                        del person.ad_fatigue[sid]

    def _process_arrivals(self) -> None:
        arrived = [s for s in self.shipments if s.arrive <= self.tick_count]
        if not arrived:
            return
        self.shipments = [s for s in self.shipments
                          if s.arrive > self.tick_count]
        for shipment in arrived:
            trade.deliver(self, shipment)
            # If feed just arrived, hungry vehicles eat right away.
            owner = shipment.buyer
            if any(v.fuel_due >= 1 for v in owner.vehicles):
                self._feed_vehicles(owner)

    def _daily_update(self, order: List[Person]) -> None:
        for person in order:
            demand.daily(self, person)
            demand.maintain_stockpile(self, person)
            self._feed_vehicles(person)
            self._update_production_pauses(person)
            self._restock(person)
            person.adjust_prices_daily(self)
            ads.npc_consider(self, person)
            self._consider_investment(person)
        for person in order:
            person.end_of_day()
        self._collect_tithe(order)
        self._population_update()

    # --- population dynamics --------------------------------------------------
    def _population_update(self) -> None:
        """Feeding people grows the village; failing them shrinks it."""
        for person in list(self.people.values()):
            if (not person.is_player
                    and person.hungry_days >= config.EMIGRATE_HUNGRY_DAYS
                    and len(self.people) > config.MIN_POPULATION):
                self._emigrate(person)
        if self.rng.random() < config.IMMIGRATION_PROB and self._prosperous():
            self._immigrate()

    def _prosperous(self) -> bool:
        """Plenty on the shelves and room to settle."""
        if not any(self.plot_sale_price(p) is not None and not p.machines()
                   for p in self.plots.values()):
            return False
        food_points = 0.0
        for d in DEMANDS:
            per_day = demand.daily_points(d)
            if per_day <= 0:
                continue
            stocked = sum(plot.inventory.get(pid, 0) * pts
                          for plot in self.plots.values()
                          for pid, pts in d.fulfilled_by.items())
            if (stocked / max(1, len(self.people)) / per_day
                    < config.IMMIGRATION_FOOD_DAYS):
                return False
        return True

    def _immigrate(self) -> None:
        from .vehicle import Vehicle
        from .worldgen import npc_name
        pid = max(self.people) + 1
        grubstake = config.NPC_START_MONEY + config.PARCEL_PRICE
        settler = self.add_person(Person(pid, npc_name(pid - 1), grubstake))
        self.minted += grubstake
        self.immigrants += 1
        # Settle the cheapest available parcel (paying the village or the
        # listing owner); meet the neighbours.
        options = [p for p in self.plots.values()
                   if self.plot_sale_price(p) is not None and not p.machines()]
        plot = min(options, key=lambda p: self.plot_sale_price(p))
        self.buy_plot(settler, plot)
        for vid in config.STARTING_VEHICLES:
            settler.vehicles.append(Vehicle(vid, plot=settler.home))
        others = sorted((p for p in self.people.values() if p is not settler),
                        key=lambda p: p.home.distance_to(settler.home))
        for neighbour in others[:2]:
            trade.add_edge(self, settler, neighbour)
        if others[2:]:
            trade.add_edge(self, settler, self.rng.choice(others[2:]))

    def _emigrate(self, person: Person) -> None:
        """Pack up and leave: machines are abandoned, parcels revert to
        common land, their coin leaves the economy."""
        self.evaporated += person.money
        self.emigrants += 1
        for plot in person.plots:
            for machine in plot.machines():
                plot.slots[plot.slots.index(machine)] = None
            plot.inventory.clear()
            plot.owner_id = None
            plot.for_sale_price = None
        del self.people[person.id]
        for other in self.people.values():
            other.knowledge.discard(person.id)
            other.ad_fatigue.pop(person.id, None)
            other.last_bought.pop(person.id, None)

    # --- persistence ------------------------------------------------------------
    def save(self, path: str) -> None:
        import pickle
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: str) -> "World":
        import pickle
        with open(path, "rb") as f:
            world = pickle.load(f)
        assert isinstance(world, World)
        return world

    # --- logistics upkeep -------------------------------------------------------
    def _feed_vehicles(self, person: Person) -> None:
        """Pay vehicles' fuel debt from stock (the horse eats from any owned
        parcel), then put feed on the shopping list if a vehicle is blocked.
        Feed runs are exempt from the fuel block so this can't deadlock."""
        for vehicle in person.vehicles:
            fuel = vehicle.definition.fuel
            if fuel.type not in DEMANDS or vehicle.fuel_due < 1:
                continue
            d = DEMANDS.get(fuel.type)
            # Cheapest feed (per point, at base prices) first. Only spend a
            # unit when the debt covers its full value -- small debts carry
            # over rather than wasting a loaf on a snack.
            for pid in sorted(d.fulfilled_by,
                              key=lambda p: PRODUCTS.get(p).base_price
                              / d.fulfilled_by[p]):
                points = d.fulfilled_by[pid]
                for plot in person.plots:
                    while (vehicle.fuel_due >= points
                           and plot.inventory.get(pid, 0) > 0):
                        plot.inventory[pid] -= 1
                        vehicle.fuel_due -= points
            if vehicle.blocked:
                # Buy feed: cheapest fulfiller, enough to clear the debt
                # plus a buffer. The order itself may use this vehicle
                # (feed-run exemption).
                pid = min(d.fulfilled_by,
                          key=lambda p: PRODUCTS.get(p).base_price
                          / d.fulfilled_by[p])
                qty = math.ceil((vehicle.fuel_due + config.FEED_BUFFER_POINTS)
                                / d.fulfilled_by[pid])
                qty -= person.inbound_total(pid)
                if qty > 0:
                    trade.buy(self, person, pid, qty=qty, dest=person.home,
                              feed_run=True, respect_capacity=False)

    def _restock(self, person: Person) -> None:
        """Daily shopping: machine inputs to each machine's parcel, and
        resale goods to each store/warehouse parcel. The buy logic compares
        external sellers against the owner's other parcels (free goods,
        paid trip) by delivered cost; orders arrive by vehicle later."""
        need: Dict[Tuple[int, str], int] = {}
        for machine in person.machines:
            if machine.paused:
                continue
            for pid, qty in machine.daily_input_need().items():
                key = (machine.plot.id, pid)
                need[key] = need.get(key, 0) + qty
        for (plot_id, pid), qty in need.items():
            dest = self.plots[plot_id]
            shortfall = (qty - dest.inventory.get(pid, 0)
                         - person.inbound_to(dest, pid))
            if shortfall > 0:
                trade.buy(self, person, pid, qty=shortfall, dest=dest)

        # Reseller restock: keep demand-fulfilling products in stock, bought
        # in bulk from producers (stores don't restock from other stores).
        for plot in person.plots:
            if not plot.resells():
                continue
            for pid in self._assortment():
                target = self._stock_target(person, pid)
                shortfall = (target - plot.inventory.get(pid, 0)
                             - person.inbound_to(plot, pid))
                if shortfall > 0:
                    trade.buy(self, person, pid, qty=shortfall, dest=plot,
                              producers_only=True)

    @staticmethod
    def _assortment() -> List[str]:
        """What resellers carry: everything that fulfills a demand."""
        out: List[str] = []
        for d in DEMANDS:
            out.extend(pid for pid in d.fulfilled_by if pid not in out)
        return out

    def _stock_target(self, person: Person, pid: str) -> int:
        hist = person.stats_history.get(pid)
        avg_sales = (sum(day.sold for day in hist) / len(hist)
                     if hist else 0.0)
        return max(config.STOCK_TARGET_MIN,
                   int(avg_sales * config.STOCK_TARGET_DAYS))

    def _update_production_pauses(self, person: Person) -> None:
        """Make-to-stock throttle: an NPC machine pauses while every one of
        its outputs already has several days of (observed) sales in stock."""
        for machine in person.machines:
            if person.is_player or not machine.definition.outputs:
                machine.paused = False  # player-managed, or a reseller
                continue
            outputs = machine.definition.outputs
            # Pause when every output is at target, or any output is grossly
            # overstocked (a by-product in demand mustn't justify producing
            # mountains of the main product nobody buys).
            machine.paused = (
                all(person.stock(pid) >= self._stock_target(person, pid)
                    for pid in outputs)
                or any(person.stock(pid)
                       >= config.STOCK_HARD_CAP_FACTOR
                       * self._stock_target(person, pid)
                       for pid in outputs)
            )

    # --- NPC investment -----------------------------------------------------------
    def _consider_investment(self, person: Person) -> None:
        """Low-frequency NPC growth heuristic: each person, every
        INVEST_PERIOD_DAYS (staggered by id), makes at most one move.

        1. Upgrade a machine that runs and whose output keeps selling out.
        2. Buy a bigger vehicle when trips keep hitting cargo capacity.
        3. Build the best-margin machine with a visible supply gap (or a
           general store if the neighbourhood has no reseller and the
           retail spread looks profitable), buying a parcel if out of room.
        4. List an idle extra parcel they've been too broke to develop.
        """
        if person.is_player or not person.plots:
            return
        if (self.day + person.id) % config.INVEST_PERIOD_DAYS != 0:
            return

        # 1) Upgrade where demand keeps outstripping supply.
        candidates = [
            m for m in person.machines
            if m.can_upgrade and m.definition.outputs
            and person.money >= m.upgrade_cost * config.INVEST_RESERVE_FACTOR
            and m.uptime() >= config.INVEST_MIN_UPTIME
            and max((person.sellout_days(pid) for pid in m.definition.outputs),
                    default=0) >= config.INVEST_SELLOUT_DAYS
        ]
        if candidates:
            machine = min(candidates, key=lambda m: m.upgrade_cost)
            self.upgrade_machine(person, machine)
            return

        # 2) A bigger cart, if capacity keeps biting and there's money.
        upgrade = VEHICLES.get(config.NPC_VEHICLE_UPGRADE)
        if (person.capped_trips >= config.CAPPED_TRIPS_FOR_UPGRADE
                and len(person.vehicles) < config.NPC_MAX_VEHICLES
                and person.money >= cents(upgrade.buy_cost)
                * config.INVEST_RESERVE_FACTOR):
            self.buy_vehicle(person, upgrade.id)
            person.capped_trips = 0
            return
        person.capped_trips = 0  # stale signal; re-earn it each period

        # 3) Build the best-margin opportunity.
        best_def, best_margin = None, 0.0
        for mdef in MACHINES:
            if (person.money
                    < cents(mdef.build_cost) * config.INVEST_RESERVE_FACTOR):
                continue
            if mdef.resells:
                margin = (self._store_margin_estimate(person)
                          if mdef.id == "general_store" else 0.0)
            elif self._supply_gap(person, mdef):
                margin = self._machine_margin_estimate(person, mdef)
            else:
                margin = 0.0
            if margin > best_margin:
                best_def, best_margin = mdef, margin

        if best_def is not None:
            build_site = next((p for p in person.plots
                               if p.free_slot() is not None), None)
            if build_site is not None:
                self.build_machine(person, build_site, best_def.id)
            else:
                self._buy_expansion_plot(person, cents(best_def.build_cost))
            return

        # 4) Divest parcels they can't afford to develop.
        cheapest_build = min(cents(m.build_cost) for m in MACHINES)
        for plot in person.plots[1:]:
            if (not plot.machines() and plot.for_sale_price is None
                    and self.day - plot.acquired_day >= config.PARCEL_IDLE_DAYS
                    and person.money <
                    cheapest_build * config.INVEST_RESERVE_FACTOR):
                self.list_plot(person, plot)
                return

    def _supply_gap(self, person: Person, mdef) -> bool:
        """The machine's primary output (first listed; by-products don't
        justify a build) has no in-stock seller among the people they know,
        themselves included."""
        pid = next(iter(mdef.outputs))
        circle = [self.people[k] for k in person.knowledge] + [person]
        return not any(p.sells(pid) for p in circle)

    def _known_price(self, person: Person, pid: str) -> int:
        offers = list(trade.iter_offers(self, person, pid))
        if offers:
            return min(o.price for o in offers)
        return cents(PRODUCTS.get(pid).base_price)

    def _machine_margin_estimate(self, person: Person, mdef) -> float:
        per_cycle = (sum(self._known_price(person, p) * q
                         for p, q in mdef.outputs.items())
                     - sum(self._known_price(person, p) * q
                           for p, q in mdef.inputs.items()))
        cycles = max(1, config.TICKS_PER_DAY // mdef.cycle_ticks)
        return float(per_cycle * cycles)

    def _store_margin_estimate(self, person: Person) -> float:
        """Estimated daily coin from running a store at home: the spread
        between what neighbours pay for a single-unit fetch and what bulk
        acquisition costs per unit -- but only in an unserved neighbourhood."""
        for plot in self.plots.values():
            if (plot.resells()
                    and plot.distance_to(person.home)
                    <= config.STORE_GAP_RADIUS):
                return 0.0
        total = 0.0
        for pid in self._assortment():
            single = trade.best_quote(self, person, pid, 1, person.home)
            if single is None:
                continue
            bulk_q = max(1, min(10, single.vehicle.max_qty(pid)))
            bulk = trade.best_quote(self, person, pid, bulk_q, person.home,
                                    producers_only=True)
            if bulk is None:
                continue
            spread = single.unit_cost - bulk.unit_cost
            if spread > 0:
                total += spread * config.STORE_EXPECTED_DAILY_SALES
        return total

    def _buy_expansion_plot(self, person: Person, build_cost_cents: int) -> bool:
        """Buy the nearest purchasable parcel, keeping enough coin to still
        afford the machine that motivated the expansion."""
        available = [p for p in self.plots.values()
                     if self.plot_sale_price(p) is not None
                     and p.owner_id != person.id]
        available = [p for p in available
                     if person.money
                     >= self.plot_sale_price(p) + build_cost_cents]
        if not available:
            return False
        plot = min(available, key=lambda p: p.distance_to(person.home))
        return self.buy_plot(person, plot)

    def _collect_tithe(self, order: List[Person]) -> None:
        """Pool a % of everyone's coin plus the treasury and share it back
        equally (conserves total money; remainder to the poorest)."""
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
