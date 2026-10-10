#!/usr/bin/env python3
"""Real GTK/CMenu integration in isolated XDG directories, never the user's menu.

Run with system PyGObject, GTK 3, gir1.2-cmenu-3.0 and a display (or xvfb-run).
The settings container is a real GTK box; Cinnamon itself is not started.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def parent():
    for version in ('4.0', '5.8'):
        with tempfile.TemporaryDirectory(prefix='canellia-gtk-') as directory:
            env = os.environ.copy()
            root = Path(directory)
            env.update(XDG_CONFIG_HOME=str(root / 'config'), XDG_CONFIG_DIRS=str(root / 'system-config'),
                       XDG_DATA_HOME=str(root / 'data'), XDG_DATA_DIRS=str(root / 'system-data'),
                       XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'),
                       XDG_MENU_PREFIX='cinnamon-', LANG='C.UTF-8', LC_ALL='C.UTF-8')
            subprocess.run([sys.executable, __file__, '--child', version], env=env, check=True)


if '--child' not in sys.argv:
    parent()
    raise SystemExit(0)

import importlib.util
import json
import shutil
import time
import types
import unittest
from unittest.mock import patch
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gtk
assert Gtk.init_check()[0], 'GTK requires a display; use xvfb-run'
Gtk.Settings.get_default().set_property('gtk-icon-theme-name', 'CanelliaTest')
version = sys.argv[-1]
settings = types.ModuleType('JsonSettingsWidgets')
settings.SettingsPage = type('SettingsPage', (Gtk.Box,), {})
settings.SettingsWidget = type('SettingsWidget', (Gtk.Box,), {})
sys.modules['JsonSettingsWidgets'] = settings
# Match Cinnamon's create_custom_widget: import by file path, no sys.path edit.
spec = importlib.util.spec_from_file_location('Canelliajson.MenuEditorPage', ROOT / 'Canellia@json' / version / 'MenuEditorPage.py')
MenuEditorPage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MenuEditorPage)
source_module = MenuEditorPage._editor_module('menuEditorTree')
CinnamonMenuSource = source_module.CinnamonMenuSource
EditorError = MenuEditorPage.EditorError

MENU = '''<Menu><Name>Applications</Name><DefaultAppDirs/><DefaultDirectoryDirs/>
<Menu><Name>Tools</Name><Directory>tools.directory</Directory><Include><Category>Utility</Category></Include></Menu>
<Menu><Name>Games</Name><Directory>games.directory</Directory><Include><Category>Game</Category></Include></Menu></Menu>'''
APP = '[Desktop Entry]\nType=Application\nName=Editor\nExec=/usr/bin/true\nCategories=Utility;\nIcon=accessories-text-editor\nX-Preserved=yes\n'
GAME = APP.replace('Name=Editor', 'Name=Game').replace('Utility;', 'Game;')


def drain():
    context = GLib.MainContext.default()
    for _ in range(100):
        if not context.pending(): break
        context.iteration(False)


def settle():
    # CMenu coalesces filesystem events with its documented source's 100 ms
    # timer. Verify the resulting tree after actual monitor delivery.
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        drain()
        time.sleep(0.01)
    drain()


class RealMenuTests(unittest.TestCase):
    def setUp(self):
        for key in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CONFIG_DIRS', 'XDG_DATA_DIRS'):
            path = Path(os.environ[key])
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True)
        self.system = Path(os.environ['XDG_DATA_DIRS'])
        (self.system / 'mime').symlink_to('/usr/share/mime')
        icons = self.system / 'icons/CanelliaTest/16x16/actions'
        icons.mkdir(parents=True)
        (icons.parent.parent / 'index.theme').write_text('[Icon Theme]\nName=CanelliaTest\nDirectories=16x16/actions\n[16x16/actions]\nSize=16\nType=Fixed\nContext=Actions\n')
        from gi.repository import GdkPixbuf
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 16, 16)
        pixbuf.fill(0x4d8ceaff)
        for name in ('image-missing', 'folder', 'accessories-text-editor', 'application-x-executable', 'view-grid-symbolic', 'edit-find-symbolic', 'edit-clear-symbolic'):
            pixbuf.savev(str(icons / (name + '.png')), 'png', [], [])
        (self.system / 'applications').mkdir()
        (self.system / 'desktop-directories').mkdir()
        (self.system / 'applications/editor.desktop').write_text(APP)
        (self.system / 'applications/game.desktop').write_text(GAME)
        for name in ('tools', 'games'):
            (self.system / ('desktop-directories/' + name + '.directory')).write_text('[Desktop Entry]\nType=Directory\nName=' + name.title() + '\nIcon=folder\n')
        config = Path(os.environ['XDG_CONFIG_DIRS']) / 'menus'
        config.mkdir()
        (config / 'cinnamon-applications.menu').write_text(MENU)
        settle()
        self.source = CinnamonMenuSource()
        self.page = None
        self.window = None

    def tearDown(self):
        if self.window: self.window.destroy()
        elif self.page: self.page.destroy()
        drain()

    def build(self):
        with patch.object(MenuEditorPage, '_', side_effect=lambda s: s), patch.object(source_module, 'CinnamonMenuSource', return_value=self.source):
            self.page = (MenuEditorPage.MenuEditorPage({}, {}) if version == '5.8' else
                         MenuEditorPage.MenuEditorWidget({}, 'menu-editor', {}))
        self.assertIsNotNone(self.page.model, self.page.status.get_text())
        self.window = Gtk.OffscreenWindow()
        self.window.set_default_size(800, 700)
        self.window.add(self.page)
        self.window.show_all()
        drain()
        return self.page

    def select_app(self, page, item_id):
        page.app_tree.get_selection().unselect_all()
        for row in page.app_store:
            if row[0] == item_id:
                page.app_tree.get_selection().select_iter(row.iter)
                return
        self.fail('Application missing: ' + item_id)

    def test_file_icons_and_invalid_icons_have_safe_fallback(self):
        from gi.repository import GdkPixbuf
        path = self.system / 'launcher.png'
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 8, 8)
        pixbuf.fill(0x336699ff)
        pixbuf.savev(str(path), 'png', [], [])
        self.assertIsInstance(MenuEditorPage._EditorHost._resolve_icon(str(path)), Gio.FileIcon)
        self.assertIsInstance(MenuEditorPage._EditorHost._resolve_icon(str(path)+'-missing'), Gio.ThemedIcon)
        self.assertIsInstance(MenuEditorPage._EditorHost._resolve_icon('folder'), Gio.ThemedIcon)

    def test_flatpak_alias_is_canonicalized_and_not_duplicated(self):
        model = self.source.load()
        self.assertEqual(self.source._canonical_id('editor.desktop:flatpak'), 'editor.desktop')
        self.assertEqual(self.source._canonical_id('custom:flatpak.desktop'), 'custom:flatpak.desktop')
        model.remove(['editor.desktop'])
        model.apply()
        settle()
        model = self.source.load()
        self.assertNotIn('editor.desktop', [app.id for app in model.search()])
        self.assertIn('editor.desktop', [app.id for app in model.search(visibility='hidden')])
        model.restore_applications(['editor.desktop'])
        model.apply()
        settle()
        self.assertTrue(self.source.load().applications['editor.desktop'].visible)

    def test_category_removal_does_not_change_other_categories_or_launcher(self):
        model = self.source.load()
        model.move(['editor.desktop'], ('Games',), ('Tools',), add=True)
        model.apply()
        settle()
        model = self.source.load()
        original = model.applications['editor.desktop'].document.to_bytes()
        model.remove(['editor.desktop'], ('Tools',))
        self.assertTrue(model.applications['editor.desktop'].memberships[('Games',)])
        self.assertEqual(model.applications['editor.desktop'].document.to_bytes(), original)
        model.undo()
        self.assertTrue(model.applications['editor.desktop'].memberships[('Tools',)])
        model.redo()
        model.apply()
        settle()
        model = self.source.load()
        self.assertNotIn('editor.desktop', [app.id for app in model.search(category=('Tools',))])
        self.assertIn('editor.desktop', [app.id for app in model.search(category=('Tools',), visibility='hidden')])
        self.assertIn('editor.desktop', [app.id for app in model.search(category=('Games',))])
        self.assertIn('editor.desktop', [app.id for app in model.search()])
        self.assertEqual(model.applications['editor.desktop'].document.to_bytes(), original)
        model.set_visible(['editor.desktop'], True, ('Tools',))
        model.apply()
        settle()
        model = self.source.load()
        self.assertTrue(model.applications['editor.desktop'].memberships[('Tools',)])
        self.assertTrue(model.applications['editor.desktop'].memberships[('Games',)])

    def test_duplicate_edit_delete_and_restore_complete_lifecycle(self):
        model = self.source.load()
        original = (self.system / 'applications/editor.desktop').read_bytes()
        duplicate = model.duplicate('editor.desktop', ('Games',))
        model.edit_application(duplicate, {'Name': 'Independent copy', 'Exec': '/usr/bin/true %u', 'Icon': 'folder'})
        model.apply()
        settle()
        model = self.source.load()
        self.assertEqual(model.applications['editor.desktop'].name, 'Editor')
        self.assertEqual(model.applications[duplicate].name, 'Independent copy')
        self.assertTrue(model.applications[duplicate].memberships[('Games',)])
        model.move([duplicate], ('Tools',), ('Games',), add=True)
        model.apply()
        settle()
        model = self.source.load()
        model.remove([duplicate], ('Games',))
        model.apply()
        settle()
        model = self.source.load()
        self.assertTrue(model.applications[duplicate].memberships[('Tools',)])
        self.assertFalse(model.applications[duplicate].memberships.get(('Games',), False))
        model.remove([duplicate])
        model.undo()
        self.assertIn(duplicate, model.applications)
        model.redo()
        model.apply()
        settle()
        model = self.source.load()
        self.assertNotIn(duplicate, model.applications)
        self.assertFalse((Path(os.environ['XDG_DATA_HOME']) / 'applications' / duplicate).exists())
        self.assertEqual((self.system / 'applications/editor.desktop').read_bytes(), original)

    def test_batch_moving_mixed_custom_and_system_launchers_after_restart(self):
        model = self.source.load()
        created = [model.create_application(('Tools',), 'Batch '+str(i)) for i in range(8)]
        for item_id in created:
            model.edit_application(item_id, {'Exec': '/usr/bin/true'})
        ids = ['editor.desktop'] + created
        model.move(ids, ('Games',), ('Tools',))
        model.apply()
        settle()
        model = self.source.load()
        for item_id in ids:
            self.assertTrue(model.applications[item_id].memberships[('Games',)])
            self.assertFalse(model.applications[item_id].memberships.get(('Tools',), False))
        model.move(ids, ('Tools',), ('Games',), add=True)
        model.apply()
        settle()
        model = self.source.load()
        model.remove(ids, ('Games',))
        model.apply()
        settle()
        model = self.source.load()
        for item_id in ids:
            self.assertTrue(model.applications[item_id].memberships[('Tools',)])
            self.assertFalse(model.applications[item_id].memberships.get(('Games',), False))
        model.remove(created)
        model.apply()
        settle()
        model = self.source.load()
        self.assertFalse(set(created) & model.applications.keys())
        self.assertIn('editor.desktop', model.applications)

    def test_nested_categories_launcher_moves_and_user_override_conflicts(self):
        model = self.source.load()
        parent = model.create_category(('Tools',), 'Parent')
        child = model.create_category(parent, 'Child')
        item_id = model.create_application(child, 'Nested launcher')
        model.edit_application(item_id, {'Exec': '/usr/bin/true', 'Categories': 'Utility;Game;'})
        model.apply()
        settle()
        model = self.source.load()
        self.assertIn(child, model.categories)
        self.assertTrue(model.applications[item_id].memberships[child])
        model.move([item_id], ('Games',), child)
        model.apply()
        settle()
        model = self.source.load()
        self.assertFalse(model.applications[item_id].memberships.get(child, False))
        self.assertTrue(model.applications[item_id].memberships[('Games',)])
        model.edit_application(item_id, {'Name': 'Pending rename'})
        target = Path(os.environ['XDG_DATA_HOME']) / 'applications' / item_id
        external = target.read_bytes() + b'# edited externally\n'
        target.write_bytes(external)
        with self.assertRaises(EditorError):
            model.apply()
        self.assertEqual(target.read_bytes(), external)
        self.assertTrue(model.dirty)

    def test_seeded_launcher_operations_survive_commits_and_reload(self):
        import copy
        import random
        import itertools
        for seed in (11, 73, 2026):
            serial = itertools.count(1)
            with self.subTest(seed=seed), patch.object(MenuEditorPage._editor_module('menuEditorCore').uuid, 'uuid4',
                    side_effect=lambda: types.SimpleNamespace(hex=f'{next(serial):08x}{seed:024x}')):
                self.setUp()
                rng = random.Random(seed)
                model = self.source.load()
                oracle = {
                    'editor.desktop': {'name': 'Editor', 'visible': True, 'custom': False, 'memberships': {('Tools',): True}},
                    'game.desktop': {'name': 'Game', 'visible': True, 'custom': False, 'memberships': {('Games',): True}},
                }
                baseline = copy.deepcopy(oracle)
                def verify():
                    self.assertEqual(set(model.applications), set(oracle), f'seed={seed}, step={step}')
                    for item_id, expected in oracle.items():
                        actual = model.applications[item_id]
                        self.assertEqual(actual.name, expected['name'], (seed, step, item_id))
                        self.assertEqual(actual.visible, expected['visible'], (seed, step, item_id))
                        for category in (('Tools',), ('Games',)):
                            self.assertEqual(actual.memberships.get(category, False), expected['memberships'].get(category, False), (seed, step, item_id, category))
                for step in range(60):
                    operation = rng.choice(['create', 'duplicate', 'edit', 'move', 'add', 'local_remove', 'global_remove', 'visibility', 'undo_redo', 'discard'])
                    item_id = rng.choice(sorted(oracle)) if oracle else None
                    target = rng.choice([('Tools',), ('Games',)])
                    if operation == 'create':
                        name = f'Created {seed}-{step}'
                        new_id = model.create_application(target, name)
                        model.edit_application(new_id, {'Exec': '/usr/bin/true'})
                        oracle[new_id] = {'name': name, 'visible': True, 'custom': True, 'memberships': {target: True}}
                    elif operation == 'duplicate' and item_id:
                        new_id = model.duplicate(item_id, target)
                        oracle[new_id] = {'name': oracle[item_id]['name']+' (copy)', 'visible': True, 'custom': True, 'memberships': {target: True}}
                    elif operation == 'edit' and item_id:
                        name = f'Renamed {seed}-{step}'
                        model.edit_application(item_id, {'Name': name})
                        oracle[item_id]['name'] = name
                    elif operation in ('move', 'add') and item_id:
                        model.move([item_id], target, add=operation=='add')
                        if operation == 'move':
                            oracle[item_id]['memberships'] = {category: False for category in oracle[item_id]['memberships']}
                        oracle[item_id]['memberships'][target] = True
                    elif operation == 'local_remove' and item_id:
                        model.remove([item_id], target)
                        oracle[item_id]['memberships'][target] = False
                    elif operation == 'global_remove' and item_id:
                        model.remove([item_id])
                        if oracle[item_id]['custom']:
                            del oracle[item_id]
                        else:
                            oracle[item_id]['visible'] = False
                    elif operation == 'visibility' and item_id:
                        visible = not oracle[item_id]['visible']
                        model.set_visible([item_id], visible)
                        oracle[item_id]['visible'] = visible
                        if visible and not any(oracle[item_id]['memberships'].values()):
                            oracle[item_id]['memberships'] = {category: True for category in oracle[item_id]['memberships'] or {(): True}}
                    elif operation == 'undo_redo' and item_id:
                        before = copy.deepcopy(oracle)
                        name = f'Undoable {seed}-{step}'
                        model.edit_application(item_id, {'Name': name})
                        oracle[item_id]['name'] = name
                        after = copy.deepcopy(oracle)
                        model.undo()
                        oracle = before
                        verify()
                        model.redo()
                        oracle = after
                    elif operation == 'discard':
                        model.discard()
                        oracle = copy.deepcopy(baseline)
                    verify()
                    if step % 5 == 4 or step == 59:
                        model.apply()
                        settle()
                        model = self.source.load()
                        baseline = copy.deepcopy(oracle)
                        verify()
                        self.assertEqual((self.system / 'applications/editor.desktop').read_text(), APP)
                        self.assertEqual((self.system / 'applications/game.desktop').read_text(), GAME)

    def test_real_buttons_duplicate_move_remove_cancel_and_restore(self):
        page = self.build()
        page._category = ('Tools',)
        page._refresh(categories=True)
        self.select_app(page, 'editor.desktop')
        before = set(page.model.applications)
        page.duplicate_button.clicked()
        duplicate = (set(page.model.applications) - before).pop()
        page.fields['Name'].set_text('UI duplicate')
        page.property_button.clicked()
        self.assertEqual(page.model.applications['editor.desktop'].name, 'Editor')
        def choose_destination():
            for window in Gtk.Window.list_toplevels():
                if isinstance(window, Gtk.Dialog) and not isinstance(window, Gtk.MessageDialog):
                    for child in window.get_content_area().get_children():
                        if isinstance(child, Gtk.ComboBoxText):
                            child.set_active_id(page._encode_path(('Games',)))
                    window.response(Gtk.ResponseType.OK)
            return False
        GLib.idle_add(choose_destination)
        page.move_button.clicked()
        self.assertFalse(page.model.applications[duplicate].memberships[('Tools',)])
        self.assertTrue(page.model.applications[duplicate].memberships[('Games',)])
        self.assertTrue(page._apply())
        page._category = ('Games',)
        page._refresh(categories=True)
        self.select_app(page, duplicate)
        def respond(response):
            def callback():
                for window in Gtk.Window.list_toplevels():
                    if isinstance(window, Gtk.MessageDialog):
                        window.response(response)
                return False
            GLib.idle_add(callback)
        respond(Gtk.ResponseType.CANCEL)
        page.remove_button.clicked()
        self.assertFalse(page.model.dirty)
        self.assertTrue(page.model.applications[duplicate].memberships[('Games',)])
        respond(Gtk.ResponseType.OK)
        page.remove_button.clicked()
        self.assertTrue(page._apply())
        self.assertNotIn(duplicate, [row[0] for row in page.app_store])
        page.filter.set_active_id('hidden')
        page._search_changed()
        self.select_app(page, duplicate)
        page.restore_button.clicked()
        self.assertTrue(page._apply())
        self.assertTrue(page.model.applications[duplicate].memberships[('Games',)])
        page._category = None
        page.filter.set_active_id('all')
        page._refresh(categories=True)
        self.select_app(page, duplicate)
        respond(Gtk.ResponseType.OK)
        page.remove_button.clicked()
        self.assertTrue(page._apply())
        self.assertNotIn(duplicate, page.model.applications)
        self.assertIn('editor.desktop', page.model.applications)

    def test_public_tree_reads_categories_and_round_trips_move(self):
        model = self.source.load()
        self.assertIn(('Tools',), model.categories)
        self.assertIn('editor.desktop', model.applications)
        self.assertTrue(model.applications['editor.desktop'].memberships[('Tools',)])
        model.move(['editor.desktop'], ('Games',), ('Tools',))
        model.apply()
        settle()
        model = self.source.load()
        self.assertFalse(model.applications['editor.desktop'].memberships.get(('Tools',), False))
        self.assertTrue(model.applications['editor.desktop'].memberships[('Games',)])
        self.assertEqual((self.system / 'applications/editor.desktop').read_text(), APP)

    def test_create_category_and_launcher_are_visible_after_reload(self):
        model = self.source.load()
        category = model.create_category(('Tools',), 'Personal')
        item_id = model.create_application(category, 'My launcher')
        model.edit_application(item_id, {'Exec': '/usr/bin/true'})
        model.apply()
        settle()
        model = self.source.load()
        self.assertIn(category, model.categories)
        self.assertTrue(model.applications[item_id].memberships[category])

    def test_category_can_be_shown_again_after_hiding_and_reload(self):
        model = self.source.load()
        model.edit_category(('Tools',), 'My tools', 'folder', visible=False)
        model.apply()
        settle()
        model = self.source.load()
        self.assertIn(('Tools',), model.categories)
        self.assertFalse(model.categories[('Tools',)].visible)
        model.restore_category(('Tools',))
        model.apply()
        settle()
        model = self.source.load()
        self.assertTrue(model.categories[('Tools',)].visible)
        self.assertEqual(model.categories[('Tools',)].name, 'Tools')

    def test_drag_payload_moves_selected_apps_and_copy_retains_source(self):
        page = self.build()
        category_row = None
        def locate(model, path, iterator, data):
            nonlocal category_row
            if model[iterator][1] == page._encode_path(('Games',)):
                category_row = path.copy()
        page.category_store.foreach(locate, None)
        payload = types.SimpleNamespace(get_data=lambda: json.dumps({'ids': ['editor.desktop'], 'source': ['Tools']}).encode())
        context = types.SimpleNamespace(get_selected_action=lambda: Gdk.DragAction.COPY)
        with patch.object(page.category_tree, 'get_dest_row_at_pos', return_value=(category_row, Gtk.TreeViewDropPosition.INTO_OR_AFTER)), patch.object(Gtk, 'drag_finish') as finish:
            page._drag_receive(page.category_tree, context, 0, 0, payload, 0, 0)
            self.assertTrue(page.model.applications['editor.desktop'].memberships[('Tools',)])
            self.assertTrue(page.model.applications['editor.desktop'].memberships[('Games',)])
            finish.assert_called_with(context, True, False, 0)
            context.get_selected_action = lambda: Gdk.DragAction.MOVE
            page._drag_receive(page.category_tree, context, 0, 0, payload, 0, 0)
            self.assertFalse(page.model.applications['editor.desktop'].memberships[('Tools',)])
        self.assertTrue(page._apply())

    def test_restore_error_keeps_message_and_pending_work(self):
        page = self.build()
        path = page.model.create_category((), 'Custom')
        page._category = path
        page._refresh(categories=True, selected=[])
        page.restore_button.clicked()
        self.assertIn('No system version', page.status.get_text())
        self.assertTrue(page.model.dirty)

    def test_edit_hide_remove_restore_preserves_system_files(self):
        model = self.source.load()
        model.edit_application('editor.desktop', {'Name': 'Changed'})
        model.set_visible(['editor.desktop'], False)
        model.apply()
        settle()
        model = self.source.load()
        self.assertFalse(model.applications['editor.desktop'].visible)
        self.assertEqual(model.applications['editor.desktop'].name, 'Changed')
        model.remove(['editor.desktop'])
        model.apply()
        settle()
        model = self.source.load()
        self.assertIn('editor.desktop', model.applications)
        model.restore_applications(['editor.desktop'])
        model.apply()
        settle()
        model = self.source.load()
        self.assertEqual(model.applications['editor.desktop'].name, 'Editor')
        self.assertTrue(model.applications['editor.desktop'].memberships[('Tools',)])

    def test_real_widgets_stage_apply_search_multiselect_and_undo(self):
        page = self.build()
        self.assertEqual(len(page.app_store), 2)
        self.select_app(page, 'editor.desktop')
        self.assertTrue(page.fields['Name'].get_mapped())
        self.assertTrue(page.fields['Exec'].get_mapped())
        self.assertTrue(page.fields['Icon'].get_mapped())
        page.fields['Name'].set_text('Edição pessoal')
        self.assertTrue(page._draft_dirty)
        self.assertTrue(page.apply_button.get_sensitive())
        self.assertFalse((Path(os.environ['XDG_DATA_HOME']) / 'applications/editor.desktop').exists())
        page.property_button.clicked()
        self.assertEqual(page.model.applications['editor.desktop'].name, 'Edição pessoal')
        page.undo_button.clicked()
        self.assertEqual(page.model.applications['editor.desktop'].name, 'Editor')
        page.redo_button.clicked()
        self.assertEqual(page.model.applications['editor.desktop'].name, 'Edição pessoal')
        self.assertTrue(page._apply())
        page.search.set_text('edicao')
        page._search_changed()
        self.assertEqual(len(page.app_store), 1)
        page.search.set_text('')
        page._search_changed()
        page.app_tree.get_selection().select_all()
        self.assertEqual(len(page._selected_ids()), 2)
        page.hide_button.clicked()
        self.assertTrue(all(not a.visible for a in page.model.applications.values()))
        page.discard_button.clicked()
        self.assertTrue(all(a.visible for a in page.model.applications.values()))
        snapshot = self.window.get_pixbuf()
        self.assertIsNotNone(snapshot)
        screenshot = os.environ.get('CANELLIA_SCREENSHOT')
        if screenshot and version == '5.8': snapshot.savev(screenshot, 'png', [], [])

    def test_invalid_form_is_preserved_when_selection_changes(self):
        page = self.build()
        self.select_app(page, 'editor.desktop')
        page.fields['Exec'].set_text('"unterminated')
        for row in page.app_store:
            if row[0] == 'game.desktop':
                page.app_tree.get_selection().select_iter(row.iter)
        self.assertEqual(page._selected_ids(), ['editor.desktop'])
        self.assertEqual(page.fields['Exec'].get_text(), '"unterminated')
        self.assertTrue(page._draft_dirty)
        self.assertFalse(page._apply())
        self.assertIn('Invalid properties:', page.status.get_text())

    def test_external_conflict_preserves_pending_edit(self):
        page = self.build()
        self.select_app(page, 'editor.desktop')
        page.fields['Name'].set_text('Pending')
        (self.system / 'applications/editor.desktop').write_text(APP + '#changed\n')
        self.assertFalse(page._apply())
        self.assertTrue(page.model.dirty)
        self.assertIn('Save failed:', page.status.get_text())

    def test_failure_then_reload_recovers_and_destroy_disconnects(self):
        original = self.source.load
        with patch.object(self.source, 'load', side_effect=EditorError('temporary failure')):
            with patch.object(source_module, 'CinnamonMenuSource', return_value=self.source), self.assertLogs(MenuEditorPage._LOG.name, level='ERROR'):
                self.page = MenuEditorPage.MenuEditorPage({}, {})
        self.assertIsNone(self.page.model)
        self.assertFalse(self.page.apply_button.get_sensitive())
        self.page.reload_button.clicked()
        self.assertIsNotNone(self.page.model)
        tree, signal = self.page._tree_signal
        self.page._tree_changed()
        self.assertTrue(self.page._refresh_id)
        self.page.destroy()
        self.assertFalse(tree.handler_is_connected(signal))
        self.assertEqual(self.page._refresh_id, 0)

    def test_unsaved_close_cancel_discard_and_apply(self):
        page = self.build()
        self.select_app(page, 'editor.desktop')
        page.fields['Name'].set_text('Pending')
        def respond(response):
            def callback():
                for window in Gtk.Window.list_toplevels():
                    if isinstance(window, Gtk.MessageDialog):
                        window.response(response)
                return False
            GLib.idle_add(callback)
        respond(Gtk.ResponseType.CANCEL)
        self.assertTrue(page._on_close())
        respond(Gtk.ResponseType.REJECT)
        self.assertFalse(page._on_close())
        self.assertFalse(page.model.dirty)
        page.fields['Name'].set_text('Saved')
        respond(Gtk.ResponseType.APPLY)
        self.assertFalse(page._on_close())
        self.assertEqual(self.source.load().applications['editor.desktop'].name, 'Saved')

    def test_test_launcher_executes_real_desktop_entry(self):
        page = self.build()
        self.select_app(page, 'editor.desktop')
        result = Path(os.environ['XDG_DATA_HOME']) / 'test-launched'
        helper = Path(os.environ['XDG_DATA_HOME']) / 'launcher-helper'
        helper.write_text('#!/bin/sh\ntouch "' + str(result) + '"\n')
        helper.chmod(0o755)
        page.fields['Exec'].set_text('"' + str(helper) + '"')
        page.test_button.clicked()
        deadline = time.monotonic() + 3
        while not result.exists() and time.monotonic() < deadline:
            drain()
            time.sleep(0.02)
        self.assertTrue(result.exists(), page.status.get_text())
        self.assertFalse((Path(os.environ['XDG_DATA_HOME']) / 'applications/editor.desktop').exists())


unittest.main(argv=[sys.argv[0]] + ([os.environ['CANELLIA_GTK_TEST']] if os.environ.get('CANELLIA_GTK_TEST') else []), verbosity=2)
