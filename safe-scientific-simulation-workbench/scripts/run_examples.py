"""Runs every examples/*.example.json offline and compares to its expectation."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from scientific_core.parsers import OfflineStubParser
from scientific_core.workflow import run_pipeline

def check_example(path):
    with open(path, encoding="utf-8") as fh:
        ex = json.load(fh)
    res = run_pipeline(ex["prompt"], OfflineStubParser(), ex["mode"])
    problems = []
    if res["status"] != ex["expected"]["status"]:
        problems.append(f"status {res['status']} != {ex['expected']['status']}")
    if res["n_attempts"] != ex["expected"]["attempts"]:
        problems.append(f"attempts {res['n_attempts']} != {ex['expected']['attempts']}")
    got = (res["validation"] or {}).get("settings")
    for k, v in (ex["expected"].get("settings") or {}).items():
        if got is None or abs(got[k] - v) > 1e-9:
            problems.append(f"setting {k}: {None if got is None else got[k]} != {v}")
    rules = {i["rule_id"] for i in (res["validation"] or {}).get("issues", [])}
    for r in ex["expected"].get("rules", []):
        if r not in rules:
            problems.append(f"missing rule {r}")
    return problems

def main():
    d = os.path.join(HERE, "..", "examples")
    bad = 0
    for name in sorted(os.listdir(d)):
        if name.endswith(".example.json"):
            problems = check_example(os.path.join(d, name))
            print(("FAIL " if problems else "ok   ") + name, "; ".join(problems))
            bad += bool(problems)
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
