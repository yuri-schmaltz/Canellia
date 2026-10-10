from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import test_helpers


class FirefoxBookmarksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)

    def profile(self, root):
        profile = root/'personal'
        profile.mkdir(parents=True)
        (root/'profiles.ini').write_text('[Profile0]\nName=personal\nPath=personal\nIsRelative=1\n')
        database = sqlite3.connect(profile/'places.sqlite')
        self.addCleanup(database.close)
        database.execute('PRAGMA journal_mode=WAL')
        database.execute('CREATE TABLE moz_places(id INTEGER, url TEXT)')
        database.execute('CREATE TABLE moz_bookmarks(id INTEGER, fk INTEGER, type INTEGER, title TEXT)')
        database.executemany('INSERT INTO moz_places VALUES (?,?)', [(1,'https://example.com'),(2,'javascript:alert(1)'),(3,'https://example.net'),(4,'http://[invalid')])
        database.executemany('INSERT INTO moz_bookmarks VALUES (?,?,?,?)', [(1,1,1,'Personal'),(2,2,1,'Unsafe'),(3,3,1,None),(4,4,1,'Invalid URL')])
        database.commit()
        return profile

    def test_custom_profile_and_flatpak_bookmarks_include_wal_without_writes(self):
        self.profile(self.home/'.mozilla/firefox')
        flatpak = self.profile(self.home/'.var/app/org.mozilla.firefox/.mozilla/firefox')
        before = (flatpak/'places.sqlite').read_bytes()
        for version in ('4.0','5.8'):
            module = test_helpers.load(version, 'firefoxBookmarks')
            self.assertEqual(len(module.profile_directories('firefox', self.home)), 2)
            self.assertEqual(module.browser_bookmarks('firefox', self.home), [{'name':'Personal','uri':'https://example.com'}])
            self.assertEqual((flatpak/'places.sqlite').read_bytes(), before)

    def test_invalid_missing_or_corrupt_data_is_an_empty_result(self):
        for version in ('4.0','5.8'):
            module = test_helpers.load(version, 'firefoxBookmarks')
            self.assertEqual(module.browser_bookmarks('unknown', self.home), [])
            root = self.home/'.librewolf'
            root.mkdir(exist_ok=True)
            (root/'profiles.ini').write_text('corrupt')
            self.assertEqual(module.browser_bookmarks('librewolf', self.home), [])
            profile = self.home/('broken-'+version)
            profile.mkdir()
            (profile/'places.sqlite').write_text('corrupt')
            self.assertEqual(module.read_bookmarks(profile), [])

    def test_helper_cli_emits_valid_json_for_unknown_browser(self):
        for version in ('4.0','5.8'):
            script = test_helpers.ROOT/'Canellia@json'/version/'firefoxBookmarks.py'
            result = subprocess.run([sys.executable,str(script),'unknown'],capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(result.stdout), [])
