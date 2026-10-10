#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

TARGET_PARENT="${XDG_DATA_HOME:-$HOME/.local/share}/cinnamon/applets"
TARGET_DIR="$TARGET_PARENT/Canellia@json"
GITHUB_METADATA=""
DOWNLOAD_URL=""
LOCAL_SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/Canellia@json"
FORCE=false
RELOAD=true
TEMP_DIR=""
COMMITTED=false

fail() { echo "Canellia: $*" >&2; exit 1; }
cleanup() {
    local status=$?
    trap - EXIT HUP INT TERM
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        if ! $COMMITTED && [[ -d "$TEMP_DIR/previous" ]]; then
            if [[ ! -e "$TARGET_DIR" && ! -L "$TARGET_DIR" ]]; then
                if ! mv -- "$TEMP_DIR/previous" "$TARGET_DIR"; then
                    echo "Restore failed. Previous installation remains at $TEMP_DIR/previous" >&2
                    exit 1
                fi
            else
                echo "Previous installation retained at $TEMP_DIR/previous" >&2
                exit 1
            fi
        fi
        rm -rf -- "$TEMP_DIR"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM

while (($#)); do
    case "$1" in
        --local) LOCAL_SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/Canellia@json" ;;
        --archive)
            (($# >= 2)) || fail "--archive requires an HTTPS URL."
            DOWNLOAD_URL="$2"; LOCAL_SOURCE=""; shift ;;
        --metadata-url)
            (($# >= 2)) || fail "--metadata-url requires an HTTPS URL."
            GITHUB_METADATA="$2"; shift ;;
        --force) FORCE=true ;;
        --no-reload) RELOAD=false ;;
        --help)
            echo "Usage: bash install.sh [--local] [--force] [--no-reload] [--archive URL --metadata-url URL]"
            echo "--local installs this checkout; --force allows reinstall/downgrade."
            echo "Default: install this Canellia checkout. Remote archives must contain Canellia@json."
            exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
    shift
done
if [[ -n "$DOWNLOAD_URL" || -n "$GITHUB_METADATA" ]]; then
    [[ "$DOWNLOAD_URL" == https://* && "$GITHUB_METADATA" == https://* && -z "$LOCAL_SOURCE" ]] || fail "Use --archive and --metadata-url together with HTTPS URLs."
fi
case "${DESKTOP_SESSION:-}" in
    cinnamon|cinnamon-wayland) ;;
    *) fail "Cinnamon is not the current desktop." ;;
esac
for tool in python3 flock mktemp mv; do
    command -v "$tool" >/dev/null || fail "Missing dependency: $tool"
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else "Python 3.8 or newer is required")'
[[ -n "$LOCAL_SOURCE" ]] || command -v curl >/dev/null || fail "Missing dependency: curl"
mkdir -p -- "$TARGET_PARENT"
exec 9>"$TARGET_PARENT/.Canellia.install.lock"
flock -n 9 || fail "Another installation is running."
[[ ! -L "$TARGET_DIR" ]] || fail "Installation target must not be a symbolic link."
[[ ! -e "$TARGET_DIR" || -d "$TARGET_DIR" ]] || fail "Installation target is not a directory."
TEMP_DIR=$(mktemp -d "$TARGET_PARENT/.Canellia-install.XXXXXXXX")
download() {
    curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 120 --retry 2 "$1" --output "$2"
}
if [[ -n "$LOCAL_SOURCE" ]]; then
    [[ -d "$LOCAL_SOURCE" ]] || fail "Local applet source not found."
    SOURCE="$LOCAL_SOURCE"
    MODE=local
else
    echo "Downloading Canellia..."
    download "$GITHUB_METADATA" "$TEMP_DIR/remote.json"
    download "$DOWNLOAD_URL" "$TEMP_DIR/package.zip"
    SOURCE="$TEMP_DIR/package.zip"
    MODE=archive
fi

# Validate and stage on the destination filesystem before replacing anything.
python3 - "$MODE" "$SOURCE" "$TEMP_DIR" "$TARGET_DIR" "$FORCE" <<'PY'
import ast
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile

mode, source, temporary, target, force = sys.argv[1:]
temporary, target = Path(temporary), Path(target)

def metadata(path):
    data = json.loads(path.read_text())
    if data.get('uuid') != 'Canellia@json':
        raise ValueError('Invalid applet UUID')
    version = data.get('version', '')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', version):
        raise ValueError('Invalid applet version')
    return data

if mode == 'archive':
    extracted = temporary / 'extracted'
    with zipfile.ZipFile(source) as archive:
        total = 0
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            total += member.file_size
            kind = stat.S_IFMT(member.external_attr >> 16)
            if path.is_absolute() or '..' in path.parts or '\\' in member.filename:
                raise ValueError('Unsafe archive path')
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('Unsupported archive entry')
            if total > 100 * 1024 * 1024:
                raise ValueError('Archive is too large')
        archive.extractall(extracted)
    candidates = list(extracted.glob('*/Canellia@json'))
    if len(candidates) != 1:
        raise ValueError('Archive must contain exactly one applet')
    source = candidates[0]
else:
    source = Path(source)
for path in source.rglob('*'):
    if path.is_symlink():
        raise ValueError('Applet source contains symbolic links')
