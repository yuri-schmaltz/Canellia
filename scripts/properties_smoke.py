#!/usr/bin/env python3
"""Verify the production properties entrypoint without saving launcher edits."""
import importlib.util
from pathlib import Path
import sys
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gio, GLib, Gtk

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('canellia_properties', root/'Canellia@json/5.8/settingsWindow.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
app = next(app for app in Gio.AppInfo.get_all() if app.get_id() and app.should_show())
selected = app.get_id()
sys.argv = ['settingsWindow.py','--instance','15','--select-launcher',selected]

def verify():
    def find(widget):
        if hasattr(widget,'_selected_ids'):
            return widget
        if isinstance(widget,Gtk.Container):
            for child in widget.get_children():
                found = find(child)
                if found is not None:
                    return found
    windows = Gtk.Window.list_toplevels()
    editor = next(found for window in windows if (found := find(window)) is not None)
    assert editor._selected_ids() == [selected], editor._selected_ids()
    assert not editor.model.dirty
    assert not editor._draft_dirty
    print('PROPERTIES_OK: production entrypoint selects launcher; no pending edits')

native_main = Gtk.main
errors = []
def run_loop():
    def verify_once():
        try:
            verify()
        except Exception as error:
            errors.append(error)
        finally:
            Gtk.main_quit()
        return False
    GLib.idle_add(verify_once)
    native_main()
Gtk.main = run_loop
helper.main()
if errors:
    raise errors[0]
