from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from installer.errors import InstallerError
from installer.helper import deploy_helper, HOOK_DATA
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


@unittest.skipUnless(shutil.which('node'), 'Node is required for helper deployment checks.')
class HelperDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'init.d').mkdir()
        tools = self.root / 'bin'
        tools.mkdir()
        self.environment = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}", WIIOS_TEST_TV=str(self.root))
        control = b"""case "$1" in
start) touch "$WIIOS_TEST_TV/running";;
stop) rm -f "$WIIOS_TEST_TV/running";;
status) test -f "$WIIOS_TEST_TV/running";;
esac
"""
        self.payload = {'metrics.js': b'void 0;', 'catalog.js': b'void 1;', 'control.sh': control}
        curl = tools / 'curl'
        curl.write_text("""#!/bin/sh
case "$*" in
*/v1/health) test -f "$WIIOS_TEST_TV/running" && cat "$WIIOS_TEST_TV/response";;
*) exit 22;;
esac
""")
        curl.chmod(0o700)
        self.base = self.root / 'wiios-metrics'
        self.hook = self.root / 'init.d/98-wiios-metrics'

    def remote(self, command, data=None, timeout=20):
        if command.startswith('test "$(id -u)"'):
            return ''
        if command == 'sh -s':
            data = data.replace(b'/var/lib/webosbrew', str(self.root).encode())
            data = data.replace(b'/usr/bin/node', shutil.which('node').encode())
        command = command.replace('/var/lib/webosbrew', str(self.root))
        result = subprocess.run(['sh', '-c', command], input=data, timeout=timeout, capture_output=True)
        if result.returncode:
            raise InstallerError('TEST_REMOTE_FAILURE', result.stderr.decode())
        return result.stdout.decode().replace(str(self.root), '/var/lib/webosbrew')

    @patch('installer.helper.helper_payload')
    def test_catalog_failure_keeps_healthy_helper_installed(self, read_payload):
        read_payload.return_value = self.payload
        metrics = hashlib.sha256(self.payload['metrics.js']).hexdigest()
        catalog = hashlib.sha256(self.payload['catalog.js']).hexdigest()
        (self.root / 'response').write_text(
            '{"schema":1,"metricsFingerprint":"' + metrics + '","catalogFingerprint":"' + catalog + '"}')
        with patch.dict(os.environ, self.environment):
            self.assertEqual(deploy_helper(self.remote)['state'], 'installed')
            self.assertEqual(deploy_helper(self.remote)['state'], 'installed')
        self.assertEqual(self.hook.read_bytes(), HOOK_DATA)
        self.assertEqual((self.base / 'catalog.js').read_bytes(), self.payload['catalog.js'])
        self.assertTrue((self.root / 'running').is_file())
        self.assertEqual(list(self.root.glob('wiios-helper.*')), [])

    @patch('installer.helper.helper_payload')
    def test_foreign_hook_is_preserved(self, read_payload):
        read_payload.return_value = self.payload
        target = self.root / 'foreign-hook'
        target.write_text('foreign')
        self.hook.symlink_to(target)
        with patch.dict(os.environ, self.environment), self.assertRaisesRegex(InstallerError, 'unrecognized'):
            deploy_helper(self.remote)
        self.assertTrue(self.hook.is_symlink())
        self.assertEqual(target.read_text(), 'foreign')
        self.assertFalse(self.base.exists())
