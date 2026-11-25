import importlib.util
import json
import re
import unittest
from pathlib import Path

from scientific_core import contract as C, docsgen
from scientific_core.validation import validate_settings
from scientific_core.models import cross_rules_for

ROOT = C.ROOT


class DocsTests(unittest.TestCase):
    def test_generated_reference_is_current(self):
        self.assertEqual(docsgen.main(["--check"]), 0)

    def test_generated_pages_state_version_units_solver_assumptions(self):
        for name in docsgen.PAGES:
            text = (ROOT / "docs" / "reference" / name).read_text(encoding="utf-8")
            for needle in ("Schema version", "Solver method", "Canonical units", "Assumptions"):
                self.assertIn(needle, text, f"{name} lacks {needle}")

    def test_examples_run(self):
        spec = importlib.util.spec_from_file_location("run_examples", ROOT / "scripts" / "run_examples.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.main(), 0)

    def test_example_settings_validate(self):
        data = json.loads((ROOT / "examples" / "settings.valid.json").read_text(encoding="utf-8"))
        self.assertTrue(validate_settings(data, cross_rules_for("damped_spring")).valid)

    def test_markdown_links_resolve(self):
        files = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
        for f in files:
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", f.read_text(encoding="utf-8")):
                if re.match(r"[a-z]+:", target):
                    continue
                self.assertTrue((f.parent / target).resolve().exists(), f"{f.name}: broken link {target}")

    def test_readme_npm_commands_exist(self):
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        used = set(re.findall(r"npm run ([\w:.-]+)", readme))
        self.assertTrue(used)
        self.assertEqual(used - set(pkg), set())

    def test_ci_runs_the_documented_commands(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for needle in ("npm ci", "npm test", "docs:check", "examples", "scientific_core.benchmark"):
            self.assertIn(needle, ci)

    def test_api_doc_lists_every_server_route(self):
        server = (ROOT / "apps" / "web" / "server.js").read_text(encoding="utf-8")
        routes = set(re.findall(r"route\('(GET|POST)', '(/api/[\w/:-]+)'", server))
        doc = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
        self.assertTrue(routes)
        for method, path in routes:
            self.assertIn(f"{method} {path}", doc)

    def test_contract_prompts_reference_known_rules_and_gold_validates(self):
        suite = json.loads(C.PROMPTS_PATH.read_text(encoding="utf-8"))
        cat = C.rule_catalog()
        for p in suite["prompts"]:
            self.assertTrue(set(p["expected_rules"]) <= set(cat), p["id"])
            self.assertIn(p["expected"], {"execute", "clarify", "reject"})
            if p["expected"] == "execute":
                g = {k: {"value": v, "unit": C.field_specs()[k]["canonical_unit"]} for k, v in p["gold"].items()}
                self.assertTrue(validate_settings({"model": "damped_spring", **g}, cross_rules_for("damped_spring")).valid, p["id"])

    def test_ui_field_metadata_matches_schema(self):
        meta = {m["name"]: m for m in C.field_metadata()}
        for name, spec in C.field_specs().items():
            self.assertEqual((meta[name]["min"], meta[name]["max"], meta[name]["canonical_unit"]), (spec["min"], spec["max"], spec["canonical_unit"]))

    def test_prompt_suite_frozen_hash_pinned(self):
        # Changing the suite must be a deliberate, reviewed act: update version + this hash together.
        import hashlib
        h = hashlib.sha256(C.PROMPTS_PATH.read_bytes()).hexdigest()
        pinned = (ROOT / "packages" / "contracts" / "prompts" / "v1.sha256").read_text(encoding="utf-8").split()[0]
        self.assertEqual(h, pinned)


if __name__ == "__main__":
    unittest.main()
