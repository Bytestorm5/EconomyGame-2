"""Main game application: window, loop, HUD, input."""

from __future__ import annotations

import time
from typing import Optional

import pygame

from ..content import load_all
from ..sim import config
from ..sim.money import fmt
from ..sim.plot import Plot
from ..sim.worldgen import generate
from . import assets
from .mapview import MapView
from .buymenu import BuyMenu
from .market import MarketView
from .panel import BuildingPanel
from .widgets import ButtonBank

WINDOW_W, WINDOW_H = 1280, 720
HUD_H = 40
MAP_W_PX, MAP_H_PX = 960, 640
BASE_TICKS_PER_SEC = 6
SAVE_PATH = "savegame.pkl"


class App:
    def __init__(self, seed: int = 0, blocks=None, npcs=None,
                 load_path: str = None):
        load_all()
        pygame.init()
        pygame.display.set_caption("Village Economy")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 22)
        self.small_font = pygame.font.Font(None, 17)

        from ..sim.world import World
        if load_path is not None:
            self.world = World.load(load_path)
        else:
            self.world = generate(seed=seed, blocks=blocks, npcs=npcs)
        self.selected: Optional[Plot] = None
        self.paused = False
        self.speed = 1
        self._tick_accum = 0.0
        self._message = ""
        self._message_until = 0.0

        self.buttons = ButtonBank(self.small_font)
        self.map_view = MapView(
            pygame.Rect(0, HUD_H, MAP_W_PX, MAP_H_PX),
            self.world, self.font, self.small_font)
        self.panel = BuildingPanel(
            pygame.Rect(MAP_W_PX, 0, WINDOW_W - MAP_W_PX, WINDOW_H),
            self.font, self.small_font, self.buttons, self.notify)
        self.market_view = MarketView(
            pygame.Rect(40, HUD_H + 20, MAP_W_PX - 80, MAP_H_PX - 40),
            self.font, self.small_font)
        self.show_market = False
        self.buy_menu = BuyMenu(
            pygame.Rect(20, HUD_H + 10, MAP_W_PX - 40, MAP_H_PX - 20),
            self.font, self.small_font, self.buttons, self.notify)
        self.show_buy = False

        self.panel.app_hooks = self
        # Start with the player's home parcel selected so the controls are
        # obvious.
        self.selected = self.world.player.home

    def notify(self, message: str) -> None:
        self._message = message
        self._message_until = time.monotonic() + 3.0

    def load_world(self) -> None:
        import os
        from ..sim.world import World
        if not os.path.exists(SAVE_PATH):
            self.notify(f"No save at {SAVE_PATH}")
            return
        self.world = World.load(SAVE_PATH)
        self.map_view = MapView(self.map_view.rect, self.world,
                                self.font, self.small_font)
        self.selected = self.world.player.home
        self.panel.build_slot = None
        self.notify(f"Loaded {SAVE_PATH} (day {self.world.day})")

    # --- loop ----------------------------------------------------------------
    def run(self, max_frames: Optional[int] = None,
            screenshot: Optional[str] = None) -> None:
        frame = 0
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            running = self.handle_events()
            self.advance_sim(dt)
            self.draw()
            pygame.display.flip()
            frame += 1
            if max_frames is not None and frame >= max_frames:
                if screenshot:
                    pygame.image.save(self.screen, screenshot)
                running = False
        pygame.quit()

    def advance_sim(self, dt: float) -> None:
        if self.paused:
            return
        self._tick_accum += dt * BASE_TICKS_PER_SEC * self.speed
        while self._tick_accum >= 1.0:
            self.world.tick()
            self._tick_accum -= 1.0

    # --- input ---------------------------------------------------------------
    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                # While the buy menu is open, the keyboard is its search box.
                if self.show_buy and event.key not in (pygame.K_ESCAPE,):
                    self.buy_menu.handle_key(event)
                    continue
                if event.key == pygame.K_ESCAPE:
                    if self.show_buy:
                        self.show_buy = False
                    elif self.panel.build_slot is not None:
                        self.panel.build_slot = None
                    elif self.panel.manage_machine is not None:
                        self.panel.manage_machine = None
                    else:
                        self.selected = None
                elif event.key == pygame.K_SPACE:
                    self.paused = not self.paused
                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                    self.speed = {pygame.K_1: 1, pygame.K_2: 2,
                                  pygame.K_3: 4}[event.key]
                elif event.key == pygame.K_k:
                    self.map_view.show_knowledge = not self.map_view.show_knowledge
                elif event.key == pygame.K_m:
                    self.show_market = not self.show_market
                elif event.key == pygame.K_F5:
                    self.world.save(SAVE_PATH)
                    self.notify(f"Saved to {SAVE_PATH}")
                elif event.key == pygame.K_F9:
                    self.load_world()
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.buttons.handle_click(event.pos):
                    continue
                if self.map_view.rect.collidepoint(event.pos):
                    plot = self.map_view.plot_at(self.world, event.pos)
                    if plot is not self.selected:
                        self.selected = plot
                        self.panel.build_slot = None
                        self.panel.manage_machine = None
        return True

    # --- drawing ---------------------------------------------------------------
    def draw(self) -> None:
        self.buttons.begin_frame()
        self.screen.fill(assets.HUD_BG)
        self.map_view.draw(self.screen, self.world, self.selected)
        if self.show_market:
            self.market_view.draw(self.screen, self.world)
        if self.show_buy and self.buy_menu.dest_plot is not None:
            self.buy_menu.draw(self.screen, self.world)
        self.panel.draw(self.screen, self.world, self.selected)
        self.draw_hud()
        self.draw_message()
        self.draw_tooltip()

    def draw_tooltip(self) -> None:
        pos = pygame.mouse.get_pos()
        for rect, lines in self.panel.hover_zones + self.map_view.hover_zones:
            if rect.collidepoint(pos):
                self._render_tooltip(lines, pos)
                return

    def _render_tooltip(self, lines, pos) -> None:
        pad = 6
        surfs = [self.small_font.render(t, True, assets.PANEL_TEXT)
                 for t in lines]
        w = max(s.get_width() for s in surfs) + 2 * pad
        h = sum(s.get_height() + 2 for s in surfs) + 2 * pad
        x = min(pos[0] + 14, WINDOW_W - w - 4)
        y = min(pos[1] + 14, WINDOW_H - h - 4)
        box = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.screen, assets.HUD_BG, box, border_radius=4)
        pygame.draw.rect(self.screen, assets.PANEL_DIM, box, width=1,
                         border_radius=4)
        ty = y + pad
        for s in surfs:
            self.screen.blit(s, (x + pad, ty))
            ty += s.get_height() + 2

    def draw_hud(self) -> None:
        hud = pygame.Rect(0, 0, MAP_W_PX, HUD_H)
        pygame.draw.rect(self.screen, assets.HUD_BG, hud)
        player = self.world.player
        tick_of_day = self.world.tick_count % config.TICKS_PER_DAY
        speed_label = "PAUSED" if self.paused else f"{self.speed}x"
        profit = player.yesterday_profit()
        text = (f"Day {self.world.day} ({tick_of_day:02d}/"
                f"{config.TICKS_PER_DAY}) {self.world.season_name()}  "
                f"Pop {len(self.world.people)}  "
                f"Coin {fmt(player.money)}  Net {fmt(player.net_worth())}  "
                f"Yday {'-' if profit < 0 else '+'}{fmt(abs(profit))}  "
                f"CoL {fmt(self.world.cost_of_living())}/d  "
                f"{speed_label}")
        surf = self.font.render(text, True, assets.PANEL_TEXT)
        self.screen.blit(surf, (12, 10))

    def draw_message(self) -> None:
        strip = pygame.Rect(0, HUD_H + MAP_H_PX, MAP_W_PX,
                            WINDOW_H - HUD_H - MAP_H_PX)
        pygame.draw.rect(self.screen, assets.HUD_BG, strip)
        hint = ("[Space] pause  [1/2/3] speed  [M] market  [K] web  "
                "[F5] save  [F9] load  [Esc] close")
        hint_surf = self.small_font.render(hint, True, assets.PANEL_DIM)
        self.screen.blit(hint_surf,
                         (strip.right - hint_surf.get_width() - 12,
                          strip.y + 13))
        if time.monotonic() < self._message_until and self._message:
            surf = self.font.render(self._message, True, assets.GOOD)
            self.screen.blit(surf, (12, strip.y + 10))


def main(seed: int = 0, blocks=None, npcs=None, load_path=None,
         max_frames: Optional[int] = None,
         screenshot: Optional[str] = None) -> None:
    App(seed=seed, blocks=blocks, npcs=npcs, load_path=load_path).run(
        max_frames=max_frames, screenshot=screenshot)
