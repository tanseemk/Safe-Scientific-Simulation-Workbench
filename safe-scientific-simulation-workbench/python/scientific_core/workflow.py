"""Baseline and bounded-feedback controllers around parse -> validate -> solve -> check."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from . import contract as C
from .models import SafetyViolation, cross_rules_for, run_model
from .parsers import ProviderError
from .validation import validate_settings

MODEL_ID = "damped_spring"


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000.0


def validate_candidate(candidate) -> object:
    return validate_settings(candidate, cross_rules_for(MODEL_ID))


def run_id_for(settings: dict) -> str:
    blob = json.dumps({"s": settings, "schema": C.schema_version(), "solver": "RK4"}, sort_keys=True)
    return "S3W-" + hashlib.sha256(blob.encode()).hexdigest()[:10].upper()


def downsample(result, max_points: int = 4000) -> dict:
    n = len(result.t)
    stride = max(1, -(-n // max_points))
    idx = list(range(0, n, stride))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return {"t": [result.t[i] for i in idx], "x": [result.x[i] for i in idx], "v": [result.v[i] for i in idx],
            "energy": [result.energy[i] for i in idx], "stride": stride, "total_samples": n}


def execute_validated(report) -> dict:
    """Solve + check a *valid* report. Solver exceptions are captured, not retried."""
    t0 = time.perf_counter()
    try:
        result, checks = run_model(MODEL_ID, report.settings)
    except SafetyViolation:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded as an execution error
        return {"ok": False, "error": {"class": "solver_exception", "message": f"{type(exc).__name__}: {exc}"},
                "solver_ms": _ms(t0)}
    solver_ms = _ms(t0)
    from .models.damped_spring import checks_failed, regime
    return {"ok": True, "solver_ms": solver_ms, "checks": checks, "checks_failed": [c["id"] for c in checks_failed(checks)],
            "series": downsample(result), "n_steps": result.n_steps, "dt_effective": result.dt_effective,
            "summary": {**regime(report.settings), "max_abs_x": max(abs(v) for v in result.x),
                        "final_x": result.x[-1], "final_energy": result.energy[-1], "initial_energy": result.energy[0]}}


def _record(settings_dict: dict, mode: str, provider: str) -> dict:
    return {"run_id": run_id_for(settings_dict), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema_version": C.schema_version(), "solver": {"method": "RK4", "model": MODEL_ID},
            "mode": mode, "provider": provider}


def run_pipeline(prompt: str, parser, mode: str = "baseline", execute: bool = True, retry_cap: int | None = None) -> dict:
    """Interpret a prompt (and optionally run it). mode: 'baseline' | 'feedback'."""
    cap = C.ext()["retry_cap"] if retry_cap is None else retry_cap
    max_attempts = 1 if mode == "baseline" else cap + 1
    t_start = time.perf_counter()
    attempts, feedback, previous = [], None, None
    status, stop_reason, final_report, final_exec, error, flags = None, None, None, None, None, []
    validation_ms = solver_ms = parse_ms = 0.0

    for n in range(1, max_attempts + 1):
        att = {"attempt": n, "feedback_in": feedback}
        t0 = time.perf_counter()
        try:
            candidate, meta = parser.parse(prompt, feedback=feedback, previous=previous, attempt=n)
        except ProviderError as exc:
            att.update(parse_ms=_ms(t0), error={"class": f"provider_{exc.kind}", "message": str(exc)})
            attempts.append(att)
            status, error, stop_reason = "provider_error", att["error"], "provider_error"
            parse_ms += att["parse_ms"]
            break
        att["parse_ms"] = _ms(t0)
        parse_ms += att["parse_ms"]
        flags = meta.get("flags", flags)
        t1 = time.perf_counter()
        report = validate_candidate(candidate)
        att["validation_ms"] = _ms(t1)
        validation_ms += att["validation_ms"]
        att.update(candidate=candidate, provenance=meta.get("provenance", {}), disposition=report.disposition,
                   issues=[i.to_dict() for i in report.issues], parser=meta.get("parser"))
        attempts.append(att)
        final_report = report
        unchanged = previous is not None and previous["candidate"] == candidate

        if report.valid:
            if not execute:
                status, stop_reason = "valid", "valid"
                break
            ex = execute_validated(report)
            att["solver_ms"] = ex["solver_ms"]
            solver_ms += ex["solver_ms"]
            final_exec = ex
            if not ex["ok"]:
                status, error, stop_reason = "solver_error", ex["error"], "solver_error"
                break
            if not ex["checks_failed"]:
                status, stop_reason = "executed", "success"
                break
            status = "checks_failed"
            feedback = [{"path": "result", "rule_id": cid, "message": f"output check failed: {cid}"} for cid in ex["checks_failed"]]
        else:
            status = "clarify" if report.disposition == "clarify" else "rejected"
            feedback = att["issues"]
            if unchanged:
                stop_reason = "no_change"
                break
        previous = {"candidate": candidate, "provenance": meta.get("provenance", {})}
        if n == max_attempts:
            stop_reason = "baseline_single_attempt" if mode == "baseline" else "cap_exhausted"

    total_ms = _ms(t_start)
    settings_dict = final_report.settings.to_dict() if final_report is not None and final_report.settings else None
    last = attempts[-1] if attempts else {}
    return {
        "prompt": prompt, "mode": mode, "provider": getattr(parser, "name", "?"), "status": status,
        "stop_reason": stop_reason, "attempts": attempts, "n_attempts": len(attempts), "retries": max(0, len(attempts) - 1),
        "cap_exhausted": stop_reason == "cap_exhausted", "flags": flags,
        "candidate": last.get("candidate"), "provenance": last.get("provenance", {}),
        "validation": final_report.to_dict() if final_report is not None else None,
        "execution": final_exec, "error": error,
        "timing_ms": {"total": total_ms, "parse": parse_ms, "validation": validation_ms, "solver": solver_ms},
        "record": _record(settings_dict, mode, getattr(parser, "name", "?")) if settings_dict else None,
    }


def execute_settings(candidate: dict, provenance: dict | None = None, provider: str = "user-confirmed") -> dict:
    """Validate user-reviewed settings and run them. Invalid settings never reach the solver."""
    t0 = time.perf_counter()
    report = validate_candidate(candidate)
    validation_ms = _ms(t0)
    out = {"validation": report.to_dict(), "execution": None, "provenance": provenance or {}, "record": None,
           "status": "clarify" if report.disposition == "clarify" else "rejected"}
    if not report.valid:
        out["timing_ms"] = {"validation": validation_ms, "solver": 0.0, "total": validation_ms}
        return out
    ex = execute_validated(report)
    out["execution"] = ex
    out["status"] = "executed" if ex["ok"] and not ex["checks_failed"] else ("solver_error" if not ex["ok"] else "checks_failed")
    out["timing_ms"] = {"validation": validation_ms, "solver": ex["solver_ms"], "total": validation_ms + ex["solver_ms"]}
    rec = _record(report.settings.to_dict(), "user-confirmed", provider)
    rec.update(settings=report.settings.to_dict(), normalized=report.normalized, provenance=provenance or {},
               derived=report.derived, checks=ex.get("checks"), timing_ms=out["timing_ms"])
    out["record"] = rec
    return out
