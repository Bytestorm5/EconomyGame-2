#!/usr/bin/env python3
"""Launch the game.

Usage:
    python run_game.py [--seed N] [--frames N --screenshot out.png]

--frames/--screenshot run the UI for N frames then save a screenshot and
exit; handy for smoke-testing rendering without a display (set
SDL_VIDEODRIVER=dummy).
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Village Economy")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--frames", type=int, default=None)
    parser.add_argument("--screenshot", type=str, default=None)
    args = parser.parse_args()

    from village.ui.app import main as run
    run(seed=args.seed, max_frames=args.frames, screenshot=args.screenshot)


if __name__ == "__main__":
    main()
