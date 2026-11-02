# RepairTrace

Source-bound verification evidence for Python coding agents.

RepairTrace connects edits and test results to the source version they concern.
Use it to reject stale or invalid replacements, distinguish selected tests from
full-suite verification, and recognize when a later edit makes a passing result
stale. Execution events are written to a local JSONL file for inspection.

## Quick start

Requirements: Python 3.10+ and Linux with `bash`, `unshare`, `mount`, `chroot`,
`setpriv`, and enabled user namespaces. The package has no Python runtime
dependencies beyond the standard library; installation may fetch build tools.
The examples need no model, GPU, API key, benchmark download, or network access.
Local validation used Python 3.12.

From the repository root:

```bash
python -m pip install .
repairtrace demo --trace demo.jsonl
repairtrace inspect demo.jsonl
```

The demo performs this sequence:

1. Apply a checked edit to a small arithmetic function.
2. Reject an edit that reuses the obsolete source digest.
3. Run the full test command and record a current pass.
4. Change the source and mark the earlier result stale.
5. Retest and record the failure.

Use a new trace filename for each run. Existing traces are never overwritten.
If the host disallows the required namespaces, the demo fails visibly; it does
not silently run agent commands directly on the host.

## Connect an agent

Create a `Workspace` with your repository, application virtual environment,
task-evidence directory, and the name of the production package. Configure the
trusted full-suite command when creating an `EvidenceSession`.

```python
from pathlib import Path
import shutil
from repairtrace import EvidenceSession, Workspace

workspace = Workspace(
    repo=Path("/path/to/repository"),
    venv=Path("/path/to/application-venv"),
    evidence=Path("/path/to/task-evidence"),
    package="myapp",
)
try:
    with EvidenceSession(
        workspace,
        "run.jsonl",
        full_test_command="python -m pytest",
        run_id="repair-001",
    ) as session:
        # Supply these callbacks to your agent loop.
        tools = {
            "read": session.read_file,
            "edit": session.edit_file,
            "test": session.run_tests,
            "status": session.status,
        }

        read = tools["read"]("myapp/calc.py")
        tools["edit"]("myapp/calc.py", read["sha256"], "a - b", "a + b")
        tools["test"]()  # configured full-suite command
        print(tools["status"]())
finally:
    shutil.rmtree(workspace.root)  # temporary execution root, not the repository
```

The paths and replacement above are illustrative. A complete scripted agent
using injected callbacks is included:

```bash
python examples/scripted_agent.py --trace second.jsonl
```

To run selected tests, supply a command explicitly:

```python
session.run_tests("python -m pytest tests/test_calc.py")
```

An explicit command is always recorded as **selected**, even if it happens to
match the configured full command. Selected tests cannot create full-suite
acceptance, but they do not erase a still-current full-suite pass.

## What the checks mean

**Edits.** A replacement must use the latest read digest, match exactly one
occurrence, change the bytes, and target an existing allowed production Python
file. The proposed contents are compiled using the application's interpreter
before replacement. Rejected edits leave source unchanged in the supported
single-writer workflow. A successful result includes before/after file digests
and the applied diff.

**Freshness.** Each completed test records its command, scope, exit status,
timeout flag, and production-source digests before and after execution.
`current_full_test_pass` requires the latest completed full-suite run to pass
without timing out, with unchanged source during execution, and with the same
current source digest. A failed full retest supersedes an earlier pass.

**Scope.** Freshness covers production `.py` paths and bytes in the configured
package, including additions and deletions. It excludes test files, configuration,
non-Python resources, stub files, and environment dependencies. Keep those inputs
and the full-suite command fixed within a session. Although the editor permits
`.pyi` edits, they are outside freshness coverage.

**Assessment.** `record_assessment` stores a caller-supplied `original_grading`
or `compatibility_review` decision with a candidate digest and evidence reference.
These records stay separate from test status. RepairTrace does not implement an
automatic semantic reviewer or infer correctness from passing tests.

**Execution.** `Workspace.command` uses a Linux namespace/chroot runtime with
read-only repository, dependency and evidence mounts. Temporary diagnostic files
can be written under `/tmp`. Commands called directly through the workspace are
not automatically recorded by `EvidenceSession`.

## Traces

Every event includes `schema_version` (`0.1`), `run_id`, contiguous `step`, `event`,
and elapsed milliseconds. The main event types are:

| Event | Evidence |
| --- | --- |
| `session_started` | Source identity, hashing scope and full test command |
| `source_read` | File path and digest |
| `edit_applied` | File/source digests before and after, test status |
| `edit_rejected` | Source digests and exception type |
| `tests_completed` | Command, scope, digests, timeout and pass/fail outcome |
| `test_error` | Scope, source digests and exception type |
| `original_grading`, `compatibility_review` | Caller-supplied decision and evidence reference |
| `session_closed` | Final source and verification status |

Traces omit prompts, source contents, diffs, command output and raw exception
messages. Caller-supplied paths, commands, IDs and assessment references are still
recorded; inspect them before sharing. The CLI checks schema version, sequence
and run identity, rather than fully validating every event field. An interrupted
run may have no closing event.

## Development checks

```bash
python -m unittest discover -s tests -v
python examples/workflow_check.py --output /tmp/repairtrace-checks
```

Use a fresh output directory. These commands exercise stale hashes, invalid and
protected edits, stale test results, test scope, legitimate operations, and
known excluded-input limitations. The workflow script includes deliberately
permissive component variants for inspecting the contribution of each check.
It writes per-scenario decisions and diagnostic traces; ablated decisions in
`results.json` may differ from the common recorder's stronger closing status.

The fixtures run **trusted toy commands on the host** to test bookkeeping without
requiring namespaces. Never use their `FixtureWorkspace` adapter for untrusted
agent execution. GitHub Actions runs these CPU checks. To check the production
runtime on a compatible Linux machine, use `repairtrace demo` and:

```bash
python -m workbench.demo
```

That additional demo checks rejection without mutation and a blocked attempt to
write to a protected test through the namespace shell.

## Boundaries

Use one trusted writer per workspace. Before/after hashes cannot detect a
concurrent change that is undone between snapshots. The execution runtime is
intended for local research, not hostile multi-tenant workloads. Test success
is conditional on the configured command and tracked inputs; it is not proof
of semantic correctness. Traces are neither tamper-proof nor deterministic
model replay. There is no automatic redaction or model-token accounting layer.

## Repository layout

```text
repairtrace/          Evidence interface and CLI
workbench/            Checked editor and namespace runtime
examples/             Scripted agent and trusted workflow checks
tests/                Regression tests
.github/workflows/    CPU CI configuration
pyproject.toml        Installation metadata
```

## License

A distribution license has not yet been selected. No open-source license is
currently granted by this repository.
