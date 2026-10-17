"""Resolve installations without modifying launchers or installed applications."""
import configparser
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


class ResolutionError(Exception):
    pass


@dataclass(frozen=True)
class Installation:
    kind: str
    identity: str
    scope: str = ''
    desktop: str = ''

    def command(self):
        if self.kind == 'flatpak':
            scope = ('--user' if self.scope == 'user' else '--system'
                     if self.scope in ('system', 'default') else '--installation=' + self.scope)
            return ['flatpak', 'uninstall', scope, '--noninteractive', self.identity]
        if not shutil.which('cinnamon-remove-application'):
            raise ResolutionError('The native application uninstaller is unavailable.')
        return ['cinnamon-remove-application', self.desktop]


def run(arguments):
    try:
        return subprocess.run(arguments, capture_output=True, text=True, timeout=30,
                              env={**os.environ, 'LC_ALL': 'C'})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ResolutionError(str(error)) from error


def read_desktop(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        with Path(path).open() as stream:
            parser.read_file(stream)
        return dict(parser['Desktop Entry'])
    except (OSError, KeyError, configparser.Error, UnicodeError) as error:
        raise ResolutionError('Cannot read launcher: ' + str(path)) from error


def exec_tokens(entry):
    try:
        return shlex.split(entry.get('exec', ''))
    except ValueError as error:
        raise ResolutionError('Invalid launcher command.') from error


def desktop_id(path, roots):
    for root in roots:
        try:
            return '-'.join(path.relative_to(root / 'applications').parts)
        except ValueError:
            pass
    return path.name[:-8] if path.name.endswith('.desktop:flatpak') else path.name


def resolve(path, item_id=None):
    path = Path(path).absolute()
    entry = read_desktop(path)
    tokens = exec_tokens(entry)
    flatpak_id = entry.get('x-flatpak', '')
    if flatpak_id:
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,}', flatpak_id):
            raise ResolutionError('Invalid Flatpak application ID.')
        # A retained X-Flatpak key must not identify an unrelated edited command.
        if not tokens or Path(tokens[0]).name != 'flatpak' or 'run' not in tokens or flatpak_id not in tokens:
            raise ResolutionError('The launcher command no longer matches its Flatpak application.')
        if not shutil.which('flatpak'):
            raise ResolutionError('Flatpak is unavailable.')
        result = run(['flatpak', 'list', '--app', '--columns=ref,installation'])
        if result.returncode:
            raise ResolutionError(result.stderr.strip() or 'Cannot query Flatpak installations.')
        branch = next((t.split('=', 1)[1] for t in tokens if t.startswith('--branch=')), None)
        arch = next((t.split('=', 1)[1] for t in tokens if t.startswith('--arch=')), None)
        matches = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) != 2:
                continue
            ref, scope = fields
            parts = ref.split('/')
            # flatpak list commonly omits the app/ prefix for application refs.
            if len(parts) == 3:
                parts.insert(0, 'app')
                ref = '/'.join(parts)
            if len(parts) == 4 and parts[:2] == ['app', flatpak_id] and (
                    not arch or parts[2] == arch) and (not branch or parts[3] == branch):
                matches.append(Installation('flatpak', ref, scope))
        return list(dict.fromkeys(matches))

    data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    roots = [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]
    identity = item_id or desktop_id(path, [data_home] + roots)
    if identity.endswith('.desktop:flatpak'):
        identity = identity[:-8]
    if '/' in identity or identity in ('.', '..'):
        raise ResolutionError('Invalid desktop ID.')
    candidates = [path]
    for root in roots:
        directory = root / 'applications'
        if directory.is_dir():
            candidates.extend(p for p in directory.rglob('*.desktop')
                              if '-'.join(p.relative_to(directory).parts) == identity and p != path)
    if not shutil.which('dpkg-query'):
        raise ResolutionError('The native package database is unavailable.')
    for candidate in candidates:
        # Only use an original whose complete command matches the active launcher.
        if candidate != path and exec_tokens(read_desktop(candidate)) != tokens:
            raise ResolutionError('The customized launcher command differs from the original. Its package association is ambiguous.')
        result = run(['dpkg-query', '--search', str(candidate)])
        if result.returncode == 1:
            continue
        if result.returncode:
            raise ResolutionError(result.stderr.strip() or 'Cannot query package ownership.')
        owners = set()
        for line in result.stdout.splitlines():
            owner, separator, filename = line.partition(': ')
            if separator and filename == str(candidate):
                owners.update(owner.split(', '))
        installed = []
        for owner in sorted(owners):
            status = run(['dpkg-query', '--show', '--showformat=${db:Status-Status}', owner])
            if status.returncode not in (0, 1):
                raise ResolutionError(status.stderr.strip() or 'Cannot query package status.')
            if status.returncode == 0 and status.stdout.strip() == 'installed':
                installed.append(Installation('native', owner, desktop=str(candidate)))
        if len(installed) > 1:
            raise ResolutionError('The launcher belongs to multiple packages.')
        if installed:
            return installed
    return []
