# Model and numerics

The workbench simulates one model: `m x″ + c x′ + k x = 0`, a linear one-dimensional damped mass–spring oscillator. It is a demonstration vehicle for interface, validation and evaluation. It is **not** fusion research and **not** production scientific software.

- **Method:** fixed-step classical RK4 on the state (x, v). `n = ceil(duration/dt)`; the effective step is `duration/n`, never larger than the requested `dt`; `n + 1` samples are returned.
- **Reference:** a closed-form solution (underdamped, critically damped, overdamped, undamped) is used for the output reference check and the solver tests.
- **Convergence:** tests confirm the error shrinks at roughly fourth order as `dt` halves.
- **Stability rule (added to the dossier's bounds):** with ω = largest eigenvalue magnitude, `ω·dt ≥ 0.2` warns and `ω·dt ≥ 2.5` is rejected, because RK4's stability limit is about 2.8 on the relevant axes.
- **Energy check:** `max E ≤ 1.001·E₀` (tolerance, not a monotonicity claim).
- **Bounds** are engineering/resource limits; see [settings reference](reference/settings.md).

Everything above the line `Assumptions` in each generated page is derived from the canonical schema.
