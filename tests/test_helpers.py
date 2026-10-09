from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(version, name):
    base = ROOT / 'Canellia@json' / version
    spec = importlib.util.spec_from_file_location(name, base / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    # Keep per-version sibling imports consistent.
    with patch.object(sys, 'path', [str(base)] + sys.path):
        for sibling in ('browserData', 'getFavicons'):
            sys.modules.pop(sibling, None)
        spec.loader.exec_module(module)
    return module


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / 'profile'
        self.profile.mkdir()
        with closing(sqlite3.connect(self.profile / 'History')) as database, database:
            database.execute('CREATE TABLE urls(url TEXT, title TEXT, last_visit_time INTEGER, visit_count INTEGER)')
            database.executemany('INSERT INTO urls VALUES(?,?,?,?)', [
                ('https://example.com/old', 'Cinnamon old', 1, 2),
                ('https://example.com/new', 'Cinnamon new', 20, 1),
                ('https://example.com/literal', '100% test_name', 30, 1),
                ('https://example.com/plain', '1000 testXname', 40, 1),
                ('javascript:alert(1)', 'Cinnamon unsafe', 50, 1),
                ('https://example.com/null', None, 60, 1)])

    def test_history_order_and_missing_favicons(self):
        for version in ('4.0', '5.8'):
            with self.subTest(version=version):
                module = load(version, 'searchHistory')
                results = module.search_history(self.profile, 'Cinnamon')
                self.assertEqual([r['name'] for r in results], ['Cinnamon new', 'Cinnamon old'])
                self.assertFalse((self.profile / 'Favicons').exists())

    def test_history_empty_query_and_literal_wildcards(self):
        for version in ('4.0', '5.8'):
            module = load(version, 'searchHistory')
            self.assertEqual(module.search_history(self.profile, '  '), [])
            for query in ('100%', 'test_name', '100% test_name'):
                self.assertEqual([r['name'] for r in module.search_history(self.profile, query)], ['100% test_name'])
            self.assertEqual(module.search_history(self.profile, "' OR 1=1 --"), [])

    def test_missing_and_corrupt_history_emit_json(self):
        for version in ('4.0', '5.8'):
            executable = ROOT / 'Canellia@json' / version / 'searchHistory.py'
            for profile in (self.root / 'missing', self.profile):
                if profile == self.profile: (profile / 'History').write_text('corrupt')
                result = subprocess.run([str(executable), str(profile), 'Cinnamon'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [])

    def test_snapshot_includes_committed_wal(self):
        for version in ('4.0', '5.8'):
            with self.subTest(version=version):
                source = self.root / ('wal-' + version)
                live = sqlite3.connect(source)
                self.addCleanup(live.close)
                live.execute('PRAGMA journal_mode=WAL')
                live.execute('CREATE TABLE values_table(value TEXT)')
                live.execute("INSERT INTO values_table VALUES('committed')")
                live.commit()
                module = load(version, 'browserData')
                snapshot = module.snapshot(source)
                try:
                    self.assertEqual(snapshot.execute('SELECT value FROM values_table').fetchone()[0], 'committed')
                finally:
                    snapshot.close()

    def test_favicons_largest_bitmap_and_profile_isolation(self):
        for version in ('4.0', '5.8'):
            module = load(version, 'getFavicons')
            module.FAVICON_CACHE_DIR = self.root / ('cache-' + version)
            for index in (1, 2):
                path = self.root / ('Favicons-' + str(index))
                if path.exists(): path.unlink()
                with closing(sqlite3.connect(path)) as database, database:
                    database.execute('CREATE TABLE icon_mapping(page_url TEXT, icon_id INTEGER)')
                    database.execute('CREATE TABLE favicon_bitmaps(icon_id INTEGER, image_data BLOB, width INTEGER, height INTEGER)')
                    database.execute("INSERT INTO icon_mapping VALUES('https://example.com/page', 1)")
                    database.executemany('INSERT INTO favicon_bitmaps VALUES(?,?,?,?)', [(1, b'small', 16, 16), (1, ('large-' + str(index)).encode(), 32, 32)])
                icons = module.get_favicons(path, ['https://example.com'])
                self.assertEqual(Path(icons['https://example.com']).read_bytes(), ('large-' + str(index)).encode())

    def test_favicon_cache_failure_does_not_discard_history(self):
        for version in ('4.0', '5.8'):
            module = load(version, 'searchHistory')
            with patch.object(module, 'get_favicons', return_value={}):
                self.assertEqual(len(module.search_history(self.profile, 'Cinnamon')), 2)
            icons = load(version, 'getFavicons')
            blocked = self.root / ('blocked-' + version)
            blocked.write_text('not a directory')
            icons.FAVICON_CACHE_DIR = blocked
            self.assertEqual(icons.get_favicons(self.profile / 'History', ['https://example.com']), {})

    def test_file_search_hidden_casefold_and_symlink_cycles(self):
        tree = self.root / 'tree'
        tree.mkdir()
        (tree / 'Visible.txt').touch()
        (tree / '.hidden.txt').touch()
        (tree / 'nested').mkdir()
        (tree / 'nested/deep.txt').touch()
        (tree / 'nested/cycle').symlink_to(tree, target_is_directory=True)
        for version in ('4.0', '5.8'):
            engine = load(version, 'searchEngine')
            results = list(engine.search_files(tree, engine.compile_matcher('.TXT'), follow_symlinks=True))
            self.assertEqual(sorted(r[0] for r in results), ['Visible.txt', 'deep.txt'])
            results = list(engine.search_files(tree, engine.compile_matcher('.txt'), hidden=True))
            self.assertEqual(len(results), 3)
            with self.assertRaises(Exception): engine.compile_matcher('[', regex=True)

    def test_file_search_cancellation_and_missing_root(self):
        for version in ('4.0', '5.8'):
            engine = load(version, 'searchEngine')
            cancel = threading.Event()
            cancel.set()
            self.assertEqual(list(engine.search_files(self.root, engine.compile_matcher(''), cancel=cancel)), [])
            with self.assertRaises(ValueError): list(engine.search_files(None, engine.compile_matcher('')))

    def test_snapshot_timeout_closes_both_connections(self):
        for version in ('4.0', '5.8'):
            module = load(version, 'browserData')
            closed = []
            class Connection:
                def close(self): closed.append(self)
                def backup(self, destination, **options):
                    options['progress'](0, 1, 1)
            source, destination = Connection(), Connection()
            with patch.object(module.sqlite3, 'connect', side_effect=[source, destination]), \
                 patch.object(module.time, 'monotonic', side_effect=[0, 4]):
                with self.assertRaises(TimeoutError): module.snapshot(self.profile / 'History')
            self.assertEqual(set(closed), {source, destination})
