import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='canellia-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checkout = self.root / 'checkout'
        self.checkout.mkdir()
        shutil.copy(ROOT / 'install.sh', self.checkout / 'install.sh')
        shutil.copytree(ROOT / 'Canellia@json', self.checkout / 'Canellia@json')
        self.source = self.checkout / 'Canellia@json'
        self.version = json.loads((self.source / 'metadata.json').read_text())['version']
        self.data = self.root / 'data with spaces'
        self.parent = self.data / 'cinnamon/applets'
        self.target = self.parent / 'Canellia@json'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.archive = self.root / 'package.zip'
        self.make_archive()
        self.metadata = self.root / 'remote.json'
        shutil.copy(self.source / 'metadata.json', self.metadata)
        self.env = dict(os.environ, DESKTOP_SESSION='cinnamon', XDG_DATA_HOME=str(self.data),
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        FIXTURE_ARCHIVE=str(self.archive), FIXTURE_METADATA=str(self.metadata))
        self.stub('curl', '''import os, pathlib, shutil, sys
args = sys.argv[1:]
output = args[args.index('--output') + 1]
kind = 'archive' if output.endswith('.zip') else 'metadata'
if os.environ.get('FAIL_DOWNLOAD') == kind: sys.exit(22)
shutil.copyfile(os.environ['FIXTURE_' + kind.upper()], output)
''')
        self.stub('dbus-send', 'import sys\nsys.exit(1)\n')

    def stub(self, name, script):
        path = self.bin / name
        path.write_text('#!/usr/bin/env python3\n' + script)
        path.chmod(0o755)

    def make_archive(self, extra=None):
        with zipfile.ZipFile(self.archive, 'w') as archive:
            for path in self.source.rglob('*'):
                if path.is_file():
                    archive.write(path, 'Canellia-main/Canellia@json/' + str(path.relative_to(self.source)))
            if extra:
                archive.writestr(*extra)

    def existing(self, version='5.6.3'):
        self.target.mkdir(parents=True)
        (self.target / 'metadata.json').write_text(json.dumps({'uuid': 'Canellia@json', 'version': version}))
        (self.target / 'marker').write_text('previous installation')

    def run_installer(self, *args, **env):
        if '--local' not in args:
            args = ('--archive', 'https://example.invalid/Canellia.zip', '--metadata-url',
                    'https://example.invalid/metadata.json') + args
        return subprocess.run(['bash', str(self.checkout / 'install.sh'), *args],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=20)

    def assert_preserved(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'marker').read_text(), 'previous installation')
        self.assertFalse(list(self.parent.glob('.Canellia-install.*')))

    def test_metadata_download_failure_preserves_installation(self):
        self.existing()
        self.assert_preserved(self.run_installer(FAIL_DOWNLOAD='metadata'))

    def test_archive_download_failure_preserves_installation(self):
        self.existing()
        self.assert_preserved(self.run_installer(FAIL_DOWNLOAD='archive'))

    def test_corrupt_archive_preserves_installation(self):
        self.existing()
        self.archive.write_text('not a zip')
        self.assert_preserved(self.run_installer())

    def test_path_traversal_is_rejected(self):
        self.existing()
        self.make_archive(('../escaped', 'unsafe'))
        self.assert_preserved(self.run_installer())
        self.assertFalse((self.parent / 'escaped').exists())

    def test_archive_symlink_is_rejected(self):
        self.existing()
        member = zipfile.ZipInfo('Canellia-main/link')
        member.external_attr = 0o120777 << 16
        self.make_archive((member, '/tmp/elsewhere'))
        self.assert_preserved(self.run_installer())

    def test_incomplete_package_preserves_installation(self):
        self.existing()
        (self.source / '5.8/applet.js').unlink()
        self.make_archive()
        self.assert_preserved(self.run_installer())

    def test_missing_module_preserves_installation(self):
        self.existing()
        (self.source / '5.8/process.js').unlink()
        self.assert_preserved(self.run_installer('--local'))

    def test_invalid_python_preserves_installation(self):
        self.existing()
        (self.source / '5.8/search.py').write_text('def broken(:')
        self.assert_preserved(self.run_installer('--local'))

    def test_metadata_mismatch_preserves_installation(self):
        self.existing()
        self.metadata.write_text(json.dumps({'uuid': 'Canellia@json', 'version': '999.0'}))
        self.assert_preserved(self.run_installer())

    def test_failed_activation_restores_previous_installation(self):
        self.existing()
        real_mv = shutil.which('mv')
        self.stub('mv', f'''import os, pathlib, sys
if any(pathlib.Path(arg).name == 'staged' for arg in sys.argv[1:]): sys.exit(1)
os.execv({real_mv!r}, [{real_mv!r}] + sys.argv[1:])
''')
        self.assert_preserved(self.run_installer('--local', '--no-reload'))

    def test_successful_local_install_without_existing_parent(self):
        result = self.run_installer('--local', '--no-reload')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.target / 'metadata.json').read_text())['version'], self.version)
        for version in ('4.0', '5.8'):
            for name in ('search.py', 'searchHistory.py', 'getFavicons.py'):
                self.assertTrue(os.access(self.target / version / name, os.X_OK))
        self.assertFalse(list(self.parent.glob('.Canellia-install.*')))

    def test_default_install_is_local_and_never_downloads_upstream(self):
        result = subprocess.run(['bash', str(self.checkout / 'install.sh'), '--no-reload'],
                                env=dict(self.env, FAIL_DOWNLOAD='metadata'), capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.target / 'metadata.json').read_text())['uuid'], 'Canellia@json')

    def test_successful_archive_upgrade(self):
        self.existing()
        result = self.run_installer('--no-reload')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.target / 'marker').exists())

    def test_equal_or_newer_version_is_preserved(self):
        for version in (self.version, '999.0'):
            with self.subTest(version=version):
                if self.target.exists(): shutil.rmtree(self.target)
                self.existing(version)
                result = self.run_installer('--local', '--no-reload')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.target / 'marker').exists())

    def test_force_reinstalls_equal_version(self):
        self.existing(self.version)
        result = self.run_installer('--local', '--force', '--no-reload')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.target / 'marker').exists())

    def test_reload_failure_reports_installed_state(self):
        result = self.run_installer('--local')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.target.is_dir())
        self.assertIn('reload failed', result.stderr)

    def test_concurrent_installation_is_rejected(self):
        self.existing()
        with (self.parent / '.Canellia.install.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_preserved(self.run_installer('--local'))

    def test_target_symlink_is_rejected(self):
        self.parent.mkdir(parents=True)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (elsewhere / 'marker').write_text('keep')
        self.target.symlink_to(elsewhere)
        self.assertNotEqual(self.run_installer('--local').returncode, 0)
        self.assertEqual((elsewhere / 'marker').read_text(), 'keep')

    def test_non_cinnamon_session_and_invalid_options_fail(self):
        self.assertNotEqual(self.run_installer('--local', DESKTOP_SESSION='other').returncode, 0)
        self.assertNotEqual(self.run_installer('--unknown').returncode, 0)

    def test_invalid_installed_metadata_requires_force(self):
        self.existing()
        (self.target / 'metadata.json').write_text('corrupt')
        self.assert_preserved(self.run_installer('--local'))
        result = self.run_installer('--local', '--force', '--no-reload')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_source_metadata_preserves_installation(self):
        self.existing()
        (self.source / 'metadata.json').write_text('{"uuid":"wrong","version":"5.6.4"}')
        self.assert_preserved(self.run_installer('--local'))

    def test_local_source_symlink_preserves_installation(self):
        self.existing()
        (self.source / 'external-link').symlink_to(self.root)
        self.assert_preserved(self.run_installer('--local'))

    def test_missing_python_module_preserves_installation(self):
        self.existing()
        (self.source / '5.8/browserData.py').unlink()
        self.assert_preserved(self.run_installer('--local'))

    def test_missing_custom_settings_module_preserves_installation(self):
        self.existing()
        (self.source / '5.8/MenuEditorPage.py').unlink()
        self.assert_preserved(self.run_installer('--local'))

    def test_missing_editor_tree_preserves_installation(self):
        self.existing()
        (self.source / '5.8/menuEditorTree.py').unlink()
        self.assert_preserved(self.run_installer('--local'))

    def test_missing_editor_core_preserves_installation(self):
        self.existing()
        (self.source / '4.0/menuEditorCore.py').unlink()
        self.assert_preserved(self.run_installer('--local'))

    def test_local_install_publishes_portuguese_editor_translation(self):
        if not shutil.which('msgfmt'):
            self.skipTest('gettext is not installed')
        import gettext
        result = self.run_installer('--local', '--no-reload')
        self.assertEqual(result.returncode, 0, result.stderr)
        translation = gettext.translation('Canellia@json', self.data / 'locale', languages=['pt_BR'])
        self.assertEqual(translation.gettext('Menu editor'), 'Editor de menu')
        self.assertEqual(translation.gettext('Stage changes'), 'Atualizar item')
        self.assertEqual(translation.gettext('Apply'), 'Aplicar')

    def test_missing_subprocess_helper_preserves_installation(self):
        self.existing()
        (self.source/'5.8/firefoxBookmarks.py').unlink()
        self.assert_preserved(self.run_installer('--local'))
