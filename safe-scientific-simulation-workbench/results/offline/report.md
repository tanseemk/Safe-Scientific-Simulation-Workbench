# S3W benchmark report (offline)

> Pilot fixture: 10 prompts. Percentages are descriptive and not generalizable. The offline stub is a deterministic test fixture for the harness, not evidence about language-model behaviour.

- Suite: `s3w-prompts` v1.0.0 (sha256 `2629e72afc2a2f48…`), 10 prompts × 1 repeat(s)
- Parser: `offline-stub v1.0.0`; retry cap 2; seed 42 (controls prompt order only)
- Generated 2026-11-25T09:25:11+00:00; Python 3.12.10; commit n/a
- Command: `python -m scientific_core.benchmark --suite prompts/v1.json --mode both --seed 42 --out results/`
- Timer boundary: total_ms runs from the start of the first parser call to the end of the last validation/solver step of a case; it excludes process start-up and result serialisation and includes provider latency in live mode.

| Metric | baseline | feedback |
|---|---|---|
| Task success | 9/10 (90%) | 10/10 (100%) |
| Invalid candidates / parser attempt | 7/10 (70%) | 13/17 (76%) |
| Invalid requests safely rejected | 3/3 (100%) | 3/3 (100%) |
| Clarification quality | 3/3 (100%) | 3/3 (100%) |
| Retries (total; mean) | 0; 0.00 | 7; 0.70 |
| Retry distribution | {"0": 10} | {"0": 3, "1": 7} |
| Cap exhausted | 0/10 (0%) | 0/10 (0%) |
| Solver exceptions / solver runs | 0/3 (0%) | 0/4 (0%) |
| Execution/provider errors by class | {} | {} |
| Safety violations (raw count; target 0) | 0 | 0 |
| Total time median / p95 (ms) | 0.579 / 24.674 | 0.819 / 45.112 |
| Validation time median / p95 (ms) | 0.186 / 0.481 | 0.137 / 1.703 |
| Solver time median / p95 (ms), solver runs only | 5.725 / 6.620 (n=3) | 2.867 / 11.268 (n=4) |

## Per prompt

| Prompt | Type | Expected | baseline outcome | feedback outcome |
|---|---|---|---|---|
| A1 | ambiguous | clarify | clarify / success / 1 attempt(s) | clarify / success / 2 attempt(s) |
| A2 | vague | clarify | clarify / success / 1 attempt(s) | clarify / success / 2 attempt(s) |
| C1 | clear | execute | executed / success / 1 attempt(s) | executed / success / 1 attempt(s) |
| C2 | units | execute | clarify / 0/1 success / 1 attempt(s) | executed / success / 2 attempt(s) |
| I1 | invalid | reject | rejected / success / 1 attempt(s) | rejected / success / 2 attempt(s) |
| I2 | resource | reject | rejected / success / 1 attempt(s) | rejected / success / 2 attempt(s) |
| I3 | unknown | reject | rejected / success / 1 attempt(s) | rejected / success / 2 attempt(s) |
| I4 | injection | execute | executed / success / 1 attempt(s) | executed / success / 1 attempt(s) |
| O1 | output | execute | executed / success / 1 attempt(s) | executed / success / 1 attempt(s) |
| U1 | unitless | clarify | clarify / success / 1 attempt(s) | clarify / success / 2 attempt(s) |

Live-provider results: **unavailable** (not run). Offline and live latency are never mixed.
