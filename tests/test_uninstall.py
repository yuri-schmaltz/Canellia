import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('uninstallCore', ROOT/'Canellia@json/5.8/uninstallCore.py')
core = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = core
spec.loader.exec_module(core)


def result(output='', code=0):
    return subprocess.CompletedProcess([], code, output, 'query failed' if code else '')


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.user = self.root/'user'
        self.system = self.root/'system'
        for directory in (self.user, self.system):
            (directory/'applications').mkdir(parents=True)
        self.env = patch.dict('os.environ', {'XDG_DATA_HOME': str(self.user), 'XDG_DATA_DIRS': str(self.system)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.which = patch.object(core.shutil, 'which', return_value='/bin/tool')
        self.which.start()
        self.addCleanup(self.which.stop)

    def launcher(self, root, name='editor.desktop', command='/usr/bin/editor %U', extra=''):
        path = root/'applications'/name
        path.write_text('[Desktop Entry]\nType=Application\nName=Editor\nExec='+command+'\n'+extra)
        return path

    def test_local_flatpak_uses_metadata_and_full_ref(self):
        path = self.launcher(self.user, command='/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=editor org.example.Editor %U', extra='X-Flatpak=org.example.Editor\n')
        with patch.object(core, 'run', return_value=result('app/org.example.Editor/x86_64/stable\tuser\napp/org.example.Editor/x86_64/stable\tsystem\napp/org.example.Editor/x86_64/beta\tuser\n')):
            found = core.resolve(path)
        self.assertEqual([x.scope for x in found], ['user', 'system'])
        self.assertEqual(found[0].command(), ['flatpak', 'uninstall', '--user', '--noninteractive', 'app/org.example.Editor/x86_64/stable'])
        self.assertIn('--system', found[1].command())

    def test_named_installation_and_auxiliary_desktop(self):
        path = self.launcher(self.user, name='org.example.Editor-handler.desktop', command='flatpak run org.example.Editor --open-url %U', extra='X-Flatpak=org.example.Editor\n')
        with patch.object(core, 'run', return_value=result('app/org.example.Editor/aarch64/stable\twork\n')):
            found = core.resolve(path)
        self.assertIn('--installation=work', found[0].command())

    def test_flatpak_query_error_does_not_mean_absent(self):
        path = self.launcher(self.user, command='flatpak run org.example.Editor', extra='X-Flatpak=org.example.Editor\n')
        with patch.object(core, 'run', return_value=result(code=1)):
            with self.assertRaises(core.ResolutionError): core.resolve(path)
        with patch.object(core, 'run', return_value=result()):
            self.assertEqual(core.resolve(path), [])
        with patch.object(core.shutil, 'which', return_value=None):
            with self.assertRaises(core.ResolutionError): core.resolve(path)

    def test_changed_flatpak_command_is_rejected(self):
        path = self.launcher(self.user, extra='X-Flatpak=org.example.Editor\n')
        with self.assertRaises(core.ResolutionError): core.resolve(path)

    def test_native_override_resolves_original_with_multiarch_owner(self):
        path = self.launcher(self.user)
        original = self.launcher(self.system)
        def query(args):
            if '--show' in args: return result('installed')
            if args[-1] == str(path): return result(code=1)
            return result('editor:amd64: '+str(original)+'\n')
        with patch.object(core, 'run', side_effect=query):
            found = core.resolve(path)
        self.assertEqual(found[0].identity, 'editor:amd64')
        self.assertEqual(found[0].command(), ['cinnamon-remove-application', str(original)])

    def test_changed_native_command_never_selects_original(self):
        path = self.launcher(self.user, command='/usr/bin/other')
        self.launcher(self.system)
        with patch.object(core, 'run', return_value=result(code=1)) as query:
            with self.assertRaises(core.ResolutionError): core.resolve(path)
        self.assertEqual(query.call_count, 1)

    def test_uninstalled_owner_and_query_error(self):
        path = self.launcher(self.system)
        with patch.object(core, 'run', side_effect=[result('editor: '+str(path)+'\n'), result('config-files')]):
            self.assertEqual(core.resolve(path), [])
        with patch.object(core, 'run', return_value=result(code=2)):
            with self.assertRaises(core.ResolutionError): core.resolve(path)

    def test_never_mutates_launcher_and_versions_match(self):
        path = self.launcher(self.user)
        before = path.read_bytes()
        with patch.object(core, 'run', return_value=result(code=1)):
            core.resolve(path)
        self.assertEqual(path.read_bytes(), before)
        for name in ('uninstallCore.py', 'uninstallApplication.py'):
            self.assertEqual((ROOT/'Canellia@json/4.0'/name).read_bytes(), (ROOT/'Canellia@json/5.8'/name).read_bytes())


class UninstallFlowTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        self.gtk = MagicMock()
        self.gtk.ResponseType.OK = 1
        self.gtk.ResponseType.CANCEL = 0
        self.dialog = self.gtk.MessageDialog.return_value
        self.dialog.run.return_value = 1
        self.gtk.ComboBoxText.return_value.get_active.return_value = 0
        self.glib = MagicMock()
        self.glib.idle_add.side_effect = lambda function, *args: function(*args)
        gi = SimpleNamespace(require_version=lambda *args: None)
        repository = SimpleNamespace(Gtk=self.gtk, GLib=self.glib)
        spec = importlib.util.spec_from_file_location('uninstallApplication', ROOT/'Canellia@json/5.8/uninstallApplication.py')
        self.ui = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository, 'uninstallCore': core}):
            spec.loader.exec_module(self.ui)
        self.args = patch.object(sys, 'argv', ['uninstallApplication.py', '/test/editor.desktop', 'editor.desktop'])
        self.args.start()
        self.addCleanup(self.args.stop)

    def test_cancel_never_executes_removal(self):
        self.dialog.run.return_value = 0
        with patch.object(self.ui, 'resolve', return_value=[core.Installation('flatpak', 'app/org.example.Editor/x86_64/stable', 'user')]), patch.object(self.ui.subprocess, 'run') as execute, patch.object(self.ui.subprocess, 'Popen') as spawn:
            self.assertEqual(self.ui.main(), 0)
        execute.assert_not_called()
        spawn.assert_not_called()

    def test_absent_and_resolution_failure_never_execute(self):
        for outcome in ([], core.ResolutionError('query failed')):
            with self.subTest(outcome=outcome), patch.object(self.ui, 'resolve') as resolve, patch.object(self.ui, 'message') as message, patch.object(self.ui.subprocess, 'run') as execute, patch.object(self.ui.subprocess, 'Popen') as spawn:
                if isinstance(outcome, Exception): resolve.side_effect = outcome
                else: resolve.return_value = outcome
                self.ui.main()
                message.assert_called_once()
                execute.assert_not_called()
                spawn.assert_not_called()

    def test_removal_failure_reports_error_without_launcher_fallback(self):
        from unittest.mock import MagicMock
        thread = MagicMock()
        thread.start.side_effect = lambda: self.target()
        def create_thread(target, **kwargs):
            self.target = target
            return thread
        with patch.object(self.ui, 'resolve', return_value=[core.Installation('flatpak', 'app/org.example.Editor/x86_64/stable', 'user')]), patch.object(self.ui.subprocess, 'run', return_value=result(code=1)) as execute, patch.object(self.ui.threading, 'Thread', side_effect=create_thread), patch.object(self.ui, 'message') as message:
            self.ui.main()
        execute.assert_called_once()
        self.assertIn('launcher was preserved', message.call_args.args[0])
        self.assertTrue(message.call_args.args[1])
        self.gtk.main_quit.assert_called_once()
