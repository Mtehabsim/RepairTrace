"""Exercise the production editor/runtime and explicit freshness interface."""
import shutil
import tempfile
import venv
from pathlib import Path
from . import EvidenceSession, Workspace


def run(trace):
    with tempfile.TemporaryDirectory(prefix="repairtrace-demo-") as folder:
        root = Path(folder)
        repo = root / "repo"
        (repo / "toyapp").mkdir(parents=True)
        (repo / "toyapp/__init__.py").write_text("")
        (repo / "toyapp/calc.py").write_text("def add(a, b):\n    return a - b\n")
        (repo / "test_calc.py").write_text("from toyapp.calc import add\nassert add(2, 3) == 5\n")
        (root / "evidence").mkdir()
        venv.EnvBuilder(with_pip=False, symlinks=True).create(root / "env")
        ws = Workspace(repo, root / "env", root / "evidence", "toyapp")
        try:
            with EvidenceSession(ws, trace, full_test_command="python test_calc.py", run_id="cpu-demo") as session:
                read = session.read_file("toyapp/calc.py")
                session.edit_file("toyapp/calc.py", read["sha256"], "a - b", "a + b")
                try:
                    session.edit_file("toyapp/calc.py", read["sha256"], "a + b", "a - b")
                except ValueError:
                    pass
                else:
                    raise AssertionError("Stale edit accepted")
                assert session.run_tests()["exit_code"] == 0
                assert session.status()["current_full_test_pass"]
                read = session.read_file("toyapp/calc.py")
                session.edit_file("toyapp/calc.py", read["sha256"], "a + b", "a - b")
                stale = session.status()
                assert stale["test_status"] == "stale" and not stale["current_full_test_pass"]
                assert session.run_tests()["exit_code"] != 0
            return {"passed": True, "trace": str(trace), "stale_status": stale,
                    "scope": "New CPU packaging validation; no model calls."}
        finally:
            shutil.rmtree(ws.root)
