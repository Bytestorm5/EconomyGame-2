"""A placed machine instance: runs a chosen recipe, needs operators."""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Deque, Dict, Optional

from ..content import MACHINES, PRODUCTS, RECIPES
from ..objects import MachineDef, RecipeDef
from . import config
from .money import cents

if TYPE_CHECKING:
    from .person import Person


@dataclass
class MachineDayRecord:
    """One finished sim day of a machine's activity."""
    uptime: float                      # fraction of ticks spent running
    consumed: Dict[str, int] = field(default_factory=dict)
    produced: Dict[str, int] = field(default_factory=dict)
    no_staff_ticks: int = 0            # ticks idled for lack of operators


class Machine:
    # Updated by the world every tick: seasonal recipes multiply their rate
    # by this (class attribute so save files don't carry stale copies).
    season_factor = 1.0

    def __init__(self, def_id: str, level: int = 1, plot=None):
        self.def_id = def_id
        self.level = level
        self.plot = plot        # the parcel this machine sits on (set on build)
        # Which of the definition's recipes is currently selected.
        d = MACHINES.get(def_id)
        self.active_recipe: Optional[str] = d.recipes[0] if d.recipes else None
        self.progress = 0       # ticks into the current cycle
        self.batches = 0        # batches being processed this cycle (0 = idle)
        # Set daily by the world when output is stockpiled with no demand;
        # a paused machine idles instead of producing into the pile.
        self.paused = False
        # True when a finished cycle can't unload because the parcel's
        # storage is full; retries every tick until space frees up.
        self.stalled = False

        self.active_ticks_today = 0
        self.ticks_today = 0
        self.no_staff_today = 0
        self.crew_today: set = set()   # person ids who operated it today
        self.consumed_today: Counter = Counter()
        self.produced_today: Counter = Counter()
        self.history: Deque[MachineDayRecord] = deque(
            maxlen=config.STATS_WINDOW_DAYS)

    @property
    def definition(self) -> MachineDef:
        return MACHINES.get(self.def_id)

    def recipe(self) -> Optional[RecipeDef]:
        if self.active_recipe is None:
            return None
        return RECIPES.get(self.active_recipe)

    def cycle_ticks_for(self, recipe_id: str) -> int:
        """Manufacture time depends on the recipe AND this machine."""
        d = self.definition
        r = RECIPES.get(recipe_id)
        rate = d.rate * d.recipe_rates.get(recipe_id, 1.0)
        if r.seasonal:
            rate *= Machine.season_factor
        return max(1, math.ceil(r.base_ticks / rate))

    @property
    def cycle_ticks(self) -> int:
        return (self.cycle_ticks_for(self.active_recipe)
                if self.active_recipe else 1)

    def outputs(self) -> Dict[str, int]:
        r = self.recipe()
        return r.outputs if r is not None else {}

    def inputs(self) -> Dict[str, int]:
        r = self.recipe()
        return r.inputs if r is not None else {}

    def abort_batch(self) -> None:
        """Scrap the batch in progress (materials lost). The escape hatch
        for a machine stalled against a full parcel."""
        self.batches = 0
        self.progress = 0
        self.stalled = False

    def set_recipe(self, recipe_id: Optional[str]) -> bool:
        """Switch recipes (only between cycles; mid-batch work isn't lost)."""
        if recipe_id is not None and recipe_id not in self.definition.recipes:
            return False
        if self.batches > 0:
            return False
        self.active_recipe = recipe_id
        self.progress = 0
        return True

    @property
    def max_batches(self) -> int:
        """Throughput multiplier: doubles with every level."""
        return 2 ** (self.level - 1)

    @property
    def upgrade_cost(self) -> int:
        return (cents(self.definition.build_cost)
                * config.UPGRADE_COST_FACTOR ** self.level)

    @property
    def can_upgrade(self) -> bool:
        return self.level < config.MACHINE_MAX_LEVEL

    def daily_input_need(self) -> Dict[str, int]:
        """Inputs needed to run at full throughput until the next restock."""
        if self.active_recipe is None:
            return {}
        cycles_per_day = max(1, config.TICKS_PER_DAY // self.cycle_ticks)
        buffer = int(cycles_per_day * config.INPUT_BUFFER_DAYS)
        return {
            pid: qty * self.max_batches * max(1, buffer)
            for pid, qty in self.inputs().items()
        }

    def uptime(self) -> float:
        """Average uptime over the rolling window (today's partial day if no
        full day has finished yet)."""
        if self.history:
            return sum(r.uptime for r in self.history) / len(self.history)
        if self.ticks_today:
            return self.active_ticks_today / self.ticks_today
        return 0.0

    def no_staff_yesterday(self) -> int:
        return self.history[-1].no_staff_ticks if self.history else 0

    def end_of_day(self) -> None:
        ticks = self.ticks_today or 1
        self.history.append(MachineDayRecord(
            uptime=self.active_ticks_today / ticks,
            consumed=dict(self.consumed_today),
            produced=dict(self.produced_today),
            no_staff_ticks=self.no_staff_today))
        self.active_ticks_today = 0
        self.ticks_today = 0
        self.no_staff_today = 0
        self.consumed_today.clear()
        self.produced_today.clear()

    def tick(self, owner: "Person", staffed: bool = True,
             quality: float = 1.0) -> None:
        """Run one tick, consuming/producing in this machine's own parcel
        inventory. ``staffed`` is decided by the owner's workforce pool --
        an unmanned machine simply waits."""
        self.ticks_today += 1
        r = self.recipe()
        if r is None:
            return  # reseller buildings etc. have nothing to run
        if not staffed:
            if not self.paused:
                self.no_staff_today += 1
            return
        if self.paused and self.batches == 0:
            return
        store = self.plot.inventory
        if self.batches == 0:
            # Try to start a cycle: run as many parallel batches as inputs allow.
            possible = self.max_batches
            for pid, qty in r.inputs.items():
                if qty > 0:
                    possible = min(possible, store.get(pid, 0) // qty)
            if possible <= 0:
                return  # starved of inputs; stay idle
            for pid, qty in r.inputs.items():
                amount = qty * possible
                store[pid] -= amount
                owner.stat(pid).consumed += amount
                self.consumed_today[pid] += amount
            self.batches = possible
            self.progress = 0

        if not self.stalled:
            self.active_ticks_today += 1
            self.progress += quality  # veterans run hot machines faster
        if self.progress >= self.cycle_ticks:
            # Unload only if the whole batch fits in the parcel's storage;
            # otherwise stall (auto-pause on full) and retry next tick.
            out_w = sum(PRODUCTS.get(pid).weight * qty * self.batches
                        for pid, qty in r.outputs.items())
            out_s = sum(PRODUCTS.get(pid).space * qty * self.batches
                        for pid, qty in r.outputs.items())
            fw, fs = self.plot.free_capacity()
            if out_w > fw + 1e-9 or out_s > fs + 1e-9:
                self.stalled = True
                return
            self.stalled = False
            for pid, qty in r.outputs.items():
                amount = qty * self.batches
                store[pid] += amount
                owner.stat(pid).produced += amount
                self.produced_today[pid] += amount
            self.batches = 0
            self.progress = 0
