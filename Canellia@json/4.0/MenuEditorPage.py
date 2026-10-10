"""Canellia's own transactional GTK menu editor, embedded in settings."""
import gettext
import hashlib
import importlib
import importlib.machinery
import json
import logging
from pathlib import Path
import tempfile
import sys
import types

from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from JsonSettingsWidgets import SettingsPage, SettingsWidget


def _editor_module(name):
    """Cinnamon loads custom widgets by path without adding their directory to
    sys.path. Give sibling helpers a private package, isolated per version/path.
    """
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


EditorError = _editor_module('menuEditorCore').EditorError

_LOG = logging.getLogger(__name__)
_TRANSLATION = gettext.translation('Canellia@json', str(Path(GLib.get_user_data_dir()) / 'locale'), fallback=True)
_ = _TRANSLATION.gettext


class _EditorHost:
    def _init_editor(self, source=None):
        self._source = source
        self.model = None
        self._loading = self._disposed = self._external = False
        self._tree_signal = self._host_window = None
        self._refresh_id = 0
        self._icon_cache = {}
        self._category = self._property_target = None
        self._draft_dirty = False
        self.connect('destroy', self._dispose)
        self.connect('realize', self._attach_window)
        self._body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._body.set_hexpand(True)
        self._body.set_vexpand(True)
        self.pack_start(self._body, True, True, 0)
        self._build()
        self._reload()

    def _button(self, label, callback, box):
        button = Gtk.Button(label=_(label))
        button.connect('clicked', callback)
        if isinstance(box, Gtk.Box):
            box.pack_start(button, False, False, 0)
        else:
            box.add(button)
        return button

    def _build(self):
        toolbar = Gtk.Box(spacing=6)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(_('Search applications or commands'))
        self.search.connect('search-changed', self._search_changed)
        toolbar.pack_start(self.search, True, True, 0)
        self.filter = Gtk.ComboBoxText()
        for key, label in [('all', 'All applications'), ('visible', 'Visible'), ('hidden', 'Hidden'), ('custom', 'Custom')]:
            self.filter.append(key, _(label))
        self.filter.set_active_id('all')
        self.filter.connect('changed', self._search_changed)
        toolbar.pack_start(self.filter, False, False, 0)
        self.reload_button = self._button('Reload', self._reload_clicked, toolbar)
        self._body.pack_start(toolbar, False, False, 0)
        panels = Gtk.Grid(column_spacing=8, column_homogeneous=False)
        panels.set_hexpand(True)
        panels.set_vexpand(True)
        self.category_store = Gtk.TreeStore(str, str, str)
        self.category_tree = Gtk.TreeView(model=self.category_store)
        self.category_tree.set_headers_visible(False)
        self._name_column(self.category_tree, 'Categories', 0, 2)
        self.category_tree.get_selection().connect('changed', self._category_selected)
        category_panel = self._scroll(self.category_tree, 180)
        category_panel.set_hexpand(True)
        panels.attach(category_panel, 0, 0, 1, 1)
        panels.attach(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), 1, 0, 1, 1)
        self.app_store = Gtk.ListStore(str, bool, str, str)
        self.app_tree = Gtk.TreeView(model=self.app_store)
        toggle = Gtk.CellRendererToggle()
        toggle.connect('toggled', self._toggle)
        self.app_tree.append_column(Gtk.TreeViewColumn(_('Visible'), toggle, active=1))
        self._name_column(self.app_tree, 'Applications', 2, 3)
        self.app_tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.app_tree.get_selection().connect('changed', self._app_selected)
        self.app_tree.set_tooltip_column(0)
        application_panel = self._scroll(self.app_tree, 170)
        properties_panel = self._properties()
        application_panel.set_hexpand(True)
        properties_panel.set_hexpand(True)
        panels.attach(application_panel, 2, 0, 1, 1)
        panels.attach(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), 3, 0, 1, 1)
        panels.attach(properties_panel, 4, 0, 1, 1)
        # Share only content widths; separators keep their natural thin width.
        self._column_sizes = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        for panel in (category_panel, application_panel, properties_panel):
            panel.set_vexpand(True)
            self._column_sizes.add_widget(panel)
        self._body.pack_start(panels, True, True, 0)
        actions = Gtk.FlowBox()
        actions.set_selection_mode(Gtk.SelectionMode.NONE)
        actions.set_max_children_per_line(6)
        actions.set_min_children_per_line(2)
        actions.set_column_spacing(6)
        actions.set_row_spacing(4)
        self.new_button = self._button('New application', self._new_app, actions)
        self.new_menu_button = self._button('New category', self._new_category, actions)
        self.move_button = self._button('Move to…', lambda *a: self._move_dialog(False), actions)
        self.add_button = self._button('Add to category…', lambda *a: self._move_dialog(True), actions)
        self.duplicate_button = self._button('Duplicate', self._duplicate, actions)
        self.remove_button = self._button('Remove', self._remove, actions)
        self._body.pack_start(actions, False, False, 0)
        footer = Gtk.Box(spacing=6)
        self.show_button = self._button('Show', lambda *a: self._visibility(True), footer)
        self.hide_button = self._button('Hide', lambda *a: self._visibility(False), footer)
        self.restore_button = self._button('Restore selected', self._restore_selected, footer)
        self.undo_button = self._button('Undo', lambda *a: self._history(False), footer)
        self.redo_button = self._button('Redo', lambda *a: self._history(True), footer)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status.set_max_width_chars(26)
        self.status.set_selectable(True)
        footer.pack_start(self.status, True, True, 0)
        self.discard_button = self._button('Discard', self._discard, footer)
        self.apply_button = self._button('Apply', self._apply, footer)
        self.apply_button.get_style_context().add_class('suggested-action')
        self._body.pack_start(footer, False, False, 0)
        targets = [Gtk.TargetEntry.new('application/x-canellia-applications', Gtk.TargetFlags.SAME_APP, 0)]
        self.app_tree.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets, Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        self.category_tree.enable_model_drag_dest(targets, Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        self.app_tree.connect('drag-data-get', self._drag_get)
        self.category_tree.connect('drag-data-received', self._drag_receive)
        self._body.show_all()

    @staticmethod
    def _scroll(widget, width):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(width, 240)
        scroll.add(widget)
        return scroll

    def _name_column(self, tree, title, text_index, icon_index):
        column = Gtk.TreeViewColumn(_(title))
        icon = Gtk.CellRendererPixbuf()
        column.pack_start(icon, False)
        column.set_cell_data_func(icon, self._render_icon, icon_index)
        text = Gtk.CellRendererText()
        text.set_property('ellipsize', 3)
        column.pack_start(text, True)
        column.add_attribute(text, 'text', text_index)
        column.set_expand(True)
        tree.append_column(column)

    @staticmethod
    def _resolve_icon(value):
        value = value or 'application-x-executable'
        if Path(value).is_absolute():
            from gi.repository import GdkPixbuf
            try:
                GdkPixbuf.Pixbuf.new_from_file_at_scale(value, 24, 24, True)
                return Gio.FileIcon.new(Gio.File.new_for_path(value))
            except GLib.Error:
                return Gio.ThemedIcon.new('application-x-executable')
        theme = Gtk.IconTheme.get_default()
        return Gio.ThemedIcon.new(value if theme.has_icon(value) else 'application-x-executable')

    def _render_icon(self, column, cell, model, iterator, index):
        value = model[iterator][index]
        if value not in self._icon_cache:
            self._icon_cache[value] = self._resolve_icon(value)
        cell.set_property('gicon', self._icon_cache[value])

    def _properties(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(200, -1)
        box.set_margin_left(8)
        box.pack_start(Gtk.Label(label=_('Properties'), xalign=0), False, False, 0)
        self.fields, self.field_rows = {}, {}
        for key, label in [('Name', 'Name'), ('Comment', 'Description'), ('Exec', 'Command'), ('Icon', 'Icon'), ('Categories', 'Desktop categories'), ('Path', 'Working directory')]:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row.pack_start(Gtk.Label(label=_(label), xalign=0), False, False, 0)
            entry = Gtk.Entry()
            entry.connect('changed', self._draft_changed)
            row.pack_start(entry, False, False, 0)
            box.pack_start(row, False, False, 0)
            self.fields[key], self.field_rows[key] = entry, row
            # no-show-all protects the row's conditional visibility, but also
            # prevents the parent's show_all from showing its label and entry.
            row.show_all()
            row.set_no_show_all(True)
        self.terminal = Gtk.CheckButton(label=_('Run in terminal'))
        self.terminal.set_no_show_all(True)
        self.terminal.connect('toggled', self._draft_changed)
        box.pack_start(self.terminal, False, False, 0)
        icon_actions = Gtk.Box(spacing=6)
        self._button('Choose icon…', self._choose_icon, icon_actions)
        self.icon_preview = Gtk.Image()
        icon_actions.pack_start(self.icon_preview, False, False, 0)
        box.pack_start(icon_actions, False, False, 0)
        self.fields['Icon'].connect('changed', self._preview_icon)
        self.property_button = self._button('Stage changes', self._stage_clicked, box)
        self.test_button = self._button('Test launcher', self._test, box)
        self.test_button.set_no_show_all(True)
        self.property_box = box
        return self._scroll(box, 200)

    def _preview_icon(self, *args):
        value = self.fields['Icon'].get_text().strip()
        if value.startswith('/'):
            try:
                from gi.repository import GdkPixbuf
                self.icon_preview.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(value, 24, 24, True))
            except GLib.Error:
                self.icon_preview.set_from_icon_name('image-missing', Gtk.IconSize.BUTTON)
        else:
            self.icon_preview.set_from_icon_name(value or 'application-x-executable', Gtk.IconSize.BUTTON)

    def _message(self, text):
        self.status.set_text(text)
        self.status.set_tooltip_text(text)

    def _run(self, action, refresh=True):
        try:
            result = action()
            if refresh:
                self._refresh(categories=True)
            return result
        except Exception as error:
            _LOG.exception('Menu editor operation failed')
            self._message(_('Operation failed:') + ' ' + str(error))
            return None

    def _disconnect_tree(self):
        if self._tree_signal is not None:
            self._tree_signal[0].disconnect(self._tree_signal[1])
            self._tree_signal = None

    def _reload(self):
        try:
            if self._source is None:
                self._source = _editor_module('menuEditorTree').CinnamonMenuSource()
            model = self._source.load()
            self._disconnect_tree()
            self.model = model
            tree = getattr(self._source, 'tree', None)
            if tree is not None:
                self._tree_signal = (tree, tree.connect('changed', self._tree_changed))
            self._external = self._draft_dirty = False
            self._property_target = None
            self._refresh(categories=True)
            if getattr(self._source, 'warnings', []):
                self._message(_('Some launchers could not be read.') + ' ' + self._source.warnings[0])
            return True
        except Exception as error:
            _LOG.exception('Unable to load menu')
            self._message(_('Unable to load menus. Check that Cinnamon menu support is installed, then reload.') + ' ' + str(error))
            self._buttons()
            return False

    def _tree_changed(self, *args):
        if self._disposed:
            return
        if self.model.dirty or self._draft_dirty:
            self._external = True
            self._message(_('The menu changed externally. Saving will check for conflicts.'))
        elif not self._refresh_id:
            self._refresh_id = GLib.timeout_add(250, self._delayed_reload)

    def _delayed_reload(self):
        self._refresh_id = 0
        if not self._disposed and not self.model.dirty and not self._draft_dirty:
            self._reload()
        return False

    @staticmethod
    def _encode_path(path):
        return json.dumps(path)

    @staticmethod
    def _decode_path(value):
        return tuple(json.loads(value))

    def _category_keys(self):
        keys = []
        def collect(model, path, iterator, data):
            if model[iterator][1] != '@all':
                keys.append(self._decode_path(model[iterator][1]))
        self.category_store.foreach(collect, None)
        return keys

    def _refresh(self, categories=False, selected=None):
        if self.model is None:
            return
        ids = selected if selected is not None else self._selected_ids()
        if self._category not in self.model.categories:
            self._category = None
        self._loading = True
        self._icon_cache.clear()
        if categories or set(self._category_keys()) != set(self.model.categories):
            self.category_store.clear()
            all_iter = self.category_store.append(None, [_('All applications'), '@all', 'view-grid-symbolic'])
            parents = {}
            for path, category in sorted(self.model.categories.items(), key=lambda pair: pair[0]):
                parent = parents.get(path[:-1]) if path else None
                label = category.name + ('' if category.visible else ' (' + _('Hidden') + ')')
                parents[path] = self.category_store.append(parent, [label, self._encode_path(path), category.icon])
            self.category_tree.expand_all()
            self.category_tree.get_selection().select_iter(parents.get(self._category, all_iter))
        self.app_store.clear()
        for app in self.model.search(self.search.get_text(), self._category, self.filter.get_active_id()):
            visible = app.visible and (any(app.memberships.values()) if self._category is None else app.memberships.get(self._category, False))
            iterator = self.app_store.append([app.id, visible, app.name, app.document.get('Icon') or 'application-x-executable'])
            if app.id in ids:
                self.app_tree.get_selection().select_iter(iterator)
        self._loading = False
        self._show_properties()
        self._buttons()
        self._message((_('Pending changes:') + ' ' + str(len(self.model.pending))) if self.model.dirty else _('No pending changes'))

    def _selected_ids(self):
        model, rows = self.app_tree.get_selection().get_selected_rows()
        return [model[row][0] for row in rows]

    def _stage_draft(self):
        if not self._draft_dirty or self._property_target is None:
            return True
        try:
            kind, item_id = self._property_target
            values = {key: entry.get_text() for key, entry in self.fields.items()}
            if kind == 'app':
                values['Terminal'] = self.terminal.get_active()
                self.model.edit_application(item_id, values)
            else:
                category = self.model.categories[item_id]
                self.model.edit_category(item_id, values['Name'], values['Icon'], values['Comment'], category.visible)
            self._draft_dirty = False
            self._buttons()
            return True
        except Exception as error:
            self._message(_('Invalid properties:') + ' ' + str(error))
            return False

    def _stage_clicked(self, *args):
        if self._stage_draft():
            self._refresh(categories=True)

    def _draft_changed(self, *args):
        if not self._loading and self._property_target is not None:
            self._draft_dirty = True
            self._message(_('Properties edited. Apply to save your changes.'))
            self._buttons()

    def _show_properties(self):
        ids = self._selected_ids()
        self._loading = True
        target, document = None, None
        if len(ids) == 1:
            target = ('app', ids[0])
            document = self.model.applications[ids[0]].document
        elif not ids and self._category:
            category = self.model.categories[self._category]
            target, document = ('category', self._category), category.document
        self._property_target, self._draft_dirty = target, False
        self.property_box.set_sensitive(target is not None)
        is_app = target is not None and target[0] == 'app'
        for key, entry in self.fields.items():
            entry.set_text((document.localized(key) if key in ('Name', 'Comment') else document.get(key)) if document else '')
            self.field_rows[key].set_visible(is_app or key in ('Name', 'Comment', 'Icon'))
        if target and target[0] == 'category' and not document:
            self.fields['Name'].set_text(self.model.categories[target[1]].name)
        self.terminal.set_active(document is not None and document.get('Terminal') == 'true')
        self.terminal.set_visible(is_app)
        self.test_button.set_visible(is_app)
        self._loading = False

    def _buttons(self):
        ready, ids = self.model is not None, self._selected_ids()
        if not ready:
            self.property_box.set_sensitive(False)
        for button in (self.new_button, self.new_menu_button):
            button.set_sensitive(ready)
        for button in (self.move_button, self.add_button, self.remove_button):
            button.set_sensitive(ready and bool(ids))
        for button in (self.show_button, self.hide_button, self.restore_button):
            button.set_sensitive(ready and (bool(ids) or bool(self._category)))
        self.duplicate_button.set_sensitive(ready and len(ids) == 1)
        self.undo_button.set_sensitive(ready and (bool(self.model.undo_stack) or self._draft_dirty))
        self.redo_button.set_sensitive(ready and bool(self.model.redo_stack) and not self._draft_dirty)
        dirty = ready and (self.model.dirty or self._draft_dirty)
        self.apply_button.set_sensitive(dirty)
        self.discard_button.set_sensitive(dirty)
        self.property_button.set_sensitive(self._draft_dirty)

    def _reselect_property(self):
        self._loading = True
        self.app_tree.get_selection().unselect_all()
        if self._property_target and self._property_target[0] == 'app':
            for row in self.app_store:
                if row[0] == self._property_target[1]:
                    self.app_tree.get_selection().select_iter(row.iter)
        self._loading = False

    def _app_selected(self, *args):
        if self._loading:
            return
        if not self._stage_draft():
            self._reselect_property()
            return
        self._show_properties()
        self._buttons()

    def _category_selected(self, selection):
        if self._loading:
            return
        if not self._stage_draft():
            self._loading = True
            def reselect(model, path, iterator, data):
                key = model[iterator][1]
                if key == ('@all' if self._category is None else self._encode_path(self._category)):
                    selection.select_iter(iterator)
            self.category_store.foreach(reselect, None)
            self._loading = False
            return
        model, iterator = selection.get_selected()
        if iterator is not None:
            value = model[iterator][1]
            self._category = None if value == '@all' else self._decode_path(value)
            self._refresh(selected=[])

    def _search_changed(self, *args):
        if not self._loading and self.model is not None and self._stage_draft():
            self._refresh()

    def _toggle(self, renderer, row):
        if self._stage_draft():
            item_id, visible = self.app_store[row][:2]
            self._run(lambda: self.model.set_visible([item_id], not visible, self._category))

    def _visibility(self, visible):
        if not self._stage_draft():
            return
        ids = self._selected_ids()
        if ids:
            self._run(lambda: self.model.set_visible(ids, visible, self._category))
        elif self._category:
            category = self.model.categories[self._category]
            self._run(lambda: self.model.edit_category(category.path, category.name, category.icon,
                category.document.localized('Comment') if category.document else '', visible))

    def _new_app(self, *args):
        if self._stage_draft():
            item_id = self._run(lambda: self.model.create_application(self._category or (), _('New application')), refresh=False)
            if item_id:
                self.search.set_text('')
                self.filter.set_active_id('all')
                self._refresh(selected=[item_id])
                self.fields['Name'].grab_focus()
                self.fields['Name'].select_region(0, -1)

    def _new_category(self, *args):
        if not self._stage_draft():
            return
        dialog = Gtk.Dialog(title=_('New category'), transient_for=self._window(), modal=True)
        dialog.add_buttons(_('Cancel'), Gtk.ResponseType.CANCEL, _('Create'), Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_placeholder_text(_('Category name'))
        entry.set_activates_default(True)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.get_content_area().pack_start(entry, False, False, 8)
        dialog.show_all()
        response, name = dialog.run(), entry.get_text()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            path = self._run(lambda: self.model.create_category(self._category or (), name), refresh=False)
            if path:
                self._category = path
                self._refresh(categories=True, selected=[])

    def _move_dialog(self, add):
        if not self._stage_draft():
            return
        ids = self._selected_ids()
        if not ids:
            return
        dialog = Gtk.Dialog(title=_('Add to category…' if add else 'Move to…'), transient_for=self._window(), modal=True)
        dialog.add_buttons(_('Cancel'), Gtk.ResponseType.CANCEL, _('Add' if add else 'Move'), Gtk.ResponseType.OK)
        combo = Gtk.ComboBoxText()
        for path, category in self.model.categories.items():
            combo.append(self._encode_path(path), ' / '.join(self.model.categories[path[:n]].name for n in range(len(path) + 1)))
        combo.set_active(0)
        dialog.get_content_area().pack_start(combo, False, False, 8)
        dialog.show_all()
        response, target = dialog.run(), combo.get_active_id()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and target:
            self._run(lambda: self.model.move(ids, self._decode_path(target), self._category, add))

    def _duplicate(self, *args):
        if self._stage_draft():
            ids = self._selected_ids()
            if len(ids) == 1:
                item_id = self._run(lambda: self.model.duplicate(ids[0], self._category or ()), refresh=False)
                if item_id:
                    self._refresh(selected=[item_id])

    def _confirm(self, message, label='Continue'):
        dialog = Gtk.MessageDialog(transient_for=self._window(), modal=True,
            message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE, text=_(message))
        dialog.add_buttons(_('Cancel'), Gtk.ResponseType.CANCEL, _(label), Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _remove(self, *args):
        if not self._stage_draft():
            return
        ids = self._selected_ids()
        message = ('Remove the selected applications from this category only? They remain in other categories.'
                   if self._category is not None else
                   'System applications will be hidden for your user. Custom launchers will be removed. Installed programs remain installed.')
        if ids and self._confirm(message, 'Remove'):
            self._run(lambda: self.model.remove(ids, self._category))

    def _restore_selected(self, *args):
        if not self._stage_draft():
            return
        ids = self._selected_ids()
        if ids:
            if self._category is not None:
                self._run(lambda: self.model.set_visible(ids, True, self._category))
            else:
                self._run(lambda: self.model.restore_applications(ids))
        elif self._category:
            self._run(lambda: self.model.restore_category(self._category))

    def _history(self, redo):
        if self._draft_dirty:
            self._show_properties()
            self._buttons()
            return
        if self.model:
            self.model.redo() if redo else self.model.undo()
            self._refresh(categories=True)

    def _discard(self, *args):
        self.model.discard()
        self._draft_dirty = False
        self._refresh(categories=True)

    def _apply(self, *args):
        if not self._stage_draft():
            return False
        try:
            backup = self.model.apply()
            if self._reload():
                self._message(_('Changes saved. Backup:') + ' ' + str(backup))
            return True
        except Exception as error:
            _LOG.exception('Unable to save menu changes')
            self._message(_('Save failed:') + ' ' + str(error))
            self._buttons()
            return False

    def _reload_clicked(self, *args):
        if self.model and (self.model.dirty or self._draft_dirty):
            if not self._confirm('Discard pending changes and reload the menu?', 'Reload'):
                return
        self._reload()

    def _choose_icon(self, *args):
        dialog = Gtk.FileChooserDialog(title=_('Choose icon…'), transient_for=self._window(), action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(_('Cancel'), Gtk.ResponseType.CANCEL, _('Choose'), Gtk.ResponseType.OK)
        image_filter = Gtk.FileFilter()
        image_filter.set_name(_('Images'))
        image_filter.add_mime_type('image/*')
        dialog.add_filter(image_filter)
        if dialog.run() == Gtk.ResponseType.OK:
            self.fields['Icon'].set_text(dialog.get_filename())
        dialog.destroy()

    def _test(self, *args):
        if not self._stage_draft():
            return
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        def launch():
            app = self.model.applications[ids[0]]
            app.document.validate()
            with tempfile.TemporaryDirectory(prefix='canellia-test-') as directory:
                path = Path(directory) / app.id
                path.write_bytes(app.document.to_bytes())
                info = Gio.DesktopAppInfo.new_from_filename(str(path))
                if info is None:
                    raise EditorError('The launcher is invalid or its executable is unavailable')
                context = Gdk.Display.get_default().get_app_launch_context()
                info.launch([], context)
            self._message(_('Launcher started'))
        self._run(launch, refresh=False)

    def _drag_get(self, widget, context, data, info, timestamp):
        if self._stage_draft():
            data.set(data.get_target(), 8, json.dumps({'ids': self._selected_ids(), 'source': self._category}).encode())

    def _drag_receive(self, widget, context, x, y, data, info, timestamp):
        success = False
        try:
            destination = self.category_tree.get_dest_row_at_pos(x, y)
            if destination is not None:
                row, position = destination
                value = self.category_store[row][1]
                if value != '@all' and self._stage_draft():
                    payload = json.loads(bytes(data.get_data()).decode())
                    source = tuple(payload['source']) if payload['source'] is not None else None
                    self.model.move(payload['ids'], self._decode_path(value), source, context.get_selected_action() == Gdk.DragAction.COPY)
                    self._refresh()
                    success = True
        except Exception as error:
            self._message(_('Operation failed:') + ' ' + str(error))
        Gtk.drag_finish(context, success, False, timestamp)

    def _window(self):
        window = self.get_toplevel()
        return window if isinstance(window, Gtk.Window) else None

    def _attach_window(self, *args):
        window = self._window()
        if window is not None and self._host_window is None:
            self._host_window = window
            self._configure_window(window)
            self._standardize_settings_controls(window)
            self._close_signal = window.connect('delete-event', self._on_close)
            self._key_signal = window.connect('key-press-event', self._on_key)

    def _standardize_settings_controls(self, window):
        layout_keys = {'applications-view-mode', 'sidebar-placement',
                       'sidebar-favorites', 'description-placement'}
        number_keys = {'custom-menu-width', 'custom-menu-height', 'category-icon-size',
                       'apps-list-icon-size', 'apps-grid-icon-size', 'sidebar-icon-size',
                       'menu-icon-size'}
        combos, numbers, panel_text = [], [], None
        def collect(widget):
            nonlocal panel_text
            key = getattr(widget, 'key', None)
            control = getattr(widget, 'content_widget', None)
            if key in layout_keys and isinstance(control, Gtk.ComboBox):
                combos.append(control)
            elif key in number_keys and isinstance(control, Gtk.SpinButton):
                numbers.append(control)
            elif key == 'menu-label' and isinstance(control, Gtk.Entry):
                panel_text = control
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    collect(child)
        collect(window)
        self._settings_size_groups = []
        for controls in (combos, numbers + ([panel_text] if panel_text else [])):
            if not controls:
                continue
            group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
            for control in controls:
                if control is panel_text:
                    control.set_width_chars(1)
                group.add_widget(control)
            self._settings_size_groups.append(group)

    def _configure_window(self, window):
        # Keep a consistent layout, bounded by the current monitor's usable area.
        width, height = 1100, 780
        display = window.get_display()
        monitor = display.get_monitor_at_window(window.get_window()) if window.get_window() else display.get_primary_monitor()
        if monitor is not None:
            area = monitor.get_workarea()
            width = min(width, max(1, area.width - 32))
            height = min(height, max(1, area.height - 64))
        window.set_default_size(width, height)
        window.resize(width, height)
        window.set_resizable(False)

    def _on_close(self, *args):
        if not self.model or not (self.model.dirty or self._draft_dirty):
            return False
        dialog = Gtk.MessageDialog(transient_for=self._window(), modal=True,
            message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE, text=_('There are unsaved menu changes.'))
        dialog.add_buttons(_('Cancel'), Gtk.ResponseType.CANCEL, _('Discard'), Gtk.ResponseType.REJECT, _('Apply'), Gtk.ResponseType.APPLY)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.REJECT:
            self._discard()
            return False
        if response == Gtk.ResponseType.APPLY:
            return not self._apply()
        return True

    def _on_key(self, window, event):
        if not self.get_mapped() or not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        key = Gdk.keyval_name(event.keyval).lower()
        if key == 'f':
            self.search.grab_focus()
        elif key == 's':
            self._apply()
        elif key == 'z' and not isinstance(window.get_focus(), Gtk.Entry):
            self._history(bool(event.state & Gdk.ModifierType.SHIFT_MASK))
        else:
            return False
        return True

    def _dispose(self, *args):
        self._disposed = True
        self._disconnect_tree()
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
            self._refresh_id = 0
        if self._host_window is not None:
            for handler in (self._close_signal, self._key_signal):
                if self._host_window.handler_is_connected(handler):
                    self._host_window.disconnect(handler)
            self._host_window = None


class MenuEditorPage(SettingsPage, _EditorHost):
    def __init__(self, info, settings):
        SettingsPage.__init__(self)
        self.set_margin_left(8)
        self.set_margin_right(8)
        self.set_spacing(8)
        self.set_vexpand(True)
        self._init_editor()


class MenuEditorWidget(SettingsWidget, _EditorHost):
    def __init__(self, info, key, settings):
        SettingsWidget.__init__(self)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_size_request(-1, 480)
        self._init_editor()
        self.connect('hierarchy-changed', self._expand_legacy_page)

    def _expand_legacy_page(self, *args):
        parent = self.get_parent()
        while parent is not None:
            if isinstance(parent, SettingsPage):
                parent.set_margin_left(8)
                parent.set_margin_right(8)
                break
            parent = parent.get_parent()
