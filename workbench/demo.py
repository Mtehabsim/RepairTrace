"""CPU-only packaging smoke test; no model, dataset or network needed."""
from pathlib import Path
import json
import shutil
import tempfile
import venv

from .workspace import Workspace


def main():
    with tempfile.TemporaryDirectory(prefix='repair-workbench-demo-') as folder:
        root = Path(folder)
        repo = root / 'repo'
        (repo / 'toyapp').mkdir(parents=True)
        (repo / 'toyapp/__init__.py').write_text('')
        (repo / 'toyapp/calc.py').write_text('def add(a, b):\n    return a - b\n')
        (repo / 'test_calc.py').write_text('from toyapp.calc import add\nassert add(2, 3) == 5\n')
        (root / 'evidence').mkdir()
        venv.EnvBuilder(with_pip=False, symlinks=True).create(root / 'env')
        workspace = Workspace(repo, root / 'env', root / 'evidence', 'toyapp')
        try:
            checked = []
            original = (repo / 'toyapp/calc.py').read_bytes()
            read = workspace.read_file('toyapp/calc.py')
            for label, old, new, sha in [
                ('stale', 'a - b', 'a + b', '0' * 64),
                ('no-op', 'a - b', 'a - b', read['sha256']),
                ('syntax', '    return a - b', 'return a + b', read['sha256']),
            ]:
                try:
                    workspace.edit_file('toyapp/calc.py', sha, old, new)
                except ValueError:
                    assert (repo / 'toyapp/calc.py').read_bytes() == original
                    checked.append(label + ' rejected without mutation')
                else:
                    raise AssertionError(label + ' was accepted')
            failing = workspace.command('python test_calc.py', 20)
            assert failing['exit_code'] != 0 and 'AssertionError' in failing['output'], failing
            readonly = workspace.command('printf wrong > test_calc.py', 20)
            assert readonly['exit_code'] != 0 and 'Read-only' in readonly['output'], readonly
            checked.append('shell cannot overwrite test')
            edit = workspace.edit_file('toyapp/calc.py', read['sha256'], 'a - b', 'a + b')
            test_hash = workspace.source_hash()
            passing = workspace.command('python test_calc.py', 20)
            assert passing['exit_code'] == 0, passing
            checked.append('applied edit passes original test')
            read = workspace.read_file('toyapp/calc.py')
            workspace.edit_file('toyapp/calc.py', read['sha256'], 'def add(a, b):', 'def add(a, b):  # later edit')
            assert workspace.source_hash() != test_hash
            checked.append('later edit changes source digest')
            print(json.dumps({'passed': True, 'checks': checked, 'applied_diff': edit['diff'],
                              'scope': 'CPU packaging smoke test, not a new model experiment.'}, indent=2))
        finally:
            shutil.rmtree(workspace.root)


if __name__ == '__main__':
    main()
