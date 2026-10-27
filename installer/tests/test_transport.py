import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from installer.errors import InstallerError
from installer.transport import Connection, DeveloperModeTransport, RootSSHTransport, json_replies, key_fingerprint, trust_host, trusted_fingerprints


class TransportTests(unittest.TestCase):
    def connection(self, **changes):
        arguments = {'host': '192.0.2.1', 'port': 9922, 'user': 'prisoner', 'identity': '/example/dev-key',
                     'known_hosts': '/example/known_hosts', 'kind': 'developer-mode'}
        arguments.update(changes)
        return Connection(**arguments)

    def test_ht36_connection_requires_host_key_and_never_disables_verification(self):
        key = '[192.0.2.1]:9922 ssh-ed25519 ' + base64.b64encode(b'synthetic-key').decode()
        runner = Mock(side_effect=[key, '1000'])
        transport = DeveloperModeTransport(self.connection(), runner)
        self.assertEqual(transport.execute('id -u'), '1000')
        command = runner.call_args[0][0]
        self.assertIn('StrictHostKeyChecking=yes', command)
        self.assertIn('UpdateHostKeys=no', command)
        self.assertNotIn('StrictHostKeyChecking=no', command)
        self.assertEqual(command[-1], 'id -u')

    def test_unknown_key_refused_before_remote_command(self):
        runner = Mock(return_value='')
        with self.assertRaises(InstallerError):
            DeveloperModeTransport(self.connection(), runner).execute('id -u')
        runner.assert_called_once()

    def test_explicit_fingerprint_persists_only_matching_key(self):
        key = '[192.0.2.1]:9922 ssh-ed25519 ' + base64.b64encode(b'synthetic-key').decode()
        with tempfile.TemporaryDirectory() as directory:
            connection = self.connection(known_hosts=str(Path(directory) / 'known_hosts'))
            trust_host(connection, key_fingerprint(key), Mock(return_value=key))
            self.assertEqual(Path(connection.known_hosts).read_text(), key + '\n')
            with self.assertRaises(InstallerError):
                trust_host(connection, 'SHA256:' + 'a' * 43, Mock(return_value=key))

    def test_missing_trust_store_key_is_reported_as_untrusted(self):
        runner = Mock(side_effect=InstallerError('TRANSPORT_FAILED', 'No matching keys.', 4))
        with self.assertRaises(InstallerError) as raised:
            trusted_fingerprints(self.connection(), runner)
        self.assertEqual(raised.exception.code, 'HOST_KEY_UNTRUSTED')

    def test_transport_privileges_are_distinct(self):
        with self.assertRaises(InstallerError):
            self.connection(user='root')
        with self.assertRaises(InstallerError):
            RootSSHTransport(self.connection())

    def test_host_argument_injection_rejected(self):
        for host in ('-oProxyCommand=command', 'host;command', 'host\ncommand', 'user@host'):
            with self.assertRaises(InstallerError):
                self.connection(host=host)

    def test_service_stream_preserves_structured_replies(self):
        self.assertEqual(json_replies('noise\n{"returnValue":true}\n{"state":"installed"}'),
                         [{'returnValue': True}, {'state': 'installed'}])
