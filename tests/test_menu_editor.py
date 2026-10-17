"""Pure editing/storage regression tests; all files stay in temporary XDG roots."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('menuEditorCore', ROOT / 'Canellia@json/5.8/menuEditorCore.py')
core = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = core
spec.loader.exec_module(core)
APP = b'[Desktop Entry]\nType=Application\nName=Editor\nName[pt_BR]=Edi\\s\\u00e7\\u00e3o\nExec=/usr/bin/true %f\nComment=Text editor\nIcon=accessories-text-editor\nCategories=Utility;\nX-Vendor=keep\nActions=New;\n\n[Desktop Action New]\nName=New window\nExec=/usr/bin/true\n'
# A real UTF-8 translation (the byte literal above keeps fixture construction simple).
APP = APP.replace(b'Edi\\s\\u00e7\\u00e3o', 'Edição'.encode())
DIRECTORY = b'[Desktop Entry]\nType=Directory\nName=Tools\nIcon=folder\n'


class MenuEditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = core.UserStorage(self.root / 'config', self.root / 'data', self.root / 'state')
        self.source = self.root / 'system/applications/editor.desktop'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(APP)
        self.categories = [core.Category((), 'Applications'), core.Category(('Tools',), 'Tools', directory_id='tools.directory', document=core.DesktopFile(DIRECTORY), fallback=DIRECTORY), core.Category(('Games',), 'Games')]
        self.app = core.Application('editor.desktop', core.DesktopFile(APP), self.source, APP, {('Tools',): True})
        self.model = core.EditorModel(self.storage, self.categories, [self.app])

    def test_editor_is_first_tab_and_tips_and_launcher_are_removed(self):
        for version in ('4.0', '5.8'):
            schema = json.loads((ROOT / 'Canellia@json' / version / 'settings-schema.json').read_text())
            self.assertEqual(schema['layout']['pages'], ['editor', 'layout', 'behaviour', 'search', 'appearance', 'tools'])
            self.assertNotIn('tips', schema['layout'])
            self.assertNotIn('menu-editor-button', schema)
            self.assertFalse(any(key.startswith('info') for key in schema))
            text = (ROOT / 'Canellia@json' / version / 'MenuEditorPage.py').read_text()
            self.assertNotIn('cme.', text)
            self.assertNotIn('Gtk.main(', text)

    def test_edit_is_pending_preserves_metadata_and_locales(self):
        with patch.dict(os.environ, {'LANG': 'pt_BR.UTF-8', 'LC_ALL': '', 'LC_MESSAGES': ''}):
            self.model.edit_application('editor.desktop', {'Name': 'Meu editor', 'Exec': '/usr/bin/true %u'})
        self.assertEqual(self.source.read_bytes(), APP)
        target = self.storage.data_home / 'applications/editor.desktop'
        self.assertFalse(target.exists())
        data = self.model.pending[target]
        self.assertIn(b'Name[pt_BR]=Meu editor', data)
        self.assertIn(b'X-Vendor=keep', data)
        self.assertIn(b'[Desktop Action New]', data)
        self.model.apply()
        self.assertEqual(target.read_bytes(), data)
        self.assertFalse(self.model.dirty)
        self.assertEqual(self.source.read_bytes(), APP)

    def test_undo_redo_and_discard_do_not_write(self):
        self.model.edit_application('editor.desktop', {'Name': 'Changed'})
        self.model.move(['editor.desktop'], ('Games',), ('Tools',))
        self.model.undo()
        self.assertNotIn(('Games',), self.model.applications['editor.desktop'].memberships)
        self.model.redo()
        self.assertTrue(self.model.applications['editor.desktop'].memberships[('Games',)])
        self.model.discard()
        self.assertEqual(self.model.applications['editor.desktop'].name, core.DesktopFile(APP).localized('Name'))
        self.assertFalse(self.model.dirty)
        self.assertFalse((self.storage.data_home / 'applications').exists())

    def test_move_and_add_have_different_semantics(self):
        self.model.move(['editor.desktop'], ('Games',), ('Tools',), add=True)
        self.assertTrue(self.model.applications['editor.desktop'].memberships[('Tools',)])
        self.model.move(['editor.desktop'], ('Games',), ('Tools',))
        self.assertFalse(self.model.applications['editor.desktop'].memberships[('Tools',)])
        xml = ET.fromstring(self.model.pending[self.model.menu_path])
        self.assertEqual(xml.find('MergeFile').get('type'), 'parent')
        self.assertEqual(xml.find("Menu[Name='Tools']/Exclude/Filename").text, 'editor.desktop')
        self.assertEqual(xml.find("Menu[Name='Games']/Include/Filename").text, 'editor.desktop')

    def test_batch_visibility_and_atomic_failure(self):
        second = core.Application('second.desktop', core.DesktopFile(APP), memberships={('Tools',): True})
        self.model.applications[second.id] = second
        self.model.set_visible(['editor.desktop', 'second.desktop'], False)
        self.assertFalse(self.model.applications['second.desktop'].visible)
        self.model.undo()
        before = self.model._snapshot()
        with self.assertRaises(KeyError): self.model.set_visible(['editor.desktop', 'missing'], False)
        self.assertEqual(self.model.pending, before[3])
        self.assertTrue(self.model.applications['editor.desktop'].visible)

    def test_hide_in_one_category_keeps_other_membership(self):
        self.model.move(['editor.desktop'], ('Games',), add=True)
        self.model.set_visible(['editor.desktop'], False, ('Tools',))
        app = self.model.applications['editor.desktop']
        self.assertTrue(app.visible)
        self.assertFalse(app.memberships[('Tools',)])
        self.assertTrue(app.memberships[('Games',)])

    def test_search_ignores_accents_and_filters_hidden(self):
        self.model.edit_application('editor.desktop', {'Name': 'Edição'})
        self.assertEqual(len(self.model.search('edicao true')), 1)
        self.model.set_visible(['editor.desktop'], False)
        self.assertEqual(len(self.model.search(visibility='hidden')), 1)
        self.assertEqual(self.model.search(visibility='visible'), [])

    def test_new_launcher_requires_command_before_apply(self):
        item_id = self.model.create_application(('Tools',))
        with self.assertRaises(core.EditorError): self.model.apply()
        self.assertFalse((self.storage.data_home / 'applications' / item_id).exists())
        self.model.edit_application(item_id, {'Exec': '/usr/bin/true', 'Name': 'New'})
        self.model.apply()
        self.assertTrue((self.storage.data_home / 'applications' / item_id).exists())

    def test_duplicate_is_independent_and_remove_is_reversible(self):
        item_id = self.model.duplicate('editor.desktop', ('Games',))
        self.model.edit_application(item_id, {'Name': 'Copy'})
        self.assertNotEqual(self.model.applications[item_id].name, self.model.applications['editor.desktop'].name)
        self.model.remove([item_id])
        self.assertNotIn(item_id, self.model.applications)
        self.model.undo()
        self.assertIn(item_id, self.model.applications)

    def test_system_remove_and_individual_restore(self):
        self.model.remove(['editor.desktop'])
        self.assertEqual(self.model.applications['editor.desktop'].document.get('Hidden'), 'true')
        self.model.apply()
        override = self.storage.data_home / 'applications/editor.desktop'
        self.assertTrue(override.exists())
        self.model.restore_applications(['editor.desktop'])
        self.model.apply()
        self.assertFalse(override.exists())
        self.assertEqual(self.source.read_bytes(), APP)

    def test_nested_user_launcher_is_edited_in_place(self):
        nested = self.storage.data_home / 'applications/vendor/editor.desktop'
        nested.parent.mkdir(parents=True)
        nested.write_bytes(APP)
        app = core.Application('vendor-editor.desktop', core.DesktopFile(APP), nested, APP, {('Tools',): True})
        model = core.EditorModel(self.storage, self.categories, [app])
        model.edit_application(app.id, {'Name': 'Nested'})
        model.apply()
        self.assertIn(b'Name=Nested', nested.read_bytes())
        self.assertFalse((nested.parent.parent / app.id).exists())
        model.restore_applications([app.id])
        model.apply()
        self.assertFalse(nested.exists())

    def test_custom_filter_includes_pending_personalization(self):
        self.assertEqual(self.model.search(visibility='custom'), [])
        self.model.edit_application('editor.desktop', {'Name': 'Custom'})
        self.assertEqual(len(self.model.search(visibility='custom')), 1)

    def test_editing_command_retains_unchanged_localized_name(self):
        with patch.dict(os.environ, {'LANG': 'pt_BR.UTF-8', 'LC_ALL': '', 'LC_MESSAGES': ''}):
            self.model.edit_application('editor.desktop', {'Name': 'Edição', 'Exec': '/usr/bin/true %u'})
        self.assertEqual(self.model.applications['editor.desktop'].document.get('Name'), 'Editor')
        self.assertIn('Name[pt_BR]=Edição'.encode(), self.model.applications['editor.desktop'].document.to_bytes())

    def test_undo_frame_retains_only_affected_applications(self):
        for index in range(100):
            item_id = str(index) + '.desktop'
            self.model.applications[item_id] = core.Application(item_id, core.DesktopFile(APP))
        self.model.edit_application('editor.desktop', {'Name': 'Changed'})
        self.assertEqual(set(self.model.undo_stack[-1][0][2]), {'editor.desktop'})

    def test_category_create_edit_hide_restore(self):
        path = self.model.create_category(('Tools',), 'Personal')
        self.model.edit_category(path, 'Renamed', 'folder-documents', visible=False)
        self.assertFalse(self.model.categories[path].visible)
        self.model.undo()
        self.assertEqual(self.model.categories[path].name, 'Personal')
        self.model.edit_category(('Tools',), 'Changed', 'folder')
        self.model.restore_category(('Tools',))
        self.assertEqual(self.model.categories[('Tools',)].name, 'Tools')
        self.model.apply()

    def test_existing_xml_preserves_unknown_rules_comments_and_layout(self):
        data = b'<Menu><Name>Applications</Name><!--keep--><MergeFile type="parent"/><Menu><Name>Tools</Name><Include><And><Category>Utility</Category><Not><Category>Game</Category></Not></And><Filename>other.desktop</Filename></Include><Layout><Merge type="all"/></Layout></Menu></Menu>'
        self.model.menu = core.MenuDocument(data)
        self.model.move(['editor.desktop'], ('Tools',), add=True)
        result = self.model.menu.to_bytes()
        self.assertIn(b'<!--keep-->', result)
        self.assertIn(b'<And>', result)
        self.assertIn(b'<Filename>other.desktop</Filename>', result)
        self.assertIn(b'<Layout>', result)

    def test_invalid_command_does_not_change_model(self):
        for command in ('"unterminated', '/usr/bin/true %Z', '/usr/bin/true %f %u', '/usr/bin/true\nfalse'):
            with self.subTest(command=command), self.assertRaises(core.EditorError):
                self.model.edit_application('editor.desktop', {'Exec': command})
        self.assertFalse(self.model.dirty)
        self.assertEqual(self.model.applications['editor.desktop'].document.get('Exec'), '/usr/bin/true %f')

    def test_literal_percent_does_not_count_as_a_field_code(self):
        self.model.edit_application('editor.desktop', {'Exec': '/usr/bin/true 100%% %%f %u'})
        self.model.apply()
        self.assertEqual(self.model.applications['editor.desktop'].document.get('Exec'), '/usr/bin/true 100%% %%f %u')

    def test_conflicting_source_blocks_save_and_retains_pending(self):
        self.model.edit_application('editor.desktop', {'Name': 'Changed'})
        self.source.write_bytes(APP + b'#external\n')
        with self.assertRaises(core.EditorError): self.model.apply()
        self.assertTrue(self.model.dirty)
        self.assertFalse((self.storage.data_home / 'applications/editor.desktop').exists())

    def test_backup_contains_originals_and_commit_journal(self):
        path = self.storage.data_home / 'applications/editor.desktop'
        path.parent.mkdir(parents=True)
        path.write_bytes(APP)
        backup = self.storage.commit({path: b'new'}, {path: APP})
        journal = json.loads((backup / 'journal.json').read_text())
        self.assertEqual(journal['status'], 'committed')
        self.assertEqual((backup / journal['files'][0]['backup']).read_bytes(), APP)
        self.assertEqual(path.read_bytes(), b'new')

    def test_failed_multi_file_commit_rolls_back(self):
        paths = [self.storage.data_home / 'applications/a.desktop', self.storage.config_home / 'menus/a.menu']
        for path in paths:
            path.parent.mkdir(parents=True)
            path.write_bytes(b'before')
        atomic = self.storage.atomic
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path == paths[1] and data == b'after' and not failed:
                failed = True
                raise OSError('disk full')
            return atomic(path, data)
        with patch.object(self.storage, 'atomic', side_effect=fail_once):
            with self.assertRaises(core.EditorError):
                self.storage.commit({path: b'after' for path in paths}, {path: b'before' for path in paths})
        self.assertEqual([path.read_bytes() for path in paths], [b'before', b'before'])

    def test_crash_recovery_restores_partial_transaction(self):
        paths = [self.storage.data_home / 'applications/a.desktop', self.storage.config_home / 'menus/a.menu']
        atomic = self.storage.atomic
        def simulated_crash(path, data):
            if path == paths[1]: raise KeyboardInterrupt()
            return atomic(path, data)
        with patch.object(self.storage, 'atomic', side_effect=simulated_crash):
            with self.assertRaises(KeyboardInterrupt): self.storage.commit({path: b'after' for path in paths}, {path: None for path in paths})
        self.assertTrue(paths[0].exists())
        self.storage.recover()
        self.assertFalse(any(path.exists() for path in paths))

    def test_recovery_does_not_overwrite_external_edit(self):
        path = self.storage.data_home / 'applications/a.desktop'
        backup = self.storage.commit({path: b'after'}, {path: None})
        journal = backup / 'journal.json'
        record = json.loads(journal.read_text())
        record['status'] = 'pending'
        journal.write_text(json.dumps(record))
        path.write_bytes(b'external')
        with self.assertRaises(core.EditorError): self.storage.recover()
        self.assertEqual(path.read_bytes(), b'external')

    def test_paths_and_symlinks_are_rejected_for_writes(self):
        outside = self.root / 'outside'
        outside.mkdir()
        self.storage.data_home.mkdir()
        (self.storage.data_home / 'applications').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(core.EditorError): self.storage.commit({self.storage.data_home / 'applications/a.desktop': b'data'}, {})
        with self.assertRaises(core.EditorError): self.storage.commit({outside / 'a.desktop': b'data'}, {})
        self.assertEqual(list(outside.iterdir()), [])

    def test_lock_prevents_concurrent_commit(self):
        with self.storage._lock():
            with self.assertRaises(core.EditorError):
                self.storage.commit({self.storage.data_home / 'applications/a.desktop': b'data'}, {})

    def test_malformed_xml_and_entities_are_rejected(self):
        for data in (b'<invalid/>', b'<Menu>', b'<!DOCTYPE Menu [<!ENTITY a "bad">]><Menu><Name>&a;</Name></Menu>'):
            with self.assertRaises(core.EditorError): core.MenuDocument(data)


class LauncherFailureMatrixTests(unittest.TestCase):
    setUp = MenuEditorTests.setUp
    # Reuse fixtures, without inheriting the original test methods below.
    def test_mixed_batch_failures_are_atomic(self):
        operations = [
            lambda: self.model.move(['editor.desktop', 'missing.desktop'], ('Games',)),
            lambda: self.model.remove(['editor.desktop', 'missing.desktop']),
            lambda: self.model.remove(['editor.desktop', 'missing.desktop'], ('Tools',)),
            lambda: self.model.restore_applications(['editor.desktop', 'missing.desktop']),
            lambda: self.model.set_visible(['editor.desktop', 'missing.desktop'], False),
        ]
        for operation in operations:
            with self.subTest(operation=operation):
                before = self.model._snapshot()
                with self.assertRaises(KeyError):
                    operation()
                self.assertEqual(self.model._snapshot()[1:], before[1:])
                self.assertEqual(self.model.menu.to_bytes(), before[0].to_bytes())
                self.assertFalse(self.model.dirty)
                self.assertFalse((self.storage.data_home / 'applications').exists())

    def test_invalid_destinations_never_modify_the_launcher(self):
        operations = [
            lambda: self.model.move(['editor.desktop'], ('Missing',)),
            lambda: self.model.duplicate('editor.desktop', ('Missing',)),
            lambda: self.model.create_application(('Missing',), 'Invalid'),
            lambda: self.model.remove(['editor.desktop'], ('Missing',)),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(core.EditorError):
                operation()
            self.assertFalse(self.model.dirty)
            self.assertEqual(self.source.read_bytes(), APP)

    def test_unrelated_edit_does_not_copy_preexisting_hidden_launchers(self):
        hidden = core.Application('hidden.desktop', core.DesktopFile(APP), self.source, APP, {('Tools',): True})
        hidden.document.set('NoDisplay', True)
        self.model.applications[hidden.id] = hidden
        self.model.move(['editor.desktop'], ('Games',))
        self.assertNotIn(self.storage.data_home / 'applications/hidden.desktop', self.model.pending)

    def test_commit_failure_after_deletion_restores_launcher_and_menu(self):
        launcher = self.storage.data_home / 'applications/custom.desktop'
        menu = self.storage.config_home / 'menus/custom.menu'
        launcher.parent.mkdir(parents=True)
        menu.parent.mkdir(parents=True)
        launcher.write_bytes(APP)
        menu.write_bytes(b'original menu')
        atomic = self.storage.atomic
        def fail_menu(path, data):
            if path == menu and data == b'changed menu':
                raise OSError('simulated disk failure')
            return atomic(path, data)
        with patch.object(self.storage, 'atomic', side_effect=fail_menu):
            with self.assertRaises(core.EditorError):
                self.storage.commit({launcher: None, menu: b'changed menu'}, {launcher: APP, menu: b'original menu'})
        self.assertEqual(launcher.read_bytes(), APP)
        self.assertEqual(menu.read_bytes(), b'original menu')
        self.storage.recover()
        self.assertEqual(launcher.read_bytes(), APP)

    def test_duplicate_preserves_actions_and_vendor_data_but_is_visible(self):
        self.model.set_visible(['editor.desktop'], False)
        item_id = self.model.duplicate('editor.desktop', ('Games',))
        copy = self.model.applications[item_id]
        self.assertTrue(copy.visible)
        self.assertFalse(self.model.applications['editor.desktop'].visible)
        data = copy.document.to_bytes()
        self.assertIn(b'X-Vendor=keep', data)
        self.assertIn(b'[Desktop Action New]', data)
        self.assertEqual(copy.document.get('Exec'), '/usr/bin/true %f')
        self.assertFalse(copy.memberships[('Tools',)])
        self.model.apply()
        self.assertEqual(self.source.read_bytes(), APP)

    def test_create_then_remove_invalid_draft_leaves_no_desktop_file(self):
        item_id = self.model.create_application(('Tools',), 'Unfinished')
        self.model.remove([item_id])
        self.model.apply()
        self.assertNotIn(item_id, self.model.applications)
        self.assertFalse((self.storage.data_home / 'applications' / item_id).exists())
        self.assertFalse(self.model.dirty)

    def test_long_edit_history_is_bounded_and_commit_clears_redo(self):
        for index in range(180):
            self.model.edit_application('editor.desktop', {'Name': 'Edit '+str(index)})
        self.assertEqual(len(self.model.undo_stack), self.model.HISTORY_LIMIT)
        for index in range(self.model.HISTORY_LIMIT):
            self.model.undo()
        self.assertEqual(self.model.applications['editor.desktop'].name, 'Edit 119')
        self.assertEqual(self.source.read_bytes(), APP)
        for index in range(self.model.HISTORY_LIMIT):
            self.model.redo()
        self.assertEqual(self.model.applications['editor.desktop'].name, 'Edit 179')
        self.model.apply()
        self.assertFalse(self.model.undo_stack)
        self.assertFalse(self.model.redo_stack)
        self.model.undo()
        self.assertEqual(self.model.applications['editor.desktop'].name, 'Edit 179')


class DesktopCacheTests(unittest.TestCase):
    def test_cached_values_preserve_duplicates_actions_and_escapes(self):
        document = core.DesktopFile(b'[Desktop Entry]\nName=First\nName=Second\\sname\nExec=/usr/bin/true\n[Desktop Action New]\nName=Action\n')
        self.assertEqual(document.get('Name'), 'Second name')
        self.assertEqual(document.get('Name'), 'Second name')
        self.assertEqual(document.get('Missing', 'Default\\nline'), 'Default\nline')
        document.lines[2] = 'Name=Direct change'
        self.assertEqual(document.get('Name'), 'Direct change')
        self.assertIn(b'Name=Action', document.to_bytes())

    def test_deepcopy_cache_never_cross_contaminates_undo_state(self):
        import copy
        document = core.DesktopFile(APP)
        before = document.get('Name')
        snapshot = copy.deepcopy(document)
        document.set('Name', 'Changed')
        self.assertEqual(document.get('Name'), 'Changed')
        self.assertEqual(snapshot.get('Name'), before)
        snapshot.set('Comment', 'Snapshot only')
        self.assertNotEqual(snapshot.get('Comment'), document.get('Comment'))
