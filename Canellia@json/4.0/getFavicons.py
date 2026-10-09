#!/usr/bin/env python3
"""Read Chromium favicons; cache failure never discards browser results."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import urllib.parse

from browserData import snapshot

FAVICON_CACHE_DIR = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'canellia' / 'favicons'


def get_favicons(sqlite_file, domains_list):
    icons = {}
    if not domains_list or not Path(sqlite_file).is_file():
        return icons
    connection = None
    try:
        cache = Path(FAVICON_CACHE_DIR)
        cache.mkdir(parents=True, exist_ok=True)
        profile = hashlib.sha256(str(Path(sqlite_file).resolve()).encode()).hexdigest()[:16]
        for domain in dict.fromkeys(domain for domain in domains_list if isinstance(domain, str)):
            if not isinstance(domain, str):
                continue
            parsed = urllib.parse.urlsplit(domain)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                continue
            key = hashlib.sha256(domain.encode()).hexdigest()
            filename = cache / (profile + '-' + key + '.png')
            if filename.is_file() and filename.stat().st_size and time.time() - filename.stat().st_mtime < 86400:
                icons[domain] = str(filename)
                continue
            if connection is None:
                connection = snapshot(sqlite_file)
            # A slash prevents matching example.com.evil for example.com.
            pattern = domain.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '/%'
            row = connection.execute(
                "SELECT b.image_data FROM icon_mapping AS m "
                "JOIN favicon_bitmaps AS b ON m.icon_id = b.icon_id "
                "WHERE m.page_url = ? OR m.page_url LIKE ? ESCAPE '\\' "
                "ORDER BY b.width DESC, b.height DESC LIMIT 1", (domain, pattern)
            ).fetchone()
            if not row or not row[0]:
                continue
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
                    temporary = Path(output.name)
                    output.write(row[0])
                os.replace(temporary, filename)
                icons[domain] = str(filename)
            finally:
                if temporary is not None:
                    if temporary.exists():
                        temporary.unlink()
    except (OSError, sqlite3.Error, TimeoutError, ValueError) as error:
        print('Canellia: favicon lookup failed: ' + str(error), file=sys.stderr)
    finally:
        if connection is not None:
            connection.close()
    return icons


if __name__ == '__main__':
    try:
        domains = json.loads(sys.argv[2]) if len(sys.argv) == 3 else []
        if not isinstance(domains, list):
            raise ValueError('Expected a domain list')
        result = get_favicons(sys.argv[1], domains) if len(sys.argv) == 3 else {}
    except (ValueError, OSError) as error:
        print('Canellia: ' + str(error), file=sys.stderr)
        result = {}
    print(json.dumps(result))
