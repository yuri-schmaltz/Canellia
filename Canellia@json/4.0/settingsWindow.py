#!/usr/bin/env python3
"""Open Cinnamon's native settings with a launcher selected in Canellia."""
import argparse
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance', type=int, required=True)
    parser.add_argument('--select-launcher', required=True)
    args = parser.parse_args()
    native = Path('/usr/share/cinnamon/cinnamon-settings')
    sys.path.insert(0, str(native))
    sys.path.insert(0, str(native / 'bin'))
    spec = importlib.util.spec_from_file_location('canellia_native_settings', native / 'xlet-settings.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from gi.repository import Gtk

    class LauncherWindow(module.MainWindow):
        def create_custom_widget(self, info, *arguments):
            widget = super().create_custom_widget(info, *arguments)
            if hasattr(widget, 'select_launcher'):
                self.editor = widget
            return widget

    window = LauncherWindow(SimpleNamespace(type='applet', uuid='Canellia@json', id=args.instance, tab=0))
    item_id = args.select_launcher[:-8] if args.select_launcher.endswith(':flatpak') else args.select_launcher
    if not getattr(window, 'editor', None) or not window.editor.select_launcher(item_id):
        if getattr(window, 'editor', None):
            window.editor._message(window.custom_modules['MenuEditorPage.py']._('Launcher is no longer available. Reload the menu.'))
    Gtk.main()


if __name__ == '__main__':
    main()
