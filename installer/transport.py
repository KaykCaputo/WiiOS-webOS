import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from installer.errors import InstallerError


@dataclass(frozen=True)
class Connection:
    host: str
    port: int
    user: str
    identity: str | None
    known_hosts: str
    kind: str = 'developer-mode'
    service_pty: bool = False

    def __post_init__(self):
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', self.host) or
                not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', self.user) or
                not 1 <= self.port <= 65535 or self.kind not in ('developer-mode', 'root-ssh')):
            raise InstallerError('INVALID_CONNECTION', 'Invalid connection settings.', 2)
        if self.kind == 'developer-mode' and self.user == 'root':
            raise InstallerError('INVALID_TRANSPORT', 'Developer Mode cannot use root.', 2)

    @property
    def endpoint(self):
        return self.user + '@' + self.host + ':' + str(self.port)


def run_process(arguments, data=None, timeout=20):
    try:
        result = subprocess.run(arguments, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise InstallerError('TRANSPORT_TIMEOUT', 'The command exceeded its deadline.', 4) from error
    except OSError as error:
        raise InstallerError('HOST_TOOL_UNAVAILABLE', 'A required host tool is unavailable.', 4) from error
    if result.returncode:
        error_text = result.stderr.decode('utf-8', errors='replace')
        reasons = [('REMOTE HOST IDENTIFICATION HAS CHANGED', 'HOST_KEY_CHANGED'),
                   ('Host key verification failed', 'HOST_KEY_UNTRUSTED'),
                   ('Permission denied', 'PERMISSION_DENIED'), ('No such file', 'NOT_FOUND')]
        code = next((code for text, code in reasons if text in error_text), 'TRANSPORT_FAILED')
        raise InstallerError(code, 'Connection or remote command failed; check credentials and host trust.', 4)
    if len(result.stdout) > 8 * 1024 * 1024:
        raise InstallerError('RESPONSE_TOO_LARGE', 'The response exceeded the size limit.', 4)
    return result.stdout.decode('utf-8', errors='replace')


def key_fingerprint(line):
    fields = line.split()
    if len(fields) != 3 or fields[0].startswith('@'):
        raise InstallerError('INVALID_HOST_KEY', 'Invalid SSH host key record.', 4)
    try:
        raw = base64.b64decode(fields[2], validate=True)
    except ValueError as error:
        raise InstallerError('INVALID_HOST_KEY', 'Invalid SSH host key encoding.', 4) from error
    return 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')


def trusted_fingerprints(connection, runner=run_process):
    name = connection.host if connection.port == 22 else '[' + connection.host + ']:' + str(connection.port)
    try:
        output = runner(['ssh-keygen', '-F', name, '-f', connection.known_hosts])
    except InstallerError as error:
        if error.code != 'TRANSPORT_FAILED':
            raise
        raise InstallerError('HOST_KEY_UNTRUSTED', 'The TV has no trusted SSH key in this trust store.', 4) from error
    keys = [key_fingerprint(line) for line in output.splitlines() if line and not line.startswith('#')]
    if not keys:
        raise InstallerError('HOST_KEY_UNTRUSTED', 'Confirm the SSH fingerprint before connecting.', 4)
    return sorted(set(keys))


def trust_host(connection, expected_fingerprint, runner=run_process):
    if not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', expected_fingerprint):
        raise InstallerError('INVALID_FINGERPRINT', 'Supply a verified SHA256 SSH fingerprint.', 2)
    name = connection.host if connection.port == 22 else '[' + connection.host + ']:' + str(connection.port)
    output = runner(['ssh-keyscan', '-T', '5', '-p', str(connection.port), connection.host])
    records = [line for line in output.splitlines() if line and not line.startswith('#')]
    matches = [line for line in records if key_fingerprint(line) == expected_fingerprint and line.split()[0] == name]
    if len(matches) != 1:
        raise InstallerError('HOST_KEY_MISMATCH', 'The observed key does not match the approved fingerprint.', 4)
    path = Path(connection.known_hosts).expanduser()
    if path.is_symlink():
        raise InstallerError('UNSAFE_TRUST_STORE', 'The trust store must not be a symlink.', 2)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    old = path.read_text() if path.exists() else ''
    if matches[0] not in old.splitlines():
        with path.open('a') as stream:
            path.chmod(0o600)
            stream.write(('\n' if old and not old.endswith('\n') else '') + matches[0] + '\n')
    return {'ok': True, 'hostFingerprint': expected_fingerprint}


def json_replies(text):
    decoder, replies, position = json.JSONDecoder(), [], 0
    while position < len(text):
        start = text.find('{', position)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text[start:])
            replies.append(value)
            position = start + end
        except ValueError:
            position = start + 1
    return replies


class SSHTransport:
    def __init__(self, connection, runner=run_process):
        self.connection, self.runner = connection, runner

    @property
    def kind(self):
        return self.connection.kind

    def fingerprint(self):
        return ','.join(trusted_fingerprints(self.connection, self.runner))

    def execute(self, command, data=None, timeout=20, tty=False):
        connection = self.connection
        self.fingerprint()
        args = ['ssh', '-tt' if tty else '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                '-o', 'UserKnownHostsFile=' + str(Path(connection.known_hosts).expanduser()),
                '-o', 'GlobalKnownHostsFile=' + str(Path(connection.known_hosts).expanduser()),
                '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=7',
                '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2', '-p', str(connection.port)]
        if connection.identity:
            args += ['-o', 'IdentitiesOnly=yes', '-i', str(Path(connection.identity).expanduser())]
        return self.runner(args + ['--', connection.user + '@' + connection.host, command], data=data, timeout=timeout)

    def read(self, path):
        return self.execute('cat -- ' + shlex.quote(path))

    def luna(self, uri, payload):
        if not re.fullmatch(r'luna://[A-Za-z0-9._-]+/[A-Za-z0-9/_-]+', uri):
            raise InstallerError('INVALID_SERVICE_URI', 'Invalid service URI.', 2)
        binary = 'luna-send-pub' if self.kind == 'developer-mode' else 'luna-send'
        output = self.execute(binary + ' -n 1 -w 5000 -f ' + shlex.quote(uri) + ' ' +
                              shlex.quote(json.dumps(payload, separators=(',', ':'))), timeout=12,
                              tty=self.connection.service_pty)
        replies = json_replies(output)
        if not replies:
            raise InstallerError('SERVICE_RESPONSE_INVALID', 'The service returned no valid JSON.', 5)
        return replies[-1]


class DeveloperModeTransport(SSHTransport):
    def __init__(self, connection, runner=run_process):
        if connection.kind != 'developer-mode':
            raise InstallerError('INVALID_TRANSPORT', 'Developer Mode transport required.', 2)
        super().__init__(connection, runner)


class RootSSHTransport(SSHTransport):
    def __init__(self, connection, runner=run_process):
        if connection.kind != 'root-ssh':
            raise InstallerError('INVALID_TRANSPORT', 'Root SSH transport required.', 2)
        super().__init__(connection, runner)
