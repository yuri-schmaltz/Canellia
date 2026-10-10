"""Menu editing model and recoverable per-user storage; independent of GTK.

The desktop's menu library resolves XDG merging. This module only adds explicit
user overrides to that resolved tree, retaining existing rules and desktop keys.
"""
import copy
from dataclasses import dataclass, field
import fcntl
import gettext
import hashlib
import json
import locale
import os
from pathlib import Path
import re
import shlex
import tempfile
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET


class EditorError(Exception):
    """A validation or storage problem that can be presented to the user."""
    def __init__(self, message):
        catalog = gettext.translation('Canellia@json', str(Path(os.environ.get(
            'XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'locale'), fallback=True)
        head, separator, tail = message.partition(': ')
        super().__init__(catalog.gettext(head) + separator + tail)


def folded(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))


def read_bytes(path):
    path = Path(path)
    if not path.exists():
        return None
    if path.stat().st_size > 4 * 1024 * 1024:
        raise EditorError('File is too large: ' + str(path))
    return path.read_bytes()


class DesktopFile:
    """Retain comments, localized keys, actions and unknown extension groups."""
    def __init__(self, data=None):
        self.lines = (data.decode('utf-8').splitlines() if data else
                      ['[Desktop Entry]', 'Type=Application'])
        if '[Desktop Entry]' not in self.lines:
            raise EditorError('Missing [Desktop Entry] group')

    def _positions(self):
        active = False
        for index, line in enumerate(self.lines):
            if line.startswith('['):
                active = line == '[Desktop Entry]'
            elif active and '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                yield index, key, value

    def __eq__(self, other):
        return isinstance(other, DesktopFile) and self.lines == other.lines

    def get(self, key, default=''):
        values = [value for _, name, value in self._positions() if name == key]
        value = values[-1] if values else default
        return re.sub(r'\\([sntr\\])', lambda m: {
            's': ' ', 'n': '\n', 't': '\t', 'r': '\r', '\\': '\\'}[m[1]], value)

    def localized(self, key):
        language = (os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or
                    os.environ.get('LANG') or locale.getlocale()[0] or 'C')
        language = language.split('.')[0]
        candidates = [language, language.split('@')[0], language.split('_')[0]]
        for code in dict.fromkeys(candidates):
            value = self.get(key + '[' + code + ']')
            if value:
                return value
        return self.get(key)

    def set(self, key, value, localized=False):
        if isinstance(value, bool):
            value = 'true' if value else 'false'
        value = str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        keys = {key}
        if localized:
            # Edit only the translation currently displayed, keeping all others.
            language = (os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG', 'C')).split('.')[0]
            for code in (language, language.split('@')[0], language.split('_')[0]):
                translated = key + '[' + code + ']'
                if any(name == translated for _, name, _ in self._positions()):
                    keys.add(translated)
                    break
        found = set()
        for index, name, _ in list(self._positions()):
            if name in keys:
                self.lines[index] = name + '=' + value
                found.add(name)
        if key not in found:
            start = self.lines.index('[Desktop Entry]') + 1
            self.lines.insert(start, key + '=' + value)

    def to_bytes(self):
        return ('\n'.join(self.lines) + '\n').encode('utf-8')

    def validate(self):
        if not self.localized('Name').strip():
            raise EditorError('Name is required')
        if self.get('Type') == 'Directory':
            return
        if self.get('Type') != 'Application':
            raise EditorError('Only application launchers can be edited')
        command = self.get('Exec').strip()
        if not command and self.get('DBusActivatable') == 'true':
            return
        if not command or any(c in command for c in '\n\r\x00'):
            raise EditorError('A valid command is required')
        try:
            arguments = shlex.split(command)
        except ValueError as error:
            raise EditorError('Invalid command: ' + str(error)) from error
        if not arguments or not arguments[0]:
            raise EditorError('A valid command is required')
        # Desktop Exec field codes are not shell substitutions.
        codes = []
        index = 0
        while index < len(command):
            if command[index] != '%':
                index += 1
                continue
            if index + 1 == len(command) or command[index + 1] not in 'fFuUdDnNickvm%':
                raise EditorError('Unsupported command field code')
            codes.append(command[index + 1])
            index += 2
        if sum(code in 'fFuU' for code in codes) > 1:
            raise EditorError('Only one file or URL field code is allowed')


@dataclass
class Application:
    id: str
    document: DesktopFile
    source: Path = None
    fallback: bytes = None
    memberships: dict = field(default_factory=dict)  # menu path -> visible there
    custom: bool = False

    @property
    def name(self):
        return self.document.localized('Name') or self.id

    @property
    def visible(self):
        return self.document.get('Hidden') != 'true' and self.document.get('NoDisplay') != 'true'


@dataclass
class Category:
    path: tuple
    name: str
    icon: str = 'folder'
    directory_id: str = ''
    document: DesktopFile = None
    source: Path = None
    fallback: bytes = None
    visible: bool = True
    custom: bool = False


class MenuDocument:
    def __init__(self, data, root_name='Applications'):
        if data and b'<!ENTITY' in data.upper():
            raise EditorError('XML entities are not supported')
        try:
            self.root = ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))) if data else ET.Element('Menu')
        except ET.ParseError as error:
            raise EditorError('Invalid menu XML: ' + str(error)) from error
        if self.root.tag != 'Menu':
            raise EditorError('The menu XML must have a Menu root')
        if data is None:
            ET.SubElement(self.root, 'Name').text = root_name
            ET.SubElement(self.root, 'MergeFile', type='parent')

    def menu(self, path):
        node = self.root
        for name in path:
            child = next((c for c in node.findall('Menu') if c.findtext('Name') == name), None)
            if child is None:
                child = ET.SubElement(node, 'Menu')
                ET.SubElement(child, 'Name').text = name
            node = child
        return node

    def text(self, path, tag, value):
        node = self.menu(path)
        if not any(c.text == value for c in node.findall(tag)):
            ET.SubElement(node, tag).text = value

    def clear_filename(self, path, item_id):
        node = self.menu(path)
        for rule in list(node):
            if rule.tag in ('Include', 'Exclude'):
                for child in list(rule):
                    if child.tag == 'Filename' and child.text == item_id:
                        rule.remove(child)
                if not len(rule):
                    node.remove(rule)

    def membership(self, path, item_id, include):
        self.clear_filename(path, item_id)
        rule = ET.SubElement(self.menu(path), 'Include' if include else 'Exclude')
        ET.SubElement(rule, 'Filename').text = item_id

    def deleted(self, path, deleted):
        node = self.menu(path)
        for child in list(node):
            if child.tag in ('Deleted', 'NotDeleted'):
                node.remove(child)
        ET.SubElement(node, 'Deleted' if deleted else 'NotDeleted')

    def to_bytes(self):
        return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(self.root, encoding='utf-8') + b'\n'


class UserStorage:
    """Lock, optimistic conflict checks, durable backups and crash recovery."""
    def __init__(self, config_home=None, data_home=None, state_home=None):
        self.config_home = Path(config_home or os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))).absolute()
        self.data_home = Path(data_home or os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))).absolute()
        self.state_home = Path(state_home or os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))).absolute() / 'canellia/menu-editor'
        self.roots = [self.config_home / 'menus', self.data_home / 'applications', self.data_home / 'desktop-directories']

    def safe(self, path):
        path = Path(path).absolute()
        if not any(path != root and root in path.parents for root in self.roots):
            raise EditorError('Path is outside the user menu directories: ' + str(path))
        for parent in (path,) + tuple(path.parents):
            if parent.is_symlink():
                raise EditorError('Symbolic links cannot be edited: ' + str(parent))
        return path

    @staticmethod
    def atomic(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            path.unlink(missing_ok=True)
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.chmod(0o644)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        descriptor = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _recover(self):
        for journal in sorted(self.state_home.glob('backups/*/journal.json')):
            record = self._journal(journal)
            if record['status'] != 'pending':
                continue
            recovery = []
            for entry in reversed(record['files']):
                path = self.safe(entry['path'])
                current = read_bytes(path)
                digest = hashlib.sha256(current).hexdigest() if current is not None else None
                if digest not in (entry['before_hash'], entry['after_hash']):
                    raise EditorError('Recovery conflict; backup retained at: ' + str(journal.parent))
                original = self._backup_original(journal.parent, entry)
                recovery.append((path, original))
            # Validate the whole transaction before restoring any file.
            for path, original in recovery:
                self.atomic(path, original)
            record['status'] = 'recovered'
            self.atomic(journal, json.dumps(record).encode())

    @staticmethod
    def _journal(path):
        try:
            if path.stat().st_size > 4 * 1024 * 1024 or path.is_symlink():
                raise EditorError('Invalid backup journal: ' + str(path))
            record = json.loads(path.read_text())
            if (not isinstance(record, dict) or record.get('version', 1) != 1 or
                record.get('status') not in ('pending', 'committed', 'recovered') or
                not isinstance(record.get('files'), list) or len(record['files']) > 10000):
                raise EditorError('Unsupported backup version: ' + str(path))
            for entry in record['files']:
                if not isinstance(entry, dict) or not {'path', 'backup', 'before_hash', 'after_hash'} <= entry.keys():
                    raise EditorError('Incomplete backup journal')
                if not isinstance(entry['path'], str):
                    raise EditorError('Invalid backup path')
                for key in ('before_hash', 'after_hash'):
                    value = entry[key]
                    if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)):
                        raise EditorError('Invalid backup fingerprint')
            return record
        except (OSError, ValueError, AttributeError) as error:
            raise EditorError('Cannot read backup journal: ' + str(path)) from error

    @staticmethod
    def _backup_original(backup, entry):
        original = None
        if entry['backup'] is not None:
            filename = entry['backup']
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise EditorError('Invalid backup file')
            source = backup / filename
            if source.is_symlink():
                raise EditorError('Invalid backup file')
            try:
                original = source.read_bytes()
            except OSError as error:
                raise EditorError('Backup file cannot be read') from error
        digest = hashlib.sha256(original).hexdigest() if original is not None else None
        if digest != entry['before_hash']:
            raise EditorError('Backup content is damaged; restoration cancelled')
        return original

    def list_backups(self):
        result = []
        for journal in sorted(self.state_home.glob('backups/*/journal.json'), reverse=True):
            try:
                record = self._journal(journal)
                result.append({'path': journal.parent, 'status': record.get('status', 'invalid'),
                               'count': len(record['files'])})
            except EditorError:
                result.append({'path': journal.parent, 'status': 'invalid', 'count': 0})
        return result

    def restore_backup(self, backup):
        backup = Path(backup).absolute()
        root = self.state_home / 'backups'
        if backup.parent != root or backup.is_symlink():
            raise EditorError('Backup is outside the backup directory')
        record = self._journal(backup / 'journal.json')
        if record.get('status') != 'committed':
            raise EditorError('Only completed backups can be restored')
        changes, expected = {}, {}
        for entry in record['files']:
            path = self.safe(entry['path'])
            current = read_bytes(path)
            digest = hashlib.sha256(current).hexdigest() if current is not None else None
            if digest != entry['after_hash']:
                raise EditorError('Files changed after this backup; restoration cancelled: ' + str(path))
            original = self._backup_original(backup, entry)
            changes[path], expected[path] = original, current
        return self.commit(changes, expected)

    def recover(self):
        with self._lock():
            self._recover()

    def _lock(self):
        self.state_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        class Lock:
            def __enter__(inner):
                inner.handle = (self.state_home / 'editor.lock').open('a+b')
                try:
                    fcntl.flock(inner.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    inner.handle.close()
                    raise EditorError('Another menu editor is saving changes') from error
            def __exit__(inner, *args):
                inner.handle.close()
        return Lock()

    def commit(self, changes, expected):
        if not changes:
            return None
        with self._lock():
            self._recover()
            for path, original in expected.items():
                if read_bytes(path) != original:
                    raise EditorError('Files changed outside this editor. Reload before applying: ' + str(path))
            originals = {self.safe(path): read_bytes(path) for path in changes}
            backup = self.state_home / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
            backup.mkdir(parents=True, mode=0o700)
            record = {'version': 1, 'status': 'pending', 'files': []}
            for index, (path, original) in enumerate(originals.items()):
                filename = str(index) + '.bak' if original is not None else None
                if filename:
                    self.atomic(backup / filename, original)
                after = changes[path]
                record['files'].append({'path': str(path), 'backup': filename,
                    'before_hash': hashlib.sha256(original).hexdigest() if original is not None else None,
                    'after_hash': hashlib.sha256(after).hexdigest() if after is not None else None})
            journal = backup / 'journal.json'
            self.atomic(journal, json.dumps(record).encode())
            try:
                for path, data in changes.items():
                    self.atomic(self.safe(path), data)
                record['status'] = 'committed'
                self.atomic(journal, json.dumps(record).encode())
            except Exception as error:
                try:
                    self._recover()
                except Exception as recovery_error:
                    raise EditorError('Save failed; recovery required at: ' + str(backup)) from recovery_error
                raise EditorError('Save failed and changes were rolled back: ' + str(error)) from error
            return backup


class EditorModel:
    HISTORY_LIMIT = 60

    def __init__(self, storage, categories, applications, menu_name='cinnamon-applications.menu', root_name='Applications'):
        self.storage = storage
        if '/' in menu_name or not menu_name.endswith('.menu'):
            raise EditorError('Invalid menu filename')
        self.menu_path = storage.config_home / 'menus' / menu_name
        self.expected = {self.menu_path: read_bytes(self.menu_path)}
        self.menu = MenuDocument(self.expected[self.menu_path], root_name)
        self.categories = {item.path: item for item in categories}
        self.applications = {item.id: item for item in applications}
        self.pending = {}
        self.undo_stack, self.redo_stack = [], []
        for item in list(categories) + list(applications):
            if item.source:
                self.expected[item.source] = read_bytes(item.source)
        self.baseline = self._snapshot()

    @property
    def dirty(self):
        return bool(self.pending)

    def _snapshot(self):
        return copy.deepcopy((self.menu, self.categories, self.applications, self.pending))

    def _restore(self, state):
        self.menu, self.categories, self.applications, self.pending = copy.deepcopy(state)

    def _change(self, callback):
        before = self._snapshot()
        try:
            callback()
        except Exception:
            self._restore(before)
            raise
        # Retain only the records affected by each command. Keeping a complete
        # catalog for every undo step scales poorly on large application menus.
        after = self._snapshot()
        def difference(old, new):
            return {key: old.get(key) for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
        old_categories = difference(before[1], after[1])
        old_apps = difference(before[2], after[2])
        if not old_categories and not old_apps and before[3] == after[3] and before[0].to_bytes() == after[0].to_bytes():
            return
        old = (before[0], old_categories, old_apps, before[3])
        new = (after[0], {key: after[1].get(key) for key in old_categories},
               {key: after[2].get(key) for key in old_apps}, after[3])
        self.undo_stack.append((old, new))
        del self.undo_stack[:-self.HISTORY_LIMIT]
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            frame = self.undo_stack.pop()
            self._apply_frame(frame[0])
            self.redo_stack.append(frame)

    def redo(self):
        if self.redo_stack:
            frame = self.redo_stack.pop()
            self._apply_frame(frame[1])
            self.undo_stack.append(frame)

    def _apply_frame(self, frame):
        self.menu = copy.deepcopy(frame[0])
        self.pending = copy.deepcopy(frame[3])
        for records, changes in ((self.categories, frame[1]), (self.applications, frame[2])):
            for key, value in changes.items():
                if value is None:
                    records.pop(key, None)
                else:
                    records[key] = copy.deepcopy(value)

    def discard(self):
        self._restore(self.baseline)
        self.undo_stack.clear()
        self.redo_stack.clear()

    def _stage(self, path, data):
        path = self.storage.safe(path)
        if path not in self.expected:
            self.expected[path] = read_bytes(path)
        if self.expected[path] == data:
            self.pending.pop(path, None)
        else:
            self.pending[path] = data

    def _save_menu(self):
        # CMenu omits Hidden launchers. Preserve their category associations in
        # the user override, so a restart cannot turn restoration into a move.
        for app in self.applications.values():
            if not app.visible and (self.pending.get(self._app_target(app)) is not None or
                                    app.document.get('X-Canellia-Category-Memberships')):
                app.document.set('X-Canellia-Category-Memberships', json.dumps(
                    {'version': 1, 'categories': [[list(path), visible] for path, visible in sorted(app.memberships.items())]}))
                self._save_app(app)
        self._stage(self.menu_path, self.menu.to_bytes())

    def _save_app(self, app):
        app.document.validate()
        self._stage(self._app_target(app), app.document.to_bytes())

    def _app_target(self, app):
        root = self.storage.data_home / 'applications'
        if app.source and root in app.source.parents:
            return app.source
        return root / app.id

    def edit_application(self, item_id, values):
        def change():
            app = self.applications[item_id]
            for key, value in values.items():
                if key not in ('Name', 'Comment', 'Icon', 'Exec', 'Terminal', 'Categories', 'Path'):
                    raise EditorError('Unsupported launcher property: ' + key)
                current = app.document.localized(key) if key in ('Name', 'Comment') else app.document.get(key)
                if isinstance(value, bool):
                    current = current.strip().lower() == 'true'
                if current != value:
                    app.document.set(key, value, localized=key in ('Name', 'Comment'))
            self._save_app(app)
        self._change(change)

    def set_visible(self, ids, visible, category=None):
        def change():
            for item_id in ids:
                app = self.applications[item_id]
                if category is None:
                    app.document.set('Hidden', False)
                    app.document.set('NoDisplay', not visible)
                    self._save_app(app)
                if category is not None:
                    self.menu.membership(category, app.id, visible)
                    app.memberships[category] = visible
                elif visible and not any(app.memberships.values()):
                    for path in app.memberships or {(): True}:
                        self.menu.membership(path, app.id, True)
                        app.memberships[path] = True
            self._save_menu()
        self._change(change)

    def move(self, ids, target, source=None, add=False):
        if target not in self.categories:
            raise EditorError('Unknown destination category')
        def change():
            for item_id in ids:
                app = self.applications[item_id]
                if not add:
                    paths = [source] if source is not None else list(app.memberships)
                    for path in paths:
                        if path != target and path in app.memberships:
                            self.menu.membership(path, app.id, False)
                            app.memberships[path] = False
                self.menu.membership(target, app.id, True)
                self.menu.text(target, 'AppDir', str(self.storage.data_home / 'applications'))
                app.memberships[target] = True
            self._save_menu()
        self._change(change)

    def create_application(self, target, name='New application'):
        if target not in self.categories:
            raise EditorError('Unknown destination category')
        item_id = 'canellia-' + uuid.uuid4().hex + '.desktop'
        def change():
            document = DesktopFile()
            document.set('Name', name)
            document.set('Exec', '')
            app = Application(item_id, document, memberships={target: True}, custom=True)
            self.applications[item_id] = app
            self._stage(self.storage.data_home / 'applications' / app.id, app.document.to_bytes())
            self.menu.membership(target, item_id, True)
            self.menu.text(target, 'AppDir', str(self.storage.data_home / 'applications'))
            self._save_menu()
        self._change(change)
        return item_id

    def duplicate(self, item_id, target):
        if target not in self.categories:
            raise EditorError('Unknown destination category')
        new_id = 'canellia-' + uuid.uuid4().hex + '.desktop'
        def change():
            document = copy.deepcopy(self.applications[item_id].document)
            document.set('Name', self.applications[item_id].name + ' (copy)', localized=True)
            document.set('Hidden', False)
            document.set('NoDisplay', False)
            app = Application(new_id, document, memberships={target: True}, custom=True)
            self.applications[new_id] = app
            # A copied Categories field otherwise lets CMenu allocate the copy
            # back to the original categories, despite the chosen destination.
            for path in self.categories:
                if path and path != target:
                    self.menu.membership(path, new_id, False)
                    app.memberships[path] = False
            self._save_app(app)
            self.menu.membership(target, new_id, True)
            self.menu.text(target, 'AppDir', str(self.storage.data_home / 'applications'))
            self._save_menu()
        self._change(change)
        return new_id

    def remove(self, ids, category=None):
        if category is not None:
            if category not in self.categories:
                raise EditorError('Unknown category')
            self.set_visible(ids, False, category)
            return
        def change():
            for item_id in ids:
                app = self.applications[item_id]
                if app.fallback is None and (app.custom or (app.source and self.storage.data_home in app.source.parents)):
                    self._stage(self._app_target(app), None)
                    for path in app.memberships:
                        self.menu.membership(path, item_id, False)
                    del self.applications[item_id]
                else:
                    app.document.set('Hidden', True)
                    self._save_app(app)
            self._save_menu()
        self._change(change)

    def restore_applications(self, ids):
        def change():
            for item_id in ids:
                app = self.applications[item_id]
                if app.fallback is None:
                    raise EditorError('No system version is available for: ' + app.name)
                app.document = DesktopFile(app.fallback)
                self._stage(self._app_target(app), None)
                for node in self.menu.root.iter('Menu'):
                    for rule in list(node):
                        if rule.tag in ('Include', 'Exclude'):
                            for child in list(rule):
                                if child.tag == 'Filename' and child.text == item_id:
                                    rule.remove(child)
                            if not len(rule):
                                node.remove(rule)
                for path in app.memberships:
                    app.memberships[path] = True
            self._save_menu()
        self._change(change)

    def create_category(self, parent, name):
        if parent not in self.categories:
            raise EditorError('Unknown parent category')
        if not name.strip():
            raise EditorError('Name is required')
        category_id = 'canellia-' + uuid.uuid4().hex
        path = parent + (category_id,)
        def change():
            document = DesktopFile()
            document.set('Type', 'Directory')
            document.set('Name', name.strip())
            document.set('Icon', 'folder')
            category = Category(path, name.strip(), directory_id=category_id + '.directory', document=document, custom=True)
            self.categories[path] = category
            self._save_category(category)
            self.menu.text(path, 'Directory', category.directory_id)
            self.menu.text(path, 'DirectoryDir', str(self.storage.data_home / 'desktop-directories'))
            self.menu.deleted(path, False)
            # Keep user-created empty categories accessible in the editor.
            layout = ET.SubElement(self.menu.menu(path), 'DefaultLayout', show_empty='true')
            ET.SubElement(layout, 'Merge', type='menus')
            ET.SubElement(layout, 'Merge', type='files')
            self._save_menu()
        self._change(change)
        return path

    def _save_category(self, category):
        category.document.validate()
        self._stage(self.storage.data_home / 'desktop-directories' / category.directory_id, category.document.to_bytes())
        self.menu.text(category.path, 'Directory', category.directory_id)

    def edit_category(self, path, name, icon, comment='', visible=True):
        if not path:
            raise EditorError('The root category cannot be edited')
        def change():
            category = self.categories[path]
            if category.document is None:
                category.document = DesktopFile()
                category.document.set('Type', 'Directory')
            if not category.directory_id:
                category.directory_id = 'canellia-' + uuid.uuid4().hex + '.directory'
                self.menu.text(path, 'Directory', category.directory_id)
            for key, value in [('Name', name), ('Icon', icon), ('Comment', comment), ('NoDisplay', not visible)]:
                category.document.set(key, value, localized=key in ('Name', 'Comment'))
            category.name, category.icon, category.visible = name, icon, visible
            self._save_category(category)
            self.menu.text(path, 'DirectoryDir', str(self.storage.data_home / 'desktop-directories'))
            # NoDisplay keeps hidden categories available through CMenu's public
            # INCLUDE_NODISPLAY API, so users can show them again after reload.
            self.menu.deleted(path, False)
            self._save_menu()
        self._change(change)

    def restore_category(self, path):
        if not path:
            raise EditorError('Select a category to restore')
        def change():
            category = self.categories[path]
            if category.fallback is None:
                raise EditorError('No system version is available for this category')
            category.document = DesktopFile(category.fallback)
            category.name = category.document.localized('Name')
            category.icon = category.document.get('Icon', 'folder')
            category.visible = category.document.get('NoDisplay') != 'true'
            self._stage(self.storage.data_home / 'desktop-directories' / category.directory_id, None)
            self.menu.deleted(path, False)
            self._save_menu()
        self._change(change)

    def apply(self):
        for path, data in self.pending.items():
            if data is not None and path.suffix in ('.desktop', '.directory'):
                DesktopFile(data).validate()
        backup = self.storage.commit(self.pending, self.expected)
        for path, data in self.pending.items():
            self.expected[path] = data
        self.pending.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.baseline = self._snapshot()
        return backup

    def search(self, text='', category=None, visibility='all'):
        terms = folded(text).split()
        result = []
        for app in self.applications.values():
            if app.document.get('Hidden') == 'true' and visibility != 'hidden':
                continue
            if category is not None and category not in app.memberships:
                continue
            if category is not None and not app.memberships.get(category, False) and visibility != 'hidden':
                continue
            visible = app.visible and (any(app.memberships.values()) if category is None else app.memberships.get(category, False))
            if visibility == 'visible' and not visible or visibility == 'hidden' and visible:
                continue
            if visibility == 'custom' and not (app.custom or (app.source and self.storage.data_home in app.source.parents) or
                                             self.pending.get(self._app_target(app)) is not None):
                continue
            haystack = folded(' '.join((app.name, app.document.get('Exec'), app.document.localized('Comment'), app.id)))
            if all(term in haystack for term in terms):
                result.append(app)
        return sorted(result, key=lambda app: folded(app.name))
