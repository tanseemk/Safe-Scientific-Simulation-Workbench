import copy
from scientific_core.models import cross_rules_for
from scientific_core.validation import validate_settings

BASE = {
    "model": "damped_spring",
    "mass": {"value": 1, "unit": "kg"}, "stiffness": {"value": 20, "unit": "N/m"}, "damping": {"value": 0.8, "unit": "N·s/m"},
    "x0": {"value": 0.1, "unit": "m"}, "v0": {"value": 0, "unit": "m/s"}, "duration": {"value": 5, "unit": "s"}, "dt": {"value": 0.01, "unit": "s"},
}


def cand(**over):
    c = copy.deepcopy(BASE)
    for k, v in over.items():
        if v is Ellipsis:
            c.pop(k, None)
        else:
            c[k] = v
    return c


def validate(c):
    return validate_settings(c, cross_rules_for("damped_spring"))


def rules(report):
    return [i.rule_id for i in report.issues]


class ScriptedParser:
    """Parser returning pre-set candidates; used to exercise the controllers deterministically."""
    name, version, deterministic, network = "scripted", "0", True, False

    def __init__(self, candidates, flags=None):
        self.candidates, self.calls, self.feedbacks = list(candidates), 0, []
        self.flags = flags or []

    def parse(self, prompt, feedback=None, previous=None, attempt=1):
        self.feedbacks.append(feedback)
        item = self.candidates[min(self.calls, len(self.candidates) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item), {"provenance": {}, "flags": self.flags, "parser": self.name, "attempt": attempt}
