"""Random world generation: a road grid of parcels, NPC businesses, and the
knowledge graph. World size (blocks of parcels) and population are
configurable; leftover parcels start unowned and purchasable."""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from ..content import DEMANDS
from . import config
from .person import Person
from .plot import Plot
from .vehicle import Vehicle
from .world import World

# Layout constants (tiles): parcels are 4x4, grouped 2x2 into blocks,
# separated by 2-tile roads on a full grid.
PARCEL = 4
ROAD = 2
BLOCK = PARCEL * 2          # 8 tiles of parcels per block side
PITCH = BLOCK + ROAD        # block-to-block stride

NPC_NAMES = [
    "Aldric", "Berta", "Cedric", "Dora", "Edwin", "Frida", "Godric",
    "Hilda", "Ivo", "Jutta", "Kerrick", "Lena", "Milo", "Nesta",
    "Osric", "Petra", "Quentin", "Rosa",
]

# Starter businesses handed to NPCs, cycled in this order so the village
# starts with a workable grain -> flour -> bread chain, wood supply, and
# one retailer to seed the logistics economy.
STARTER_BUSINESSES = [
    "farm", "mill", "bakery", "forestry", "general_store", "workshop",
    "farm", "mill", "bakery",
    "farm", "forestry", "mill", "bakery",
]


def npc_name(i: int) -> str:
    base = NPC_NAMES[i % len(NPC_NAMES)]
    gen = i // len(NPC_NAMES)
    return base if gen == 0 else f"{base} {'I' * (gen + 1)}"


def generate(seed: int = 0,
             blocks: Optional[Tuple[int, int]] = None,
             npcs: Optional[int] = None) -> World:
    bx, by = blocks if blocks is not None else (config.BLOCKS_X, config.BLOCKS_Y)
    n_npcs = npcs if npcs is not None else config.NPC_COUNT
    n_laborers = max(3, int(n_npcs * config.LABORER_FRACTION))
    parcel_count = bx * by * 4
    if n_npcs + n_laborers + 1 > parcel_count:
        raise ValueError(
            f"{n_npcs} NPCs + {n_laborers} laborers + player need "
            f"{n_npcs + n_laborers + 1} parcels but a "
            f"{bx}x{by}-block village only has {parcel_count}")

    width = ROAD + bx * PITCH
    height = ROAD + by * PITCH
    world = World(width, height, seed=seed)
    rng = world.rng

    # Road grid: full-length strips between (and around) the blocks.
    for i in range(bx + 1):
        world.roads.append((i * PITCH, 0, ROAD, height))
    for j in range(by + 1):
        world.roads.append((0, j * PITCH, width, ROAD))

    # Parcels: 2x2 per block.
    plot_id = 0
    for j in range(by):
        for i in range(bx):
            ox, oy = ROAD + i * PITCH, ROAD + j * PITCH
            for dy in (0, PARCEL):
                for dx in (0, PARCEL):
                    world.add_plot(Plot(plot_id,
                                        (ox + dx, oy + dy, PARCEL, PARCEL)))
                    plot_id += 1

    plots = list(world.plots.values())
    rng.shuffle(plots)

    # Player gets the first shuffled parcel, empty, with money to build,
    # and a starter cart like everyone else.
    player = world.add_person(Person(0, "You", config.PLAYER_START_MONEY,
                                     is_player=True))
    world.player_id = player.id
    world.assign_plot(player, plots[0])
    for vid in config.STARTING_VEHICLES:
        player.vehicles.append(Vehicle(vid, plot=player.home))

    # NPCs get one random parcel each, with a starter machine, a cart, and
    # a little stock so day-1 trade works. Remaining parcels stay unowned
    # (purchasable at the fixed parcel price).
    for idx in range(n_npcs):
        npc = world.add_person(Person(idx + 1, npc_name(idx),
                                      config.NPC_START_MONEY))
        plot = plots[idx + 1]
        world.assign_plot(npc, plot)
        for vid in config.STARTING_VEHICLES:
            npc.vehicles.append(Vehicle(vid, plot=npc.home))
        biz = STARTER_BUSINESSES[idx % len(STARTER_BUSINESSES)]
        machine = world.build_machine(npc, plot, biz, free=True)
        for pid, qty in machine.outputs().items():
            npc.add_items(pid, qty * 2)
        for pid, qty in machine.inputs().items():
            npc.add_items(pid, qty * 6)  # a day's inputs to start rolling
        if biz == "workshop":
            npc.add_items("wood", 16)  # something to build with on day 1
        if machine.definition.resells:
            # Seed the store so it can retail from day 1.
            for d in DEMANDS:
                for pid in d.fulfilled_by:
                    npc.add_items(pid, 6)

    # Laborers: citizens with a home but no business -- the hiring pool
    # that lets owners staff machines and crew vehicles.
    for j in range(n_laborers):
        idx = n_npcs + j
        worker = world.add_person(Person(idx + 1, npc_name(idx),
                                         config.NPC_START_MONEY // 2))
        plot = plots[idx + 1]
        world.assign_plot(worker, plot)
        for vid in config.STARTING_VEHICLES:
            worker.vehicles.append(Vehicle(vid, plot=worker.home))

    _generate_knowledge_graph(world)
    return world


def _generate_knowledge_graph(world: World) -> None:
    """Each person knows their 2 nearest neighbours (by home parcel) plus
    1-2 random others -- a small-world graph with local clustering and a
    few long links."""
    rng = world.rng
    people = list(world.people.values())

    def pos(p: Person):
        return p.home.center

    for person in people:
        px, py = pos(person)
        others = [o for o in people if o.id != person.id]
        others.sort(key=lambda o: math.dist((px, py), pos(o)))
        for neighbour in others[:2]:
            person.knowledge.add(neighbour.id)
            neighbour.knowledge.add(person.id)
        for _ in range(rng.randint(1, 2)):
            stranger = rng.choice(others)
            person.knowledge.add(stranger.id)
            stranger.knowledge.add(person.id)
