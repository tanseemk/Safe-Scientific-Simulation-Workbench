# Benchmark protocol

```text
python -m scientific_core.benchmark --suite prompts/v1.json --mode both --seed 42 --out results/
```

- **Suite:** `packages/contracts/prompts/v1.json` (10 prompts, frozen; its SHA-256 is pinned in `v1.sha256` and recorded in every `protocol.json`). See the [corpus](reference/prompt-corpus.md).
- **Conditions (paired):** *baseline* = one parse, one validation; a failure ends the attempt. *feedback* = validator errors returned to the parser, at most two retries (three attempts). Same prompts, parser, environment. Output-check failures may be retried; solver exceptions are recorded and not retried; provider errors are recorded and not retried. A retry that yields an unchanged candidate stops early (`no_change`).
- **Success:** judged against labels, not confidence — `execute`: runs, passes checks, matches gold settings; `clarify`: asks without executing; `reject`: rejected without executing.
- **Metrics:** task success, invalid candidates per parser attempt, invalid requests safely rejected, retries (total, mean, distribution, cap exhaustion), execution/provider errors by class, safety violations (raw count), clarification quality, response time (median, p95 for total, validation, solver). Every ratio is reported with its denominator.
- **Timer boundary:** from the start of the first parser call to the end of the last validation/solver step; excludes process start-up and serialisation.
- **Outputs** in `results/<provider>/`: `raw.jsonl`, `summary.csv`, `summary.json`, `per_prompt.csv`, `protocol.json`, `report.md`.
- **Live trials:** `--provider live --repeats 5` with `S3W_LLM_API_KEY` set. Without a key the run reports *unavailable*; nothing is fabricated. Offline and live latency are never mixed.

**Reading the offline numbers.** The offline stub is a deterministic fixture whose second pass is deliberately more lenient than its first. The baseline/feedback gap it shows proves the *harness* (retry cap, accounting, revalidation) works; it says nothing about language models. The 10-prompt suite is a pilot, so percentages are descriptive only.
