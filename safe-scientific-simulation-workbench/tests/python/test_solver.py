import math
import unittest

from scientific_core.models.damped_spring import analytic_displacement, check_output, simulate
from helpers import cand, validate


def S(**kw):
    r = validate(cand(**kw))
    assert r.valid, r.to_dict()
    return r.settings


def q(v, u):
    return {"value": v, "unit": u}


def max_err(s, res):
    return max(abs(x - analytic_displacement(s, t)) for t, x in zip(res.t, res.x))


class SolverTests(unittest.TestCase):
    def test_regimes_match_analytic(self):
        cases = {
            "undamped": dict(damping=q(0, "N·s/m")),
            "underdamped": dict(),
            "critical": dict(damping=q(2 * math.sqrt(20), "N·s/m")),
            "overdamped": dict(damping=q(30, "N·s/m")),
            "initial velocity": dict(x0=q(0, "m"), v0=q(2, "m/s")),
        }
        for name, over in cases.items():
            with self.subTest(name):
                s = S(dt=q(0.001, "s"), **over)
                self.assertLess(max_err(s, simulate(s)), 1e-8)

    def test_equilibrium_stays_at_rest(self):
        s = S(x0=q(0, "m"), v0=q(0, "m/s"))
        r = simulate(s)
        self.assertTrue(all(x == 0 for x in r.x))
        self.assertTrue(all(c["status"] == "pass" for c in check_output(s, r) if c["id"] != "OUTPUT_REFERENCE"))

    def test_finite_length_and_grid(self):
        s = S()
        r = simulate(s)
        self.assertEqual(len(r.t), len(r.x), r.n_steps + 1)
        self.assertEqual(r.n_steps, 500)
        self.assertTrue(all(math.isfinite(v) for v in r.x + r.v))
        self.assertAlmostEqual(r.t[-1], s.duration, places=12)

    def test_non_divisible_step_uses_smaller_effective_dt(self):
        s = S(duration=q(1, "s"), dt=q(0.03, "s"))
        r = simulate(s)
        self.assertEqual(r.n_steps, 34)
        self.assertLessEqual(r.dt_effective, 0.03)
        self.assertAlmostEqual(r.t[-1], 1.0, places=12)

    def test_zero_damping_energy_nearly_conserved(self):
        s = S(damping=q(0, "N·s/m"), dt=q(0.001, "s"))
        r = simulate(s)
        self.assertLess(abs(r.energy[-1] - r.energy[0]) / r.energy[0], 1e-6)

    def test_damped_energy_decays_overall(self):
        r = simulate(S())
        self.assertAlmostEqual(r.energy[-1] / r.energy[0], math.exp(-0.8 * 5), delta=0.01)  # E ~ exp(-c t / m) on average

    def test_fourth_order_convergence(self):
        errs = []
        for dt in (0.04, 0.02, 0.01):
            s = S(dt=q(dt, "s"), damping=q(0.4, "N·s/m"), duration=q(2, "s"))
            errs.append(max_err(s, simulate(s)))
        self.assertGreater(errs[0] / errs[1], 10)  # ideal RK4 ratio is 16
        self.assertGreater(errs[1] / errs[2], 10)

    def test_deterministic(self):
        s = S()
        self.assertEqual(simulate(s).x, simulate(s).x)

    def test_output_checks_pass_on_good_run_and_detect_failure(self):
        s = S()
        r = simulate(s)
        checks = check_output(s, r)
        self.assertTrue(all(c["status"] == "pass" for c in checks), checks)
        r.x[34] = math.nan
        bad = {c["id"]: c for c in check_output(s, r)}
        self.assertEqual(bad["OUTPUT_NONFINITE"]["status"], "fail")
        self.assertIn("index 34", bad["OUTPUT_NONFINITE"]["detail"])
        r2 = simulate(s)
        r2.energy[10] = r2.energy[0] * 2
        r2.x[10] = r2.x[0] * 5
        self.assertEqual({c["id"]: c for c in check_output(s, r2)}["OUTPUT_ENERGY"]["status"], "fail")

    def test_coarse_step_reports_reference_warning_not_failure(self):
        s = S(mass=q(1, "kg"), stiffness=q(100, "N/m"), damping=q(0, "N·s/m"), dt=q(0.05, "s"), duration=q(5, "s"))
        ids = {c["id"]: c["status"] for c in check_output(s, simulate(s))}
        self.assertEqual(ids["OUTPUT_REFERENCE"], "warn")
        self.assertEqual(ids["OUTPUT_ENERGY"], "pass")

    def test_maximum_allowed_work_finishes_quickly(self):
        import time
        s = S(mass=q(100, "kg"), stiffness=q(0.01, "N/m"), damping=q(0, "N·s/m"), duration=q(120, "s"), dt=q(0.0006, "s"))
        t0 = time.perf_counter()
        r = simulate(s)
        self.assertEqual(r.n_steps, 200000)
        self.assertLess(time.perf_counter() - t0, 30)


if __name__ == "__main__":
    unittest.main()
