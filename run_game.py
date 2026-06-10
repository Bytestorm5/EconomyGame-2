#!/usr/bin/env python3
"""Launch the game.

Usage:
    python run_game.py [--seed N] [--blocks WxH] [--npcs N]
                       [--frames N --screenshot out.png]

--blocks controls the village size as a WxH grid of blocks (4 parcels per
block); --npcs the population (player excluded). --frames/--screenshot run
the UI for N frames then save a screenshot and exit; handy for smoke-testing
rendering without a display (set SDL_VIDEODRIVER=dummy).
"""

from __future__ import annotations

import argparse


def parse_blocks(text):
    w, _, h = text.lower().partition("x")
    return (int(w), int(h))


def main() -> None:
    parser = argparse.ArgumentParser(description="Village Economy")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--blocks", type=parse_blocks, default=None,
                        help="village size in blocks, e.g. 4x3")
    parser.add_argument("--npcs", type=int, default=None)
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--screenshot", type=str, default=None)
    args = parser.parse_args()

    from village.ui.app import main as run
    run(seed=args.seed, blocks=args.blocks, npcs=args.npcs,
        max_frames=args.frames, screenshot=args.screenshot)


if __name__ == "__main__":
    main()
