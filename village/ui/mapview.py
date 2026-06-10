"""Top-down 2D map: terrain, plots, machines, knowledge overlay."""

from __future__ import annotations

from typing import Optional

import pygame

from ..sim import worldgen
from ..sim.plot import Plot
from ..sim.world import World
from . import assets

TILE = 32


class MapView:
    def __init__(self, rect: pygame.Rect, font: pygame.font.Font,
                 small_font: pygame.font.Font):
        self.rect = rect
        self.font = font
        self.small_font = small_font
        self.show_knowledge = False
        # (rect, lines) hover tooltips, rebuilt every frame during draw.
        self.hover_zones: list = []

    # --- coordinate helpers -------------------------------------------------
    def plot_px_rect(self, plot: Plot) -> pygame.Rect:
        x, y, w, h = plot.rect
        return pygame.Rect(self.rect.x + x * TILE, self.rect.y + y * TILE,
                           w * TILE, h * TILE)

    def plot_at(self, world: World, pos) -> Optional[Plot]:
        for plot in world.plots.values():
            if self.plot_px_rect(plot).collidepoint(pos):
                return plot
        return None

    # --- drawing -------------------------------------------------------------
    def draw(self, screen: pygame.Surface, world: World,
             selected: Optional[Plot]) -> None:
        self.hover_zones.clear()
        # Terrain (placeholder art: flat colors; see ASSETS.md).
        grass = assets.get_tile("terrain_grass", self.rect.size, assets.GRASS)
        screen.blit(grass, self.rect.topleft)
        road_rect = pygame.Rect(self.rect.x,
                                self.rect.y + worldgen.ROAD_Y * TILE,
                                self.rect.w, 2 * TILE)
        road = assets.get_tile("terrain_road", road_rect.size, assets.ROAD)
        screen.blit(road, road_rect.topleft)

        for plot in world.plots.values():
            self._draw_plot(screen, world, plot, selected)

        if self.show_knowledge:
            self._draw_knowledge(screen, world, selected)

    def _draw_plot(self, screen, world: World, plot: Plot,
                   selected: Optional[Plot]) -> None:
        r = self.plot_px_rect(plot)
        ground = assets.get_tile("plot_ground", (r.w - 4, r.h - 4),
                                 assets.PLOT_FILL)
        screen.blit(ground, (r.x + 2, r.y + 2))

        owner = world.people[plot.owner_id] if plot.owner_id is not None else None
        border = assets.PLOT_BORDER
        width = 2
        if owner is not None and owner.is_player:
            border, width = assets.PLAYER_BORDER, 3
        if selected is plot:
            border, width = assets.SELECT_BORDER, 3
        pygame.draw.rect(screen, border, r, width=width)

        # Machines on a 2x2 slot grid inside the plot.
        pad, gap = 8, 6
        slot_w = (r.w - 2 * pad - gap) // 2
        slot_h = (r.h - 2 * pad - gap - 14) // 2
        for i, machine in enumerate(plot.slots):
            sx = r.x + pad + (i % 2) * (slot_w + gap)
            sy = r.y + pad + (i // 2) * (slot_h + gap)
            slot_rect = pygame.Rect(sx, sy, slot_w, slot_h)
            if machine is None:
                pygame.draw.rect(screen, assets.PLOT_BORDER, slot_rect, width=1)
                continue
            d = machine.definition
            block = assets.get_tile(f"machine_{d.id}", slot_rect.size, d.color)
            screen.blit(block, slot_rect.topleft)
            pygame.draw.rect(screen, (20, 20, 20), slot_rect, width=1)
            from .panel import machine_tooltip
            self.hover_zones.append((slot_rect.copy(),
                                     machine_tooltip(machine)))
            lvl = self.small_font.render(f"L{machine.level}", True, (15, 15, 15))
            screen.blit(lvl, (sx + 3, sy + 2))
            # Cycle progress bar along the slot bottom.
            if machine.batches > 0:
                frac = machine.progress / d.cycle_ticks
                bar = pygame.Rect(sx, sy + slot_h - 4, int(slot_w * frac), 4)
                pygame.draw.rect(screen, assets.GOOD, bar)

        if owner is not None:
            name = owner.name + (" *" if owner.is_player else "")
            label = self.small_font.render(name, True, (250, 248, 240))
            screen.blit(label, (r.x + 6, r.bottom - 16))

    def _draw_knowledge(self, screen, world: World,
                        selected: Optional[Plot]) -> None:
        overlay = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        focus_id = (selected.owner_id if selected is not None else None)

        def center(person_id: int):
            plot = world.plots[world.people[person_id].plot_id]
            cx, cy = plot.center
            return (cx * TILE, cy * TILE)

        drawn = set()
        for person in world.people.values():
            for other_id in person.knowledge:
                key = (min(person.id, other_id), max(person.id, other_id))
                if key in drawn:
                    continue
                drawn.add(key)
                if focus_id in key:
                    color = (255, 220, 90, 220)
                else:
                    color = (255, 255, 255, 45)
                pygame.draw.line(overlay, color, center(key[0]),
                                 center(key[1]), 2)
        screen.blit(overlay, self.rect.topleft)
