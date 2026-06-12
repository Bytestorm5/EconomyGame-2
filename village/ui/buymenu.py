"""The buy menu: a searchable catalog of everything purchasable, opened
from a parcel (deliveries go there).

Left: search box + tag filters + the product list. Typing matches name,
tags, and -- for machine kits -- anything the machine could output, so
searching "bread" surfaces the bakery kit. Right: details for the selected
product (recipes it unlocks, price history sparkline) and every seller
ranked by delivered cost to the destination parcel.
"""

from __future__ import annotations

from typing import Optional

import pygame

import math

from ..content import MACHINES, PRODUCTS, RECIPES
from ..sim import trade
from ..sim.money import cents, fmt
from ..sim.world import World
from . import assets
from .market import _sparkline
from .widgets import ButtonBank


def _machine_outputs(pid: str) -> set:
    """Everything a machine kit could ever produce."""
    if pid not in MACHINES:
        return set()
    out = set()
    for rid in MACHINES.get(pid).recipes:
        out.update(RECIPES.get(rid).outputs)
    return out


def _matches(pid: str, query: str, tag: Optional[str]) -> bool:
    prod = PRODUCTS.get(pid)
    if tag is not None and tag not in prod.tags:
        return False
    if not query:
        return True
    q = query.lower()
    if q in prod.name.lower() or any(q in t for t in prod.tags):
        return True
    # Machines match on what they could output ("bread" -> bakery kit).
    return any(q in PRODUCTS.get(o).name.lower()
               for o in _machine_outputs(pid))


