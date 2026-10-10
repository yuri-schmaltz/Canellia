#!/usr/bin/env python3
"""Read Firefox/LibreWolf bookmarks without libgda or database writes."""
import configparser
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import urlsplit
from browserData import snapshot


def profile_directories(browser, home=None):
    home = Path(home or Path.home())
    roots = {'firefox': [home/'.mozilla/firefox', home/'.var/app/org.mozilla.firefox/.mozilla/firefox'],
             'librewolf': [home/'.librewolf', home/'.var/app/io.gitlab.librewolf-community/.librewolf']}
    found = []
    for root in roots.get(browser, []):
        config = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            filename = root/'profiles.ini'
            if not filename.is_file() or filename.stat().st_size > 1024 * 1024:
                continue
            config.read(filename, encoding='utf-8')
            for section in config.sections():
                if not section.startswith('Profile') or not config.has_option(section, 'Path'):
                    continue
                path = Path(config.get(section, 'Path'))
                if config.get(section, 'IsRelative', fallback='1') == '1':
                    path = root/path
                path = path.resolve()
                if path not in found and (path/'places.sqlite').is_file():
                    found.append(path)
                    if len(found) >= 8:
                        return found
        except (OSError, ValueError, configparser.Error):
            continue
    return found


def read_bookmarks(profile):
    connection = None
    try:
        connection = snapshot(Path(profile)/'places.sqlite', timeout=0.75)
        rows = connection.execute('SELECT b.title, p.url FROM moz_bookmarks b JOIN moz_places p ON b.fk=p.id '
            'WHERE b.type=1 AND b.title IS NOT NULL ORDER BY b.id LIMIT 5000').fetchall()
        results = []
        for name, uri in rows:
            if not isinstance(name, str) or not isinstance(uri, str) or not name:
                continue
            try:
                parsed = urlsplit(uri)
            except ValueError:
                continue
            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                continue
            results.append({'name':name[:512], 'uri':uri})
        return results
    except (OSError, ValueError, sqlite3.Error, TimeoutError) as error:
        print('Canellia: bookmarks lookup failed: '+str(error), file=sys.stderr)
        return []
    finally:
        if connection is not None:
            connection.close()


def browser_bookmarks(browser, home=None):
    unique = {}
    for profile in profile_directories(browser, home):
        for bookmark in read_bookmarks(profile):
            unique.setdefault(bookmark['uri'], bookmark)
            if len(unique) >= 5000:
                return list(unique.values())
    return list(unique.values())


if __name__ == '__main__':
    print(json.dumps(browser_bookmarks(sys.argv[1]) if len(sys.argv) == 2 else []))
