"""Minimal immediate-mode-ish button helper."""

from __future__ import annotations

from typing import Callable, List, Optional

import pygame

from . import assets


class Button:
    def __init__(self, rect: pygame.Rect, label: str,
                 callback: Callable[[], None], enabled: bool = True):
        self.rect = rect
        self.label = label
        self.callback = callback
        self.enabled = enabled


class ButtonBank:
    """Buttons are re-registered every frame during draw; clicks are matched
    against the most recently drawn frame."""

    def __init__(self, font: pygame.font.Font):
        self.font = font
        self.buttons: List[Button] = []

    def begin_frame(self) -> None:
        self.buttons.clear()

    def draw(self, screen: pygame.Surface, rect: pygame.Rect, label: str,
             callback: Callable[[], None], enabled: bool = True) -> None:
        self.buttons.append(Button(rect, label, callback, enabled))
        hover = enabled and rect.collidepoint(pygame.mouse.get_pos())
        color = (assets.BUTTON_DISABLED if not enabled
                 else assets.BUTTON_HOVER if hover else assets.BUTTON_BG)
        pygame.draw.rect(screen, color, rect, border_radius=4)
        pygame.draw.rect(screen, assets.PANEL_DIM, rect, width=1,
                         border_radius=4)
        text_color = assets.PANEL_TEXT if enabled else assets.PANEL_DIM
        text = self.font.render(label, True, text_color)
        screen.blit(text, text.get_rect(center=rect.center))

    def handle_click(self, pos) -> bool:
        for b in self.buttons:
            if b.enabled and b.rect.collidepoint(pos):
                b.callback()
                return True
        return False
