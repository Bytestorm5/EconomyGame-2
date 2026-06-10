"""A placed machine instance and its production logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict

from ..content.machines import MACHINES, MachineDef
from . import config

if TYPE_CHECKING:
    from .person import Person


class Machine:
    def __init__(self, def_id: str, level: int = 1):
        self.def_id = def_id
        self.level = level
        self.progress = 0       # ticks into the current cycle
        self.batches = 0        # batches being processed this cycle (0 = idle)

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

    def tick(self, owner: "Person") -> None:
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
                owner.remove_items(pid, qty * possible)
            self.batches = possible
            self.progress = 0

        self.progress += 1
        if self.progress >= d.cycle_ticks:
            for pid, qty in d.outputs.items():
                owner.add_items(pid, qty * self.batches)
            self.batches = 0
            self.progress = 0
