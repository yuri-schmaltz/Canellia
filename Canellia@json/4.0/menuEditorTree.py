"""Public Cinnamon menu API adapter; no cinnamon-menu-editor internals."""
import os
import json
from pathlib import Path
import gi
gi.require_version('CMenu', '3.0')
from gi.repository import CMenu, Gio
if __package__:
    from .menuEditorCore import Application, Category, DesktopFile, EditorError, EditorModel, UserStorage
else:
    from menuEditorCore import Application, Category, DesktopFile, EditorError, EditorModel, UserStorage


class CinnamonMenuSource:
    def __init__(self, storage=None):
        self.storage = storage or UserStorage()
        self.tree = None
        self.warnings = []
        self.data_dirs = [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]

    @staticmethod
    def _canonical_id(item_id):
        # Gio adds this suffix to Flatpak launchers; it is not part of the file ID.
        return item_id[:-8] if item_id.endswith('.desktop:flatpak') else item_id

    def _system_files(self, subdir, suffix):
        files = {}
        for root in self.data_dirs:
            directory = root / subdir
            if directory.is_dir():
                for path in sorted(directory.rglob('*' + suffix)):
                    item_id = ('-' if suffix == '.desktop' else '/').join(path.relative_to(directory).parts)
                    files.setdefault(item_id, path)
        return files

    def _read(self, path):
        if not path:
            return None
        try:
            path = Path(path)
            if path.stat().st_size > 4 * 1024 * 1024:
                raise EditorError('File is too large: ' + str(path))
            return path.read_bytes()
        except (OSError, EditorError) as error:
            self.warnings.append(str(error))
            return None

    def load(self):
        self.storage.recover()
        self.warnings = []
        flags = (CMenu.TreeFlags.SHOW_EMPTY | CMenu.TreeFlags.INCLUDE_EXCLUDED |
                 CMenu.TreeFlags.INCLUDE_NODISPLAY | CMenu.TreeFlags.SORT_DISPLAY_NAME)
        tree = CMenu.Tree.new('cinnamon-applications.menu', flags)
        if not tree.load_sync():
            raise EditorError('Cinnamon could not load its application menu')
        root = tree.get_root_directory()
        if root is None:
            raise EditorError('The application menu has no root directory')
        system_apps = self._system_files('applications', '.desktop')
        system_dirs = self._system_files('desktop-directories', '.directory')
        user_apps = self.storage.data_home / 'applications'
        user_files = {}
        if user_apps.is_dir():
            for path in user_apps.rglob('*.desktop'):
                user_files['-'.join(path.relative_to(user_apps).parts)] = path
        categories, applications = [], {}

        def add_entry(entry, path):
            item_id = self._canonical_id(entry.get_desktop_file_id())
            source = user_files.get(item_id, system_apps.get(item_id, Path(entry.get_desktop_file_path())))
            if item_id not in applications:
                data = self._read(source)
                if data is None:
                    return
                try:
                    applications[item_id] = Application(item_id, DesktopFile(data), source,
                        self._read(system_apps.get(item_id)), custom=item_id not in system_apps)
                except (EditorError, UnicodeError) as error:
                    self.warnings.append(str(error))
                    return
            applications[item_id].memberships[path] = not entry.get_is_excluded()

        def walk(directory, path):
            source = directory.get_desktop_file_path()
            directory_id = Path(source).name if source else ''
            if source:
                for base in [self.storage.data_home] + self.data_dirs:
                    directory_root = base / 'desktop-directories'
                    if directory_root in Path(source).parents:
                        directory_id = Path(source).relative_to(directory_root).as_posix()
                        break
            override = self.storage.data_home / 'desktop-directories' / directory_id
            if directory_id and override.is_file():
                source = str(override)
            elif directory_id in system_dirs:
                source = str(system_dirs[directory_id])
            data = self._read(source)
            try:
                document = DesktopFile(data) if data else None
            except (EditorError, UnicodeError) as error:
                self.warnings.append(str(error))
                document = None
            categories.append(Category(path, document.localized('Name') if document else directory.get_name(),
                document.get('Icon', 'folder') if document else 'folder', directory_id,
                document, Path(source) if source else None, self._read(system_dirs.get(directory_id)),
                document.get('NoDisplay') != 'true' if document else not directory.get_is_nodisplay(),
                bool(path) and directory_id not in system_dirs))
            iterator = directory.iter()
            while True:
                kind = iterator.next()
                if kind == CMenu.TreeItemType.INVALID:
                    break
                if kind == CMenu.TreeItemType.DIRECTORY:
                    child = iterator.get_directory()
                    walk(child, path + (child.get_menu_id(),))
                elif kind == CMenu.TreeItemType.ENTRY:
                    add_entry(iterator.get_entry(), path)
                elif kind == CMenu.TreeItemType.ALIAS:
                    alias = iterator.get_alias()
                    if alias.get_aliased_item_type() == CMenu.TreeItemType.ENTRY:
                        add_entry(alias.get_aliased_entry(), path)
        walk(root, ())

        # Keep hidden, unallocated and user-only launchers available for restore.
        candidates = dict(system_apps)
        candidates.update(user_files)
        for info in Gio.AppInfo.get_all():
            filename = info.get_filename() if isinstance(info, Gio.DesktopAppInfo) else None
            if filename and info.get_id():
                candidates.setdefault(self._canonical_id(info.get_id()), Path(filename))
        for item_id, source in candidates.items():
            if item_id in applications:
                continue
            data = self._read(source)
            if data is None:
                continue
            try:
                document = DesktopFile(data)
                if document.get('Type') != 'Application':
                    continue
                applications[item_id] = Application(item_id, document, source,
                    self._read(system_apps.get(item_id)), custom=item_id not in system_apps)
            except (EditorError, UnicodeError) as error:
                self.warnings.append(str(error))
        category_paths = {category.path for category in categories}
        for app in applications.values():
            saved = app.document.get('X-Canellia-Category-Memberships')
            if saved and not app.visible:
                try:
                    rows = json.loads(saved)
                    if isinstance(rows, dict):
                        if rows.get('version') != 1:
                            raise ValueError('Unsupported saved category version')
                        rows = rows.get('categories')
                    if not isinstance(rows, list):
                        raise ValueError('Expected category list')
                    restored = {}
                    for row in rows:
                        if (not isinstance(row, list) or len(row) != 2 or
                            not isinstance(row[0], list) or
                            not all(isinstance(part, str) for part in row[0]) or
                            not isinstance(row[1], bool)):
                            raise ValueError('Invalid saved category association')
                        path = tuple(row[0])
                        if path in category_paths:
                            restored[path] = row[1]
                    app.memberships.update(restored)
                except (ValueError, TypeError) as error:
                    self.warnings.append('Invalid saved categories for ' + app.id + ': ' + str(error))
        model = EditorModel(self.storage, categories, list(applications.values()), tree.props.menu_basename, root.get_menu_id())
        self.tree = tree
        return model
