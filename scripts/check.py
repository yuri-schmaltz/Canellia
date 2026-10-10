#!/usr/bin/env python3
"""Repository checks using Python, Node.js and gettext; no desktop required."""
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    for tool in ('node', 'msgfmt', 'bash'):
        if not shutil.which(tool):
            raise SystemExit('Missing verification dependency: ' + tool)
    for path in (ROOT / 'Canellia@json').rglob('*.py'):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('_editor_module', '_module'):
                module = ast.literal_eval(node.args[0])
                if not (path.parent / (module + '.py')).is_file():
                    raise SystemExit('Missing menu editor module: ' + module)
            modules = ([node.module] if isinstance(node, ast.ImportFrom) else
                       [name.name for name in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                if module in ('browserData', 'getFavicons', 'searchEngine', 'menuEditorCore', 'menuEditorTree') and not (path.parent / (module + '.py')).is_file():
                    raise SystemExit('Missing Python module: ' + module)
    for path in (ROOT / 'Canellia@json').rglob('*.json'):
        json.loads(path.read_text())
    for path in (ROOT / 'Canellia@json').rglob('*.js'):
        for helper in re.findall(r"runJsonScript\(['\"]([^'\"]+\.py)['\"]", path.read_text()):
            if not (path.parent / helper).is_file():
                raise ValueError('Missing subprocess helper: ' + helper)

        run('node', '--check', str(path))
        for module in re.findall(r"require\(['\"](\./[^'\"]+)['\"]\)", path.read_text()):
            if not (path.parent / (module + '.js')).is_file():
                raise SystemExit('Missing module: ' + module)
    for version in ('4.0', '5.8'):
        base = ROOT / 'Canellia@json' / version
        schema = json.loads((base / 'settings-schema.json').read_text())
        custom_nodes = list(schema.values()) + list(schema['layout'].values())
        for node in custom_nodes:
            if not isinstance(node, dict) or node.get('type') != 'custom':
                continue
            module = base / node['file']
            classes = {item.name for item in ast.parse(module.read_text()).body if isinstance(item, ast.ClassDef)}
            if node['widget'] not in classes:
                raise SystemExit('Missing custom settings class: ' + node['widget'])
        bound = re.findall(r"key:\s*'([^']+)'", (base / 'applet.js').read_text())
        if set(bound) - schema.keys():
            raise SystemExit('Missing settings: ' + version)
        for value in schema.get('layout', {}).values():
            if isinstance(value, dict) and set(value.get('keys', [])) - schema.keys():
                raise SystemExit('Missing layout settings: ' + version)
    # Cinnamon requires version-specific entrypoints; common helpers stay identical.
    for name in ('process.js', 'browserHistory.js', 'browserData.py', 'getFavicons.py',
                 'searchHistory.py', 'search.py', 'searchEngine.py', 'MenuEditorPage.py',
                 'menuEditorCore.py', 'menuEditorTree.py', 'settingsWindow.py', 'calculator.js', 'ToolsPage.py', 'projectTools.py', 'firefoxBookmarks.py'):
        if (ROOT / 'Canellia@json/4.0' / name).read_bytes() != (ROOT / 'Canellia@json/5.8' / name).read_bytes():
            raise SystemExit('Common helper diverged: ' + name)
    for path in ROOT.rglob('*.sh'):
        run('bash', '-n', str(path))
    for path in (ROOT / 'Canellia@json/po').glob('*.po'):
        run('msgfmt', '--check', '-o', '/dev/null', str(path))
    run(sys.executable, '-W', 'error::ResourceWarning', '-m', 'unittest', 'discover', '-s', 'tests', '-v')
    run('node', '--test', *[str(p.relative_to(ROOT)) for p in sorted((ROOT / 'tests').glob('*.test.js'))])
    print('All checks passed. Desktop smoke testing remains required before a release.')


if __name__ == '__main__':
    main()
