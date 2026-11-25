import unittest
from unittest import mock

from scientific_core import models
from scientific_core.parsers import OfflineStubParser, ProviderError
from scientific_core.workflow import execute_settings, run_pipeline
from helpers import ScriptedParser
import helpers

C1 = "Simulate a damped spring: mass 1 kg, stiffness 20 N/m, damping 0.8 N·s/m, x0 0.1 m, v0 0 m/s, duration 5 s, dt 0.01 s."
C2 = "Mass 500 g, stiffness 20 N/m, damping 0.8 N·s/m, x0 10 cm, zero speed, duration 2 s, step 10 ms."


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        models.reset_stats()

    def test_clear_prompt_executes(self):
        r = run_pipeline(C1, OfflineStubParser(), "baseline")
        self.assertEqual((r["status"], r["retries"]), ("executed", 0))
        self.assertTrue(r["record"]["run_id"].startswith("S3W-"))
        self.assertEqual(r["provenance"]["mass"]["source"], "prompt")

    def test_run_id_is_reproducible(self):
        a = run_pipeline(C1, OfflineStubParser(), "baseline")["record"]["run_id"]
        b = run_pipeline(C1, OfflineStubParser(), "feedback")["record"]["run_id"]
        self.assertEqual(a, b)

    def test_unit_prompt_baseline_clarifies_feedback_recovers(self):
        base = run_pipeline(C2, OfflineStubParser(), "baseline")
        fb = run_pipeline(C2, OfflineStubParser(), "feedback")
        self.assertEqual(base["status"], "clarify")
        self.assertEqual(base["n_attempts"], 1)
        self.assertEqual((fb["status"], fb["n_attempts"], fb["retries"]), ("executed", 2, 1))
        self.assertEqual(fb["provenance"]["v0"]["source"], "inferred")
        self.assertEqual(fb["validation"]["settings"]["mass"], 0.5)

    def test_ambiguous_asks_and_never_runs(self):
        for text in ("Show what happens when the spring is released.", "Use a light mass, fairly stiff spring, short run.",
                     "Mass 1, k 20, damping 0.8, x0 0.1, v0 0, duration 5, dt 0.01."):
            for mode in ("baseline", "feedback"):
                with self.subTest(text=text, mode=mode):
                    r = run_pipeline(text, OfflineStubParser(), mode)
                    self.assertEqual(r["status"], "clarify")
                    self.assertIsNone(r["execution"])
        self.assertEqual(models.STATS["calls"], 0)

    def test_unitless_values_are_not_guessed_even_with_feedback(self):
        r = run_pipeline("Mass 1, k 20, damping 0.8, x0 0.1, v0 0, duration 5, dt 0.01.", OfflineStubParser(), "feedback")
        self.assertEqual({i["rule_id"] for i in r["validation"]["issues"]}, {"UNIT_MISSING"})

    def test_invalid_rejected_without_solver(self):
        for text, rule in (("mass -1 kg, stiffness 20 N/m, damping 0.8 N·s/m, x0 0.1 m, v0 0 m/s, duration 5 s, dt 0.01 s. damped spring", "RANGE_MIN"),
                           (C1.replace("5 s", "120 s").replace("dt 0.01 s", "dt 0.0001 s"), "CROSS_STEP_CAP"),
                           ("Use the plasma turbulence simulator.", "MODEL_UNKNOWN")):
            r = run_pipeline(text, OfflineStubParser(), "feedback")
            self.assertEqual(r["status"], "rejected")
            self.assertEqual(r["validation"]["issues"][0]["rule_id"], rule)
        self.assertEqual(models.STATS["calls"], 0)

    def test_retries_stop_at_cap(self):
        bad = [helpers.cand(mass={"value": -i, "unit": "kg"}) for i in (1, 2, 3, 4, 5)]
        p = ScriptedParser(bad)
        r = run_pipeline("x", p, "feedback")
        self.assertEqual((r["n_attempts"], r["retries"], p.calls), (3, 2, 3))
        self.assertTrue(r["cap_exhausted"])
        self.assertEqual(r["stop_reason"], "cap_exhausted")
        self.assertEqual(models.STATS["calls"], 0)

    def test_baseline_makes_exactly_one_attempt(self):
        p = ScriptedParser([helpers.cand(mass={"value": -1, "unit": "kg"}), helpers.cand()])
        r = run_pipeline("x", p, "baseline")
        self.assertEqual((r["n_attempts"], p.calls, r["status"]), (1, 1, "rejected"))

    def test_feedback_receives_structured_validator_errors(self):
        p = ScriptedParser([helpers.cand(mass={"value": -1, "unit": "kg"}), helpers.cand()])
        r = run_pipeline("x", p, "feedback")
        self.assertEqual(r["status"], "executed")
        self.assertEqual(p.feedbacks[0], None)
        self.assertEqual(p.feedbacks[1][0]["rule_id"], "RANGE_MIN")

    def test_feedback_cannot_bypass_validation(self):
        evil = helpers.cand(code="__import__('os').system('id')", tool="shell")
        p = ScriptedParser([helpers.cand(mass={"value": -1, "unit": "kg"}), evil, evil])
        r = run_pipeline("x", p, "feedback")
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(models.STATS["calls"], 0)
        self.assertEqual({i["rule_id"] for i in r["attempts"][1]["issues"]}, {"FIELD_UNKNOWN"})

    def test_provider_error_recorded_and_not_retried(self):
        p = ScriptedParser([ProviderError("timeout", "slow"), helpers.cand()])
        r = run_pipeline("x", p, "feedback")
        self.assertEqual((r["status"], r["n_attempts"], p.calls, r["error"]["class"]), ("provider_error", 1, 1, "provider_timeout"))

    def test_solver_exception_recorded_not_retried(self):
        boom = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.dict(models.APPROVED["damped_spring"], {"solve": boom}):
            p = ScriptedParser([helpers.cand()])
            r = run_pipeline("x", p, "feedback")
        self.assertEqual((r["status"], r["n_attempts"], r["error"]["class"]), ("solver_error", 1, "solver_exception"))
        self.assertEqual(boom.call_count, 1)

    def test_output_check_failure_is_retried_up_to_cap(self):
        fail = lambda s, res: [{"id": "OUTPUT_ENERGY", "name": "x", "status": "fail", "detail": "forced"}]  # noqa: E731
        with mock.patch.dict(models.APPROVED["damped_spring"], {"check": fail}):
            p = ScriptedParser([helpers.cand(), helpers.cand(dt={"value": 0.02, "unit": "s"}), helpers.cand(dt={"value": 0.03, "unit": "s"})])
            r = run_pipeline("x", p, "feedback")
        self.assertEqual((r["status"], r["n_attempts"]), ("checks_failed", 3))
        self.assertEqual(p.feedbacks[1][0]["rule_id"], "OUTPUT_ENERGY")

    def test_execute_settings_validates_user_edits(self):
        ok = execute_settings(helpers.cand(), {"mass": {"source": "user_edit"}})
        self.assertEqual(ok["status"], "executed")
        self.assertEqual(ok["record"]["provenance"]["mass"]["source"], "user_edit")
        bad = execute_settings(helpers.cand(mass={"value": -1, "unit": "kg"}))
        self.assertEqual((bad["status"], bad["execution"], bad["record"]), ("rejected", None, None))
        self.assertEqual(models.STATS["calls"], 1)

    def test_series_downsampled_but_complete(self):
        r = execute_settings(helpers.cand(mass={"value": 100, "unit": "kg"}, stiffness={"value": 0.01, "unit": "N/m"},
                                         duration={"value": 120, "unit": "s"}, dt={"value": 0.0006, "unit": "s"}))
        s = r["execution"]["series"]
        self.assertLessEqual(len(s["t"]), 4001)
        self.assertEqual(s["total_samples"], 200001)
        self.assertEqual(s["t"][-1], r["execution"]["series"]["t"][-1])


if __name__ == "__main__":
    unittest.main()
