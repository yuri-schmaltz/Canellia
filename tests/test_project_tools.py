import importlib.util
import json
from pathlib import Path
import unittest
import test_menu_editor as fixtures
core, APP = fixtures.core, fixtures.APP

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('projectTools', root/'Canellia@json/5.8/projectTools.py')
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)


class ProjectToolsTests(unittest.TestCase):
    setUp = fixtures.MenuEditorTests.setUp

    def test_profiles_round_trip_and_presets_preserve_internal_state(self):
        schema = json.loads((root/'Canellia@json/5.8/settings-schema.json').read_text())
        exported = tools.export_profile(schema)
        self.assertNotIn('categories', exported['settings'])
        self.assertNotIn('recent-apps', exported['settings'])
        self.assertEqual(tools.validate_profile(exported, schema), exported['settings'])
        for name in ('compact','grid','list'):
            self.assertTrue(tools.validate_profile(tools.preset(name, schema), schema))

    def test_invalid_profiles_never_apply(self):
        schema = json.loads((root/'Canellia@json/5.8/settings-schema.json').read_text())
        for document in [None, {}, {'format':'canellia-profile','version':2,'settings':{}},
            {'format':'canellia-profile','version':1,'settings':{'categories':[]}},
            {'format':'canellia-profile','version':1,'settings':{'custom-menu-width':True}},
            {'format':'canellia-profile','version':1,'settings':{'custom-menu-width':-10}},
            {'format':'canellia-profile','version':1,'settings':{'applications-view-mode':99}}]:
            with self.subTest(document=document), self.assertRaises(tools.ProfileError):
                tools.validate_profile(document, schema)

    def test_diagnostics_report_missing_commands_icons_and_duplicates(self):
        self.model.edit_application('editor.desktop', {'Exec':'/missing/canellia-test', 'Icon':'/missing/canellia-icon'})
        duplicate = self.model.duplicate('editor.desktop', ('Games',))
        findings = tools.diagnose(self.model)
        self.assertEqual({issue['kind'] for issue in findings}, {'command','icon','duplicate'})
        self.assertTrue(any(issue['id'] == duplicate for issue in findings))
        self.assertEqual(self.source.read_bytes(), APP)

    def test_backup_restore_is_reversible_and_rejects_external_changes(self):
        target = self.storage.data_home/'applications/editor.desktop'
        self.model.edit_application('editor.desktop', {'Name':'Changed'})
        backup = self.model.apply()
        reverse = self.storage.restore_backup(backup)
        self.assertFalse(target.exists())
        self.assertIsNotNone(reverse)
        self.storage.restore_backup(reverse)
        self.assertTrue(target.exists())
        target.write_bytes(b'external')
        with self.assertRaises(core.EditorError):
            self.storage.restore_backup(backup)
        self.assertEqual(target.read_bytes(), b'external')

    def test_damaged_or_future_backups_are_retained_and_not_restored(self):
        self.model.edit_application('editor.desktop', {'Name':'Changed'})
        backup = self.model.apply()
        journal = backup/'journal.json'
        record = json.loads(journal.read_text())
        record['version'] = 99
        journal.write_text(json.dumps(record))
        self.assertEqual(self.storage.list_backups()[0]['status'], 'invalid')
        with self.assertRaises(core.EditorError):
            self.storage.restore_backup(backup)
        self.assertTrue(journal.exists())

    def test_backup_path_traversal_cannot_read_or_write_external_files(self):
        self.model.edit_application('editor.desktop', {'Name':'Changed'})
        backup = self.model.apply()
        journal = backup/'journal.json'
        record = json.loads(journal.read_text())
        record['files'][0]['backup'] = '../../outside'
        journal.write_text(json.dumps(record))
        with self.assertRaises(core.EditorError):
            self.storage.restore_backup(backup)
        self.assertEqual(self.source.read_bytes(), APP)

    def test_recovery_preflights_all_files_before_writing(self):
        self.model.move(['editor.desktop'], ('Games',), ('Tools',))
        self.model.edit_application('editor.desktop', {'Name':'Changed'})
        backup = self.model.apply()
        journal = backup/'journal.json'
        record = json.loads(journal.read_text())
        record['status'] = 'pending'
        journal.write_text(json.dumps(record))
        first = Path(record['files'][0]['path'])
        last = Path(record['files'][-1]['path'])
        self.assertNotEqual(first, last)
        first.write_bytes(b'external conflict')
        last_before = last.read_bytes()
        with self.assertRaises(core.EditorError):
            self.storage.recover()
        self.assertEqual(first.read_bytes(), b'external conflict')
        self.assertEqual(last.read_bytes(), last_before)
        self.assertEqual(json.loads(journal.read_text())['status'], 'pending')

    def test_missing_backup_status_is_a_controlled_error(self):
        self.model.edit_application('editor.desktop', {'Name':'Changed'})
        backup = self.model.apply()
        journal = backup/'journal.json'
        record = json.loads(journal.read_text())
        del record['status']
        journal.write_text(json.dumps(record))
        self.assertEqual(self.storage.list_backups()[0]['status'], 'invalid')
        with self.assertRaises(core.EditorError):
            self.storage.recover()

    def test_numeric_profiles_accept_gtk_floats_and_reject_nonfinite(self):
        schema = json.loads((root/'Canellia@json/5.8/settings-schema.json').read_text())
        profile = {'format':'canellia-profile', 'version':1, 'settings':{'custom-menu-width':800.0}}
        self.assertEqual(tools.validate_profile(profile, schema)['custom-menu-width'], 800)
        for value in (float('nan'), float('inf'), -float('inf'), True):
            profile['settings']['custom-menu-width'] = value
            with self.assertRaises(tools.ProfileError):
                tools.validate_profile(profile, schema)

    def test_dbus_activated_launcher_does_not_require_exec(self):
        # Retain activation metadata like a native DBusActivatable desktop file.
        self.model.applications['editor.desktop'].document.set('DBusActivatable', True)
        self.model.edit_application('editor.desktop', {'Exec':'', 'Icon':'application-x-executable'})
        self.assertFalse(any(issue['kind'] in ('command','invalid') for issue in tools.diagnose(self.model)))
