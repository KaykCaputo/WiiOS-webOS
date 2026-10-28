from contextlib import redirect_stderr, redirect_stdout
import io
import subprocess
import unittest
from unittest.mock import patch

from scripts import install_metrics


class InstallMetricsArgumentsTests(unittest.TestCase):
    def test_host_is_required_for_install_and_remove(self):
        for extra in ([], ['--remove']):
            with self.subTest(extra=extra), \
                    patch('sys.argv', ['install_metrics.py', *extra]), \
                    patch.object(install_metrics.subprocess, 'run') as run, \
                    redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as raised:
                    install_metrics.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn('--host', error.getvalue())
                run.assert_not_called()

    def test_invalid_host_is_rejected_before_ssh(self):
        for host in ('', '-oProxyCommand=bad', 'tv;echo bad', 'tv name'):
            for extra in ([], ['--remove']):
                with self.subTest(host=host, extra=extra), \
                        patch('sys.argv', ['install_metrics.py', '--host', host, *extra]), \
                        patch.object(install_metrics.subprocess, 'run') as run, \
                        redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        install_metrics.main()
                    self.assertEqual(raised.exception.code, 2)
                    run.assert_not_called()

    def test_help_documents_required_host_without_ssh(self):
        with patch('sys.argv', ['install_metrics.py', '--help']), \
                patch.object(install_metrics.subprocess, 'run') as run, \
                redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as raised:
                install_metrics.main()
            self.assertEqual(raised.exception.code, 0)
            self.assertIn('--host HOST', output.getvalue())
            self.assertNotIn('[--host HOST]', output.getvalue())
            run.assert_not_called()

    def test_explicit_host_is_used_for_install(self):
        for host in ('tv.local', '192.0.2.10'):
            with self.subTest(host=host), \
                    patch('sys.argv', ['install_metrics.py', '--host', host]), \
                    patch.object(install_metrics.subprocess, 'run',
                                 side_effect=RuntimeError('stop before SSH')) as run, \
                    redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'stop before SSH'):
                    install_metrics.main()
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][-2], 'root@' + host)

    def test_explicit_host_is_used_for_remove(self):
        with patch('sys.argv', ['install_metrics.py', '--host', 'tv.local', '--remove']), \
                patch.object(install_metrics.subprocess, 'run', return_value=
                             subprocess.CompletedProcess([], 0, b'', b'')) as run, \
                redirect_stdout(io.StringIO()):
            install_metrics.main()
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][-2], 'root@tv.local')
            self.assertIn('control.sh stop', run.call_args.args[0][-1])
