"""Scripted checks for editing and test-evidence behavior.

The permissive reference retains an exit-only pass flag and applies Python
str.replace without validation. Ablations change only editing or freshness.
Trusted toy commands run on the host to isolate bookkeeping from namespaces;
the production namespace runtime is exercised separately by repairtrace demo.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from repairtrace import EvidenceSession, Workspace

MODES = ("permissive", "without_edit_checks", "without_freshness", "repairtrace")


class FixtureWorkspace(Workspace):
    """TRUSTED FIXTURE ONLY: deliberately no namespace isolation."""
    def command(self, command, timeout=20):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(command, shell=True, cwd=self.repo, env=env,
                                capture_output=True, text=True, timeout=timeout)
        return {"exit_code": result.returncode, "output": result.stdout + result.stderr,
                "timed_out": False}


class Harness:
    def __init__(self, mode, ws, session):
        self.mode, self.ws, self.session = mode, ws, session

    def edit(self, path, sha, old, new):
        if self.mode in {"repairtrace", "without_freshness"}:
            return self.session.edit_file(path, sha, old, new)
        p = self.ws.repo / path
        p.write_text(p.read_text().replace(old, new))
        return {"status": "applied"}  # deliberately permissive reference

    def status(self):
        if self.mode not in {"permissive", "without_freshness"}:
            return self.session.status()
        tests = self.session.tests
        if self.mode == "without_freshness":
            tests = [t for t in tests if t["scope"] == "full"]
        return {"current_full_test_pass": bool(tests and tests[-1]["passed"])}


@contextmanager
def fixture(mode, trace):
    with tempfile.TemporaryDirectory(prefix="repairtrace-fixture-") as folder:
        root = Path(folder)
        repo = root / "repo"
        (repo / "toyapp").mkdir(parents=True)
        (repo / "toyapp/__init__.py").write_text("")
        (repo / "toyapp/calc.py").write_text("def add(a, b):\n    return a + b\n")
        (repo / "tests.py").write_text("from toyapp.calc import add\nassert add(2, 3) == 5\n")
        (repo / "selected.py").write_text("from toyapp.calc import add\nassert add(0, 0) == 0\n")
        (root / "outside.py").write_text("value = 1\n")
        (root / "evidence").mkdir()
        # Only compilation needs env/bin/python; no dependency installation.
        (root / "env/bin").mkdir(parents=True)
        (root / "env/bin/python").symlink_to(sys.executable)
        ws = FixtureWorkspace(repo, root / "env", root / "evidence", "toyapp")
        try:
            with EvidenceSession(ws, trace, full_test_command="python3 -B tests.py", run_id=trace.stem) as session:
                yield Harness(mode, ws, session)
        finally:
            shutil.rmtree(ws.root)


def inventory(root):
    # Independent byte oracle, not Workspace.source_hash or trace outcomes.
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*.py") if p.is_file()}


def oracle_pass(ws):
    return subprocess.run([sys.executable, "-B", "tests.py"], cwd=ws.repo,
                          capture_output=True).returncode == 0


def evaluate(h, scenario):
    ws, s = h.ws, h.session
    source = ws.repo / "toyapp/calc.py"
    edits = {"stale_hash", "missing_match", "ambiguous_match", "no_op", "invalid_syntax",
             "protected_test", "path_escape"}
    details = {}
    if scenario in edits:
        path, old, new = "toyapp/calc.py", "a + b", "a - b"
        if scenario == "ambiguous_match":
            source.write_text(source.read_text() + "# a + b\n")
        if scenario == "missing_match": old = "missing expression"
        if scenario == "no_op": new = old
        if scenario == "invalid_syntax": new = "a +"
        if scenario == "protected_test": path, old, new = "tests.py", "== 5", "== 0"
        if scenario == "path_escape": path, old, new = "../outside.py", "1", "2"
        sha = hashlib.sha256((ws.repo / path).read_bytes()).hexdigest()
        if scenario != "path_escape": s.read_file(path)
        if scenario == "stale_hash": sha = "0" * 64
        before = inventory(ws.repo.parent)
        rejected = False
        try: h.edit(path, sha, old, new)
        except ValueError: rejected = True
        unchanged = before == inventory(ws.repo.parent)
        return rejected and unchanged, {"rejected": rejected, "bytes_unchanged": unchanged}

    if scenario in {"stale_test", "test_file_change", "untracked_config_change"}:
        if scenario == "untracked_config_change":
            (ws.repo / "factor.txt").write_text("1")
            source.write_text("from pathlib import Path\ndef add(a,b):\n    return (a+b)*int(Path('factor.txt').read_text())\n")
        assert s.run_tests()["exit_code"] == 0
        if scenario == "stale_test":
            read = s.read_file("toyapp/calc.py")
            h.edit("toyapp/calc.py", read["sha256"], "a + b", "a - b")
        elif scenario == "test_file_change":
            # External mutation, outside the supported single-writer contract.
            (ws.repo / "tests.py").write_text("assert False\n")
        else:
            (ws.repo / "factor.txt").write_text("2")
        actual = oracle_pass(ws)
        assert not actual
        reported = h.status()["current_full_test_pass"]
        return not reported, {"fresh_oracle_pass": actual, "reported_current_full_pass": reported}

    if scenario == "selected_only":
        source.write_text(source.read_text().replace("a + b", "a - b"))
        assert s.run_tests("python3 -B selected.py")["exit_code"] == 0
        assert not oracle_pass(ws)
        reported = h.status()["current_full_test_pass"]
        return not reported, {"fresh_oracle_pass": False, "reported_current_full_pass": reported}

    if scenario == "mutation_during_test":
        (ws.repo / "tests.py").write_text("from pathlib import Path\np=Path('toyapp/calc.py')\np.write_text(p.read_text().replace('a + b','a - b'))\n")
        assert s.run_tests()["exit_code"] == 0
        changed = b"a - b" in source.read_bytes()
        reported = h.status()["current_full_test_pass"]
        return changed and not reported, {"source_changed_during_test": changed,
                                         "reported_current_full_pass": reported}

    if scenario == "valid_edit_retest":
        source.write_text(source.read_text().replace("a + b", "a - b"))
        read = s.read_file("toyapp/calc.py")
        h.edit("toyapp/calc.py", read["sha256"], "a - b", "a + b")
    elif scenario == "failed_suite":
        source.write_text(source.read_text().replace("a + b", "a - b"))
    s.run_tests()
    if scenario == "selected_after_full": s.run_tests("python3 -B selected.py")
    actual = oracle_pass(ws)
    reported = h.status()["current_full_test_pass"]
    return actual == reported, {"fresh_oracle_pass": actual, "reported_current_full_pass": reported}


SCENARIOS = {
    "supported_fault": ["stale_hash", "missing_match", "ambiguous_match", "no_op", "invalid_syntax",
                        "protected_test", "path_escape", "stale_test", "selected_only", "mutation_during_test"],
    "legitimate_control": ["valid_edit_retest", "full_pass", "failed_suite", "selected_after_full"],
    "unsupported_boundary": ["test_file_change", "untracked_config_change"],
}


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    traces = output / "traces"
    traces.mkdir(exist_ok=True)
    rows = []
    for mode in MODES:
        for group, names in SCENARIOS.items():
            for scenario in names:
                path = traces / f"{mode}-{scenario}.jsonl"
                with fixture(mode, path) as h:
                    success, evidence = evaluate(h, scenario)
                rows.append(dict(mode=mode, group=group, scenario=scenario,
                                 correct_handling=success, oracle=evidence))
    summary = {mode: {group: {"correct": sum(r["correct_handling"] for r in rows
                                            if r["mode"] == mode and r["group"] == group),
                             "total": len(names)} for group, names in SCENARIOS.items()} for mode in MODES}
    report = dict(protocol="workflow-checks-v1", scope="64 scripted executions; no model calls; fixed nonrandom fixtures",
                  runtime="trusted host fixture, not the namespace isolation runtime", summary=summary, rows=rows)
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Fresh output directory")
    args = parser.parse_args()
    print(json.dumps(run(args.output)["summary"], indent=2))
