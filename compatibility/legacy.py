import hashlib
import json
import shlex
from importlib.resources import files

from compatibility.mountinfo import parse_mountinfo, related_mounts


BASE = '/var/lib/webosbrew/wiios-fullhome-diag/diag-3e891511b377'
HOOK = '99-wiios-fullhome'
PRIVACY_HOOK = '97-wiios-privacy'
PRIVACY_HOOK_SHA256 = '909bc582012b3065abd1dccadc6c10d79ada74f3c81c490f7adc8d2e0d5b7fd1'
METRICS_HOOK = '98-wiios-metrics'
METRICS_HOOK_SHA256 = 'e498e98b61de0d8866bb83b701b4120fb36f1f27828933a46be3de10212307e8'
HOME = '/usr/palm/applications/com.webos.app.fullhome'
TARGETS = (
    HOME + '/qml/main.qml',
    HOME + '/qml/UserInterfaceLayer/UIController.qml',
    '/tmp/checkpoint/com.webos.app.fullhome',
    '/mnt/lg/cmn_data/checkpoint/com.webos.app.fullhome',
)
SOURCES = (
    BASE + '/main.qml',
    BASE + '/UIController.qml',
    BASE + '/mask-tmp',
    BASE + '/mask-persistent',
)


def _read(transport, path):
    return transport.read(path)


def _row_identity(row):
    return (row.mountId, row.parentId, row.device, row.root, row.target,
            row.optional, row.filesystem, row.source, row.superOptions)


def _matching_mounts(mounts, recorded, target):
    actual = [mount for mount in mounts if mount.target == target]
    expected = parse_mountinfo(recorded)
    return len(expected) == 1 and sum(_row_identity(row) == _row_identity(expected[0]) for row in actual) == 1


def inspect_legacy(transport, mounts, namespace, hooks):
    report = {'status': 'ABSENT', 'ownedMounts': [], 'recognizedHooks': [],
              'reasonCode': None, 'transactionId': None, 'failureCheck': None}
    if mounts is None or not namespace:
        return report
    evidence = any(related_mounts(mounts, target) for target in TARGETS)
    hook_present = HOOK in hooks
    if not evidence and not hook_present:
        return report
    report['status'] = 'UNVERIFIED'
    check = 'reviewed-metadata'
    try:
        metadata = json.loads(files('home.operations').joinpath('legacy-recovery.json').read_text())
        if metadata['base'] != BASE:
            raise ValueError('Legacy base does not match the reviewed recovery metadata')
        for filename, digest in metadata['files'].items():
            check = 'reviewed-file-integrity'
            data = _read(transport, BASE + '/' + filename)
            if hashlib.sha256(data.encode()).hexdigest() != digest:
                raise ValueError('Legacy recovery file hash mismatch')
        check = 'startup-hook-integrity'
        if hook_present:
            hook = _read(transport, '/var/lib/webosbrew/init.d/' + HOOK)
            if hashlib.sha256(hook.encode()).hexdigest() != metadata['files'][HOOK]:
                raise ValueError('Legacy startup hook hash mismatch')
        check = 'session-status'
        if _read(transport, BASE + '/state/status').strip() != 'ACTIVE':
            raise ValueError('Legacy session is not active')
        check = 'mount-namespace'
        if _read(transport, BASE + '/state/namespace').strip() != namespace:
            raise ValueError('Legacy mount namespace changed')
        check = 'boot-identity'
        if _read(transport, BASE + '/state/boot-id').strip() != _read(transport, '/proc/sys/kernel/random/boot_id').strip():
            raise ValueError('Legacy TV boot changed')
        owned = []
        for number, (source, target) in enumerate(zip(SOURCES, TARGETS), start=1):
            check = 'mount-record-' + str(number)
            state = BASE + '/state/' + str(number)
            if _read(transport, state + '.source').strip() != source:
                raise ValueError('Legacy bind source differs')
            if _read(transport, state + '.target').strip() != target:
                raise ValueError('Legacy bind target differs')
            if _read(transport, state + '.intent').strip() != 'ready':
                raise ValueError('Legacy bind intent incomplete')
            recorded = _read(transport, state + '.owned')
            if not _matching_mounts(mounts, recorded, target):
                raise ValueError('Legacy mount identity changed')
            related = related_mounts(mounts, target)
            previous = parse_mountinfo(_read(transport, state + '.before'))
            actual = [mount for mount in related if mount.target == target]
            if len(related) != len(previous) + 1 or sorted(_row_identity(m) for m in actual) != sorted(
                    [_row_identity(m) for m in previous] + [_row_identity(parse_mountinfo(recorded)[0])]):
                raise ValueError('Legacy bind has unexpected stacked or nested mounts')
            device, root = _read(transport, state + '.coordinates').split()
            mount = parse_mountinfo(recorded)[0]
            if (mount.device, mount.root) != (device, root):
                raise ValueError('Legacy source coordinates changed')
            inode = _read(transport, state + '.inode').strip()
            for path in (source, target):
                actual_inode = transport.execute("stat -c '%d:%i' -- " + shlex.quote(path)).strip()
                if actual_inode != inode:
                    raise ValueError('Legacy bind inode changed')
            owned.append(mount.mountId)
        report.update(status='VERIFIED', ownedMounts=owned,
                      recognizedHooks=[HOOK] if hook_present else [],
                      reasonCode='WIIOS_LEGACY_HOME_VERIFIED', transactionId=metadata['transactionId'])
    except (OSError, KeyError, ValueError, TypeError, UnicodeError, IndexError):
        report['reasonCode'] = 'WIIOS_LEGACY_OWNERSHIP_UNVERIFIED'
        report['failureCheck'] = check
    except Exception:
        report['reasonCode'] = 'WIIOS_LEGACY_OWNERSHIP_UNVERIFIED'
        report['failureCheck'] = check
    return report


def recognized_auxiliary_hooks(transport, hooks):
    recognized = []
    for name, digest in ((PRIVACY_HOOK, PRIVACY_HOOK_SHA256),
                         (METRICS_HOOK, METRICS_HOOK_SHA256)):
        if name not in hooks:
            continue
        try:
            value = transport.read('/var/lib/webosbrew/init.d/' + name)
            if hashlib.sha256(value.encode()).hexdigest() == digest:
                recognized.append(name)
        except (OSError, ValueError, TypeError, UnicodeError):
            continue
    return recognized
