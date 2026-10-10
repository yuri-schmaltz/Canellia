# Canellia development and release checks

This checkout contains Canellia **5.7.0**. The installer uses this checkout by
default. Remote archives require explicit URLs; no other project's release is
used implicitly.

## Structure

- `Canellia@json/4.0/`: legacy Cinnamon implementation.
- `Canellia@json/5.8/`: implementation selected for Cinnamon 5.8 and newer.
- `applet.js`: applet lifecycle, settings, categories and search orchestration.
- `display.js`, `appsview.js`, `categoriesview.js`, `sidebar.js`, `contextmenu.js`:
  UI components.
- `process.js`: asynchronous Python execution, JSON validation and a 10-second
  timeout. Failures return the provider's empty result and log a diagnostic.
- `browserData.py`: read-only SQLite snapshots with a 3-second backup limit;
  includes committed WAL transactions without copying an active database file.
- `searchEngine.py`: filesystem traversal independent of GTK.
- `search.py`: GTK window, bounded worker queue and cancellation by generation.
- `settings-schema.json`: persistent settings and their configuration layout.
- `MenuEditorPage.py`: Canellia's own GTK 3 editor in the first settings tab,
  with search, visibility filters, multiple selection, drag to categories (Ctrl
  to add), inline properties, icon selection and a launcher test. Changes are
  staged until Apply; Discard, Undo and Redo stay in memory. Closing settings
  with unsaved changes offers Apply, Discard or Cancel. Ctrl+F searches, Ctrl+S
  applies, and Ctrl+Z / Ctrl+Shift+Z undo/redo outside text fields.
- `menuEditorTree.py`: reads the resolved hierarchy through public `CMenu` and
  `Gio` APIs, including hidden/unallocated launchers and system fallback copies.
  It does not import `cme` or rearrange another application's GTK widgets.
- `menuEditorCore.py`: GTK-independent model, preserved desktop fields and XML
  rules, selective undo records (60 commands), per-user overrides, validation,
  optimistic conflict checks and recoverable multi-file storage. System files
  are read only. Both Cinnamon versions share these modules; Cinnamon 5.8 uses
  a custom page and the legacy schema uses a custom row.

Cinnamon loads each version directory separately. Common helpers are copied to
both directories, and `scripts/check.py` rejects divergence. Make changes to both
versions where appropriate. Keep UI differences in their existing entrypoints.

## Requirements and compatibility

Runtime: Cinnamon, Python **3.8+**, PyGObject and GTK 3 for the file-search window.
The integrated editor requires PyGObject, GTK 3 and the `CMenu` 3.0 introspection
library provided by Cinnamon (`gir1.2-cmenu-3.0` on Debian/Ubuntu). It does not
require the `cinnamon-menu-editor` or `cinnamon-desktop-editor` applications.
If loading fails, the first tab shows an inline explanation and Reload button.
Firefox/LibreWolf bookmarks
additionally require libgda introspection. The
installer requires Bash, Python 3.8+ and `flock`; remote installation also needs
`curl`. Applet reload uses session D-Bus and `dbus-send` when available.

