# Limitations and troubleshooting

| Limitation | Response |
|---|---|
| A toy model could be mistaken for fusion work. | It is a damped oscillator; the UI and docs say so. |
| LLMs can misread values or units. | Candidate settings, provenance and errors are shown; deterministic checks; ambiguity prompts clarification. |
| Retries may disguise one-shot weakness. | Both modes are reported with the same suite, cap and exhausted cases. |
| Small corpus. | Findings are a pilot; add held-out paraphrases and independent review before generalising. |
| Numerics depend on regime and dt. | Bounded work, stability rules, analytic reference check, convergence tests. |
| Live service undermines reproducibility and privacy. | Offline by default; explicit live mode; the key stays in the environment; the prompt text is sent to the provider. |
| Not verified here | The live adapter was tested only against mocked responses; no real provider call was made. |

## Troubleshooting

- **"Python 3.12+ not found":** install Python 3.12 or set `S3W_PYTHON` to its path (Windows example: `set S3W_PYTHON=C:\Python312\python.exe`).
- **Port in use:** `PORT=3100 npm run dev` (Windows: `set PORT=3100 && npm run dev`).
- **`npm ci` complains about the lockfile:** there are no dependencies; `npm ci` should still succeed with Node 22+.
- **Docs check fails:** run `npm run docs:build` and commit the regenerated `docs/reference/`.
- **Live provider selected but disabled:** set `S3W_LLM_API_KEY` (optionally `S3W_LLM_BASE_URL`, `S3W_LLM_MODEL`) before `npm run dev`.
