import csv
import json
import tempfile
import unittest
from pathlib import Path

from scientific_core import contract as C
from scientific_core.benchmark import aggregate, percentile, run_benchmark, run_case
from scientific_core.parsers import OpenAICompatibleParser, ProviderError
from helpers import ScriptedParser
import helpers

N = len(json.loads(C.PROMPTS_PATH.read_text(encoding="utf-8"))["prompts"])


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.res = run_benchmark("prompts/v1.json", "both", 42, cls.tmp.name, "offline", 2, command="test")
        cls.out = Path(cls.res["outdir"])
        cls.rows = [json.loads(l) for l in (cls.out / "raw.jsonl").read_text(encoding="utf-8").splitlines()]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_prompts_in_both_modes_and_repeats(self):
        for mode in ("baseline", "feedback"):
            ids = [r["suite_prompt_id"] for r in self.rows if r["mode"] == mode]
            self.assertEqual(len(ids), N * 2)
            self.assertEqual(len(set(ids)), N)

    def test_denominators_and_retry_accounting_consistent(self):
        for mode, a in self.res["aggregate"].items():
            rs = [r for r in self.rows if r["mode"] == mode]
            self.assertEqual(a["task_success"]["den"], len(rs))
            self.assertEqual(a["invalid_candidates_per_attempt"]["den"], sum(r["attempts"] for r in rs))
            self.assertEqual(a["retries"]["total"], sum(r["attempts"] - 1 for r in rs))
            self.assertEqual(sum(a["retries"]["distribution"].values()), len(rs))
            self.assertEqual(a["clarification_quality"]["den"], 3 * 2)
            self.assertEqual(a["invalid_requests_safely_rejected"]["den"], 3 * 2)

    def test_baseline_never_retries_and_feedback_respects_cap(self):
        self.assertTrue(all(r["retries"] == 0 for r in self.rows if r["mode"] == "baseline"))
        self.assertTrue(all(r["retries"] <= 2 and r["attempts"] <= 3 for r in self.rows if r["mode"] == "feedback"))

    def test_paired_conditions_same_prompts_and_offline_is_deterministic(self):
        def outcome(mode):
            return {(r["suite_prompt_id"], r["repeat"]): (r["status"], r["success"]) for r in self.rows if r["mode"] == mode}
        for pid in {r["suite_prompt_id"] for r in self.rows}:
            self.assertEqual(outcome("feedback")[(pid, 1)], outcome("feedback")[(pid, 2)])
            self.assertEqual(outcome("baseline")[(pid, 1)], outcome("baseline")[(pid, 2)])

    def test_zero_safety_violations(self):
        self.assertTrue(all(a["safety_violations"]["count"] == 0 for a in self.res["aggregate"].values()))

    def test_outputs_exist_and_are_consistent(self):
        for name in ("raw.jsonl", "summary.csv", "summary.json", "per_prompt.csv", "protocol.json", "report.md"):
            self.assertTrue((self.out / name).is_file(), name)
        rows = list(csv.DictReader((self.out / "summary.csv").read_text(encoding="utf-8").splitlines()))
        ts = next(r for r in rows if r["mode"] == "feedback" and r["metric"] == "task_success")
        self.assertEqual(int(ts["denominator"]), N * 2)
        proto = json.loads((self.out / "protocol.json").read_text(encoding="utf-8"))
        self.assertEqual(proto["suite"]["n_prompts"], N)
        self.assertEqual(len(proto["suite"]["sha256"]), 64)
        self.assertIn("timer_boundary", proto)
        self.assertIn("unavailable", (self.out / "report.md").read_text(encoding="utf-8"))

    def test_failure_classes_separate(self):
        base = json.loads(C.PROMPTS_PATH.read_text(encoding="utf-8"))["prompts"][0]
        rows = [run_case(base, ScriptedParser([ProviderError("timeout", "t")]), "feedback", 1),
                run_case(base, ScriptedParser([ProviderError("rate_limit", "r")]), "feedback", 1),
                run_case(base, ScriptedParser([helpers.cand()]), "feedback", 1)]
        a = aggregate(rows)["feedback"]
        self.assertEqual(a["execution_errors"]["by_class"], {"provider_timeout": 1, "provider_rate_limit": 1})
        self.assertEqual(a["execution_errors"]["solver_exceptions"], {"num": 0, "den": 1})
        self.assertEqual(a["task_success"]["num"], 1)

    def test_percentile_nearest_rank(self):
        self.assertEqual(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.5), 5)
        self.assertEqual(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95), 10)
        self.assertIsNone(percentile([], 0.5))

    def test_live_unavailable_without_key_is_reported_not_faked(self):
        import os
        old = os.environ.pop("S3W_LLM_API_KEY", None)
        try:
            with self.assertRaises(ProviderError) as cm:
                run_benchmark("prompts/v1.json", "both", 42, self.tmp.name, "live", 1)
            self.assertEqual(cm.exception.kind, "not_configured")
        finally:
            if old:
                os.environ["S3W_LLM_API_KEY"] = old


class FakeResp:
    def __init__(self, body): self.body = body
    def read(self): return json.dumps(self.body).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


class LiveAdapterTests(unittest.TestCase):
    ENV = {"S3W_LLM_API_KEY": "test-key"}

    def test_parses_structured_json_and_sends_no_extension_keys(self):
        seen = {}
        def opener(req, timeout):
            seen["body"] = json.loads(req.data); seen["auth"] = req.get_header("Authorization")
            return FakeResp({"choices": [{"message": {"content": json.dumps(helpers.cand())}}]})
        cand, meta = OpenAICompatibleParser(self.ENV, opener).parse("hi")
        self.assertEqual(cand["model"], "damped_spring")
        self.assertEqual(seen["auth"], "Bearer test-key")
        self.assertNotIn("x-s3w", json.dumps(seen["body"]))
        self.assertEqual(seen["body"]["temperature"], 0)

    def test_error_classification(self):
        import socket, urllib.error
        def mk(exc):
            def opener(req, timeout): raise exc
            return opener
        cases = [(urllib.error.HTTPError("u", 429, "x", {}, None), "rate_limit"), (urllib.error.HTTPError("u", 500, "x", {}, None), "api"),
                 (socket.timeout(), "timeout"), (urllib.error.URLError("down"), "network")]
        for exc, kind in cases:
            with self.assertRaises(ProviderError) as cm:
                OpenAICompatibleParser(self.ENV, mk(exc)).parse("hi")
            self.assertEqual(cm.exception.kind, kind)

    def test_bad_response_and_missing_key(self):
        bad = lambda req, timeout: FakeResp({"choices": [{"message": {"content": "not json"}}]})  # noqa: E731
        with self.assertRaises(ProviderError) as cm:
            OpenAICompatibleParser(self.ENV, bad).parse("hi")
        self.assertEqual(cm.exception.kind, "bad_response")
        with self.assertRaises(ProviderError) as cm:
            OpenAICompatibleParser({}).parse("hi")
        self.assertEqual(cm.exception.kind, "not_configured")

    def test_live_output_still_goes_through_validation(self):
        from scientific_core.workflow import run_pipeline
        evil = helpers.cand(code="import os")
        opener = lambda req, timeout: FakeResp({"choices": [{"message": {"content": json.dumps(evil)}}]})  # noqa: E731
        r = run_pipeline("x", OpenAICompatibleParser(self.ENV, opener), "baseline")
        self.assertEqual(r["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
