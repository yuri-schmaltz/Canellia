#!/usr/bin/env python3
"""Synthetic menu-editor CPU benchmark using temporary files only."""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('menuEditorCore', ROOT/'Canellia@json/5.8/menuEditorCore.py')
    core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = core
    spec.loader.exec_module(core)
    report = {}
    with tempfile.TemporaryDirectory(prefix='canellia-editor-benchmark-') as directory:
        root = Path(directory)
        storage = core.UserStorage(root/'config', root/'data', root/'state')
        apps = [core.Application(str(i)+'.desktop', core.DesktopFile(
            ('[Desktop Entry]\nType=Application\nName=Application '+str(i)+'\nExec=/usr/bin/true\nComment=Example editor\n').encode()),
            memberships={('Tools',): True}) for i in range(1000)]
        model = core.EditorModel(storage, [], apps)
        jobs = {
            'edit_and_undo_1000_apps': lambda: (model.edit_application('0.desktop', {'Comment': 'Changed'}), model.undo()),
            'filter_empty_1000_apps': lambda: model.search('', visibility='visible'),
            'search_1000_apps': lambda: model.search('example editor', visibility='visible'),
        }
        for name, job in jobs.items():
            samples = []
            for repetition in range(8):
                start = time.perf_counter()
                job()
                duration = (time.perf_counter()-start)*1000
                if repetition:
                    samples.append(duration)
            report[name] = {'median_ms': statistics.median(samples), 'samples_ms': samples}
            print(name, report[name]['median_ms'])
        assert model.applications['0.desktop'].document.get('Comment') == 'Example editor'
        assert not model.dirty
        assert not list((root/'data').rglob('*.desktop'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
