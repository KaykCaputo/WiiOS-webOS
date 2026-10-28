import contextlib
import sys
from io import StringIO
from unittest import TestCase
from unittest.mock import Mock, patch

from installer.cli import main, dispatch, build_info
from installer.errors import InstallerError
from installer.version import INSTALLER_VERSION, INSTALLER_BUILD


class CliOutputTests(TestCase):
    def test_tui_exit_does_not_print_json_over_restored_terminal(self):
        output = StringIO()
        with patch('installer.cli.create_engine', return_value=Mock()), patch(
                'installer.cli.dispatch', return_value={'ok': True, 'state': 'CLOSED'}), contextlib.redirect_stdout(output):
            code = main(['tui', '--transport', 'root-ssh', '--host', '192.0.2.1', '--port', '22', '--user', 'root'])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), '')

    def test_version_identifies_exact_installer_build_without_connection(self):
        output = StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as exit_result:
            main(['--version'])
        self.assertEqual(exit_result.exception.code, 0)
        self.assertIn(INSTALLER_VERSION, output.getvalue())
        self.assertIn(INSTALLER_BUILD, output.getvalue())

    def test_build_info_identifies_invoked_path_and_embedded_tui(self):
        with patch('installer.cli.sys.argv', ['wiios-installer.pyz']):
            info = build_info()
        self.assertTrue(info['ok'])
        self.assertFalse(info['legacyMenuDefault'])
        self.assertTrue(info['fullscreenTuiAvailable'])
        self.assertIn('compat-r10', info['installerVersion'])

    def test_build_info_cli_does_not_require_connection(self):
        output = StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['build-info'])
        self.assertEqual(code, 0)
        self.assertIn('\"installerVersion\": \"' + INSTALLER_VERSION + '\"', output.getvalue())

    def test_fullscreen_missing_curses_does_not_silently_use_old_menu(self):
        args = Mock(command='tui', text_mode=False)
        engine = Mock()
        with patch('installer.cli.sys.stdin.isatty', return_value=True), patch('installer.cli.sys.stdout.isatty', return_value=True), patch.dict(sys.modules, {'installer.fullscreen': None}):
            with self.assertRaises(InstallerError) as error:
                dispatch(args, engine)
        self.assertEqual(error.exception.code, 'TUI_UNAVAILABLE')

    def test_fullscreen_requires_interactive_terminal(self):
        args = Mock(command='tui', text_mode=False)
        with patch('installer.cli.sys.stdin.isatty', return_value=False):
            with self.assertRaises(InstallerError) as error:
                dispatch(args, Mock())
        self.assertEqual(error.exception.code, 'TERMINAL_REQUIRED')

    def test_legacy_menu_requires_explicit_text_mode(self):
        args = Mock(command='tui', text_mode=True)
        with patch('installer.tui.run', return_value={'ok': True}) as legacy:
            dispatch(args, Mock())
        legacy.assert_called_once()

    def test_noninteractive_commands_still_emit_json(self):
        output = StringIO()
        with patch('installer.cli.create_engine', return_value=Mock()), patch(
                'installer.cli.dispatch', return_value={'ok': True, 'state': 'APP_INSTALLED'}), contextlib.redirect_stdout(output):
            code = main(['probe', '--transport', 'root-ssh', '--host', '192.0.2.1', '--port', '22', '--user', 'root'])
        self.assertEqual(code, 0)
        self.assertIn('"APP_INSTALLED"', output.getvalue())