stage = temporary / 'staged'
shutil.copytree(source, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'favicon_cache'))
incoming = metadata(stage / 'metadata.json')
if mode == 'archive' and incoming['version'] != metadata(temporary / 'remote.json')['version']:
    raise ValueError('Remote metadata and archive versions differ; retry the installation')
required = ('applet.js', 'appsview.js', 'categoriesview.js', 'contextmenu.js',
            'display.js', 'sidebar.js', 'utils.js', 'emoji.js', 'suggestions.js',
            'browserBookmarks.js', 'browserHistory.js', 'settings-schema.json',
            'stylesheet.css', 'search.py', 'searchHistory.py', 'getFavicons.py')
for version in ('4.0', '5.8'):
    for filename in required:
        path = stage / version / filename
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f'Missing or empty applet file: {version}/{filename}')
for path in stage.rglob('*.json'):
    data = json.loads(path.read_text())
    if path.name == 'settings-schema.json':
        for node in list(data.values()) + list(data.get('layout', {}).values()):
            if isinstance(node, dict) and node.get('type') == 'custom':
                module = path.parent / node['file']
                if module.parent != path.parent or not module.is_file():
                    raise ValueError('Missing or unsafe custom settings module')
                classes = {item.name for item in ast.parse(module.read_text()).body if isinstance(item, ast.ClassDef)}
                if node['widget'] not in classes:
                    raise ValueError('Missing custom settings class')
for path in stage.rglob('*.js'):
    for helper in re.findall(r"runJsonScript\(['\"]([^'\"]+\.py)['\"]", path.read_text()):
        if not (path.parent / helper).is_file():
            raise ValueError('Missing subprocess helper: ' + helper)


    for dependency in re.findall(r"require\(['\"](\./[^'\"]+)['\"]\)", path.read_text()):
        required_path = path.parent / (dependency + '.js')
        if not required_path.is_file():
            raise ValueError(f'Missing JavaScript module: {required_path.name}')
for path in stage.rglob('*.py'):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ('_editor_module', '_module'):
            module = ast.literal_eval(node.args[0])
            if not (path.parent / (module + '.py')).is_file():
                raise ValueError('Missing menu editor module: ' + module)
        modules = ([node.module] if isinstance(node, ast.ImportFrom) else
                   [name.name for name in node.names] if isinstance(node, ast.Import) else [])
        for module in modules:
            if module in ('browserData', 'getFavicons', 'searchEngine', 'menuEditorCore', 'menuEditorTree') and not (path.parent / (module + '.py')).is_file():
                raise ValueError(f'Missing Python module: {module}')
for path in stage.rglob('*'):
    path.chmod(0o755 if path.is_dir() or path.suffix in ('.py', '.sh') else 0o644)
stage.chmod(0o755)

def version_tuple(value):
    parts = [int(part) for part in value.split('.')]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)
if (target / 'metadata.json').exists() and force != 'true':
    try:
        installed = metadata(target / 'metadata.json')
    except (ValueError, OSError) as error:
        raise ValueError('Installed metadata is invalid; use --force to replace it') from error
    if version_tuple(incoming['version']) <= version_tuple(installed['version']):
        (temporary / 'skip').touch()
        print('Installed version is equal or newer; use --force to reinstall.')
if not (temporary / 'skip').exists():
    if shutil.which('msgfmt'):
        for catalog in (stage / 'po').glob('*.po'):
            output = temporary / 'translations' / catalog.stem / 'LC_MESSAGES' / 'Canellia@json.mo'
            output.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['msgfmt', '--check', '-o', str(output), str(catalog)], check=True)
            shutil.copyfile(output, output.with_name('Canellia@json-' + incoming['version'] + '.mo'))
    else:
        print('msgfmt is unavailable; existing translations will be kept.', file=sys.stderr)
print(f"Validated Canellia {incoming['version']}.")
PY

[[ ! -e "$TEMP_DIR/skip" ]] || exit 0
if [[ -d "$TARGET_DIR" ]]; then
    mv -- "$TARGET_DIR" "$TEMP_DIR/previous"
fi
mv -- "$TEMP_DIR/staged" "$TARGET_DIR"
COMMITTED=true
# Publish compiled catalogs with per-file atomic replacement. A catalog write
# failure leaves the previous translation and the valid installed applet intact.
if [[ -d "$TEMP_DIR/translations" ]]; then
    python3 - "$TEMP_DIR/translations" "${XDG_DATA_HOME:-$HOME/.local/share}/locale" <<'PY_LOCALES'
import os
from pathlib import Path
import shutil
import sys
import tempfile
for source in Path(sys.argv[1]).glob('*/LC_MESSAGES/*.mo'):
    target = Path(sys.argv[2]) / source.relative_to(sys.argv[1])
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            with source.open('rb') as catalog:
                shutil.copyfileobj(catalog, output)
        temporary.chmod(0o644)
        os.replace(temporary, target)
    except OSError as error:
        print('Canellia: translation update failed: ' + str(error), file=sys.stderr)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
PY_LOCALES
fi
echo "Canellia installed successfully."
if $RELOAD; then
    if ! command -v dbus-send >/dev/null || ! dbus-send --session --print-reply --reply-timeout=10000 \
        --dest=org.Cinnamon.LookingGlass --type=method_call /org/Cinnamon/LookingGlass \
        org.Cinnamon.LookingGlass.ReloadExtension string:Canellia@json string:APPLET; then
        echo "Installed successfully, but reload failed. Reload Canellia from Cinnamon or sign in again." >&2
    fi
fi
