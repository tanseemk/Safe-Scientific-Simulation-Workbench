"""Unit normalisation for a small declared set of units."""
from __future__ import annotations


def normalise_unit(unit: str, allowed: dict, aliases: dict) -> str | None:
    """Return the canonical spelling of `unit` if it is declared, else None."""
    token = unit.strip()
    if token in allowed:
        return token
    mapped = aliases.get(token) or aliases.get(token.lower())
    if mapped in allowed:
        return mapped
    return None


def to_si(value: float, unit: str, allowed: dict) -> float:
    """Convert to the field's canonical unit; 12 significant digits remove binary noise."""
    return float(f"{value * allowed[unit]:.12g}")
