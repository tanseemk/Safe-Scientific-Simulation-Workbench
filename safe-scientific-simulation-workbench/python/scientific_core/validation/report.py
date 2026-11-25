"""Machine-stable validation report objects."""
from __future__ import annotations

from dataclasses import dataclass, field

_TOKEN = object()  # private proof that settings came from the validator


@dataclass
class Issue:
    path: str
    rule_id: str
    severity: str  # "error" | "warning"
    kind: str      # "clarify" | "reject" | "warn" | "output"
    message: str
    guidance: str

    def to_dict(self) -> dict:
        return {"path": self.path, "rule_id": self.rule_id, "severity": self.severity,
                "kind": self.kind, "message": self.message, "guidance": self.guidance}


@dataclass(frozen=True)
class ValidatedSettings:
    """Typed SI settings. Only `validate_settings` can mint one."""
    model: str
    mass: float
    stiffness: float
    damping: float
    x0: float
    v0: float
    duration: float
    dt: float
    _proof: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._proof is not _TOKEN:
            raise PermissionError("ValidatedSettings can only be created by the validator")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("model", "mass", "stiffness", "damping", "x0", "v0", "duration", "dt")}


def is_validated(obj) -> bool:
    return isinstance(obj, ValidatedSettings) and obj._proof is _TOKEN


@dataclass
class ValidationReport:
    schema_version: str
    disposition: str  # "valid" | "clarify" | "reject"
    issues: list = field(default_factory=list)
    normalized: list = field(default_factory=list)
    derived: dict = field(default_factory=dict)
    settings: ValidatedSettings | None = None

    @property
    def valid(self) -> bool:
        return self.disposition == "valid"

    def errors(self) -> list:
        return [i for i in self.issues if i.severity == "error"]

    def rule_ids(self) -> list[str]:
        return [i.rule_id for i in self.issues]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "valid": self.valid,
            "disposition": self.disposition,
            "issues": [i.to_dict() for i in self.issues],
            "normalized": self.normalized,
            "derived": self.derived,
            "settings": self.settings.to_dict() if self.settings else None,
        }