class BuyMenu:
    TAGS = [None, "food", "raw", "material", "machine-kit", "vehicle-kit"]

    def __init__(self, rect: pygame.Rect, font, small_font,
                 buttons: ButtonBank, notify):
        self.rect = rect
        self.font = font
        self.small_font = small_font
        self.buttons = buttons
        self.notify = notify
        self.query = ""
        self.tag: Optional[str] = None
        self.selected: Optional[str] = None
        self.dest_plot = None   # set when opened from a parcel

    def open_for(self, plot) -> None:
        self.dest_plot = plot
        self.selected = None

    def handle_key(self, event) -> bool:
        """Typing feeds the search box while the menu is open."""
        if event.key == pygame.K_BACKSPACE:
            self.query = self.query[:-1]
            return True
        ch = event.unicode
        if ch and (ch.isalnum() or ch in " -_"):
            self.query += ch.lower()
            return True
        return False

    # --- drawing -----------------------------------------------------------
    def draw(self, screen, world: World) -> None:
        pygame.draw.rect(screen, assets.PANEL_BG, self.rect)
        pygame.draw.rect(screen, assets.PANEL_DIM, self.rect, width=1)
        x, y = self.rect.x + 12, self.rect.y + 8
        dest = self.dest_plot
        title = self.font.render(
            f"BUY -- deliveries to parcel #{dest.id}   "
            f"(type to search, Esc closes)", True, assets.PANEL_TEXT)
        screen.blit(title, (x, y))
        y += 26

        # search box
        box = pygame.Rect(x, y, 240, 20)
        pygame.draw.rect(screen, (30, 28, 25), box)
        pygame.draw.rect(screen, assets.PANEL_DIM, box, width=1)
        q = self.small_font.render(self.query + "_", True, assets.PANEL_TEXT)
        screen.blit(q, (x + 5, y + 3))
        # tag chips
        cx = x + 252
        for tag in self.TAGS:
            label = tag or "all"
            w = 10 + 7 * len(label)
            def set_tag(t=tag):
                self.tag = t
            active = (self.tag == tag)
            self.buttons.draw(screen, pygame.Rect(cx, y, w, 20),
                              ("*" if active else "") + label, set_tag)
            cx += w + 6
        y += 28

        rows = [pid for pid in PRODUCTS.ids()
                if _matches(pid, self.query, self.tag)]
        rows.sort(key=lambda p: PRODUCTS.get(p).name)
        list_w = 270
        for pid in rows[:16]:
            prod = PRODUCTS.get(pid)
            offers = self._offers(world, pid, dest)
            price = (fmt(int(offers[0][1])) if offers else "none sold")
            def select(p=pid):
                self.selected = p
            marker = ">" if pid == self.selected else " "
            self.buttons.draw(
                screen, pygame.Rect(x, y, list_w, 19),
                f"{marker} {prod.name:<16} {price}", select)
            y += 22

        if self.selected is not None:
            self._draw_detail(screen, world, self.rect.x + 300,
                              self.rect.y + 62)

    def _draw_detail(self, screen, world: World, x: int, y: int) -> None:
        pid = self.selected
        prod = PRODUCTS.get(pid)
        dest = self.dest_plot
        player = world.player

        def line(text, dy=18, color=assets.PANEL_TEXT, small=True):
            nonlocal y
            f = self.small_font if small else self.font
            screen.blit(f.render(text, True, color), (x, y))
            y += dy

        line(prod.name, 22, assets.PLAYER_BORDER, small=False)
        line(f"tags: {', '.join(prod.tags) or '-'}   "
             f"wt {prod.weight:g} / sp {prod.space:g}"
             + (f"   keeps ~{prod.shelf_life_days:.0f}d"
                if prod.shelf_life_days else ""), 18, assets.PANEL_DIM)

        # machine kits: what it can run
        if pid in MACHINES:
            mdef = MACHINES.get(pid)
            line(f"BUILDING -- workers {mdef.workers}"
                 + (f", needs {mdef.skill}" if mdef.skill else "")
                 + (", buildable with coin (no kit)" if mdef.natural else ""),
                 18, assets.GOOD)
            probe = __import__("village.sim.machine",
                               fromlist=["Machine"]).Machine(pid)
            for rid in mdef.recipes[:6]:
                r = RECIPES.get(rid)
                io = " + ".join(f"{q} {PRODUCTS.get(p).name}"
                                for p, q in r.inputs.items()) or "nothing"
                out = " + ".join(f"{q} {PRODUCTS.get(p).name}"
                                 for p, q in r.outputs.items())
                line(f"  {r.name}: {io} -> {out} "
                     f"({probe.cycle_ticks_for(rid)}t)", 16, assets.PANEL_DIM)

        # price history sparkline
        hist = list(world.market_history.get(pid, []))
        prices = [p for p, _ in hist]
        chart = pygame.Rect(x, y + 4, 300, 42)
        pygame.draw.rect(screen, (30, 28, 25), chart)
        _sparkline(screen, chart, prices, assets.GOOD)
        recent = [p for p in prices if p is not None]
        label = (f"avg paid, {len(hist)}d -- now "
                 f"{fmt(recent[-1]) if recent else '--'}")
        screen.blit(self.small_font.render(label, True, assets.PANEL_DIM),
                    (x + 308, y + 20))
        y += 54

        # sellers ranked by delivered cost (estimates don't need an idle
        # cart; actually buying does)
        line("SELLERS (price + est. shipping here):", 20)
        offers = self._offers(world, pid, dest)
        if not offers:
            line("  nobody sells this right now", 18, assets.BAD)
            def do_request(p=pid):
                got = trade.buy(world, player, p, qty=1, dest=dest,
                                allow_import=True)
                if got:
                    self.notify("Found one after all -- ordered")
                else:
                    self.notify("Requested -- producers watch unmet demand")
            self.buttons.draw(screen, pygame.Rect(x, y, 150, 20),
                              "Request it", do_request)
            y += 26
            return
        for offer, total, ship in offers[:6]:
            seller = offer.seller
            outside = seller is world.outside
            stock = ("endless" if outside
                     else offer.plot.inventory.get(pid, 0))
            row = (f"{seller.name:<16} {fmt(offer.price)} "
                   f"+ ~{fmt(ship)} ship  ({stock} in stock)")
            screen.blit(self.small_font.render(row, True, assets.PANEL_TEXT),
                        (x, y))
            def buy_n(sl=seller, p=pid, n=1):
                got = 0
                for _ in range(n):
                    if sl is world.outside:
                        fresh = trade.import_quote(world, player, p, 1, dest)
                    else:
                        fresh = trade.best_quote(world, player, p, 1, dest,
                                                 sellers=[sl])
                    if fresh is None:
                        break
                    got += trade.place_order(world, player, fresh, p, dest)
                if got:
                    self.notify(f"Ordered {got} {PRODUCTS.get(p).name} "
                                f"from {sl.name}")
                else:
                    self.notify("No idle cart & driver (or no coin)")
            bx = x + 360
            self.buttons.draw(screen, pygame.Rect(bx, y, 50, 17),
                              "Buy 1", lambda s=seller, p=pid: buy_n(s, p, 1))
            self.buttons.draw(screen, pygame.Rect(bx + 56, y, 50, 17),
                              "Buy 5", lambda s=seller, p=pid: buy_n(s, p, 5))
            y += 21

    def _offers(self, world: World, pid: str, dest):
        """(offer, delivered estimate, ship estimate) for every seller the
        player can see, cheapest first. Ship estimate uses the cheapest of
        the player's vehicles whether or not it's idle right now."""
        player = world.player
        out = []
        offers = list(trade.iter_offers(world, player, pid))
        imported = trade.import_offer(world, pid)
        if imported is not None:
            offers.append(imported)
        for offer in offers:
            ships = []
            for v in player.vehicles:
                if v.max_qty(pid) < 1:
                    continue
                d1 = v.plot.distance_to(offer.plot)
                d2 = offer.plot.distance_to(dest)
                ships.append(math.ceil(
                    v.trip_cost(d1, d2, pid, 1) * 100))
            if not ships:
                continue
            ship = min(ships)
            out.append((offer, offer.price + ship, ship))
        out.sort(key=lambda t: t[1])
        return out
