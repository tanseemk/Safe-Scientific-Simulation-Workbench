# HTTP API (Node.js)

All bodies are JSON (`Content-Type: application/json`), limited to 32 KB. Prompts are limited to 2,000 characters.

| Route | Purpose |
|---|---|
| GET /api/health | Python availability, provider availability, schema version. |
| GET /api/contract | Field metadata (units, bounds, defaults), rule catalog, approved models — generated from the schema. |
| GET /api/prompts | The fixed example prompts (no gold labels). |
| POST /api/interpret | `{prompt, mode: baseline\|feedback, provider: offline\|live}` → attempts trace, candidate, provenance, validation. Never runs the solver. |
| POST /api/validate | `{settings}` → validation report only. |
| POST /api/run | `{settings, provenance}` → validates again, then solves and checks. Returns **422** with the report (and no solver call) if validation fails. |
| GET /api/runs/:id | A stored run record from `runs/`. |
| GET /api/evaluation | Offline benchmark summary and per-prompt outcomes; live results reported as unavailable unless present. |
| POST /api/evaluation/run | Re-runs the offline benchmark (deterministic stub) and rewrites `results/offline/`. |

`settings` is the candidate object described in the [settings reference](reference/settings.md); validation issues follow the [rule catalog](reference/validation-rules.md).
