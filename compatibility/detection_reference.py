import hashlib
import json

from compatibility.resolver import resolve
from compatibility.schema import validate_document


EXPECTED_TARGETS = (
    '/usr/palm/applications/com.webos.app.fullhome/qml/main.qml',
    '/usr/palm/applications/com.webos.app.fullhome/qml/UserInterfaceLayer/UIController.qml',
    '/tmp/checkpoint/com.webos.app.fullhome',
    '/mnt/lg/cmn_data/checkpoint/com.webos.app.fullhome',
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def create_detection_reference(report):
    if not isinstance(report, dict) or not isinstance(report.get('deviceProfile'), dict):
        raise ValueError('A complete WiiOS diagnostic report is required.')
    profile = validate_document(report['deviceProfile'], 'device-profile')
    decision = resolve(profile)
    home = profile['home']
    installation = profile['wiiOsInstallation']
    if (decision['homeStatus'] != 'HOME_INSTALLED' or
            decision['selectedHomeAdapter'] != 'qml-redirect' or
            home.get('appId') != 'com.webos.app.fullhome' or
            home.get('implementation') != 'qml' or
            home.get('ownershipStatus') != 'VERIFIED' or
            home.get('namespaceVerified') is not True or
            home.get('foreignMounts') or home.get('conflictingHooks') or
            installation.get('homeAdapter') != 'qml-redirect' or
            not installation.get('transactionId') or
            not isinstance(report.get('pendingTransactions'), list) or
            report['pendingTransactions'] or profile.get('errors') or profile.get('redacted') is not True):
        raise ValueError('The report does not prove an intact, existing QML Home installation.')
    if (report.get('compatibility', {}).get('homeStatus') != decision['homeStatus'] or
            report.get('compatibility', {}).get('deviceProfileDigest') != decision['deviceProfileDigest']):
        raise ValueError('The diagnostic compatibility decision does not match its observations.')
    mounts = home.get('ownedMounts', [])
    targets = [mount.get('target') for mount in mounts]
    hashes = home.get('targetHashes', {})
    if (sorted(targets) != sorted(EXPECTED_TARGETS) or
            len(targets) != len(set(targets)) or
            not all(isinstance(hashes.get(target), str) and len(hashes[target]) == 64
                    for target in EXPECTED_TARGETS[:2])):
        raise ValueError('The existing QML mount topology or target hashes are incomplete.')
    identity = profile['identity']
    if not all(identity.get(field) for field in ('model', 'board', 'firmware', 'sdkVersion', 'architecture')):
        raise ValueError('A complete device identity is required.')
    reference = {
        'schemaVersion': 1,
        'referenceType': 'OBSERVED_QML_DETECTION',
        'qualification': 'DETECTION_ONLY',
        'takeoverApproved': False,
        'independentRecoveryRehearsed': False,
        'sourceProfileDigest': decision['deviceProfileDigest'],
        'identity': {key: identity[key] for key in ('model', 'board', 'firmware', 'sdkVersion', 'architecture')},
        'home': {
            'appId': home['appId'],
            'implementation': home['implementation'],
            'effectiveManifestSha256': home.get('effectiveManifestSha256'),
            'stockManifestSha256': home.get('stockManifestSha256'),
            'targetHashes': {key: hashes[key] for key in EXPECTED_TARGETS[:2]},
            'mountTargets': sorted(targets),
            'recognizedHooks': sorted(home.get('recognizedHooks', [])),
            'transactionId': installation['transactionId'],
        },
        'expectedDecision': {
            'homeStatus': 'HOME_INSTALLED',
            'selectedHomeAdapter': 'qml-redirect',
            'ownershipStatus': 'VERIFIED',
            'namespaceVerified': True,
            'foreignMountCount': 0,
            'conflictingHookCount': 0,
        },
        'limitations': [
            'Observed detection only; no new Home takeover is approved.',
            'Effective QML file hashes are not stock QML hashes.',
            'Independent stock Home recovery has not been demonstrated.',
            'No other TV model or firmware is qualified by this reference.',
        ],
    }
    reference['referenceSha256'] = _digest(reference)
    return reference


def compare_detection_reference(reference, report):
    if (not isinstance(reference, dict) or reference.get('schemaVersion') != 1 or
            reference.get('referenceType') != 'OBSERVED_QML_DETECTION' or
            reference.get('qualification') != 'DETECTION_ONLY' or
            reference.get('independentRecoveryRehearsed') is not False):
        raise ValueError('An observed QML detection reference is required.')
    sealed = dict(reference)
    checksum = sealed.pop('referenceSha256', None)
    if checksum != _digest(sealed) or sealed.get('takeoverApproved') is not False:
        raise ValueError('The observed detection reference is modified or unsafe.')
    try:
        current = create_detection_reference(report)
    except (ValueError, KeyError) as error:
        return {'ok': False, 'status': 'NOT_MATCHED', 'reasonCode': 'DEVICE_DETECTION_UNVERIFIED',
                'message': str(error), 'takeoverApproved': False}
    compared = ('identity', 'home', 'expectedDecision')
    differences = [field for field in compared if current[field] != reference.get(field)]
    return {'ok': not differences, 'status': 'MATCH' if not differences else 'MISMATCH',
            'changedFields': differences, 'takeoverApproved': False,
            'independentRecoveryRehearsed': False}
