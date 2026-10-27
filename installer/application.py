import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import tarfile
import time

from installer.errors import InstallerError

APP_ID = 'com.wiios.launcher'
APP_PATHS = ['/media/developer/apps/usr/palm/applications/' + APP_ID,
             '/media/cryptofs/apps/usr/palm/applications/' + APP_ID]


class Artifact:
    def __init__(self, path, expected_digest=None):
        self.path = Path(path).resolve()
        if not self.path.is_file() or self.path.stat().st_size > 64 * 1024 * 1024:
            raise InstallerError('INVALID_ARTIFACT', 'Select a WiiOS IPK smaller than 64 MiB.', 2)
        raw = self.path.read_bytes()
        self.digest = hashlib.sha256(raw).hexdigest()
        if expected_digest and self.digest != expected_digest:
            raise InstallerError('ARTIFACT_DIGEST_MISMATCH', 'The IPK checksum does not match.', 8)
        try:
            if not raw.startswith(b'!<arch>\n'):
                raise ValueError('Invalid IPK')
            members, position = {}, 8
            while position < len(raw):
                header = raw[position:position + 60]
                name, size = header[:16].decode().strip().rstrip('/'), int(header[48:58])
                if header[-2:] != b'`\n' or size < 0 or position + 60 + size > len(raw) or name in members:
                    raise ValueError('Invalid archive')
                members[name] = raw[position + 60:position + 60 + size]
                position += 60 + size + size % 2
            if set(members) != {'debian-binary', 'control.tar.gz', 'data.tar.gz'} or members['debian-binary'] != b'2.0\n':
                raise ValueError('Unexpected package members')
            with tarfile.open(fileobj=io.BytesIO(members['control.tar.gz']), mode='r:gz') as archive:
                control = None
                for member in archive:
                    if member.name.removeprefix('./') != 'control' or not member.isfile() or member.size > 16384 or control is not None:
                        raise ValueError('Package hooks are not allowed')
                    control = archive.extractfile(member).read().decode()
                if control is None or '\nPackage: ' + APP_ID + '\n' not in '\n' + control:
                    raise ValueError('Unexpected package identity')
            with tarfile.open(fileobj=io.BytesIO(members['data.tar.gz']), mode='r:gz') as archive:
                prefix = 'usr/palm/applications/' + APP_ID + '/'
                total = 0
                info = None
                for member in archive:
                    name = member.name.removeprefix('./')
                    total += member.size
                    if total > 128 * 1024 * 1024 or '..' in name.split('/') or name.startswith('/') or member.issym() or member.islnk():
                        raise ValueError('Unsafe archive member')
                    if member.isfile() and not (name.startswith(prefix) or name == 'usr/palm/packages/' + APP_ID + '/packageinfo.json'):
                        raise ValueError('Unexpected package payload')
                    if name == prefix + 'appinfo.json':
                        if info is not None or member.size > 16384:
                            raise ValueError('Invalid app metadata')
                        info = json.load(archive.extractfile(member))
                if not info or info.get('id') != APP_ID or info.get('type') != 'web' or not re.fullmatch(r'\d+\.\d+\.\d+', info.get('version', '')):
                    raise ValueError('Invalid app metadata')
                self.version = info['version']
                if '\nVersion: ' + self.version + '\n' not in '\n' + control:
                    raise ValueError('Package version mismatch')
        except (ValueError, KeyError, UnicodeError, tarfile.TarError, OSError) as error:
            raise InstallerError('INVALID_ARTIFACT', 'The file is not a supported WiiOS application IPK.', 2) from error

    def recheck(self):
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.digest:
            raise InstallerError('ARTIFACT_CHANGED', 'The package changed after planning.', 8)


class ApplicationInstaller:
    def __init__(self, transport, sleep=time.sleep):
        self.transport, self.sleep = transport, sleep

    def version(self):
        unreadable = False
        for path in APP_PATHS:
            output = self.transport.execute('if [ -f ' + shlex.quote(path + '/appinfo.json') +
                ' ]; then cat ' + shlex.quote(path + '/appinfo.json') + '; else printf ABSENT; fi')
            if output == 'ABSENT':
                continue
            try:
                info = json.loads(output)
                if info.get('id') == APP_ID and isinstance(info.get('version'), str):
                    return info['version']
                unreadable = True
            except ValueError:
                unreadable = True
        if unreadable:
            raise InstallerError('APP_STATE_UNKNOWN', 'The installed application metadata cannot be verified.', 5)
        return None

    def install(self, artifact, transaction_id):
        artifact.recheck()
        current = self.version()
        if current == artifact.version:
            return {'ok': True, 'state': 'APP_INSTALLED', 'version': current, 'changed': False, 'uiConfirmed': False}
        if not re.fullmatch(r'[a-f0-9]{64}', transaction_id):
            raise InstallerError('INVALID_TRANSACTION', 'Invalid transaction ID.', 2)
        directory = '/media/developer/temp/wiios-' + transaction_id
        package = directory + '/application.ipk'
        self.transport.execute('umask 077; mkdir ' + shlex.quote(directory))
        self.transport.execute('umask 077; cat > ' + shlex.quote(package), data=artifact.path.read_bytes(), timeout=60)
        checksum = self.transport.execute('sha256sum ' + shlex.quote(package)).split()[0]
        if checksum != artifact.digest:
            raise InstallerError('STAGING_DIGEST_MISMATCH', 'The uploaded IPK failed verification.', 5)
        response = self.transport.luna('luna://com.webos.appInstallService/dev/install',
                                       {'id': APP_ID, 'ipkUrl': package, 'subscribe': True})
        if response.get('returnValue') is not True:
            raise InstallerError('APP_INSTALL_REJECTED', 'The TV rejected application installation.', 5)
        for attempt in range(15):
            if self.version() == artifact.version:
                self.transport.execute('rm ' + shlex.quote(package) + ' && rmdir ' + shlex.quote(directory))
                return {'ok': True, 'state': 'APP_INSTALLED', 'version': artifact.version, 'changed': True, 'uiConfirmed': False}
            self.sleep(2)
        raise InstallerError('APP_INSTALL_UNCONFIRMED', 'Installation was accepted but the installed version was not confirmed.', 5)

    def launch(self):
        response = self.transport.luna('luna://com.webos.applicationManager/launch', {'id': APP_ID})
        return {'ok': response.get('returnValue') is True, 'launchAccepted': response.get('returnValue') is True,
                'uiConfirmed': False, 'homeConfirmed': False}

    def uninstall(self):
        if self.version() is None:
            return {'ok': True, 'state': 'APP_ABSENT', 'changed': False}
        response = self.transport.luna('luna://com.webos.appInstallService/dev/remove', {'id': APP_ID, 'subscribe': True})
        if response.get('returnValue') is not True:
            raise InstallerError('APP_REMOVE_REJECTED', 'The TV rejected application removal.', 5)
        for attempt in range(15):
            if self.version() is None:
                return {'ok': True, 'state': 'APP_ABSENT', 'changed': True}
            self.sleep(2)
        raise InstallerError('APP_REMOVE_UNCONFIRMED', 'Application removal was not confirmed.', 5)
