"""Money is integer cents everywhere in the sim; content JSON stays in
dollars for readability. Convert at the boundary, format for the UI."""

from __future__ import annotations


def cents(dollars: float) -> int:
    return int(round(dollars * 100))


def fmt(c: float) -> str:
    """$1,234.56 (cents -> display)."""
    return f"${c / 100:,.2f}"
