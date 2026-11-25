"""Command line + JSON bridge used by the Node API.

User commands:
    python -m scientific_core simulate --prompt "..." [--mode feedback] [--provider offline]
    python -m scientific_core validate settings.json
Bridge (stdin JSON -> stdout JSON), called only with a fixed argv by Node:
    python -m scientific_core bridge <contract|interpret|validate|execute|benchmark>
"""
from __future__ import annotations

import argparse
import json
import sys

from . import contract as C
from .benchmark import run_benchmark
from .parsers import ProviderError, OpenAICompatibleParser, get_parser
from .workflow import execute_settings, run_pipeline, validate_candidate

MAX_PROMPT = 2000


def op_contract(_: dict) -> dict:
    return {"schema_version": C.schema_version(), "model": C.ext()["model"], "fields": C.field_metadata(),
            "max_steps": C.ext()["max_steps"], "retry_cap": C.ext()["retry_cap"], "rules": C.ext()["rules"],
            "approved_models": list(C.load_contract()["properties"]["model"]["enum"]),
            "providers": {"offline": {"available": True, "network": False},
                          "live": {"available": OpenAICompatibleParser.configured(), "network": True}}}


def op_interpret(req: dict) -> dict:
    prompt = req.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        return {"error": {"code": "bad_prompt", "message": f"prompt must be 1-{MAX_PROMPT} characters"}}
    mode, provider = req.get("mode", "baseline"), req.get("provider", "offline")
    if mode not in ("baseline", "feedback") or provider not in ("offline", "live"):
        return {"error": {"code": "bad_request", "message": "mode must be baseline|feedback; provider offline|live"}}
    return run_pipeline(prompt, get_parser(provider), mode, execute=False)


def op_execute(req: dict) -> dict:
    cand = req.get("settings")
    if not isinstance(cand, dict):
        return {"error": {"code": "bad_request", "message": "settings object required"}}
    return execute_settings(cand, req.get("provenance") if isinstance(req.get("provenance"), dict) else None)


def op_validate(req: dict) -> dict:
    cand = req.get("settings")
    if not isinstance(cand, dict):
        return {"error": {"code": "bad_request", "message": "settings object required"}}
    return validate_candidate(cand).to_dict()


def op_benchmark(req: dict) -> dict:
    res = run_benchmark("prompts/v1.json", "both", int(req.get("seed", 42)), "results", "offline", 1,
                        command="python -m scientific_core.benchmark --suite prompts/v1.json --mode both --seed 42 --out results/")
    return {"outdir": res["outdir"], "aggregate": res["aggregate"]}


OPS = {"contract": op_contract, "interpret": op_interpret, "validate": op_validate, "execute": op_execute, "benchmark": op_benchmark}


def bridge(op: str) -> int:
    if op not in OPS:
        print(json.dumps({"error": {"code": "unknown_op", "message": op}}))
        return 2
    try:
        data = sys.stdin.read()
        req = json.loads(data) if data.strip() else {}
        out = OPS[op](req if isinstance(req, dict) else {})
    except ProviderError as exc:
        out = {"error": {"code": f"provider_{exc.kind}", "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001
        out = {"error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(prog="scientific_core")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simulate", help="parse, validate, run and check one request")
    s.add_argument("--prompt", required=True)
    s.add_argument("--mode", choices=["baseline", "feedback"], default="feedback")
    s.add_argument("--provider", choices=["offline", "live"], default="offline")
    v = sub.add_parser("validate", help="validate a settings JSON file")
    v.add_argument("file")
    b = sub.add_parser("bridge")
    b.add_argument("op")
    a = ap.parse_args(argv)
    if a.cmd == "bridge":
        return bridge(a.op)
    if a.cmd == "validate":
        with open(a.file, encoding="utf-8") as fh:
            rep = validate_candidate(json.load(fh))
        print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
        return 0 if rep.valid else 1
    try:
        res = run_pipeline(a.prompt, get_parser(a.provider), a.mode)
    except ProviderError as exc:
        print(f"provider error ({exc.kind}): {exc}", file=sys.stderr)
        return 2
    ex = res.pop("execution", None)
    if ex and ex.get("series"):
        ex["series"] = {k: (v if k in ("stride", "total_samples") else f"[{len(v)} values]") for k, v in ex["series"].items()}
    res["execution"] = ex
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["status"] == "executed" else 1
