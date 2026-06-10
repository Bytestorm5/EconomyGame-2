"""Sidebar: inspect a building, build/upgrade/demolish machines, set prices."""

from __future__ import annotations

from typing import Callable, Optional

import pygame

from ..content import MACHINES
from ..content import PRODUCTS
from ..sim.plot import Plot
from ..sim.world import World
from . import assets
from .widgets import ButtonBank


def recipe_text(mdef) -> str:
    fmt = lambda d: " + ".join(f"{q} {PRODUCTS.get(p).name}" for p, q in d.items())
    inputs = fmt(mdef.inputs) or "nothing"
    return f"{inputs} -> {fmt(mdef.outputs)}"


def io_text(io: dict) -> str:
    if not io:
        return "nothing"
    return ", ".join(f"{q} {PRODUCTS.get(p).name}" for p, q in sorted(io.items()))


def machine_tooltip(machine) -> list:
    """Hover detail for a machine: yesterday's consumption/production."""
    lines = [f"{machine.definition.name}  Lv{machine.level}",
             f"Uptime (7d): {machine.uptime():.0%}"]
    if machine.history:
        day = machine.history[-1]
        lines += [f"Yesterday  (ran {day.uptime:.0%} of the day)",
                  f"  consumed: {io_text(day.consumed)}",
                  f"  produced: {io_text(day.produced)}"]
    else:
        lines.append("(no full day recorded yet)")
    if machine.paused:
        lines.append("Paused: stock covers current demand")
    return lines


def product_tooltip(owner, pid) -> list:
    """Hover detail for a good on sale: yesterday's economics."""
    name = PRODUCTS.get(pid).name
    day = owner.yesterday(pid)
    if day is None:
        return [f"{name} -- yesterday", "(no full day recorded yet)"]
    return [f"{name} -- yesterday",
            f"  profit: ${day.profit}  ({day.sold} sales for ${day.revenue})",
            f"  produced: {day.produced}",
            f"  consumed by own machines: {day.consumed}"]


