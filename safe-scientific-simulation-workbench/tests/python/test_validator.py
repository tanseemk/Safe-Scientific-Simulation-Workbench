import math
import unittest

from scientific_core import contract as C
from scientific_core.validation import ValidatedSettings, validate_settings
from helpers import cand, rules, validate


class ValidatorTests(unittest.TestCase):
    def test_valid_baseline(self):
        r = validate(cand())
        self.assertEqual(r.disposition, "valid")
        self.assertEqual(r.settings.mass, 1.0)

    def test_each_required_field_missing_is_clarify(self):
        for name in ["model", *C.FIELD_ORDER]:
            with self.subTest(name):
                r = validate(cand(**{name: ...}))
                self.assertEqual(r.disposition, "clarify")
                self.assertIn("REQUIRED_MISSING", rules(r))
                self.assertEqual(r.issues[0].path, f"settings.{name}")
                self.assertIn("required field is missing", r.issues[0].message)

    def test_unit_conversions(self):
        r = validate(cand(mass={"value": 500, "unit": "g"}, x0={"value": 10, "unit": "cm"},
                          dt={"value": 10, "unit": "ms"}, duration={"value": 2000, "unit": "ms"},
                          damping={"value": 0.8, "unit": "Ns/m"}))
        self.assertTrue(r.valid, r.to_dict())
        self.assertEqual((r.settings.mass, r.settings.x0, r.settings.dt, r.settings.duration), (0.5, 0.1, 0.01, 2.0))
        self.assertTrue(any(n["converted"] for n in r.normalized))

    def test_missing_unit_forms(self):
        for raw in (5, {"value": 5, "unit": ""}, {"value": 5, "unit": None}, {"value": 5}):
            with self.subTest(raw=raw):
                r = validate(cand(duration=raw))
                self.assertEqual(r.disposition, "clarify")
                self.assertIn("UNIT_MISSING", rules(r))
        self.assertIn("has no unit", validate(cand(duration=5)).issues[0].message)

    def test_unknown_and_wrong_dimension_units(self):
        self.assertEqual(rules(validate(cand(mass={"value": 1, "unit": "lb"}))), ["UNIT_UNKNOWN"])
        self.assertEqual(rules(validate(cand(mass={"value": 1, "unit": "m"}))), ["UNIT_UNKNOWN"])
        self.assertEqual(validate(cand(mass={"value": 1, "unit": "lb"})).disposition, "clarify")

    def test_types_bool_nan_inf_strings(self):
        bad = [True, False, "5", None.__class__, [1], {"value": True, "unit": "kg"}, {"value": "1", "unit": "kg"},
               {"value": math.nan, "unit": "kg"}, {"value": math.inf, "unit": "kg"}, {"value": -math.inf, "unit": "kg"},
               {"value": 1, "unit": 5}, {"value": 1, "unit": "kg", "extra": 1}]
        for raw in bad:
            with self.subTest(raw=repr(raw)):
                r = validate(cand(mass=raw))
                self.assertFalse(r.valid)
                self.assertIsNone(r.settings)

    def test_bool_never_masquerades_as_number(self):
        self.assertEqual(rules(validate(cand(mass={"value": True, "unit": "kg"}))), ["TYPE_INVALID"])
        self.assertEqual(rules(validate(cand(mass=True))), ["TYPE_INVALID"])

    def test_nonfinite_rule_id(self):
        self.assertEqual(rules(validate(cand(mass={"value": math.nan, "unit": "kg"}))), ["VALUE_NOT_FINITE"])
        self.assertEqual(validate(cand(mass={"value": math.inf, "unit": "kg"})).disposition, "reject")

    def test_range_boundaries_for_every_field(self):
        for name, s in C.field_specs().items():
            cu = s["canonical_unit"]
            for label, value, ok in (("min", s["min"], True), ("max", s["max"], True)):
                with self.subTest(name=name, edge=label):
                    r = validate(cand(**{name: {"value": value, "unit": cu}, "dt": {"value": 0.01, "unit": "s"}} if name != "dt" else {name: {"value": value, "unit": cu}}))
                    self.assertNotIn("RANGE_MIN", rules(r))
                    self.assertNotIn("RANGE_MAX", rules(r))
            lo = validate(cand(**{name: {"value": s["min"] - max(abs(s["min"]) * 0.01, 1e-5), "unit": cu}}))
            hi = validate(cand(**{name: {"value": s["max"] + max(abs(s["max"]) * 0.01, 1e-5), "unit": cu}}))
            with self.subTest(name=name, edge="below"):
                self.assertIn("RANGE_MIN", rules(lo))
                self.assertEqual(lo.disposition, "reject")
            with self.subTest(name=name, edge="above"):
                self.assertIn("RANGE_MAX", rules(hi))

    def test_documented_error_messages(self):
        self.assertEqual(validate(cand(dt={"value": 0.2, "unit": "s"})).issues[0].message, "settings.dt: 0.2 s exceeds maximum 0.05 s.")
        self.assertEqual(validate(cand(mass={"value": -1, "unit": "kg"})).issues[0].message, "settings.mass: -1 kg is below minimum 0.01 kg.")

    def test_zero_damping_allowed_but_zero_mass_not(self):
        self.assertTrue(validate(cand(damping={"value": 0, "unit": "N·s/m"})).valid)
        self.assertIn("RANGE_MIN", rules(validate(cand(mass={"value": 0, "unit": "kg"}))))

    def test_unknown_model_and_fields(self):
        r = validate(cand(model="plasma_turbulence"))
        self.assertEqual((r.disposition, rules(r)), ("reject", ["MODEL_UNKNOWN"]))
        r = validate(cand(code="import os"))
        self.assertEqual((r.disposition, rules(r)), ("reject", ["FIELD_UNKNOWN"]))
        self.assertIn("MODEL_UNKNOWN", rules(validate(cand(model=["damped_spring"]))))

    def test_non_dict_candidates_never_raise(self):
        for junk in (None, [], "text", 5, True):
            r = validate_settings(junk)
            self.assertEqual(r.disposition, "reject")

    def test_step_cap_boundary(self):
        ok = validate(cand(mass={"value": 100, "unit": "kg"}, stiffness={"value": 0.01, "unit": "N/m"}, damping={"value": 0, "unit": "N·s/m"},
                           duration={"value": 120, "unit": "s"}, dt={"value": 0.0006, "unit": "s"}))
        self.assertTrue(ok.valid, ok.to_dict())
        self.assertEqual(ok.derived["steps"], 200000)
        over = validate(cand(mass={"value": 100, "unit": "kg"}, stiffness={"value": 0.01, "unit": "N/m"},
                             duration={"value": 120, "unit": "s"}, dt={"value": 120 / 200001, "unit": "s"}))
        self.assertIn("CROSS_STEP_CAP", rules(over))
        self.assertIn("exceeds cap", over.issues[0].message)
        r = validate(cand(duration={"value": 120, "unit": "s"}, dt={"value": 0.0001, "unit": "s"}))
        self.assertEqual((r.disposition, rules(r)), ("reject", ["CROSS_STEP_CAP"]))

    def test_dt_exceeds_duration(self):
        r = validate(cand(duration={"value": 0.02, "unit": "s"}, dt={"value": 0.05, "unit": "s"}))
        self.assertIn("CROSS_DT_EXCEEDS_DURATION", rules(r))

    def test_stability_warn_and_reject(self):
        warn = validate(cand(mass={"value": 0.01, "unit": "kg"}, stiffness={"value": 100, "unit": "N/m"}, dt={"value": 0.0025, "unit": "s"}))
        self.assertTrue(warn.valid)
        self.assertIn("STABILITY_WARN", rules(warn))
        rej = validate(cand(mass={"value": 0.01, "unit": "kg"}, stiffness={"value": 10000, "unit": "N/m"}, dt={"value": 0.01, "unit": "s"}))
        self.assertIn("CROSS_STABILITY", rules(rej))

    def test_cross_rules_skipped_when_field_errors_exist(self):
        r = validate(cand(mass={"value": -1, "unit": "kg"}, duration={"value": 120, "unit": "s"}, dt={"value": 0.0001, "unit": "s"}))
        self.assertEqual(rules(r), ["RANGE_MIN"])

    def test_report_is_machine_stable(self):
        d = validate(cand(dt={"value": 0.2, "unit": "s"})).to_dict()
        self.assertEqual(set(d), {"schema_version", "valid", "disposition", "issues", "normalized", "derived", "settings"})
        self.assertEqual(set(d["issues"][0]), {"path", "rule_id", "severity", "kind", "message", "guidance"})
        self.assertEqual(validate(cand()).to_dict(), validate(cand()).to_dict())

    def test_every_emitted_rule_is_in_catalog(self):
        import pathlib, re
        src = "".join(p.read_text(encoding="utf-8") for p in pathlib.Path(C.ROOT, "python").rglob("*.py"))
        used = set(re.findall(r'_issue\(\s*"([A-Z_]+)"', src)) | set(re.findall(r'add\(\s*"(OUTPUT_[A-Z_]+)"', src))
        self.assertTrue(used <= set(C.rule_catalog()), used - set(C.rule_catalog()))

    def test_validated_settings_cannot_be_forged(self):
        with self.assertRaises(PermissionError):
            ValidatedSettings("damped_spring", 1, 1, 1, 1, 1, 1, 1)
        with self.assertRaises(PermissionError):
            ValidatedSettings("damped_spring", 1, 1, 1, 1, 1, 1, 1, _proof=object())


if __name__ == "__main__":
    unittest.main()
