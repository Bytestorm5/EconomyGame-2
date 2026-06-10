"""Asset lookup with solid-color placeholder fallbacks.

Every sprite the game wants is requested through :func:`get_tile`. If a PNG
with the matching name exists in ``assets/``, it is loaded and scaled;
otherwise a flat colored block is generated. This means artists can drop in
real art file-by-file without code changes. See ASSETS.md for the full list
of art the game asks for.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

import pygame

ASSET_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "assets")

# UI palette (placeholder "assets" for terrain/chrome).
GRASS = (88, 129, 87)
ROAD = (146, 137, 120)
PLOT_FILL = (167, 138, 100)
PLOT_BORDER = (96, 76, 51)
PLAYER_BORDER = (240, 196, 25)
SELECT_BORDER = (235, 235, 235)
PANEL_BG = (38, 35, 31)
PANEL_TEXT = (230, 225, 215)
PANEL_DIM = (160, 152, 140)
BUTTON_BG = (72, 66, 58)
BUTTON_HOVER = (95, 88, 77)
BUTTON_DISABLED = (50, 47, 43)
HUD_BG = (24, 22, 20)
GOOD = (140, 200, 120)
BAD = (220, 120, 100)

_cache: Dict[Tuple[str, int, int], pygame.Surface] = {}


def get_tile(name: str, size: Tuple[int, int],
             fallback_color: Tuple[int, int, int]) -> pygame.Surface:
    """Return the sprite ``assets/<name>.png`` scaled to size, or a solid
    color block if the file doesn't exist (the current placeholder art)."""
    key = (name, size[0], size[1])
    if key in _cache:
        return _cache[key]
    path = os.path.join(ASSET_DIR, f"{name}.png")
    if os.path.exists(path):
        surf = pygame.transform.smoothscale(
            pygame.image.load(path).convert_alpha(), size)
    else:
        surf = pygame.Surface(size)
        surf.fill(fallback_color)
    _cache[key] = surf
    return surf