class BuildingPanel:
    def __init__(self, rect: pygame.Rect, font: pygame.font.Font,
                 small_font: pygame.font.Font, buttons: ButtonBank,
                 notify: Callable[[str], None]):
        self.rect = rect
        self.font = font
        self.small_font = small_font
        self.buttons = buttons
        self.notify = notify
        self.build_slot: Optional[int] = None  # slot picking a machine to build
        # (rect, lines) hover tooltips, rebuilt every frame during draw.
        self.hover_zones: list = []

    # --- text helpers -------------------------------------------------------
    def _line(self, screen, text: str, y: int, color=assets.PANEL_TEXT,
              small: bool = False, x_off: int = 12) -> int:
        font = self.small_font if small else self.font
        surf = font.render(text, True, color)
        screen.blit(surf, (self.rect.x + x_off, y))
        return y + surf.get_height() + 4

    def _header(self, screen, text: str, y: int) -> int:
        y += 6
        y = self._line(screen, text, y, color=assets.PANEL_DIM)
        pygame.draw.line(screen, assets.PANEL_DIM,
                         (self.rect.x + 10, y), (self.rect.right - 10, y))
        return y + 6

    # --- drawing -------------------------------------------------------------
    def draw(self, screen: pygame.Surface, world: World,
             plot: Optional[Plot]) -> None:
        self.hover_zones.clear()
        pygame.draw.rect(screen, assets.PANEL_BG, self.rect)
        pygame.draw.line(screen, assets.PANEL_DIM, self.rect.topleft,
                         self.rect.bottomleft)
        if plot is None:
            self._line(screen, "Click a plot to inspect it.",
                       self.rect.y + 16, color=assets.PANEL_DIM)
            return

        owner = world.people[plot.owner_id]
        mine = owner.is_player
        y = self.rect.y + 12
        y = self._line(screen, f"{owner.name}'s plot" if not mine
                       else "Your plot", y)
        y = self._line(screen, f"Coin: ${owner.money}", y,
                       color=assets.PLAYER_BORDER if mine else assets.PANEL_TEXT)
        y = self._line(screen, f"Knows {len(owner.knowledge)} people  "
                       f"|  Hunger {owner.hunger}", y, small=True,
                       color=assets.PANEL_DIM)
        if mine:
            y = self._line(screen, "Your auto-buy reaches the whole village",
                           y, small=True, color=assets.PLAYER_BORDER)

        if self.build_slot is not None and mine:
            self._draw_build_menu(screen, world, owner, plot, y)
            return

        y = self._header(screen, "MACHINES", y)
        for i, machine in enumerate(plot.slots):
            y = self._draw_slot(screen, world, owner, plot, i, machine, y, mine)

        y = self._header(screen, "GOODS FOR SALE", y)
        produced = sorted(owner.produced_products())
        if not produced:
            y = self._line(screen, "(nothing produced here)", y,
                           color=assets.PANEL_DIM, small=True)
        for pid in produced:
            prod = PRODUCTS.get(pid)
            stock = owner.inventory.get(pid, 0)
            price = owner.price_of(pid)
            y0 = y
            y = self._line(screen, f"{prod.name}: {stock} in stock @ ${price}",
                           y, small=True)
            self.hover_zones.append((
                pygame.Rect(self.rect.x, y0, self.rect.w, y - y0),
                product_tooltip(owner, pid)))
            if mine:
                def make_adj(p=pid, delta=0):
                    def adj():
                        owner.prices[p] = max(1, owner.price_of(p) + delta)
                    return adj
                bx = self.rect.right - 64
                self.buttons.draw(screen, pygame.Rect(bx, y0, 24, 18), "-",
                                  make_adj(pid, -1))
                self.buttons.draw(screen, pygame.Rect(bx + 30, y0, 24, 18), "+",
                                  make_adj(pid, +1))

        y = self._header(screen, "INVENTORY", y)
        items = [(pid, qty) for pid, qty in sorted(owner.inventory.items())
                 if qty > 0]
        if not items:
            y = self._line(screen, "(empty)", y, color=assets.PANEL_DIM,
                           small=True)
        for pid, qty in items:
            y = self._line(screen, f"{PRODUCTS.get(pid).name}: {qty}", y,
                           small=True)

    def _draw_slot(self, screen, world: World, owner, plot: Plot, index: int,
                   machine, y: int, mine: bool) -> int:
        if machine is None:
            y0 = y
            y = self._line(screen, f"Slot {index + 1}: empty", y,
                           color=assets.PANEL_DIM, small=True)
            if mine:
                def open_build(i=index):
                    self.build_slot = i
                self.buttons.draw(
                    screen, pygame.Rect(self.rect.right - 70, y0, 58, 18),
                    "Build", open_build)
            return y + 4

        d = machine.definition
        if machine.paused:
            status = "paused"
        elif machine.batches:
            status = f"running x{machine.batches}"
        else:
            status = "idle"
        y0 = y
        y = self._line(screen,
                       f"{d.name}  Lv{machine.level}  ({status})", y)
        y = self._line(screen,
                       f"{recipe_text(d)}   |   up {machine.uptime():.0%}",
                       y, small=True, color=assets.PANEL_DIM)
        self.hover_zones.append((
            pygame.Rect(self.rect.x, y0, self.rect.w, y - y0),
            machine_tooltip(machine)))
        if mine:
            bx = self.rect.x + 12
            row = pygame.Rect(bx, y, 130, 20)
            if machine.can_upgrade:
                cost = machine.upgrade_cost
                def do_upgrade(m=machine):
                    if world.upgrade_machine(owner, m):
                        self.notify(f"Upgraded {m.definition.name} to "
                                    f"Lv{m.level}")
                    else:
                        self.notify("Not enough coin to upgrade")
                self.buttons.draw(screen, row, f"Upgrade ${cost}", do_upgrade,
                                  enabled=owner.money >= cost)
            else:
                self.buttons.draw(screen, row, "Max level", lambda: None,
                                  enabled=False)
            def do_demolish(i=index, name=d.name):
                world.demolish_machine(owner, plot, i)
                self.notify(f"Demolished {name}")
            self.buttons.draw(screen, pygame.Rect(bx + 140, y, 90, 20),
                              "Demolish", do_demolish)
            y += 26
        return y + 4

    def _draw_build_menu(self, screen, world: World, owner, plot: Plot,
                         y: int) -> None:
        y = self._header(screen, f"BUILD IN SLOT {self.build_slot + 1}", y)
        for mdef in MACHINES:
            y0 = y
            y = self._line(screen, f"{mdef.name}  (${mdef.build_cost})", y)
            y = self._line(screen, recipe_text(mdef), y, small=True,
                           color=assets.PANEL_DIM)
            def do_build(d=mdef):
                if world.build_machine(owner, plot, d.id) is not None:
                    self.notify(f"Built {d.name}")
                    self.build_slot = None
                else:
                    self.notify("Not enough coin")
            self.buttons.draw(
                screen, pygame.Rect(self.rect.right - 70, y0, 58, 20),
                "Build", do_build, enabled=owner.money >= mdef.build_cost)
            y += 6
        def cancel():
            self.build_slot = None
        self.buttons.draw(screen,
                          pygame.Rect(self.rect.x + 12, y + 8, 80, 22),
                          "Cancel", cancel)