The obsolete `cinnamon-version` whitelist was removed: it restricted modern
Cinnamon releases despite the multiversion implementation. Cinnamon's loader
selects the appropriate directory. This is not a claim that every Cinnamon
version or display backend has been tested; test your target desktop before
releasing. See the [Cinnamon metadata loader](https://github.com/linuxmint/cinnamon/blob/master/js/ui/extension.js).

Favicons live in `$XDG_CACHE_HOME/canellia/favicons` (default
`~/.cache/canellia/favicons`), separated by profile, with a one-day TTL and atomic
writes. Browser bookmarks refresh after 30 seconds. Cache failures do not discard
history or bookmarks. Settings remain managed by Cinnamon outside the installed
applet directory.


Menu edits follow the [XDG menu editing specification](https://specifications.freedesktop.org/menu/latest/implementation-notes.html):
the user's `cinnamon-applications.menu` merges its system parent and records
explicit Include/Exclude rules, retaining existing complex rules and layouts.
Launcher changes preserve translations, desktop actions, comments and extension
keys. A custom launcher requires a valid command before it can be applied.
Hide within a category affects that membership; Hide in All applications affects
the launcher globally. Move from a category removes that membership, while Move
from All applications removes its known memberships; Add keeps them. Removing a
system launcher creates a user-level Hidden override; removing a user-only
launcher deletes its file. Programs are never uninstalled. Individual restore
removes the override when a system fallback exists.

Apply holds a nonblocking process lock, verifies the loaded files haven't changed,
backs up originals and writes a durable journal before atomically replacing each
file. Failure rolls back; a pending crash journal is recovered at the next load.
Recovery refuses to overwrite unrelated external changes. Backups are retained
under `$XDG_STATE_HOME/canellia/menu-editor/backups` (default
`~/.local/state/canellia/menu-editor/backups`); Apply reports the exact directory.
There is no blanket removal of existing menu customizations. Multiple files do
not have filesystem-wide atomic visibility, but recovery preserves their pre-save
state after an interrupted transaction. CMenu delivers filesystem events
asynchronously; the UI debounces those updates and retains unsaved work.

## Verification

Install Node.js 22+, gettext (`msgfmt`) and Python, then run from the repository:

```sh
python3 scripts/check.py
```

This checks JavaScript syntax, Python syntax, JSON, translation catalogs,
relative module dependencies, setting bindings, common-helper consistency and
Bash syntax. It runs Python regression tests and Node tests with mocked Cinnamon
APIs. GitHub Actions runs the same command on pushes and pull requests.

Tests cover download failure, malformed/incomplete archives, unsafe ZIP paths,
failed activation with rollback, locking, version checks, executable helpers,
invalid browser JSON, helper timeout/failure, stale search results, read-only WAL
snapshots, SQL wildcard handling, favicon failures, symlink cycles, GTK thread
boundaries, cancellation and removal of applet timers.

Mocks do not establish actual GJS, GTK, theme or compositor compatibility.

For the real GTK/CMenu integration suite, install `python3-gi`,
`gir1.2-gtk-3.0`, `gir1.2-cmenu-3.0` and `xvfb`, then run:

```sh
xvfb-run -a python3 tests/gtk_menu_editor_smoke.py
```

This suite uses a real GTK settings container and Cinnamon's menu library with
isolated temporary XDG roots. It checks both entrypoints, menu round trips,
creation, properties, visibility, restore, drag payloads, undo/redo, launcher
execution, validation, conflicts, unsaved-close behavior and signal cleanup. It
does not change the user's menus or launch Cinnamon itself. The desktop smoke
test below still covers actual Cinnamon settings/theme integration.


## Install this checkout

Run inside a Cinnamon session:

```sh
bash install.sh --local --force
```

`--force` permits reinstalling the same version or deliberately downgrading.
Use `--no-reload` to install files without requesting a reload. By default the script installs this checkout. A remote Canellia archive can be
installed with `--archive HTTPS_URL --metadata-url HTTPS_URL`. No original-project
release is downloaded implicitly.

When `msgfmt` is available, installation compiles and publishes the PO catalogs
so new labels use the updated translations. Without it, existing translations
are retained.

The installer holds a per-user lock, stages on the destination filesystem,
validates the package and fixes script permissions before replacing the applet.
It restores the previous directory if activation fails. Validation failures
leave the existing directory intact. A D-Bus reload failure reports that files
were installed and asks for a manual reload; it does not claim a successful
reload or discard the valid installed files.

## Desktop smoke test before release

1. Install locally and add Canellia to a panel. Check opening, closing, keyboard
   navigation, grid/list mode, resizing, categories and application actions.
2. Change several settings rapidly; verify the final layout reflects all of them.
3. Search applications, recent files, emojis, calculator expressions and browser
   data. Try empty input, accents and invalid regular expressions.
4. In the file-search window, start, stop and restart a large search. Include
   hidden files, inaccessible directories and symlink cycles.
5. Remove/re-add the applet and change the theme while delayed work is pending.
   Inspect Looking Glass and session logs for errors.
6. Repeat on each intended Cinnamon release, X11/Wayland backend, panel
   orientation and scaling setting. In settings, verify that Menu editor is the
   first tab, Tips is absent, and search, filters, multiple selection, drag/move/
   add, new categories/launchers, properties, icon choice, launcher testing,
   individual restore and Apply/Discard/Undo/Redo work. Try saving conflicts and
   closing with an invalid/unsaved draft. Close/reopen settings and try multiple
   applet instances. Record actual results before expanding any
   compatibility claims.

For new settings, add defaults and validate existing user configurations. For
new search providers, follow `process.js` and the existing search-generation
checks: bound the work, handle malformed data and ignore obsolete results.

## Recovery tools and versioned data

`projectTools.py` validates version 1 `canellia-profile` documents against the
settings schema. It rejects internal keys, unknown options, invalid types,
nonfinite numbers and values outside their allowed range. ToolsPage saves
preference snapshots under `$XDG_STATE_HOME/canellia/settings-backups`, then
atomically replaces the settings JSON and updates native bindings. Exported
profiles contain preferences only, never launcher files.

Menu journals now declare version 1; legacy journals without a version remain
readable. Restore verifies each current file against the post-save hash, validates
the original backup hash, and commits restoration as a new reversible transaction.
Recovery preflights every file before writing. Invalid/future journals are kept
and shown as invalid rather than silently discarded. Category membership metadata
now has an explicit version; the existing list format remains supported.

`calculator.js` implements a bounded arithmetic parser (512 characters, 256
tokens, 32 nested primaries, 16 function arguments). Application buttons use a
WeakMap for reuse and large application lists expose 200-item pages. Ctrl+PageUp
and Ctrl+PageDown navigate pages. Preference dimensions update the current
menu without rebuilding unrelated components.

`firefoxBookmarks.py` reads native and Flatpak Firefox/LibreWolf profile lists,
snapshots databases read-only with a time limit, excludes unsafe URL schemes and
caps profiles/results. It replaces the optional libgda path. Browser providers
run concurrently; one corrupt provider does not suppress the others.

Additional session checks, from a running Cinnamon session with Python GI:

```sh
python3 scripts/desktop_runtime_smoke.py --instance 15 --output /tmp/canellia-runtime.json
python3 scripts/native_settings_smoke.py
```

The runtime suite opens/closes the actual applet, checks search, arithmetic,
empty results, page navigation and a safe `/usr/bin/true` launch, then restores
menu state and dimensions. Favorites remain unchanged. The native settings suite
uses temporary preferences/state while reading real installed launchers; it
captures all Tools subpages and validates profiles without applying them to the
user's settings. Its screenshots are written under `test-results`.

For strict GTK validation, use `bash scripts/run_gtk_suite.sh`. It opens real
windows in an isolated Xvfb/Xephyr display and treats GLib critical warnings as
errors. This avoids the GDK origin warnings caused by Gtk.OffscreenWindow while
preserving full widget and screenshot coverage. Xephyr requires an X11 session.
