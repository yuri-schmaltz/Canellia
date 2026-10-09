#!/usr/bin/env python3
"""Search a read-only Chromium snapshot and always emit a JSON array."""
import json
from pathlib import Path
import sqlite3
import sys
import urllib.parse

from browserData import snapshot
from getFavicons import get_favicons


def search_history(profile, pattern):
    words = pattern.split()
    if not words:
        return []
    connection = None
    try:
        connection = snapshot(Path(profile) / 'History')
        predicates = ["(url LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')"] * len(words)
        params = []
        for word in words:
            escaped = word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            params.extend(['%' + escaped + '%'] * 2)
        rows = connection.execute(
            'SELECT url, title, last_visit_time FROM urls WHERE ' + ' AND '.join(predicates) +
            ' ORDER BY last_visit_time DESC, visit_count DESC LIMIT 10', params
        ).fetchall()
        results = []
        for url, title, visited in rows:
            if not isinstance(url, str) or not isinstance(title, str) or not title:
                continue
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                continue
            results.append({'id': url, 'uri': url, 'domain': parsed.scheme + '://' + parsed.netloc,
                            'description': url if len(url) <= 150 else url[:150] + ' ...',
                            'name': title, 'last_visit_time': visited})
    except (OSError, sqlite3.Error, TimeoutError, ValueError) as error:
        print('Canellia: history lookup failed: ' + str(error), file=sys.stderr)
        return []
    finally:
        if connection is not None:
            connection.close()
    icons = get_favicons(Path(profile) / 'Favicons', [result['domain'] for result in results])
    for result in results:
        if result['domain'] in icons:
            result['icon_filename'] = icons[result['domain']]
    return results


if __name__ == '__main__':
    results = search_history(sys.argv[1], ' '.join(sys.argv[2:])) if len(sys.argv) > 2 else []
    print(json.dumps(results))
