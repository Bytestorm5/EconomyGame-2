"""A placed machine instance: production logic plus uptime/IO tracking."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Deque, Dict

from ..content import MACHINES
from ..objects import MachineDef
from . import config

if TYPE_CHECKING:
    from .person import Person


@dataclass
class MachineDayRecord:
    """One finished sim day of a machine's activity."""
    uptime: float                      # fraction of ticks spent running
    consumed: Dict[str, int] = field(default_factory=dict)
    produced: Dict[str, int] = field(default_factory=dict)


class Machine:
    def __init__(self, def_id: str, level: int = 1):
        self.def_id = def_id
        self.level = level
        self.progress = 0       # ticks into the current cycle
        self.batches = 0        # batches being processed this cycle (0 = idle)
        # Set daily by the world when output is stockpiled with no demand;
        # a paused machine idles instead of producing into the pile.
        self.paused = False

        self.active_ticks_today = 0
        self.ticks_today = 0
        self.consumed_today: Counter = Counter()
        self.produced_today: Counter = Counter()
        self.history: Deque[MachineDayRecord] = deque(
            maxlen=config.STATS_WINDOW_DAYS)

    @property
    def definition(self) -> MachineDef:
        return MACHINES.get(self.def_id)

    @property
    def max_batches(self) -> int:
        """Throughput multiplier: doubles with every level."""
        return 2 ** (self.level - 1)

    @property
    def upgrade_cost(self) -> int:
        return self.definition.build_cost * config.UPGRADE_COST_FACTOR ** self.level

    @property
    def can_upgrade(self) -> bool:
        return self.level < config.MACHINE_MAX_LEVEL

    def daily_input_need(self) -> Dict[str, int]:
        """Inputs needed to run at full throughput until the next restock."""
        cycles_per_day = max(1, config.TICKS_PER_DAY // self.definition.cycle_ticks)
        buffer = int(cycles_per_day * config.INPUT_BUFFER_DAYS)
        return {
            pid: qty * self.max_batches * buffer
            for pid, qty in self.definition.inputs.items()
        }

    def uptime(self) -> float:
        """Average uptime over the rolling window (today's partial day if no
        full day has finished yet)."""
        if self.history:
            return sum(r.uptime for r in self.history) / len(self.history)
        if self.ticks_today:
            return self.active_ticks_today / self.ticks_today
        return 0.0

    def end_of_day(self) -> None:
        ticks = self.ticks_today or 1
        self.history.append(MachineDayRecord(
            uptime=self.active_ticks_today / ticks,
            consumed=dict(self.consumed_today),
            produced=dict(self.produced_today)))
        self.active_ticks_today = 0
        self.ticks_today = 0
        self.consumed_today.clear()
        self.produced_today.clear()

    def tick(self, owner: "Person") -> None:
        self.ticks_today += 1
        if self.paused and self.batches == 0:
            return
        d = self.definition
        if self.batches == 0:
            # Try to start a cycle: run as many parallel batches as inputs allow.
            possible = self.max_batches
            for pid, qty in d.inputs.items():
                if qty > 0:
                    possible = min(possible, owner.inventory.get(pid, 0) // qty)
            if possible <= 0:
                return  # starved of inputs; stay idle
            for pid, qty in d.inputs.items():
                amount = qty * possible
                owner.remove_items(pid, amount)
                owner.stat(pid).consumed += amount
                self.consumed_today[pid] += amount
            self.batches = possible
            self.progress = 0

        self.active_ticks_today += 1
        self.progress += 1
        if self.progress >= d.cycle_ticks:
            for pid, qty in d.outputs.items():
                amount = qty * self.batches
                owner.add_items(pid, amount)
                owner.stat(pid).produced += amount
                self.produced_today[pid] += amount
            self.batches = 0
            self.progress = 0
