"""Machine (recipe) definitions.

Every machine follows the same tycoon structure: it consumes ``inputs`` from
its owner's inventory, runs for ``cycle_ticks`` ticks, then adds ``outputs``
to the owner's inventory. Level L multiplies the batch size by
``2 ** (L - 1)`` (exponential throughput upgrade path); upgrade costs grow
exponentially too (see sim.machine).

All machines occupy exactly one plot slot for now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from ..registry import REGISTRY, ContentDef


@dataclass(frozen=True)
class MachineDef(ContentDef):
    inputs: Dict[str, int]
    outputs: Dict[str, int]
    cycle_ticks: int
    build_cost: int
    color: Tuple[int, int, int]  # placeholder asset: solid color block
    footprint: int = 1  # plot slots occupied (uniform for now)


MACHINES = REGISTRY.category("machine", MachineDef)


def register_machines() -> None:
    MACHINES.register(MachineDef(
        id="wheat_farm", name="Wheat Farm",
        inputs={}, outputs={"grain": 2},
        cycle_ticks=6, build_cost=50, color=(106, 168, 79)))
    MACHINES.register(MachineDef(
        id="woodcutter", name="Woodcutter",
        inputs={}, outputs={"wood": 2},
        cycle_ticks=6, build_cost=50, color=(87, 65, 47)))
    MACHINES.register(MachineDef(
        id="mill", name="Mill",
        inputs={"grain": 2}, outputs={"flour": 2, "bran": 1},
        cycle_ticks=4, build_cost=80, color=(180, 180, 190)))
    MACHINES.register(MachineDef(
        id="bakery", name="Bakery",
        inputs={"flour": 2, "wood": 1}, outputs={"bread": 2},
        cycle_ticks=4, build_cost=100, color=(196, 98, 45)))
