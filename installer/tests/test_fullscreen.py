import curses
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from installer.fullscreen import MENU, TerminalController, TerminalModel, render, run_fullscreen
from installer.errors import InstallerError


class TerminalModelTests(unittest.TestCase):
    def test_menu_navigation_uses_one_state_and_shortcuts(self):
        model = TerminalModel()
        model.key(curses.KEY_DOWN)
        self.assertEqual(model.key('\n'), ('menu', '2'))
        self.assertEqual(model.key('3'), ('menu', '3'))
        model.key(curses.KEY_UP)
        self.assertEqual(model.key('\n'), ('menu', '1'))
        model.selected = 0
        model.key(curses.KEY_UP)
        self.assertEqual(model.key('\n'), ('menu', MENU[-1][0]))

    def test_input_supports_cursor_navigation_editing_and_cancel(self):
        model = TerminalModel()
        model.input('Confirmation', 'Type INSTALL', 'confirm')
        for character in 'INSTAL':
            model.key(character)
        model.key(curses.KEY_LEFT)
        model.key('L')
        self.assertEqual(model.key('\n'), ('submit', ('confirm', 'INSTALL')))
        model.key(curses.KEY_HOME)
        model.key(curses.KEY_DC)
        self.assertEqual(model.input_value, 'NSTALL')
        model.key('\x15')
        self.assertEqual(model.input_value, '')
        self.assertEqual(model.key('\x1b'), ('back', None))

    def test_input_has_independent_state_and_preserves_long_values(self):
        model = TerminalModel()
        model.input('Plan confirmation', 'Type phrase', 'approve', limit=64)
        for character in 'a' * 70:
            model.key(character)
        self.assertEqual(len(model.input_value), 64)
        model.input('Report path', 'Save file', 'report')
        self.assertEqual(model.input_value, '')
        self.assertEqual(model.input_token, 'report')

    def test_raw_details_are_separate_from_the_plan(self):
        model = TerminalModel()
        plan = {'operations': [{'action': 'update-ipk'}], 'approvalDigest': 'a' * 64}
        model.show('plan', 'Installation plan', ['Package: 0.3.34'], plan)
        model.key('d')
        self.assertEqual(model.page, 'details')
        model.key(curses.KEY_NPAGE)
        self.assertEqual(model.scroll, 12)
        model.key('\x1b')
        self.assertEqual(model.page, 'plan')
        self.assertEqual(model.lines, ['Package: 0.3.34'])

    def test_result_closes_to_clean_menu(self):
        model = TerminalModel()
        model.show('result', 'Compatibility', ['Firmware verified'], {'ok': True})
        self.assertEqual(model.key('\n'), ('back', None))
        model.menu()
        self.assertEqual(model.page, 'menu')
        self.assertEqual(model.scroll, 0)

    def test_render_has_single_menu_without_raw_json(self):
        model = TerminalModel()
        screen = Mock()
        screen.getmaxyx.return_value = (30, 100)
        render(screen, model, 'root@192.0.2.1:22', 'wiios.ipk')
        drawn = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertEqual(sum('Install WiiOS' in line for line in drawn), 1)
        self.assertEqual(sum('OPERATIONS' in line for line in drawn), 1)
        self.assertTrue(any('root@192.0.2.1:22' in line for line in drawn))
        self.assertFalse(any('approvalDigest' in line for line in drawn))

    def test_render_input_keeps_cursor_inside_its_field(self):
        model = TerminalModel()
        model.input('Select release', 'IPK path', 'artifact')
        for character in '/home/developer/very/long/' + 'a' * 120:
            model.key(character)
        screen = Mock()
        screen.getmaxyx.return_value = (26, 56)
        render(screen, model)
        self.assertTrue(screen.move.called)
        self.assertLess(screen.move.call_args.args[1], 53)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            'mode': 'app-only', 'action': 'install', 'adapter': None,
            'operations': [{'action': 'install-ipk', 'target': 'com.wiios.launcher'}],
            'version': '0.3.34', 'approvalDigest': 'a' * 64,
        }
        self.engine = Mock()
        self.engine.artifact = SimpleNamespace(path=Path('/tmp/release.ipk'), version='0.3.34')
        self.engine.transport.connection.endpoint = 'root@192.0.2.1:22'
        self.engine.transport.fingerprint.return_value = 'SHA256:verified'
        self.engine.plan.return_value = self.plan
        self.engine.apply.return_value = {'ok': True, 'state': 'APP_INSTALLED', 'version': '0.3.34'}
        self.controller = TerminalController(self.engine)
        self.controller.trusted = True

        def perform(token, label, operation):
            try:
                self.controller.completed_operation(token, True, operation())
            except Exception as error:
                self.controller.completed_operation(token, False, error)
        self.controller.perform = perform

    def test_full_install_flow_shows_plan_without_duplicate_menu(self):
        self.controller.choose('1')
        self.assertEqual(self.controller.model.page, 'plan')
        self.assertTrue(any('LG Home unchanged' in line for line in self.controller.model.lines))
        self.controller.dispatch_key('a')
        self.assertEqual(self.controller.model.page, 'input')
        self.assertEqual(self.controller.model.input_label, 'Type INSTALL')
        self.controller.submit('approve', 'INSTALL')
        self.assertEqual(self.controller.model.page, 'result')
        self.engine.apply.assert_called_once_with(self.plan, self.plan['approvalDigest'])
        self.assertFalse(any('approvalDigest' in line for line in self.controller.model.lines))

    def test_invalid_confirmation_makes_no_mutation(self):
        self.controller.choose('1')
        self.controller.submit('approve', 'WRONG')
        self.engine.apply.assert_not_called()
        self.assertEqual(self.controller.model.page, 'result')

    def test_home_plan_is_still_blocked_on_unqualified_firmware(self):
        self.engine.plan.side_effect = InstallerError('HOME_NOT_RELEASE_QUALIFIED', 'No approved adapter.', 3)
        self.controller.choose('3')
        self.assertEqual(self.controller.model.page, 'error')
        self.engine.apply.assert_not_called()

    def test_uninstall_requires_exact_phrase(self):
        self.controller.choose('6')
        self.controller.submit('uninstall', 'uninstall')
        self.engine.uninstall.assert_not_called()
        self.controller.choose('6')
        self.controller.submit('uninstall', 'UNINSTALL')
        self.engine.uninstall.assert_called_once_with()

    def test_diagnostics_have_separate_readable_summary_and_full_json(self):
        self.engine.diagnose.return_value = {
            'deviceProfile': {'identity': {'model': 'LG TV', 'firmware': '05.00', 'sdkVersion': '4.5'},
                              'home': {'appId': 'com.webos.app.fullhome', 'implementation': 'qml'}},
            'compatibility': {'appStatus': 'APP_ELIGIBLE', 'homeStatus': 'HOME_EXPERIMENTAL'},
            'pendingTransactions': [],
        }
        self.controller.choose('2')
        self.assertEqual(self.controller.model.page, 'result')
        self.assertIn('Device: LG TV', self.controller.model.lines)
        self.controller.dispatch_key('d')
        self.assertEqual(self.controller.model.page, 'details')

    def test_reconcile_lists_are_selectable_and_do_not_print_over_menu(self):
        self.engine.reconcile.return_value = [{'transactionId': 'a' * 64, 'state': 'RECONCILE_REQUIRED'}]
        self.engine.reconcile_transaction.return_value = {'ok': True, 'reconciled': True}
        self.controller.choose('9')
        self.assertEqual(self.controller.model.page, 'options')
        self.controller.dispatch_key('\n')
        self.engine.reconcile_transaction.assert_called_once_with('a' * 64)
        self.assertEqual(self.controller.model.page, 'result')

    def test_root_transport_still_uses_configured_endpoint(self):
        self.controller.choose('8')
        self.engine.application.launch.assert_called_once_with()

    def test_wrapper_is_injected_for_terminal_tests(self):
        with patch('installer.fullscreen.session', return_value={'ok': True, 'state': 'CLOSED'}) as target:
            result = run_fullscreen(self.engine, wrapper=lambda callback: callback(Mock()))
        self.assertEqual(result['state'], 'CLOSED')
        target.assert_called_once()


if __name__ == '__main__':
    unittest.main()
