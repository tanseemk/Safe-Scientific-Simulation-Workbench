# Architecture and trust boundary

```text
Browser UI (Node.js static files)
   │ request + explicit run mode (baseline | feedback) + provider (offline | live)
   ▼
Node.js API (apps/web/server.js)      bounded bodies, fixed allow-list of Python operations, no shell
   │ JSON on stdin of:  python -m scientific_core bridge <op>
   ▼
Parser (offline stub  |  optional live LLM adapter)   structured JSON candidate only
   │ candidate; no generated code, no tools
   ▼
Validator (scientific_core.validation)  schema + unit normalisation + cross-field rules
   │ ValidatedSettings only (cannot be constructed outside the validator)
   ▼
Approved model registry (scientific_core.models)  -> damped_spring RK4 solver
   ├── output checks + bounded feedback controller (2 retries max, every retry re-validates)
   ├── run record / benchmark JSONL + CSV
   └── generated docs + examples + CI
```

**Safety invariant.** Solver functions accept only a `ValidatedSettings` object, which can only be minted by `validate_settings`. The registry refuses anything else and counts it as a *safety violation* (target: zero). The model name must be in the fixed registry. The LLM adapter returns JSON; it cannot call Python, a shell, the filesystem, or tools. Validation errors may be returned to the parser for correction, but every candidate re-enters full validation. At the retry cap the controller stops and reports failure or asks for clarification.

| Layer | Responsibility |
|---|---|
| Node.js | Serve the interface and API, bound request sizes, coordinate modes, write run records to `runs/`. |
| Parser | Offline deterministic stub (default) or provider-neutral live adapter (environment key). |
| Python core | Units, validation, model registry, solver, output checks, feedback controller. |
| Benchmark | Fixed prompts, paired conditions, timing, raw and aggregate records. |
| Docs/CI | Generated model/schema reference, runnable examples, drift and test checks. |

Honest limits of the guard: `ValidatedSettings` is protected by a private token inside one Python process. That stops accidental or model-driven bypass through the supported code paths; it is not a sandbox against arbitrary code running inside the same interpreter.
