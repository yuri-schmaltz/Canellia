"""Versioned profiles and non-destructive launcher diagnostics."""
import copy
import gettext
import json
import math
import os
from pathlib import Path
import shlex
import shutil

PROFILE_VERSION = 1
PROFILE_TYPES = {'switch', 'spinbutton', 'combobox', 'entry', 'keybinding', 'iconfilechooser', 'filechooser'}


class ProfileError(ValueError):
    def __init__(self, message):
        directory = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'locale'
        catalog = gettext.translation('Canellia@json', str(directory), fallback=True)
        head, separator, detail = message.partition(': ')
        super().__init__(catalog.gettext(head) + separator + detail)


def validate_profile(document, schema):
    if not isinstance(document, dict) or document.get('format') != 'canellia-profile' or document.get('version') != PROFILE_VERSION:
        raise ProfileError('Unsupported profile format or version')
    values = document.get('settings')
    if not isinstance(values, dict) or len(values) > len(schema):
        raise ProfileError('Invalid profile settings')
    checked = {}
    for key, value in values.items():
        node = schema.get(key, {})
        if node.get('type') not in PROFILE_TYPES:
            raise ProfileError('Unknown or internal setting: ' + key)
        default = node['default']
        numeric = isinstance(default, (int, float)) and not isinstance(default, bool)
        if (numeric and (isinstance(value, bool) or not isinstance(value, (int, float)) or
                         not math.isfinite(value))) or (not numeric and type(value) is not type(default)):
            raise ProfileError('Invalid value type: ' + key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not node.get('min', value) <= value <= node.get('max', value):
                raise ProfileError('Value outside allowed range: ' + key)
        if node.get('type') == 'combobox' and value not in node.get('options', {}).values():
            raise ProfileError('Unknown option: ' + key)
        if isinstance(value, str) and len(value) > 4096:
            raise ProfileError('Setting is too long: ' + key)
        checked[key] = copy.deepcopy(value)
    return checked


def export_profile(settings):
    return {'format': 'canellia-profile', 'version': PROFILE_VERSION, 'settings': {
        key: copy.deepcopy(node.get('value', node['default'])) for key, node in settings.items()
        if isinstance(node, dict) and node.get('type') in PROFILE_TYPES}}


def preset(name, schema):
    presets = {
        'compact': {'applications-view-mode': 1, 'custom-menu-width': 650, 'custom-menu-height': 450, 'apps-grid-icon-size': 40, 'sidebar-icon-size': 32},
        'grid': {'applications-view-mode': 1, 'custom-menu-width': 900, 'custom-menu-height': 600, 'apps-grid-icon-size': 64},
        'list': {'applications-view-mode': 0, 'custom-menu-width': 750, 'custom-menu-height': 600, 'apps-list-icon-size': 24},
    }
    if name not in presets:
        raise ProfileError('Unknown preset')
    result = {'format': 'canellia-profile', 'version': PROFILE_VERSION, 'settings': presets[name]}
    validate_profile(result, schema)
    return result


def diagnose(model, icon_exists=None):
    issues, commands = [], {}
    for app in model.applications.values():
        def issue(kind, message):
            issues.append({'id': app.id, 'name': app.name, 'kind': kind, 'message': message})
        try:
            app.document.validate()
        except Exception as error:
            issue('invalid', str(error))
        command = app.document.get('Exec')
        try:
            args = shlex.split(command)
        except ValueError:
            args = []
        if not args and app.document.get('DBusActivatable') == 'true':
            pass
        elif not args:
            issue('command', 'Command is empty or invalid')
        else:
            executable = args[0]
            if '%' not in executable and not ((Path(executable).is_file() and os.access(executable, os.X_OK)) if Path(executable).is_absolute() else shutil.which(executable)):
                issue('command', 'Executable was not found: ' + executable)
            # Distinct executable arguments remain distinct launcher actions.
            commands.setdefault(tuple(args), []).append(app)
        icon = app.document.get('Icon')
        if not icon:
            issue('icon', 'No icon is configured')
        elif Path(icon).is_absolute() and not Path(icon).is_file():
            issue('icon', 'Icon file was not found: ' + icon)
        elif icon_exists and not Path(icon).is_absolute() and not icon_exists(icon):
            issue('icon', 'Icon is not available in the current theme: ' + icon)
    for apps in commands.values():
        if len(apps) > 1:
            for app in apps:
                issues.append({'id': app.id, 'name': app.name, 'kind': 'duplicate',
                               'message': 'Possible duplicate command; review before removing'})
    return issues
