"""Loads the canonical contract (JSON Schema + x-s3w extensions)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(os.environ.get("S3W_ROOT", Path(__file__).resolve().parents[2]))
CONTRACT_DIR = ROOT / "packages" / "contracts"
SCHEMA_PATH = CONTRACT_DIR / "schema" / "settings.v1.json"
PROMPTS_PATH = CONTRACT_DIR / "prompts" / "v1.json"

FIELD_ORDER = ["mass", "stiffness", "damping", "x0", "v0", "duration", "dt"]


@lru_cache(maxsize=1)
def load_contract() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def ext() -> dict:
    return load_contract()["x-s3w"]


def field_specs() -> dict:
    props = load_contract()["properties"]
    return {name: props[name]["x-s3w"] for name in FIELD_ORDER}


def rule_catalog() -> dict:
    return {r["id"]: r for r in ext()["rules"]}


def schema_version() -> str:
    return ext()["schema_version"]


def field_metadata() -> list[dict]:
    """UI/runtime field metadata generated from the contract."""
    out = []
    for name, spec in field_specs().items():
        out.append({
            "name": name, "label": spec["label"], "symbol": spec["symbol"],
            "canonical_unit": spec["canonical_unit"], "units": list(spec["units"]),
            "min": spec["min"], "max": spec["max"], "default": spec["default"],
            "description": spec["description"],
        })
    return out
