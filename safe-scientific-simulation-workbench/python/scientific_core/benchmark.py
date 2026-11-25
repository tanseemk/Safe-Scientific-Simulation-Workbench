"""Paired baseline-vs-feedback benchmark on the frozen prompt suite.

    python -m scientific_core.benchmark --suite prompts/v1.json --mode both --seed 42 --out results/

Outputs (under <out>/<provider>/): raw.jsonl, summary.csv, summary.json,
per_prompt.csv, protocol.json, report.md. Nothing is hand-written: every number
is computed from raw.jsonl.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from . import contract as C
from .models import STATS, reset_stats
from .parsers import ProviderError, get_parser, OpenAICompatibleParser
from .workflow import run_pipeline

CAVEAT = ("Pilot fixture: 10 prompts. Percentages are descriptive and not generalizable. "
          "The offline stub is a deterministic test fixture for the harness, not evidence about language-model behaviour.")


def resolve_suite(path: str) -> Path:
    p = Path(path)
    for cand in (p, C.CONTRACT_DIR / p, C.ROOT / p):
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"suite not found: {path}")


def percentile(values: list[float], q: float):
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]


def gold_match(settings: dict | None, gold: dict | None) -> bool:
    if not settings or not gold:
        return False
    return all(math.isclose(settings[k], v, rel_tol=1e-9, abs_tol=1e-12) for k, v in gold.items())


def run_case(entry: dict, parser, mode: str, repeat: int) -> dict:
    v_before = STATS["violations"]
    c_before = STATS["calls"]
    res = run_pipeline(entry["prompt"], parser, mode, execute=True)
    solver_calls = STATS["calls"] - c_before
    violations = STATS["violations"] - v_before
    status = res["status"]
    exp = entry["expected"]
    rules = [i["rule_id"] for i in (res["validation"] or {}).get("issues", [])]
    settings = (res["validation"] or {}).get("settings")
    failed = (res["execution"] or {}).get("checks_failed", []) if res["execution"] else []
    if exp == "execute":
        success = status == "executed" and gold_match(settings, entry.get("gold")) and not (entry.get("expected_checks_pass") and failed)
    elif exp == "clarify":
        success = status == "clarify" and solver_calls == 0
    else:
        success = status == "rejected" and solver_calls == 0
    rules_ok = all(r in rules for r in entry.get("expected_rules", []))
    err_class = (res["error"] or {}).get("class")
    return {
        "suite_prompt_id": entry["id"], "type": entry["type"], "expected": exp, "mode": mode, "repeat": repeat,
        "provider": res["provider"], "status": status, "success": bool(success), "expected_rules_ok": rules_ok,
        "flags": res["flags"], "flags_ok": all(f in res["flags"] for f in entry.get("expected_flags", [])),
        "attempts": res["n_attempts"], "retries": res["retries"], "stop_reason": res["stop_reason"],
        "cap_exhausted": res["cap_exhausted"],
        "invalid_candidates": sum(1 for a in res["attempts"] if a.get("disposition") in ("clarify", "reject")),
        "solver_calls": solver_calls, "safety_violations": violations,
        "error_class": err_class, "final_rule_ids": sorted(set(rules)), "checks_failed": failed,
        "timing_ms": res["timing_ms"], "settings": settings,
    }


def aggregate(rows: list[dict]) -> dict:
    out = {}
    for mode in sorted({r["mode"] for r in rows}):
        rs = [r for r in rows if r["mode"] == mode]
        n = len(rs)
        att = sum(r["attempts"] for r in rs)
        invalid = sum(r["invalid_candidates"] for r in rs)
        exp_reject = [r for r in rs if r["expected"] == "reject"]
        exp_clar = [r for r in rs if r["expected"] == "clarify"]
        solver_runs = [r for r in rs if r["solver_calls"] > 0]
        retries = [r["retries"] for r in rs]
        err = {}
        for r in rs:
            if r["error_class"]:
                err[r["error_class"]] = err.get(r["error_class"], 0) + 1
        def tm(k):
            src = solver_runs if k == "solver" else rs  # solver time only where the solver actually ran
            return [r["timing_ms"][k] for r in src]
        out[mode] = {
            "task_success": {"num": sum(r["success"] for r in rs), "den": n},
            "invalid_candidates_per_attempt": {"num": invalid, "den": att},
            "invalid_requests_safely_rejected": {"num": sum(1 for r in exp_reject if r["success"]), "den": len(exp_reject)},
            "retries": {"total": sum(retries), "mean": sum(retries) / n if n else None,
                        "distribution": {str(k): retries.count(k) for k in sorted(set(retries))},
                        "zero_retry_cases": retries.count(0), "cap_exhausted": {"num": sum(r["cap_exhausted"] for r in rs), "den": n}},
            "execution_errors": {"solver_exceptions": {"num": err.get("solver_exception", 0), "den": len(solver_runs)},
                                 "by_class": err},
            "safety_violations": {"count": sum(r["safety_violations"] for r in rs), "den_runs": n},
            "clarification_quality": {"num": sum(1 for r in exp_clar if r["success"] and r["expected_rules_ok"]), "den": len(exp_clar)},
            "response_time_ms": {k: {"n": len(tm(k)), "median": percentile(tm(k), 0.5), "p95": percentile(tm(k), 0.95)}
                                 for k in ("total", "parse", "validation", "solver")},
        }
    return out


def write_outputs(rows, agg, protocol, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "raw.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    with open(outdir / "summary.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"protocol": protocol, "caveat": CAVEAT, "aggregate": agg}, fh, indent=2, ensure_ascii=False)
    with open(outdir / "summary.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["mode", "metric", "numerator", "denominator", "value"])
        for mode, a in agg.items():
            def frac(name, d):
                w.writerow([mode, name, d["num"], d["den"], f"{d['num'] / d['den']:.4f}" if d["den"] else ""])
            frac("task_success", a["task_success"])
            frac("invalid_candidates_per_attempt", a["invalid_candidates_per_attempt"])
            frac("invalid_requests_safely_rejected", a["invalid_requests_safely_rejected"])
            frac("clarification_quality", a["clarification_quality"])
            frac("cap_exhausted", a["retries"]["cap_exhausted"])
            frac("solver_exceptions", a["execution_errors"]["solver_exceptions"])
            w.writerow([mode, "retries_total", a["retries"]["total"], a["task_success"]["den"], f"{a['retries']['mean']:.4f}"])
            w.writerow([mode, "safety_violations", a["safety_violations"]["count"], a["safety_violations"]["den_runs"], a["safety_violations"]["count"]])
            for k, t in a["response_time_ms"].items():
                if t["n"]:
                    w.writerow([mode, f"time_{k}_median_ms", "", t["n"], f"{t['median']:.4f}"])
                    w.writerow([mode, f"time_{k}_p95_ms", "", t["n"], f"{t['p95']:.4f}"])
    with open(outdir / "per_prompt.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["prompt_id", "type", "expected", "mode", "repeat", "status", "success", "attempts", "retries", "stop_reason", "rule_ids", "total_ms"])
        for r in rows:
            w.writerow([r["suite_prompt_id"], r["type"], r["expected"], r["mode"], r["repeat"], r["status"], int(r["success"]),
                        r["attempts"], r["retries"], r["stop_reason"], "|".join(r["final_rule_ids"]), f"{r['timing_ms']['total']:.4f}"])
    with open(outdir / "protocol.json", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(protocol, fh, indent=2, ensure_ascii=False)
    with open(outdir / "report.md", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_report(rows, agg, protocol))


def render_report(rows, agg, protocol) -> str:
    L = [f"# S3W benchmark report ({protocol['provider']})", "", f"> {CAVEAT}", "",
         f"- Suite: `{protocol['suite']['name']}` v{protocol['suite']['version']} (sha256 `{protocol['suite']['sha256'][:16]}…`), {protocol['suite']['n_prompts']} prompts × {protocol['repeats']} repeat(s)",
         f"- Parser: `{protocol['parser']}`; retry cap {protocol['retry_cap']}; seed {protocol['seed']} (controls prompt order only)",
         f"- Generated {protocol['generated_at']}; Python {protocol['python']}; commit {protocol['git_commit'] or 'n/a'}",
         f"- Command: `{protocol['command']}`", f"- Timer boundary: {protocol['timer_boundary']}", "",
         "| Metric | " + " | ".join(agg) + " |", "|---|" + "---|" * len(agg)]
    def cell(a, key, path=None):
        d = a[key] if path is None else a[key][path]
        return f"{d['num']}/{d['den']}" + (f" ({d['num'] / d['den']:.0%})" if d["den"] else "")
    rows_def = [("Task success", lambda a: cell(a, "task_success")),
                ("Invalid candidates / parser attempt", lambda a: cell(a, "invalid_candidates_per_attempt")),
                ("Invalid requests safely rejected", lambda a: cell(a, "invalid_requests_safely_rejected")),
                ("Clarification quality", lambda a: cell(a, "clarification_quality")),
                ("Retries (total; mean)", lambda a: f"{a['retries']['total']}; {a['retries']['mean']:.2f}"),
                ("Retry distribution", lambda a: json.dumps(a["retries"]["distribution"])),
                ("Cap exhausted", lambda a: cell(a["retries"], "cap_exhausted")),
                ("Solver exceptions / solver runs", lambda a: cell(a["execution_errors"], "solver_exceptions")),
                ("Execution/provider errors by class", lambda a: json.dumps(a["execution_errors"]["by_class"]) ),
                ("Safety violations (raw count; target 0)", lambda a: str(a["safety_violations"]["count"])),
                ("Total time median / p95 (ms)", lambda a: f"{a['response_time_ms']['total']['median']:.3f} / {a['response_time_ms']['total']['p95']:.3f}"),
                ("Validation time median / p95 (ms)", lambda a: f"{a['response_time_ms']['validation']['median']:.3f} / {a['response_time_ms']['validation']['p95']:.3f}"),
                ("Solver time median / p95 (ms), solver runs only", lambda a: (f"{a['response_time_ms']['solver']['median']:.3f} / {a['response_time_ms']['solver']['p95']:.3f} (n={a['response_time_ms']['solver']['n']})") if a['response_time_ms']['solver']['n'] else "n/a")]
    for label, fn in rows_def:
        L.append(f"| {label} | " + " | ".join(fn(agg[m]) for m in agg) + " |")
    L += ["", "## Per prompt", "", "| Prompt | Type | Expected | " + " | ".join(f"{m} outcome" for m in agg) + " |", "|---|---|---|" + "---|" * len(agg)]
    ids = []
    for r in rows:
        if r["suite_prompt_id"] not in ids:
            ids.append(r["suite_prompt_id"])
    for pid in sorted(ids):
        sub = [r for r in rows if r["suite_prompt_id"] == pid]
        cells = []
        for m in agg:
            ms = [r for r in sub if r["mode"] == m]
            ok = sum(r["success"] for r in ms)
            cells.append(f"{ms[0]['status']} / {'success' if ok == len(ms) else f'{ok}/{len(ms)} success'} / {ms[0]['attempts']} attempt(s)")
        L.append(f"| {pid} | {sub[0]['type']} | {sub[0]['expected']} | " + " | ".join(cells) + " |")
    L += ["", "Live-provider results: " + ("included above." if protocol["provider"] == "live" else "**unavailable** (not run). Offline and live latency are never mixed."), ""]
    return "\n".join(L)


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=C.ROOT, capture_output=True, text=True, timeout=5, check=True).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def run_benchmark(suite: str, mode: str, seed: int, out: str, provider: str = "offline", repeats: int = 1, command: str | None = None) -> dict:
    suite_path = resolve_suite(suite)
    raw = suite_path.read_bytes()
    spec = json.loads(raw)
    parser = get_parser(provider)
    if provider == "live" and not OpenAICompatibleParser.configured():
        raise ProviderError("not_configured", "live results unavailable: S3W_LLM_API_KEY is not set")
    modes = ["baseline", "feedback"] if mode == "both" else [mode]
    rng = random.Random(seed)
    rows = []
    reset_stats()
    for rep in range(1, repeats + 1):
        order = list(spec["prompts"])
        rng.shuffle(order)
        for entry in order:
            for m in modes:  # paired: same prompt, parser, environment, back-to-back
                rows.append(run_case(entry, parser, m, rep))
    rows.sort(key=lambda r: (r["mode"], r["suite_prompt_id"], r["repeat"]))
    agg = aggregate(rows)
    protocol = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "provider": provider, "parser": f"{parser.name} v{parser.version}",
        "suite": {"name": spec["suite"], "version": spec["version"], "sha256": hashlib.sha256(raw).hexdigest(), "n_prompts": len(spec["prompts"])},
        "schema_version": C.schema_version(), "retry_cap": C.ext()["retry_cap"], "seed": seed, "repeats": repeats, "modes": modes,
        "python": platform.python_version(), "platform": platform.platform(), "scientific_core": __version__, "git_commit": git_commit(),
        "command": command or " ".join(["python", "-m", "scientific_core.benchmark"] + sys.argv[1:]),
        "timer_boundary": "total_ms runs from the start of the first parser call to the end of the last validation/solver step of a case; it excludes process start-up and result serialisation and includes provider latency in live mode.",
        "seed_note": "The seed fixes prompt order only; the live adapter does not forward it to the provider.",
    }
    outdir = Path(out) / provider
    write_outputs(rows, agg, protocol, outdir)
    return {"outdir": str(outdir), "aggregate": agg, "protocol": protocol}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="scientific_core.benchmark")
    ap.add_argument("--suite", default="prompts/v1.json")
    ap.add_argument("--mode", choices=["baseline", "feedback", "both"], default="both")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="results/")
    ap.add_argument("--provider", choices=["offline", "live"], default="offline")
    ap.add_argument("--repeats", type=int, default=1)
    a = ap.parse_args(argv)
    try:
        res = run_benchmark(a.suite, a.mode, a.seed, a.out, a.provider, a.repeats)
    except ProviderError as exc:
        print(f"UNAVAILABLE: {exc}", file=sys.stderr)
        return 2
    for mode, agg in res["aggregate"].items():
        ts = agg["task_success"]
        print(f"{mode:9s} task success {ts['num']}/{ts['den']}  retries {agg['retries']['total']}  safety violations {agg['safety_violations']['count']}")
    print(f"wrote {res['outdir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
