"""Deterministic damped mass-spring model:  m x'' + c x' + k x = 0  (RK4)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .. import contract as C
from ..validation.engine import _issue, fmt
from ..validation.report import ValidatedSettings


@dataclass
class SimulationResult:
    t: list
    x: list
    v: list
    energy: list
    n_steps: int
    dt_requested: float
    dt_effective: float
    method: str = "RK4"


def omega_max(m: float, c: float, k: float) -> float:
    """Magnitude of the fastest eigenvalue of the linear system."""
    a, b = c / m, k / m
    disc = a * a - 4 * b
    if disc >= 0:
        return (a + math.sqrt(disc)) / 2
    return math.sqrt(b)


def step_count(duration: float, dt: float) -> int:
    return max(1, math.ceil(duration / dt - 1e-9))


def cross_rules(si: dict):
    """Cross-field rules. Returns (issues, derived)."""
    ex = C.ext()
    issues = []
    n = step_count(si["duration"], si["dt"])
    om = omega_max(si["mass"], si["damping"], si["stiffness"])
    derived = {"steps": n, "omega_max": om, "omega_dt": om * si["dt"]}
    if si["dt"] > si["duration"]:
        issues.append(_issue("CROSS_DT_EXCEEDS_DURATION", "settings",
                             f"settings: dt {fmt(si['dt'])} s exceeds duration {fmt(si['duration'])} s."))
    if n > ex["max_steps"]:
        issues.append(_issue("CROSS_STEP_CAP", "settings",
                             f"settings: {n:,} integration steps exceeds cap of {ex['max_steps']:,}."))
    st = ex["stability"]
    if derived["omega_dt"] >= st["reject_omega_dt"]:
        issues.append(_issue("CROSS_STABILITY", "settings.dt",
                             f"settings.dt: fastest rate × dt = {fmt(derived['omega_dt'])} is outside the RK4 stability limit "
                             f"({fmt(st['reject_omega_dt'])})."))
    elif derived["omega_dt"] >= st["warn_omega_dt"]:
        issues.append(_issue("STABILITY_WARN", "settings.dt",
                             f"settings.dt: fastest rate × dt = {fmt(derived['omega_dt'])} is coarse (warn at {fmt(st['warn_omega_dt'])})."))
    return issues, derived


def simulate(s: ValidatedSettings) -> SimulationResult:
    m, c, k = s.mass, s.damping, s.stiffness
    n = step_count(s.duration, s.dt)
    h = s.duration / n
    x, v = s.x0, s.v0
    t_arr, x_arr, v_arr = [0.0], [x], [v]
    h2, h6 = h / 2, h / 6

    for i in range(1, n + 1):
        k1x = v
        k1v = -(c * v + k * x) / m
        xm, vm = x + h2 * k1x, v + h2 * k1v
        k2x = vm
        k2v = -(c * vm + k * xm) / m
        xm, vm = x + h2 * k2x, v + h2 * k2v
        k3x = vm
        k3v = -(c * vm + k * xm) / m
        xe, ve = x + h * k3x, v + h * k3v
        k4x = ve
        k4v = -(c * ve + k * xe) / m
        x += h6 * (k1x + 2 * k2x + 2 * k3x + k4x)
        v += h6 * (k1v + 2 * k2v + 2 * k3v + k4v)
        t_arr.append(i * h)
        x_arr.append(x)
        v_arr.append(v)
    energy = [0.5 * m * vi * vi + 0.5 * k * xi * xi for xi, vi in zip(x_arr, v_arr)]
    return SimulationResult(t_arr, x_arr, v_arr, energy, n, s.dt, h)


def analytic_displacement(s: ValidatedSettings, t: float) -> float:
    """Closed-form x(t) for all damping regimes."""
    w0 = math.sqrt(s.stiffness / s.mass)
    zeta = s.damping / (2 * math.sqrt(s.stiffness * s.mass))
    x0, v0 = s.x0, s.v0
    if zeta < 1 - 1e-9:
        wd = w0 * math.sqrt(1 - zeta * zeta)
        return math.exp(-zeta * w0 * t) * (x0 * math.cos(wd * t) + (v0 + zeta * w0 * x0) / wd * math.sin(wd * t))
    if zeta <= 1 + 1e-9:
        return (x0 + (v0 + w0 * x0) * t) * math.exp(-w0 * t)
    root = w0 * math.sqrt(zeta * zeta - 1)
    r1, r2 = -w0 * zeta + root, -w0 * zeta - root
    b = (v0 - r1 * x0) / (r2 - r1)
    a = x0 - b
    return a * math.exp(r1 * t) + b * math.exp(r2 * t)


def regime(s: ValidatedSettings) -> dict:
    w0 = math.sqrt(s.stiffness / s.mass)
    zeta = s.damping / (2 * math.sqrt(s.stiffness * s.mass))
    name = "undamped" if s.damping == 0 else "underdamped" if zeta < 1 - 1e-9 else "critically damped" if zeta <= 1 + 1e-9 else "overdamped"
    return {"omega0_rad_s": w0, "zeta": zeta, "regime": name,
            "period_s": (2 * math.pi / (w0 * math.sqrt(1 - zeta * zeta))) if zeta < 1 - 1e-9 else None}


def check_output(s: ValidatedSettings, r: SimulationResult) -> list[dict]:
    """Output checks. status: pass | fail | warn."""
    checks = []

    def add(rule_id, name, status, detail):
        checks.append({"id": rule_id, "name": name, "status": status, "detail": detail})

    bad = next((i for i, (a, b) in enumerate(zip(r.x, r.v)) if not (math.isfinite(a) and math.isfinite(b))), None)
    add("OUTPUT_NONFINITE", "Finite values", "fail" if bad is not None else "pass",
        f"result.displacement: non-finite value at index {bad}." if bad is not None else f"All {len(r.x):,} samples finite.")
    exp = r.n_steps + 1
    ok_len = len(r.t) == len(r.x) == len(r.v) == exp
    add("OUTPUT_LENGTH", "Grid length", "pass" if ok_len else "fail", f"{len(r.t):,} samples; expected {exp:,}.")
    steps = [r.t[i + 1] - r.t[i] for i in range(len(r.t) - 1)]
    ok_grid = all(abs(d - r.dt_effective) <= 1e-9 * max(1.0, r.dt_effective) + 1e-12 for d in steps) if steps else True
    add("OUTPUT_GRID", "Uniform time grid", "pass" if ok_grid else "fail", f"Effective step {fmt(r.dt_effective)} s (requested {fmt(r.dt_requested)} s).")
    if bad is None:
        e0 = r.energy[0]
        emax = max(r.energy)
        tol = e0 * 1.001 + 1e-12
        add("OUTPUT_ENERGY", "Energy bounded by initial value (0.1 % tolerance)", "pass" if emax <= tol else "fail",
            f"max E = {fmt(emax)} J, E₀ = {fmt(e0)} J. Tolerance check only; strict monotonic decay is not claimed.")
        w0 = math.sqrt(s.stiffness / s.mass)
        scale = max(abs(s.x0), abs(s.v0) / w0, 0.0)
        err = max(abs(xi - analytic_displacement(s, ti)) for ti, xi in zip(r.t[:: max(1, len(r.t) // 2000)], r.x[:: max(1, len(r.x) // 2000)]))
        limit = 1e-3 * scale + 1e-12
        add("OUTPUT_REFERENCE", "Agreement with analytic solution (sampled)", "pass" if err <= limit else "warn",
            f"max |x − x_analytic| = {err:.3e} m; tolerance {limit:.3e} m.")
    return checks


def checks_failed(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["status"] == "fail"]
