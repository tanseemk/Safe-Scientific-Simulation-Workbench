# Verification record

Checks actually run when this archive was produced (sandbox: Linux, Python 3.12.3, Node v22.23.5, no network), from a fresh copy of the tree:

| Check | Command | Outcome |
|---|---|---|
| Install from lockfile | `npm ci` | ok (no dependencies; Python stdlib only) |
| Python tests | `npm run test:py` | 80 tests, OK |
| Node API tests | `npm run test:node` | 14 tests, 14 pass |
| Docs drift | `npm run docs:check` | generated docs are current |
| Examples | `npm run examples` | 5/5 ok |
| Offline benchmark | `npm run benchmark` | baseline 9/10, feedback 10/10, safety violations 0 / 0 (offline stub fixture; see docs/benchmark.md) |
| Server smoke | `PORT=3456 node apps/web/server.js`, `GET /api/health`, `POST /api/interpret` | ok |
| Browser UI (Chromium via Playwright) | desktop 1280×900 and mobile 390×844: launch → interpret → review → run → results, defaults confirmation, reject/clarify paths, edit-to-invalid, benchmark button, reduced-motion, skip-link focus | no console errors, no CSP violations, no horizontal overflow on mobile |

## Not run (do not assume these pass)

- GitHub Actions CI on Windows/macOS (the workflow is provided but was never executed here); Linux only was exercised.
- Any real LLM provider call. The live adapter is tested against mocked HTTP responses only; live benchmark results are **unavailable**.
- `python -m pytest` (pytest was not installable offline; the tests are plain `unittest` and are expected to be pytest-compatible).
- Python 3.12 on Windows/macOS and Node 24.
- A formal accessibility audit (screen reader, automated axe run). Basics were checked by hand: keyboard order, visible focus, labels, table alternative, reduced motion; palette contrast ratios were computed (paper/ink 18.0:1, stone/ink 7.1:1, amber/ink 9.1:1; concrete #6A6B66 at 3.65:1 on ink is used only for lines and decoration).

`results/offline/` contains one real run of the offline benchmark; its timing figures are specific to the machine that produced them.
