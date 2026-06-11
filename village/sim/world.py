"""The world: people, parcels, the land market, logistics, and the tick loop."""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Dict, List, Optional, Tuple

from ..content import DEMANDS, MACHINES, PRODUCTS, RECIPES, VEHICLES
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
        # Demand the market failed to serve (product -> units), used by
        # producers to pick recipes and investments. Swapped daily.
        self.unmet_today: Dict[str, int] = {}
        self.unmet_yesterday: Dict[str, int] = {}
        # Market data: per product, today's traded units/value and a daily
        # history of (avg price paid, units) -- what the player's market
        # screen charts. Player history tracks (net worth, daily profit).
        self.market_today: Dict[str, Tuple[int, int]] = {}
        self.market_history: Dict[str, deque] = {}
        self.player_history: deque = deque(maxlen=config.MARKET_HISTORY_DAYS)
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
        """Erect a machine by consuming its kit (the product with the same
        id) from this parcel's inventory. ``free`` is for worldgen only."""
        d = MACHINES.get(def_id)
        slot = plot.free_slot()
        if slot is None or plot.owner_id != person.id:
            return None
        if not free:
            if plot.inventory.get(def_id, 0) < 1:
                return None
            plot.inventory[def_id] -= 1
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
        """Put a vehicle into service at a parcel. Craftable vehicles (ones
        with a matching product) are commissioned by consuming the kit from
        the parcel; the porter is simple hired labor, paid in coin."""
        plot = plot or person.home
        if plot.owner_id != person.id:
            return None
        d = VEHICLES.get(def_id)
        if def_id in PRODUCTS:
            if plot.inventory.get(def_id, 0) < 1:
                return None
            plot.inventory[def_id] -= 1
        else:
            cost = cents(d.buy_cost)
            if person.money < cost:
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
            # Allocate today's free workforce: machines mid-cycle keep
            # their crews first, then idle machines staff up in slot order.
            free = len(trade.free_crew(self, person))
            running = [m for m in person.machines if m.batches > 0]
            waiting = [m for m in person.machines if m.batches == 0]
            staffed = set()
            for machine in running + waiting:
                need = machine.definition.workers
                if need <= free:
                    free -= need
                    staffed.add(id(machine))
            for machine in person.machines:
                machine.tick(person, staffed=id(machine) in staffed
                             or machine.definition.workers == 0)

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
        self.unmet_yesterday = self.unmet_today
        self.unmet_today = {}
        self._record_market_day()
        for person in order:
            demand.daily(self, person)
            self._pay_wages(person)
            demand.maintain_stockpile(self, person)
            self._feed_vehicles(person)
            self._choose_recipes(person)
            self._update_production_pauses(person)
            self._restock(person)
            self._execute_pending(person)
            person.adjust_prices_daily(self)
            ads.npc_consider(self, person)
            self._consider_staffing(person)
            self._consider_investment(person)
        for person in order:
            person.end_of_day()
        self._collect_tithe(order)
        self._population_update()

    def _record_market_day(self) -> None:
        for pid in PRODUCTS.ids():
            units, value = self.market_today.get(pid, (0, 0))
            hist = self.market_history.setdefault(
                pid, deque(maxlen=config.MARKET_HISTORY_DAYS))
            hist.append((value / units if units else None, units))
        self.market_today = {}
        player = self.player
        self.player_history.append(
            (player.net_worth(), player.yesterday_profit()))

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
        for sid in person.staff:
            worker = self.people.get(sid)
            if worker is not None:
                worker.employer_id = None
        if person.employer_id is not None:
            boss = self.people.get(person.employer_id)
            if boss is not None and person.id in boss.staff:
                boss.staff.remove(person.id)
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
            have = dest.inventory.get(pid, 0) + person.inbound_to(dest, pid)
            # Reorder only when the buffer is genuinely low; each trip costs
            # someone's working hours.
            if have < qty * config.RESTOCK_TRIGGER:
                trade.buy(self, person, pid, qty=qty - have, dest=dest)

        # Reseller restock: keep demand-fulfilling products in stock, bought
        # in bulk from producers (stores don't restock from other stores).
        for plot in person.plots:
            if not plot.resells():
                continue
            for pid in self._assortment():
                target = self._stock_target(person, pid)
                have = (plot.inventory.get(pid, 0)
                        + person.inbound_to(plot, pid))
                if have < target * config.RESTOCK_TRIGGER:
                    trade.buy(self, person, pid, qty=target - have, dest=plot,
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
        floor = (config.STOCK_TARGET_MIN_HEAVY
                 if PRODUCTS.get(pid).weight >= 5
                 else config.STOCK_TARGET_MIN)
        return max(floor, int(avg_sales * config.STOCK_TARGET_DAYS))

    def _pay_wages(self, person: Person) -> None:
        """Payday, every day. An employer who can't pay loses the worker."""
        for sid in list(person.staff):
            worker = self.people.get(sid)
            if worker is None:
                person.staff.remove(sid)
                continue
            if person.money >= config.WAGE_PER_DAY:
                person.money -= config.WAGE_PER_DAY
                worker.money += config.WAGE_PER_DAY
            else:
                person.staff.remove(sid)
                worker.employer_id = None

    def _consider_staffing(self, person: Person) -> None:
        """NPCs hire when machines sat unmanned yesterday and they can
        afford a couple of weeks of wages; they let people go when the
        coffers run dry. The player hires/fires manually."""
        if person.is_player:
            return
        if person.money < config.WAGE_PER_DAY * 2 and person.staff:
            sid = person.staff.pop()
            worker = self.people.get(sid)
            if worker is not None:
                worker.employer_id = None
            return
        starved = sum(m.no_staff_yesterday() for m in person.machines)
        runs_production = any(m.recipe() is not None for m in person.machines)
        # A production owner without staff is owner+driver+operator in one
        # body; the first hire is almost always worth it.
        first_hire = runs_production and not person.staff
        if ((starved >= config.HIRE_NO_STAFF_TICKS or first_hire)
                and person.money >= config.WAGE_PER_DAY * 14):
            self.hire(person)

    def hire(self, employer: Person) -> Optional[Person]:
        """Take on the nearest unemployed citizen (no business, no job)."""
        candidates = [p for p in self.people.values()
                      if not p.is_player and p is not employer
                      and p.employer_id is None and not p.machines]
        if not candidates:
            return None
        worker = min(candidates,
                     key=lambda p: p.home.distance_to(employer.home))
        worker.employer_id = employer.id
        employer.staff.append(worker.id)
        return worker

    def fire(self, employer: Person, worker_id: int) -> bool:
        if worker_id not in employer.staff:
            return False
        employer.staff.remove(worker_id)
        worker = self.people.get(worker_id)
        if worker is not None:
            worker.employer_id = None
        return True

    def _choose_recipes(self, person: Person) -> None:
        """NPCs point multi-recipe machines at the most promising recipe:
        prefer ones whose primary output has a visible supply gap, then by
        estimated margin per day; stick with steady sellers otherwise."""
        if person.is_player:
            return
        for machine in person.machines:
            options = machine.definition.recipes
            if len(options) < 2:
                continue
            if machine.stalled:
                # Stuck against a full parcel: scrap the batch so the
                # machine can do something useful instead.
                machine.abort_batch()
            if machine.batches > 0:
                continue
            # Anti-herding: a machine whose current output is selling and
            # not glutted stays the course, only occasionally glancing at
            # alternatives -- otherwise every farm chases the same hot
            # signal at once and the staple supply collapses.
            cur = machine.active_recipe
            if cur is not None:
                cur_primary = next(iter(RECIPES.get(cur).outputs))
                cur_sold = (person.yesterday(cur_primary).sold
                            if person.yesterday(cur_primary) else 0)
                cur_healthy = (cur_sold > 0
                               and person.stock(cur_primary)
                               < self._stock_target(person, cur_primary))
                if cur_healthy and self.rng.random() > 0.15:
                    continue
            best_rid, best_score = None, 0.0
            for rid in options:
                rdef = RECIPES.get(rid)
                margin = self._recipe_margin(person, machine, rid)
                if margin <= 0:
                    continue
                primary = next(iter(rdef.outputs))
                unmet = self.unmet_yesterday.get(primary, 0)
                sold = (person.yesterday(primary).sold
                        if person.yesterday(primary) else 0)
                # Make what the market demonstrably wants: stuff that's
                # selling, or stuff people tried and failed to buy. A bare
                # "nobody sells it" gap is not demand (nobody wants it
                # either) -- that's what bankrupted the horse barons. And
                # never pile more onto an already-saturated stock.
                if unmet <= 0 and sold <= 0:
                    continue
                if (unmet <= 0 and person.stock(primary)
                        >= self._stock_target(person, primary)):
                    continue
                score = margin * (2.0 if unmet > 0 else 1.0)
                if score > best_score:
                    best_rid, best_score = rid, score
            if best_rid is not None and best_rid != machine.active_recipe:
                machine.set_recipe(best_rid)
            elif best_rid is None and cur is not None and not cur_healthy:
                # Nothing in demand and the current line is dead: fall back
                # to the definition's staple (its first recipe).
                staple = options[0]
                if staple != cur:
                    machine.set_recipe(staple)

    def _execute_pending(self, person: Person) -> None:
        """Finish closed-loop intents once the kit has arrived: erect the
        planned machine, commission the planned vehicle."""
        if person.pending_build is not None:
            if self.day - person.pending_build_day > config.PENDING_KIT_DAYS:
                person.pending_build = None
            else:
                built = False
                for plot in person.plots:
                    if (plot.inventory.get(person.pending_build, 0) > 0
                            and plot.free_slot() is not None):
                        self.build_machine(person, plot, person.pending_build)
                        person.pending_build = None
                        built = True
                        break
                if (not built and person.pending_build is not None
                        and person.inbound_total(person.pending_build) == 0):
                    # Keep the order alive; each failed attempt records
                    # unmet demand for the kit, which cues the workshops.
                    site = next((p for p in person.plots
                                 if p.free_slot() is not None), None)
                    if site is not None:
                        trade.buy(self, person, person.pending_build,
                                  qty=1, dest=site)
        if person.pending_vehicle is not None:
            for plot in person.plots:
                if plot.inventory.get(person.pending_vehicle, 0) > 0:
                    self.buy_vehicle(person, person.pending_vehicle, plot)
                    person.pending_vehicle = None
                    break

    def _product_gap(self, person: Person, pid: str) -> bool:
        """No in-stock seller of pid among the people they know (self
        included) -- as far as they can tell, demand is going unmet."""
        circle = [self.people[k] for k in person.knowledge
                  if k in self.people] + [person]
        return not any(p.sells(pid) for p in circle)

    def _recipe_margin(self, person: Person, machine, rid: str) -> float:
        """Estimated coin/day from running rid on this machine, at the
        prices this person knows about."""
        rdef = RECIPES.get(rid)
        per_cycle = (sum(self._known_price(person, p) * q
                         for p, q in rdef.outputs.items())
                     - sum(self._known_price(person, p) * q
                           for p, q in rdef.inputs.items()))
        cycles = max(1, config.TICKS_PER_DAY
                     // machine.cycle_ticks_for(rid))
        return float(per_cycle * cycles)

    def _update_production_pauses(self, person: Person) -> None:
        """Make-to-stock throttle: an NPC machine pauses while every one of
        its outputs already has several days of (observed) sales in stock."""
        for machine in person.machines:
            if person.is_player or machine.recipe() is None:
                machine.paused = False  # player-managed, or a reseller
                continue
            outputs = machine.outputs()
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
            if m.can_upgrade and m.outputs()
            and person.money >= m.upgrade_cost * config.INVEST_RESERVE_FACTOR
            and m.uptime() >= config.INVEST_MIN_UPTIME
            and max((person.sellout_days(pid) for pid in m.outputs()),
                    default=0) >= config.INVEST_SELLOUT_DAYS
        ]
        if candidates:
            machine = min(candidates, key=lambda m: m.upgrade_cost)
            self.upgrade_machine(person, machine)
            return

        # 2) A bigger cart, if capacity keeps biting and there's money:
        #    order the cart kit from the market (a workshop has to have
        #    built one) and commission it when it arrives.
        upgrade = VEHICLES.get(config.NPC_VEHICLE_UPGRADE)
        if (person.capped_trips >= config.CAPPED_TRIPS_FOR_UPGRADE
                and len(person.vehicles) < config.NPC_MAX_VEHICLES
                and person.pending_vehicle is None
                and person.money >= cents(upgrade.buy_cost)
                * config.INVEST_RESERVE_FACTOR):
            if trade.buy(self, person, upgrade.id, qty=1,
                         dest=person.home) > 0:
                person.pending_vehicle = upgrade.id
            person.capped_trips = 0
            return
        person.capped_trips = 0  # stale signal; re-earn it each period

        # 3) Build the best-margin opportunity: every (machine, recipe)
        #    combo competes; resellers use the retail spread estimate. The
        #    machine itself is a product -- order the kit, then erect it
        #    when it arrives (_execute_pending).
        if person.pending_build is not None:
            return  # a kit is already on order
        best_def, best_margin = None, 0.0
        for mdef in MACHINES:
            kit_cost = self._known_price(person, mdef.id)
            if person.money < kit_cost * config.INVEST_RESERVE_FACTOR:
                continue
            if mdef.resells:
                margin = (self._store_margin_estimate(person)
                          if mdef.id == "general_store" else 0.0)
            else:
                margin = 0.0
                probe = Machine(mdef.id)
                for rid in mdef.recipes:
                    primary = next(iter(RECIPES.get(rid).outputs))
                    wanted = (self.unmet_yesterday.get(primary, 0) > 0
                              or self._product_gap(person, primary)
                              and primary in self._assortment())
                    if not wanted:
                        continue
                    margin = max(margin,
                                 self._recipe_margin(person, probe, rid))
            if margin > best_margin:
                best_def, best_margin = mdef, margin

        if best_def is not None:
            site = next((p for p in person.plots
                         if p.free_slot() is not None), None)
            if site is None:
                self._buy_expansion_plot(
                    person, self._known_price(person, best_def.id))
                return
            trade.buy(self, person, best_def.id, qty=1, dest=site)
            person.pending_build = best_def.id
            person.pending_build_day = self.day
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

    def _known_price(self, person: Person, pid: str) -> int:
        offers = list(trade.iter_offers(self, person, pid))
        if offers:
            return min(o.price for o in offers)
        return cents(PRODUCTS.get(pid).base_price)

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
