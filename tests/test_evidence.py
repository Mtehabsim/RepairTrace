import json
from pathlib import Path
import tempfile
import unittest
from examples.workflow_check import fixture, evaluate, SCENARIOS


class EvidenceTests(unittest.TestCase):
    def test_supported_workflows_and_controls(self):
        # Outcomes checked against fixture bytes and fresh execution, not events alone.
        for group in ("supported_fault", "legitimate_control"):
            for name in SCENARIOS[group]:
                with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                    with fixture("repairtrace", Path(tmp) / "trace.jsonl") as h:
                        success, evidence = evaluate(h, name)
                        self.assertTrue(success, evidence)

    def test_untracked_inputs_are_explicit_limits(self):
        for name in SCENARIOS["unsupported_boundary"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with fixture("repairtrace", Path(tmp) / "trace.jsonl") as h:
                    detected, _ = evaluate(h, name)
                    self.assertFalse(detected)

    def test_failed_retest_replaces_earlier_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            with fixture("repairtrace", Path(tmp) / "trace.jsonl") as h:
                h.session.run_tests()
                self.assertTrue(h.session.status()["current_full_test_pass"])
                (h.ws.repo / "tests.py").write_text("assert False\n")
                h.session.run_tests()
                self.assertFalse(h.session.status()["current_full_test_pass"])

    def test_timeout_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            with fixture("repairtrace", Path(tmp) / "trace.jsonl") as h:
                h.ws.command = lambda *args: {"exit_code": 0, "timed_out": True}
                h.session.run_tests()
                self.assertFalse(h.session.status()["current_full_test_pass"])

    def test_membership_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            with fixture("repairtrace", Path(tmp) / "trace.jsonl") as h:
                h.session.run_tests()
                p = h.ws.repo / "toyapp/new.py"
                p.write_text("value = 1\n")
                self.assertFalse(h.session.status()["current_full_test_pass"])
                h.session.run_tests()
                p.unlink()
                self.assertFalse(h.session.status()["current_full_test_pass"])

    def test_evidence_separation_and_minimal_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            with fixture("repairtrace", trace) as h:
                h.session.run_tests()
                sha = h.ws.source_hash()
                h.session.record_assessment("original_grading", candidate_sha256=sha,
                                            accepted=True, evidence_ref="grade.json")
                h.session.record_assessment("compatibility_review", candidate_sha256=sha,
                                            accepted=False, evidence_ref="review.json")
                self.assertTrue(h.session.status()["current_full_test_pass"])
            rows = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual([r["step"] for r in rows], list(range(len(rows))))
            self.assertNotIn("return a + b", trace.read_text())
            with self.assertRaises(FileExistsError):
                with fixture("repairtrace", trace): pass


if __name__ == "__main__": unittest.main()
