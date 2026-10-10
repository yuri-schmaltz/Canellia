#!/usr/bin/env python3
"""Confirmed application removal; launcher deletion remains in the menu editor."""
import gettext
import os
from pathlib import Path
import subprocess
import sys
import threading

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk
from uninstallCore import ResolutionError, resolve

gettext.install('Canellia@json', str(Path.home() / '.local/share/locale'))


def message(text, error=False):
    dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                               buttons=Gtk.ButtonsType.CLOSE, text=text)
    dialog.set_keep_above(True)
    dialog.run()
    dialog.destroy()


def main():
    if len(sys.argv) < 2:
        return 1
    try:
        installations = resolve(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
        if not installations:
            message(_('No managed installation was found for this launcher. To hide or remove the launcher, use the menu editor.'))
            return 0
        dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=_('Uninstall application?'))
        dialog.set_keep_above(True)
        choice = Gtk.ComboBoxText()
        for installation in installations:
            choice.append_text(installation.identity + (' — ' + installation.scope if installation.scope else ''))
        choice.set_active(0)
        dialog.get_content_area().add(choice)
        choice.show()
        response = dialog.run()
        selected = choice.get_active()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return 0
        command = installations[selected].command()
        if installations[selected].kind == 'native':
            # The distribution tool retains its package/dependency confirmation.
            subprocess.Popen(command)
            return 0
        progress = Gtk.MessageDialog(message_type=Gtk.MessageType.INFO,
                                     buttons=Gtk.ButtonsType.NONE, text=_('Uninstalling application…'))
        progress.connect('delete-event', lambda *args: True)
        progress.show()
        def finish(result, error):
            progress.destroy()
            if error or result.returncode:
                message(_('Application removal failed. The launcher was preserved.') + '\n' +
                        (error or result.stderr.strip()), True)
            Gtk.main_quit()
            return False
        def worker():
            try:
                result = subprocess.run(command, capture_output=True, text=True)
                GLib.idle_add(finish, result, '')
            except OSError as error:
                GLib.idle_add(finish, None, str(error))
        threading.Thread(target=worker, daemon=True).start()
        Gtk.main()
        return 0
    except (ResolutionError, OSError) as error:
        message(str(error), True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
