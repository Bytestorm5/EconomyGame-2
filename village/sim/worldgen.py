"""Random world generation: plots, NPC businesses, and the knowledge graph."""

from __future__ import annotations

import math
import random
from typing import List

from . import config
from .person import Person
from .plot import Plot
from .world import World

# Map size in tiles (the UI draws one tile = TILE_PX pixels).
MAP_W, MAP_H = 30, 20

# Plot layout: two rows of 7 plots flanking a horizontal road.
PLOT_W, PLOT_H = 4, 4
PLOTS_PER_ROW = 7
ROAD_Y = 9          # road occupies tile rows 9-10
ROW_YS = (4, 11)    # top row above road, bottom row below
ROW_X0 = 1
PLOT_GAP = 0

NPC_NAMES = [
    "Aldric", "Berta", "Cedric", "Dora", "Edwin", "Frida", "Godric",
    "Hilda", "Ivo", "Jutta", "Kerrick", "Lena", "Milo", "Nesta",
    "Osric", "Petra", "Quentin", "Rosa",
]

# Starter businesses handed to NPCs, cycled in this order so the village
# starts with a workable grain -> flour -> bread chain plus wood supply.
STARTER_BUSINESSES = [
    "wheat_farm", "mill", "bakery", "woodcutter",
    "wheat_farm", "mill", "bakery",
    "wheat_farm", "woodcutter", "wheat_farm",
    "mill", "bakery", "woodcutter",
]


def generate(seed: int = 0) -> World:
    world = World(MAP_W, MAP_H, seed=seed)
    rng = world.rng

    # Pre-set plots along the road.
    plot_id = 0
    for row_y in ROW_YS:
        for i in range(PLOTS_PER_ROW):
            x = ROW_X0 + i * (PLOT_W + PLOT_GAP)
            world.add_plot(Plot(plot_id, (x, row_y, PLOT_W, PLOT_H)))
            plot_id += 1

    plots = list(world.plots.values())
    rng.shuffle(plots)

    # Player gets the first shuffled plot, empty, with money to build.
    player = world.add_person(Person(0, "You", config.PLAYER_START_MONEY,
                                     is_player=True))
    world.player_id = player.id
    world.assign_plot(player, plots[0])

    # NPCs fill the remaining plots with starter machines.
    names = NPC_NAMES[:]
    rng.shuffle(names)
    for idx, plot in enumerate(plots[1:]):
        npc = world.add_person(Person(idx + 1, names[idx % len(names)],
                                      config.NPC_START_MONEY))
        world.assign_plot(npc, plot)
        biz = STARTER_BUSINESSES[idx % len(STARTER_BUSINESSES)]
        world.build_machine(npc, plot, biz, free=True)
        # Give producers a small head start of stock so day-1 trade works.
        for pid, qty in world.people[npc.id].machines[0].definition.outputs.items():
            npc.add_items(pid, qty * 2)

    _generate_knowledge_graph(world)
    return world


def _generate_knowledge_graph(world: World) -> None:
    """Each person knows their 2 nearest plot neighbours plus 1-2 random
    others -- a small-world graph with local clustering and a few long links."""
    rng = world.rng
    people = list(world.people.values())

    def pos(p: Person):
        return world.plots[p.plot_id].center

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
