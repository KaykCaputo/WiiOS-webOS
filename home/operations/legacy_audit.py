import hashlib
import json
import shlex
from importlib.resources import files

from installer.errors import InstallerError


def audit_legacy_recovery(transport, profile):
    metadata = json.loads(files('home.operations').joinpath('legacy-recovery.json').read_text())
    if transport.kind != 'root-ssh' or transport.execute('id -u').strip() != '0':
        raise InstallerError('ROOT_AUDIT_REQUIRED', 'A read-only legacy recovery audit requires authorized Root SSH.', 3)
    base = metadata['base']
    home = profile['home']
    installation = profile['wiiOsInstallation']
    checks = {}
    checks['existingQmlHome'] = (home.get('appId') == 'com.webos.app.fullhome' and
                                 home.get('implementation') == 'qml' and
                                 installation.get('homeAdapter') == 'qml-redirect' and
                                 installation.get('transactionId') == metadata['transactionId'])
    checks['mountOwnershipVerified'] = (home.get('ownershipStatus') == 'VERIFIED' and
                                         home.get('namespaceVerified') is True and
                                         len(home.get('ownedMounts', [])) == 4)
    checks['noForeignMounts'] = not home.get('foreignMounts')
    checks['noConflictingHooks'] = not home.get('conflictingHooks')
    checks['noUnexpectedStartupHooks'] = '99-wiios-fullhome' in home.get('recognizedHooks', [])
    mismatches = []
    for name, expected in metadata['files'].items():
        payload = transport.read(base + '/' + name)
        if hashlib.sha256(payload.encode()).hexdigest() != expected:
            mismatches.append(name)
    checks['recoveryPayloadHashesVerified'] = not mismatches
    status = transport.read(base + '/state/status').strip()
    checks['activeTransactionStatus'] = status == 'ACTIVE'
    recorded_boot = transport.read(base + '/state/boot-id').strip()
    current_boot = transport.read('/proc/sys/kernel/random/boot_id').strip()
    checks['sameBootIdentity'] = bool(recorded_boot) and recorded_boot == current_boot
    recorded_namespace = transport.read(base + '/state/namespace').strip()
    current_namespace = transport.execute('readlink /proc/self/ns/mnt').strip()
    checks['sameMountNamespace'] = bool(recorded_namespace) and recorded_namespace == current_namespace
    state = base + '/state'
    paths = [state + '/' + str(index) + '.' + suffix
             for index in range(1, 5)
             for suffix in ('intent', 'target', 'source', 'inode', 'before', 'coordinates', 'owned')]
    command = ' && '.join('test -f ' + shlex.quote(path) for path in paths)
    try:
        transport.execute(command, timeout=20)
        checks['rollbackJournalReceiptsPresent'] = True
    except InstallerError:
        checks['rollbackJournalReceiptsPresent'] = False
    return {
        'schemaVersion': 1,
        'ok': all(checks.values()),
        'mode': 'READ_ONLY',
        'changesApplied': False,
        'transactionId': metadata['transactionId'],
        'deviceHomeStatus': 'HOME_INSTALLED' if checks['existingQmlHome'] else 'UNVERIFIED',
        'recoveryState': status,
        'checks': checks,
        'mismatchedRecoveryFiles': mismatches,
        'independentRecoveryRehearsed': False,
        'recoveryQualified': False,
        'assessment': 'PRECHECK_PASSED' if all(checks.values()) else 'PRECHECK_BLOCKED',
        'message': ('Read-only checks passed; an independent rollback rehearsal is still required.'
                    if all(checks.values()) else 'The recovery precheck found a blocker; do not restore without review.'),
    }
