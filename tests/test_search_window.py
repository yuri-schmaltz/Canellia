"""Exercise worker/UI boundaries without requiring an installed GTK desktop."""
import importlib.util
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SearchWindowTests(unittest.TestCase):
    def load_window(self, version):
        main_thread = threading.get_ident()
        callbacks = {}
        GLib = types.SimpleNamespace(SOURCE_REMOVE=False, SOURCE_CONTINUE=True, Error=OSError)
        GLib.timeout_add = lambda delay, callback: callbacks.setdefault(1, callback) and 1
        GLib.source_remove = lambda identifier: callbacks.pop(identifier, None)
        Gtk = types.SimpleNamespace(Entry=object, Menu=object, Window=object,
                                   IconTheme=types.SimpleNamespace(get_default=lambda: types.SimpleNamespace(has_icon=lambda name: True)))
        Gio = types.SimpleNamespace(File=types.SimpleNamespace(new_for_path=lambda path: types.SimpleNamespace(
            query_info=lambda *args: types.SimpleNamespace(get_icon=lambda: types.SimpleNamespace(get_names=lambda: ['text-x-generic'])))))
        gi = types.ModuleType('gi')
        gi.require_version = lambda *args: None
        repository = types.ModuleType('gi.repository')
        for name, value in dict(Gio=Gio, Gtk=Gtk, GLib=GLib, GObject=object, Pango=object, GdkPixbuf=object).items():
            setattr(repository, name, value)
        base = ROOT / 'Canellia@json' / version
        spec = importlib.util.spec_from_file_location('search_window', base / 'search.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository}), patch.object(sys, 'path', [str(base)] + sys.path):
            sys.modules.pop('searchEngine', None)
            spec.loader.exec_module(module)

        def guard(value):
            self.assertEqual(threading.get_ident(), main_thread, 'GTK accessed by a worker')
            return value

        instance = object.__new__(module.SearchWindow)
        instance.search = None
        instance._cancel = None
        instance._generation = 0
        instance._closed = False
        instance._poll = 0
        instance.searching = False
        instance.location = types.SimpleNamespace(get_filename=lambda: guard(str(ROOT)))
        instance.searchBox = types.SimpleNamespace(get_text=lambda: guard('README'))
        instance.hidden = types.SimpleNamespace(get_active=lambda: guard(False))
        instance.symlinks = types.SimpleNamespace(get_active=lambda: guard(False))
        instance.regex = types.SimpleNamespace(get_active=lambda: guard(False))
        statuses = []
        rows = []
        instance.stopButton = types.SimpleNamespace(set_sensitive=lambda value: guard(value))
        instance.results = types.SimpleNamespace(clear=lambda: guard(rows.clear()), append=lambda row: guard(rows.append(row)))
        instance.currentLabel = types.SimpleNamespace(set_text=lambda text: guard(statuses.append(text)))
        return instance, callbacks, statuses, rows

    def test_worker_never_touches_gtk(self):
        for version in ('4.0', '5.8'):
            instance, callbacks, statuses, rows = self.load_window(version)
            instance.startSearch()
            instance.search.join(timeout=3)
            self.assertFalse(instance.search.is_alive())
            self.assertFalse(callbacks[1]())
            self.assertFalse(instance.searching)
            self.assertIn('Search Completed', statuses[-1])
            self.assertEqual([row[1] for row in rows], ['README.md'])

    def test_invalid_regex_stays_on_ui_thread(self):
        for version in ('4.0', '5.8'):
            instance, callbacks, statuses, rows = self.load_window(version)
            instance.searchBox.get_text = lambda: '['
            instance.regex.get_active = lambda: True
            instance.startSearch()
            self.assertFalse(callbacks)
            self.assertFalse(instance.searching)
            self.assertTrue(statuses[-1])
            self.assertFalse(rows)

    def test_stop_never_joins_worker_or_renders_stale_results(self):
        for version in ('4.0', '5.8'):
            instance, callbacks, statuses, rows = self.load_window(version)
            instance.startSearch()
            worker = instance.search
            callback = callbacks[1]
            instance.stopSearch()
            worker.join(timeout=3)
            self.assertFalse(callback())
            self.assertEqual(rows, [])
            self.assertFalse(instance.searching)
            self.assertFalse(callbacks)
