# Safe Scientific Simulation Workbench (S3W)

An evaluated natural-language interface for validated simulation inputs. One reproducible project joins a safe LLM-to-model harness, a reusable scientific data validation package, and docs-as-code. A damped mass–spring oscillator demonstrates the workflow; it is **not** fusion research and **not** production scientific software.

> Every request becomes inspectable settings. Every setting passes deterministic checks. Every run leaves a traceable record.

## Quick start (offline, no API key, no network)

Requirements: **Python 3.12** and **Node.js 22+ (LTS)**. There are no third-party dependencies.

```text
npm ci
npm run dev
```

Open http://127.0.0.1:3000. If Python is not found, set `S3W_PYTHON` to the interpreter path.

| Task | Command |
|---|---|
| Tests (Python + Node) | `npm test` (`npm run test:py`, `npm run test:node`) |
| Offline benchmark | `npm run benchmark` |
| Generate docs | `npm run docs:build` |
| Docs drift check (CI) | `npm run docs:check` |
| Run the examples | `npm run examples` |
| One request from the terminal | `npm run simulate -- "Mass 1 kg, stiffness 20 N/m, damping 0.8 N·s/m, x0 0.1 m, v0 0 m/s, duration 5 s, dt 0.01 s"` |

Equivalent without npm: `PYTHONPATH=python python -m unittest discover -s tests/python -p "test_*.py"` and `PYTHONPATH=python python -m scientific_core.benchmark --suite prompts/v1.json --mode both --seed 42 --out results/`. (The suites are plain `unittest`, so `python -m pytest` also works if you install pytest.)

## What is inside

```text
apps/web/               Node.js interface and API (built-ins only)
packages/contracts/     canonical JSON schema + frozen prompt corpus
python/scientific_core/ validation, solver, parsers, feedback controller, benchmark
docs/                   architecture, model, API, benchmark protocol, limitations, generated reference
examples/               prompt runs with expected outcomes
tests/python/           unit, integration, safety, benchmark-accounting, docs tests
scripts/                docs generation, example runner, Python launcher
.github/workflows/      CI: tests, examples, docs drift, benchmark
```

Read next: [architecture](docs/architecture.md) · [model](docs/model.md) · [API](docs/api.md) · [benchmark protocol](docs/benchmark.md) · [limitations and troubleshooting](docs/limitations.md) · [settings reference](docs/reference/settings.md) · [validation rules](docs/reference/validation-rules.md) · [prompt corpus](docs/reference/prompt-corpus.md)

## Safety in one paragraph

The language model (when you opt in) may only return schema-constrained JSON. Nothing it produces is ever executed. Settings must pass full validation (model, fields, types, units, finite values, ranges, cross-field limits, step cap) before a solver can run; the solver accepts only a validator-minted object, and the registry counts any violation (target zero). Unitless numbers are never guessed; documented defaults are offered only for you to confirm.

## Optional live LLM

```text
export S3W_LLM_API_KEY=...        # never commit it
export S3W_LLM_MODEL=...          # optional
export S3W_LLM_BASE_URL=...       # optional; any OpenAI-compatible chat/completions endpoint
npm run dev                       # then choose “Live LLM” in the request form
```

Your prompt text is sent to the provider. The adapter has been tested only with mocked responses; live results will vary between runs and providers, so they are reported separately from the deterministic offline results.

## Honest scope

The offline parser is a deterministic fixture used to prove the harness; its baseline-versus-feedback gap is **not** evidence about language models. The 10-prompt suite is a pilot. Run the live protocol (`--provider live --repeats 5`) before drawing conclusions.
