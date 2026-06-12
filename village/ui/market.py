"""Market screen (toggle with M): traded-price history per product, your
position vs the market, and your business trendline."""

from __future__ import annotations

import pygame

from ..content import PRODUCTS
from ..sim.money import fmt
from ..sim.world import World
from . import assets


def _sparkline(screen, rect: pygame.Rect, values, color) -> None:
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    span = (hi - lo) or 1
    n = max(1, len(values) - 1)
    coords = [(rect.x + rect.w * i / n,
               rect.bottom - rect.h * (v - lo) / span) for i, v in pts]
    pygame.draw.lines(screen, color, False, coords, 2)


class MarketView:
    def __init__(self, rect: pygame.Rect, font, small_font):
        self.rect = rect
        self.font = font
        self.small_font = small_font

    def draw(self, screen, world: World) -> None:
        pygame.draw.rect(screen, assets.PANEL_BG, self.rect)
        pygame.draw.rect(screen, assets.PANEL_DIM, self.rect, width=1)
        x, y = self.rect.x + 14, self.rect.y + 10
        title = self.font.render(
            "MARKET -- avg price paid per unit (last "
            f"{len(next(iter(world.market_history.values()), []))} days)",
            True, assets.PANEL_TEXT)
        screen.blit(title, (x, y))
        y += 28

        player = world.player
        row_h = 42
        for prod in PRODUCTS:
            hist = list(world.market_history.get(prod.id, []))
            prices = [p for p, _ in hist]
            recent = [p for p in prices if p is not None]
            units_day = (sum(u for _, u in hist[-7:]) / max(1, len(hist[-7:]))
                         if hist else 0)
            stock = sum(pl.inventory.get(prod.id, 0)
                        for pl in world.plots.values())
            # name + swatch
            pygame.draw.rect(screen, prod.color,
                             pygame.Rect(x, y + 4, 10, 10))
            name = self.small_font.render(prod.name, True, assets.PANEL_TEXT)
            screen.blit(name, (x + 16, y + 2))
            # sparkline
            chart = pygame.Rect(x + 130, y + 2, 280, row_h - 10)
            pygame.draw.rect(screen, (30, 28, 25), chart)
            _sparkline(screen, chart, prices, assets.GOOD)
            # numbers
            last = recent[-1] if recent else None
            yours = (fmt(player.price_of(prod.id))
                     if prod.id in player.sellable_products() else "--")
            info = (f"now {fmt(last) if last else '--'}   "
                    f"vol {units_day:.1f}/d   stock {stock}   "
                    f"you: {yours}")
            surf = self.small_font.render(info, True, assets.PANEL_DIM)
            screen.blit(surf, (x + 424, y + 8))
            y += row_h
            if y > self.rect.bottom - 90:
                break

        # player trendline
        y = self.rect.bottom - 78
        label = self.small_font.render(
            "YOUR BUSINESS -- net worth (gold) / daily profit (green)",
            True, assets.PANEL_TEXT)
        screen.blit(label, (x, y))
        chart = pygame.Rect(x, y + 18, 520, 48)
        pygame.draw.rect(screen, (30, 28, 25), chart)
        hist = list(world.player_history)
        _sparkline(screen, chart, [w for w, _ in hist], assets.PLAYER_BORDER)
        _sparkline(screen, chart, [p for _, p in hist], assets.GOOD)
        if hist:
            net, profit = hist[-1]
            sign = "-" if profit < 0 else "+"
            txt = self.small_font.render(
                f"net {fmt(net)}   yday {sign}{fmt(abs(profit))}",
                True, assets.PANEL_DIM)
            screen.blit(txt, (x + 530, y + 36))
