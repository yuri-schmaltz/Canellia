"""Capture the working tree in Cinnamon's real settings window, without saving
user settings or applying menu edits. Run with host system Python/PyGObject.
"""
import argparse
import copy
import gettext
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'test-results/gauntlet-2026-10-09/screenshots'
NATIVE = Path('/usr/share/cinnamon/cinnamon-settings')
sys.path.insert(0, str(NATIVE))
sys.path.insert(0, str(NATIVE / 'bin'))
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Gdk, GdkX11, Gio, GLib, Gtk

spec = importlib.util.spec_from_file_location('canellia_capture_settings', NATIVE / 'xlet-settings.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def drain():
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


with tempfile.TemporaryDirectory(prefix='canellia-capture-') as temporary:
    scratch = Path(temporary)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    os.environ['XDG_STATE_HOME'] = str(scratch / 'state')
    catalog = scratch / 'Canellia@json.mo'
    subprocess.run(['msgfmt', '-o', str(catalog), str(ROOT / 'Canellia@json/po/pt_BR.po')], check=True)
    with catalog.open('rb') as handle:
        translation = gettext.GNUTranslations(handle).gettext
    native.translations['Canellia@json'] = translation
    schema = json.loads((ROOT / 'Canellia@json/5.8/settings-schema.json').read_text())
    current = Path(GLib.get_user_config_dir()) / 'cinnamon/spices/Canellia@json/15.json'
    saved = json.loads(current.read_text()) if current.exists() else {}
    for key, node in schema.items():
        if isinstance(node, dict) and 'default' in node:
            node['value'] = saved.get(key, {}).get('value', copy.deepcopy(node['default']))
    settings_file = scratch / '15.json'
    settings_file.write_text(json.dumps(schema, ensure_ascii=False, indent=2))

    class CaptureWindow(native.MainWindow):
        def load_xlet_data(self):
            self.xlet_dir = str(ROOT / 'Canellia@json')
            self.xlet_meta = json.loads((ROOT / 'Canellia@json/metadata.json').read_text())

        def load_instances(self):
            handler = native.JSONSettingsHandler(str(settings_file), self.uuid, '15', None)
            instance_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.instance_stack.add_named(instance_box, '15')
            info = {'settings': handler, 'id': '15'}
            self.instance_info = [info]
            settings_map = handler.get_settings()
            # Apply the same translations as Cinnamon's normal load_instances.
            for key, node in settings_map.items():
                if not isinstance(node, dict):
                    continue
                for prop in ('description', 'tooltip', 'units'):
                    if prop in node:
                        node[prop] = native.translate(self.uuid, node[prop])
                if 'options' in node:
                    node['options'] = {native.translate(self.uuid, label): value for label, value in node['options'].items()}
                for column in node.get('columns', []):
                    if 'title' in column:
                        column['title'] = native.translate(self.uuid, column['title'])
            self.build_with_layout(settings_map, info, instance_box, settings_map['layout'])
            self.selected_instance = info
            self.stack_switcher.set_stack(info['stack'])
            self.prev_button.set_no_show_all(True)
            self.next_button.set_no_show_all(True)

        def create_custom_widget(self, info, *args):
            file_path = ROOT / 'Canellia@json/5.8' / info['file']
            widget_spec = importlib.util.spec_from_file_location('Canelliajson.MenuEditorPage', file_path)
            module = importlib.util.module_from_spec(widget_spec)
            widget_spec.loader.exec_module(module)
            module._ = translation
            source_module = (getattr(module, '_editor_module', None) or module._module)('menuEditorTree')
            original_source = getattr(source_module, '_smoke_source', source_module.CinnamonMenuSource)
            source_module._smoke_source = original_source
            # Read the real menus but keep crash-recovery state in scratch space.
            storage = (getattr(module, '_editor_module', None) or module._module)('menuEditorCore').UserStorage(state_home=scratch / 'state')
            source_module.CinnamonMenuSource = lambda *args: original_source(storage)
            self.custom_modules[info['file']] = module
            return getattr(module, info['widget'])(info, *args)

        def notify_dbus(self, *args):
            pass

        def _on_proxy_ready(self, *args):
            pass

        def quit(self, *args):
            self.window.destroy()
            if Gtk.main_level():
                Gtk.main_quit()

    original_settings = current.read_bytes() if current.exists() else None
    app = CaptureWindow(argparse.Namespace(type='applet', uuid='Canellia@json', id=15, tab=0))
    stack = app.selected_instance['stack']
    stack.set_transition_type(Gtk.StackTransitionType.NONE)
    editor = stack.get_child_by_name('editor')
    tools = stack.get_child_by_name('tools')
    assert editor.model is not None, editor.status.get_text()
    assert len(stack.get_children()) == 6
    selected = next(a for a in editor.model.applications.values() if a.visible)
    assert editor.select_launcher(selected.id)
    assert not editor.model.dirty
    notebook = next(w for w in tools.get_children() if isinstance(w, Gtk.Notebook))
    tools._scan()
    assert len(tools.issues) > 0
    for page, name in enumerate(('diagnostico', 'backups', 'perfis', 'previa')):
        stack.set_visible_child_name('tools')
        notebook.set_current_page(page)
        app.window.present()
        drain()
        for _ in range(10):
            time.sleep(0.03)
            drain()
        xid = app.window.get_window().get_xid()
        subprocess.run(['xdotool','windowactivate','--sync',str(xid)], check=True)
        subprocess.run(['gnome-screenshot','--window','--file',str(OUTPUT / (name+'.png'))],check=True)
        assert app.window.get_size().width <= 1100, app.window.get_size()
        print('NATIVE_TAB_OK', name, flush=True)
    profile = tools.tools if hasattr(tools, 'tools') else app.custom_modules['ToolsPage.py'].tools
    assert tools._apply_profile(profile.preset('list', tools.settings.settings), confirm=False)
    assert tools.settings.get_value('applications-view-mode') == 0
    assert tools.preview_box.get_children()
    assert current.read_bytes() == original_settings
    assert not editor.model.dirty
    app.quit()
    print('NATIVE_SETTINGS_OK: six tabs, launcher selection, diagnostics, isolated profile and preview; user preferences unchanged', flush=True)
