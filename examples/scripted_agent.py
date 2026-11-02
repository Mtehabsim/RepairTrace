"""Second integration: a tiny plan dispatcher, no LLM and no framework claim.

Run from the resource root: python examples/scripted_agent.py --trace second.jsonl
Uses the production namespace runtime; requires the same host support as demo.
"""
import argparse
from pathlib import Path
import shutil
import tempfile
import venv
from repairtrace import EvidenceSession, Workspace


def dispatch_agent(tools):
    """Agent knows only three injected callbacks, not RepairTrace internals."""
    plan = ["read", "replace", "verify"]
    context = {}
    for action in plan:
        if action == "read": context["read"] = tools["read"]("toyapp/calc.py")
        elif action == "replace":
            tools["replace"]("toyapp/calc.py", context["read"]["sha256"], "a - b", "a + b")
        else: context["verified"] = tools["verify"]()["exit_code"] == 0
    return context["verified"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "repo/toyapp").mkdir(parents=True)
        (root / "repo/toyapp/__init__.py").write_text("")
        (root / "repo/toyapp/calc.py").write_text("def add(a,b):\n    return a - b\n")
        (root / "repo/tests.py").write_text("from toyapp.calc import add\nassert add(2,3)==5\n")
        (root / "evidence").mkdir()
        venv.EnvBuilder(with_pip=False, symlinks=True).create(root / "env")
        ws = Workspace(root / "repo", root / "env", root / "evidence", "toyapp")
        try:
            with EvidenceSession(ws, args.trace, full_test_command="python tests.py", run_id="scripted-agent") as session:
                assert dispatch_agent({"read": session.read_file, "replace": session.edit_file,
                                       "verify": session.run_tests})
                assert session.status()["current_full_test_pass"]
        finally:
            shutil.rmtree(ws.root)
    print("Scripted integration passed; no model was used.")


if __name__ == "__main__": main()
