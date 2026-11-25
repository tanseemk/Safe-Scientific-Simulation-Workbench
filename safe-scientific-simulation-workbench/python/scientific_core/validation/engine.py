"""Contract-driven validator for quantity-style scientific settings.

Generic parts (required, type, unit, range) read the contract. Model-specific
cross-field rules are passed in by the caller as callables.
"""
from __future__ import annotations

import math
from typing import Callable

from .. import contract as C
from .report import _TOKEN, Issue, ValidatedSettings, ValidationReport
from .units import normalise_unit, to_si

CrossRule = Callable[[dict], "tuple[list[Issue], dict]"]


def fmt(v: float) -> str:
    return f"{v:.10g}"


def _issue(rule_id: str, path: str, message: str, guidance: str | None = None) -> Issue:
    rule = C.rule_catalog()[rule_id]
    return Issue(path, rule_id, rule["severity"], rule["kind"], message, guidance or rule["guidance"])


def _validate_field(name: str, spec: dict, raw, aliases: dict):
    """Return (issues, normalized_entry | None)."""
    path = f"settings.{name}"
    units = ", ".join(spec["units"])
    cu = spec["canonical_unit"]
    if raw is None:
        return [_issue("REQUIRED_MISSING", path, f"{path}: required field is missing.",
                       f"Provide {spec['label'].lower()} in {units}.")], None
    if isinstance(raw, bool):
        return [_issue("TYPE_INVALID", path, f"{path}: boolean is not a number.")], None
    if isinstance(raw, (int, float)):
        shown = fmt(float(raw)) if math.isfinite(raw) else str(raw)
        return [_issue("UNIT_MISSING", path, f"{path}: supply {cu}; “{shown}” has no unit.",
                       f"Add a unit: {units}.")], None
    if not isinstance(raw, dict):
        return [_issue("TYPE_INVALID", path, f"{path}: expected an object with value and unit.")], None
    extra = sorted(set(raw) - {"value", "unit"})
    if extra:
        return [_issue("FIELD_UNKNOWN", f"{path}.{extra[0]}", f"{path}.{extra[0]}: unknown field.")], None
    if "value" not in raw:
        return [_issue("REQUIRED_MISSING", f"{path}.value", f"{path}.value: required field is missing.")], None
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [_issue("TYPE_INVALID", f"{path}.value", f"{path}.value: expected a JSON number, got {type(value).__name__}.")], None
    if not math.isfinite(value):
        return [_issue("VALUE_NOT_FINITE", f"{path}.value", f"{path}.value: {value} is not finite.")], None
    unit = raw.get("unit")
    if unit is None or (isinstance(unit, str) and not unit.strip()):
        return [_issue("UNIT_MISSING", path, f"{path}: supply {cu}; “{fmt(float(value))}” has no unit.",
                       f"Add a unit: {units}.")], None
    if not isinstance(unit, str):
        return [_issue("TYPE_INVALID", f"{path}.unit", f"{path}.unit: expected a string.")], None
    canon = normalise_unit(unit, spec["units"], aliases)
    if canon is None:
        return [_issue("UNIT_UNKNOWN", path, f"{path}: unit “{unit}” is not recognised for {spec['label'].lower()}.",
                       f"Use one of: {units}.")], None
    si = to_si(float(value), canon, spec["units"])
    issues = []
    if si < spec["min"]:
        issues.append(_issue("RANGE_MIN", path, f"{path}: {fmt(si)} {cu} is below minimum {fmt(spec['min'])} {cu}."))
    elif si > spec["max"]:
        issues.append(_issue("RANGE_MAX", path, f"{path}: {fmt(si)} {cu} exceeds maximum {fmt(spec['max'])} {cu}."))
    entry = {"field": name, "input": {"value": value, "unit": unit}, "unit_used": canon,
             "si": si, "si_unit": cu, "converted": canon != cu or canon != unit}
    return issues, entry


def validate_settings(candidate, cross_rules: list[CrossRule] | None = None) -> ValidationReport:
    """Validate a candidate settings object. Never raises on bad input."""
    ver = C.schema_version()
    ex = C.ext()
    if not isinstance(candidate, dict):
        return ValidationReport(ver, "reject", [_issue("TYPE_INVALID", "settings", "settings: expected a JSON object.")])
    issues: list[Issue] = []
    allowed_models = load_models()
    model = candidate.get("model")
    if model is None:
        issues.append(_issue("REQUIRED_MISSING", "settings.model", "settings.model: required field is missing.",
                             f"Name the model; the only approved model is {', '.join(allowed_models)}."))
    elif not isinstance(model, str) or model not in allowed_models:
        shown = model if isinstance(model, str) else type(model).__name__
        issues.append(_issue("MODEL_UNKNOWN", "settings.model", f"settings.model: “{shown}” is not an approved model.",
                             f"Only {', '.join(allowed_models)} can run."))
    known = {"model", *C.FIELD_ORDER}
    for key in sorted(set(candidate) - known):
        issues.append(_issue("FIELD_UNKNOWN", f"settings.{key}", f"settings.{key}: unknown field is not part of the schema."))

    if any(i.rule_id == "MODEL_UNKNOWN" for i in issues):
        return ValidationReport(ver, "reject", issues)

    normalized, si = [], {}
    for name, spec in C.field_specs().items():
        f_issues, entry = _validate_field(name, spec, candidate.get(name), ex["unit_aliases"])
        issues.extend(f_issues)
        if entry:
            normalized.append(entry)
            if not f_issues:
                si[name] = entry["si"]

    derived: dict = {}
    if len(si) == len(C.FIELD_ORDER) and not any(i.severity == "error" for i in issues):
        for rule in cross_rules or []:
            r_issues, r_derived = rule(si)
            issues.extend(r_issues)
            derived.update(r_derived)

    errors = [i for i in issues if i.severity == "error"]
    if any(i.kind == "reject" for i in errors):
        disposition = "reject"
    elif errors:
        disposition = "clarify"
    else:
        disposition = "valid"
    settings = None
    if disposition == "valid":
        settings = ValidatedSettings(model=model, **si, _proof=_TOKEN)
    return ValidationReport(ver, disposition, issues, normalized, derived, settings)


def load_models() -> list[str]:
    return list(C.load_contract()["properties"]["model"]["enum"])
