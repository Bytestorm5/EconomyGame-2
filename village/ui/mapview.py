"""Top-down 2D map: terrain, road grid, parcels, machines, knowledge web."""

from __future__ import annotations

from typing import Optional

import pygame

from ..sim.plot import Plot
from ..sim.world import World
from . import assets


class MapView:
    def __init__(self, rect: pygame.Rect, world: World,
                 font: pygame.font.Font, small_font: pygame.font.Font):
        self.rect = rect
        self.font = font
        self.small_font = small_font
        self.show_knowledge = False
        # (rect, lines) hover tooltips, rebuilt every frame during draw.
        self.hover_zones: list = []
        # Tile size adapts to the configured world size; map is centered.
        self.tile = max(8, min(rect.w // world.width, rect.h // world.height))
        self.origin = (rect.x + (rect.w - world.width * self.tile) // 2,
                       rect.y + (rect.h - world.height * self.tile) // 2)

    # --- coordinate helpers -------------------------------------------------
    def tile_rect(self, rect_tiles) -> pygame.Rect:
        x, y, w, h = rect_tiles
        return pygame.Rect(self.origin[0] + x * self.tile,
                           self.origin[1] + y * self.tile,
                           w * self.tile, h * self.tile)

    def plot_px_rect(self, plot: Plot) -> pygame.Rect:
        return self.tile_rect(plot.rect)

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
        for road in world.roads:
            r = self.tile_rect(road)
            road_img = assets.get_tile("terrain_road", r.size, assets.ROAD)
            screen.blit(road_img, r.topleft)

        for plot in world.plots.values():
            self._draw_plot(screen, world, plot, selected)

        self._draw_shipments(screen, world)

        if self.show_knowledge:
            self._draw_knowledge(screen, world, selected)

    def _draw_shipments(self, screen, world: World) -> None:
        """Goods in transit: a product-colored dot moving src -> dest."""
        from ..content import PRODUCTS
        for s in world.shipments:
            span = max(1, s.arrive - s.depart)
            t = min(1.0, max(0.0, (world.tick_count - s.depart) / span))
            # Two legs: parked -> source (empty), source -> destination
            # (loaded); split the timeline by distance share.
            d1 = s.start.distance_to(s.src)
            d2 = s.src.distance_to(s.dest)
            cut = d1 / (d1 + d2) if (d1 + d2) > 0 else 0.0
            if t < cut and cut > 0:
                (ax, ay), (bx, by) = s.start.center, s.src.center
                f = t / cut
            else:
                (ax, ay), (bx, by) = s.src.center, s.dest.center
                f = (t - cut) / (1 - cut) if cut < 1 else 1.0
            x = self.origin[0] + (ax + (bx - ax) * f) * self.tile
            y = self.origin[1] + (ay + (by - ay) * f) * self.tile
            color = PRODUCTS.get(s.product_id).color
            pygame.draw.circle(screen, (20, 20, 20), (int(x), int(y)), 5)
            pygame.draw.circle(screen, color, (int(x), int(y)), 4)

    def _draw_plot(self, screen, world: World, plot: Plot,
                   selected: Optional[Plot]) -> None:
        r = self.plot_px_rect(plot)
        owner = world.people.get(plot.owner_id)
        ground_name = "plot_ground" if owner is not None else "plot_ground_unowned"
        ground_color = assets.PLOT_FILL if owner is not None else assets.PLOT_UNOWNED
        ground = assets.get_tile(ground_name, (r.w - 4, r.h - 4), ground_color)
        screen.blit(ground, (r.x + 2, r.y + 2))

        border = assets.PLOT_BORDER
        width = 2
        if owner is not None and owner.is_player:
            border, width = assets.PLAYER_BORDER, 3
        if selected is plot:
            border, width = assets.SELECT_BORDER, 3
        pygame.draw.rect(screen, border, r, width=width)

        # Machines on a 2-column slot grid inside the parcel.
        pad, gap = 6, 5
        rows = max(1, (len(plot.slots) + 1) // 2)
        slot_w = (r.w - 2 * pad - gap) // 2
        slot_h = (r.h - 2 * pad - gap * (rows - 1) - 14) // rows
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
                frac = machine.progress / machine.cycle_ticks
                bar = pygame.Rect(sx, sy + slot_h - 4, int(slot_w * frac), 4)
                pygame.draw.rect(screen, assets.GOOD, bar)

        price = world.plot_sale_price(plot)
        if owner is not None:
            name = owner.name + (" *" if owner.is_player else "")
            label = self.small_font.render(name, True, (250, 248, 240))
            screen.blit(label, (r.x + 5, r.bottom - 16))
        if price is not None:
            tag = self.small_font.render(f"${price // 100}", True,
                                         assets.PLAYER_BORDER)
            screen.blit(tag, (r.right - tag.get_width() - 5, r.y + 3))

    def _draw_knowledge(self, screen, world: World,
                        selected: Optional[Plot]) -> None:
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        focus_id = (selected.owner_id if selected is not None else None)

        def center(person_id: int):
            cx, cy = world.people[person_id].home.center
            return (self.origin[0] + cx * self.tile,
                    self.origin[1] + cy * self.tile)

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
        screen.blit(overlay, (0, 0))
