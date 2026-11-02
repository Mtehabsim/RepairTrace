"""Source-bound evidence, not a semantic verifier or a tamper-proof ledger.

The configured full-suite command and environment are trusted inputs. Freshness
covers production .py files only.
Use one session/writer per workspace; concurrent or adversarial mutation is not
supported. Traces omit code, prompts, command output and exception messages.
"""
import json
import time
from pathlib import Path


class EvidenceSession:
    def __init__(self, workspace, trace_path, *, full_test_command, run_id="local"):
        if not full_test_command.strip():
            raise ValueError("Configure a nonempty full-suite command.")
        self.workspace = workspace
        self.full_test_command = full_test_command
        self.run_id = run_id
        self.tests = []
        self.step = 0
        self._file = Path(trace_path).open("x", encoding="utf-8")
        self._start = time.monotonic()
        self._emit("session_started", source_sha256=workspace.source_hash(),
                   source_scope="configured package: production .py files",
                   full_test_command=full_test_command)

    def _emit(self, event, **fields):
        record = dict(schema_version="0.1", run_id=self.run_id, step=self.step,
                      event=event, elapsed_ms=round((time.monotonic()-self._start)*1000, 3),
                      **fields)
        self._file.write(json.dumps(record, allow_nan=False) + "\n")
        self._file.flush()
        self.step += 1
        return record

    def read_file(self, path, **kwargs):
        result = self.workspace.read_file(path, **kwargs)
        self._emit("source_read", file=str(path), file_sha256=result["sha256"])
        return result

    def edit_file(self, path, expected_sha256, old_text, new_text):
        before = self.workspace.source_hash()
        try:
            result = self.workspace.edit_file(path, expected_sha256, old_text, new_text)
        except Exception as exc:
            self._emit("edit_rejected", source_before=before,
                       source_after=self.workspace.source_hash(), error_type=type(exc).__name__)
            raise
        self._emit("edit_applied", file=str(path), source_before=before,
                   source_after=self.workspace.source_hash(),
                   file_before=result["before_sha256"], file_after=result["after_sha256"],
                   test_status=self.status()["test_status"])
        return result

    def run_tests(self, selected_command=None, timeout=120):
        # A caller cannot promote arbitrary selected tests to full-suite evidence.
        scope = "full" if selected_command is None else "selected"
        command = self.full_test_command if selected_command is None else selected_command
        before = self.workspace.source_hash()
        try:
            result = self.workspace.command(command, timeout)
        except Exception as exc:
            self._emit("test_error", source_before=before,
                       source_after=self.workspace.source_hash(), scope=scope,
                       error_type=type(exc).__name__)
            raise
        after = self.workspace.source_hash()
        timed_out = bool(result.get("timed_out", False))
        passed = result["exit_code"] == 0 and not timed_out
        test = self._emit("tests_completed", command=command, scope=scope,
                          source_before=before, source_after=after,
                          source_unchanged=before == after, exit_code=result["exit_code"],
                          timed_out=timed_out, passed=passed)
        self.tests.append(test)
        return {**result, "evidence": test}

    def status(self):
        current = self.workspace.source_hash()
        last = self.tests[-1] if self.tests else None
        full = next((t for t in reversed(self.tests) if t["scope"] == "full"), None)
        def fresh(t):
            return bool(t and t["source_unchanged"] and t["source_after"] == current)
        state = ("untested" if last is None else "stale" if not fresh(last)
                 else "current_pass" if last["passed"] else "current_failure")
        return dict(source_sha256=current, test_status=state,
                    latest_test_step=last["step"] if last else None,
                    latest_test_scope=last["scope"] if last else None,
                    current_full_test_pass=bool(fresh(full) and full["passed"]))

    def record_assessment(self, kind, *, candidate_sha256, accepted, evidence_ref):
        """Record caller-supplied assessment; never infer semantics from test exit."""
        if kind not in {"original_grading", "compatibility_review"}:
            raise ValueError("Unknown assessment kind")
        if type(accepted) is not bool or not evidence_ref:
            raise ValueError("Assessment needs a boolean and an evidence reference")
        return self._emit(kind, candidate_sha256=candidate_sha256, accepted=accepted,
                          evidence_ref=str(evidence_ref), origin="caller_supplied")

    def close(self):
        if not self._file.closed:
            self._emit("session_closed", **self.status())
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
