"""Recovery, diagnostics, profiles and appearance preview in native settings."""
import copy
import gettext
import hashlib
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import time
import types
import uuid
from gi.repository import Gio, GLib, Gtk
from JsonSettingsWidgets import SettingsPage


def _module(name):
    directory = Path(__file__).resolve().parent
    package = '_canellia_editor_' + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    if package not in sys.modules:
        module = types.ModuleType(package)
        module.__path__ = [str(directory)]
        module.__package__ = package
        module.__spec__ = importlib.machinery.ModuleSpec(package, loader=None, is_package=True)
        module.__spec__.submodule_search_locations = module.__path__
        sys.modules[package] = module
    return importlib.import_module(package + '.' + name)


core, tools = _module('menuEditorCore'), _module('projectTools')
_ = gettext.translation('Canellia@json', str(Path(GLib.get_user_data_dir()) / 'locale'), fallback=True).gettext


class ToolsPage(SettingsPage):
    def __init__(self, info, settings):
        super().__init__()
        self.settings = settings
        self.storage = core.UserStorage()
        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_selectable(True)
        self.status.set_max_width_chars(90)
        notebook = Gtk.Notebook()
        self.pack_start(notebook, True, True, 0)
        for title, builder in [('Diagnostics', self._diagnostics), ('Backups', self._backups),
                               ('Profiles', self._profiles), ('Preview', self._preview)]:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            page.set_border_width(12)
            builder(page)
            notebook.append_page(page, Gtk.Label(label=_(title)))
        self.pack_start(self.status, False, False, 8)
        self.show_all()
        self.connect('map', lambda *args: self._render_preview())
        self._load_backups()
        # Cinnamon's default writer removes the previous file before writing.
        # Patch only this instance to retain atomic replacement semantics.
        if hasattr(settings, 'save_settings') and hasattr(settings, 'filepath'):
            settings.save_settings = self._atomic_settings_save

    def _atomic_settings_save(self):
        self.settings.pause_monitor()
        try:
            core.UserStorage.atomic(Path(self.settings.filepath),
                json.dumps(self.settings.settings, ensure_ascii=False, indent=4).encode())
        finally:
            self.settings.resume_monitor()

    def _run(self, action):
        try:
            return action()
        except Exception as error:
            self.status.set_text(_('Operation failed:') + ' ' + str(error))
            return None

    def _button(self, box, label, callback):
        button = Gtk.Button(label=_(label))
        button.connect('clicked', lambda *args: self._run(callback))
        box.pack_start(button, False, False, 0)
        return button

    def _confirm(self, text):
        window = self.get_toplevel()
        dialog = Gtk.MessageDialog(transient_for=window if isinstance(window, Gtk.Window) else None,
            modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
            text=_(text))
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    @staticmethod
    def _scroll(widget):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(widget)
        return scroll

    def _diagnostics(self, box):
        box.pack_start(Gtk.Label(label=_('Inspect launchers without modifying or uninstalling applications.'), xalign=0), False, False, 0)
        self._button(box, 'Run diagnostics', self._scan)
        self.issues = Gtk.ListStore(str, str, str, str)
        self.issue_tree = Gtk.TreeView(model=self.issues)
        for index, title in enumerate(('Application', 'Type', 'Details')):
            renderer = Gtk.CellRendererText()
            renderer.set_property('wrap-width', 450 if index == 2 else 180)
            column = Gtk.TreeViewColumn(_(title), renderer, text=index+1)
            self.issue_tree.append_column(column)
        box.pack_start(self._scroll(self.issue_tree), True, True, 0)
        self._button(box, 'Edit selected launcher', self._edit_issue)

    def _scan(self):
        source = _module('menuEditorTree').CinnamonMenuSource(self.storage)
        model = source.load()
        self.issues.clear()
        findings = tools.diagnose(model, Gtk.IconTheme.get_default().has_icon)
        for issue in findings:
            head, separator, detail = issue['message'].partition(': ')
            message = _(head) + separator + detail
            self.issues.append([issue['id'], issue['name'], _(issue['kind']), message])
        for warning in source.warnings:
            self.issues.append(['', '', _('Read error'), warning])
        self.status.set_text(_('Diagnostics completed:') + ' ' + str(len(findings) + len(source.warnings)))

    def _find_editor(self):
        def find(widget):
            if hasattr(widget, 'select_launcher'):
                return widget
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    result = find(child)
                    if result is not None:
                        return result
        return find(self.get_toplevel())

    def _edit_issue(self):
        model, iterator = self.issue_tree.get_selection().get_selected()
        if iterator is None or not model[iterator][0]:
            return
        editor = self._find_editor()
        if editor and editor.select_launcher(model[iterator][0]):
            parent, child = editor.get_parent(), editor
            while parent:
                if isinstance(parent, Gtk.Stack):
                    parent.set_visible_child(child)
                    break
                child, parent = parent, parent.get_parent()

    def _backups(self, box):
        text = Gtk.Label(label=_('Restoration checks for external changes and creates a new backup. Unsaved menu edits must be discarded or applied first.'), xalign=0)
        text.set_line_wrap(True)
        box.pack_start(text, False, False, 0)
        self.backups = Gtk.ListStore(str, str, str, int)
        tree = Gtk.TreeView(model=self.backups)
        for index, title in enumerate(('Backup', 'Status', 'Files')):
            tree.append_column(Gtk.TreeViewColumn(_(title), Gtk.CellRendererText(), text=index+1))
        self.backup_tree = tree
        box.pack_start(self._scroll(tree), True, True, 0)
        row = Gtk.Box(spacing=8)
        self._button(row, 'Refresh', self._load_backups)
        self._button(row, 'Restore selected backup', self._restore_backup)
        self._button(row, 'Open backup folder', lambda: Gio.AppInfo.launch_default_for_uri(self.storage.state_home.as_uri(), None))
        box.pack_start(row, False, False, 0)

    def _load_backups(self):
        self.backups.clear()
        for backup in self.storage.list_backups():
            self.backups.append([str(backup['path']), backup['path'].name, _(backup['status']), backup['count']])

    def _restore_backup(self):
        editor = self._find_editor()
        if editor and editor.model and (editor.model.dirty or editor._draft_dirty):
            raise core.EditorError(_('Apply or discard pending menu edits before restoring a backup.'))
        model, iterator = self.backup_tree.get_selection().get_selected()
        if iterator is None:
            return
        path = model[iterator][0]
        if self._confirm('Restore this backup? Current menu files will be backed up first.'):
            restored = self.storage.restore_backup(path)
            if editor:
                editor._reload()
            self._load_backups()
            self.status.set_text(_('Backup restored. New backup:') + ' ' + str(restored))

    def _profiles(self, box):
        box.pack_start(Gtk.Label(label=_('Profiles change preferences only; launchers and menu edits are preserved.'), xalign=0), False, False, 0)
        self.preset = Gtk.ComboBoxText()
        for name, title in [('compact', 'Compact'), ('grid', 'Grid'), ('list', 'List')]:
            self.preset.append(name, _(title))
        self.preset.set_active_id('compact')
        box.pack_start(self.preset, False, False, 0)
        self._button(box, 'Apply preset', lambda: self._apply_profile(tools.preset(self.preset.get_active_id(), self.settings.settings)))
        self._button(box, 'Export preferences', lambda: self._profile_file(False))
        self._button(box, 'Import preferences', lambda: self._profile_file(True))
        self._button(box, 'Restore previous preferences', self._restore_preferences)

    def _apply_profile(self, document, confirm=True):
        checked = tools.validate_profile(document, self.settings.settings)
        if confirm and not self._confirm('Apply this profile? Current preferences will be backed up first.'):
            return False
        filepath = Path(self.settings.filepath)
        before = filepath.read_bytes()
        disk = json.loads(before)
        for key in checked:
            if disk[key].get('value') != self.settings.settings[key].get('value'):
                raise tools.ProfileError(_('Preferences changed externally. Reopen settings before applying.'))
        folder = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'canellia/settings-backups'
        backup = folder / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')
        core.UserStorage.atomic(backup, json.dumps(tools.export_profile(disk), ensure_ascii=False, indent=2).encode())
        after = copy.deepcopy(disk)
        for key, value in checked.items():
            after[key]['value'] = value
        core.UserStorage.atomic(filepath, json.dumps(after, ensure_ascii=False, indent=4).encode())
        self.settings.settings = after
        for key in checked:
            self.settings.do_key_update(key)
        if self.settings.notify_callback:
            self.settings.notify_callback(self.settings, '', '')
        self.status.set_text(_('Preferences saved. Backup:') + ' ' + str(backup))
        self._render_preview()
        return True

    def _restore_preferences(self):
        folder = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'canellia/settings-backups'
        backups = sorted(folder.glob('*.json'), reverse=True)
        if not backups:
            raise tools.ProfileError(_('No preferences backup is available.'))
        self._apply_profile(json.loads(backups[0].read_text()))

    def _profile_file(self, importing):
        dialog = Gtk.FileChooserDialog(title=_('Import preferences' if importing else 'Export preferences'),
            transient_for=self.get_toplevel(), action=Gtk.FileChooserAction.OPEN if importing else Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(_('Cancel'), Gtk.ResponseType.CANCEL, _('Import' if importing else 'Export'), Gtk.ResponseType.OK)
        if not importing:
            dialog.set_do_overwrite_confirmation(True)
            dialog.set_current_name('canellia-profile.json')
        file_filter = Gtk.FileFilter()
        file_filter.set_name('JSON')
        file_filter.add_pattern('*.json')
        dialog.add_filter(file_filter)
        response, filename = dialog.run(), None
        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
        dialog.destroy()
        if not filename:
            return
        path = Path(filename)
        if importing:
            if path.stat().st_size > 1024 * 1024:
                raise tools.ProfileError(_('Profile is too large.'))
            self._apply_profile(json.loads(path.read_text()))
        else:
            core.UserStorage.atomic(path, json.dumps(tools.export_profile(self.settings.settings), ensure_ascii=False, indent=2).encode())
            self.status.set_text(_('Profile exported.'))

    def _preview(self, box):
        box.pack_start(Gtk.Label(label=_('Scaled preview of current preferences. It does not launch applications.'), xalign=0), False, False, 0)
        self._button(box, 'Refresh preview', self._render_preview)
        self.preview_label = Gtk.Label(xalign=0)
        box.pack_start(self.preview_label, False, False, 0)
        self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(self._scroll(self.preview_box), True, True, 0)

    def _render_preview(self):
        for child in self.preview_box.get_children():
            child.destroy()
        get = self.settings.get_value
        width, height = get('custom-menu-width'), get('custom-menu-height')
        self.preview_label.set_text(_('Menu dimensions:') + f' {width} × {height}')
        scale = min(720 / max(1, width), 360 / max(1, height), 1)
        horizontal = Gtk.Box(spacing=12)
        horizontal.set_size_request(round(width * scale), round(height * scale))
        horizontal.set_border_width(12)
        if get('show-categories'):
            categories = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            for name in ('Applications', 'Accessories', 'Office', 'Graphics', 'Internet', 'Games'):
                categories.pack_start(Gtk.Label(label=_(name), xalign=0), False, False, 0)
            horizontal.pack_start(categories, False, False, 0)
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_max_children_per_line(1 if get('applications-view-mode') == 0 else 3)
        grid.set_min_children_per_line(1)
        grid.set_column_spacing(14)
        grid.set_row_spacing(14)
        icon_size = get('apps-list-icon-size') if get('applications-view-mode') == 0 else get('apps-grid-icon-size')
        for name, icon in [('Files', 'system-file-manager'), ('Calculator', 'accessories-calculator'), ('Editor', 'accessories-text-editor'), ('Internet', 'web-browser'), ('Terminal', 'utilities-terminal'), ('Preferences', 'preferences-system')]:
            tile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if get('applications-view-mode') == 0 else Gtk.Orientation.VERTICAL, spacing=6)
            image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
            image.set_pixel_size(min(max(round(icon_size * scale), 16), 96))
            tile.pack_start(image, False, False, 0)
            tile.pack_start(Gtk.Label(label=_(name)), False, False, 0)
            grid.add(tile)
        horizontal.pack_start(grid, True, True, 0)
        self.preview_box.pack_start(horizontal, False, False, 0)
        self.preview_box.show_all()
