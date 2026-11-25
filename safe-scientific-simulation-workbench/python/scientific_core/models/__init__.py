"""Approved model registry: the only path from settings to a solver."""
from __future__ import annotations

from ..validation.report import ValidatedSettings, is_validated
from . import damped_spring

APPROVED = {
    "damped_spring": {
        "solve": damped_spring.simulate,
        "cross_rules": [damped_spring.cross_rules],
        "check": damped_spring.check_output,
    }
}

# Observable counters used by the benchmark and the safety tests.
STATS = {"calls": 0, "violations": 0}


class SafetyViolation(Exception):
    """Raised when something other than validated settings reaches the registry."""


def reset_stats() -> None:
    STATS["calls"] = 0
    STATS["violations"] = 0


def cross_rules_for(model_id: str) -> list:
    return APPROVED[model_id]["cross_rules"]


def run_model(model_id: str, settings):
    """Run an approved model. Refuses anything not minted by the validator."""
    if not is_validated(settings):
        STATS["violations"] += 1
        raise SafetyViolation("solver invoked without validated settings")
    if model_id not in APPROVED or settings.model != model_id:
        STATS["violations"] += 1
        raise SafetyViolation(f"unsupported model invocation: {model_id!r}")
    STATS["calls"] += 1
    entry = APPROVED[model_id]
    result = entry["solve"](settings)
    return result, entry["check"](settings, result)


__all__ = ["APPROVED", "STATS", "SafetyViolation", "run_model", "reset_stats", "cross_rules_for", "ValidatedSettings"]
