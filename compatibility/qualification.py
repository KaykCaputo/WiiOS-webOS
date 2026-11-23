import re

from compatibility.resolver import ADAPTER_CAPABILITIES, ADAPTERS, resolve
from compatibility.schema import validate_document
from compatibility.signatures import digest


CHECKLIST = (
    'exact-model-and-board',
    'exact-firmware-and-sdk',
    'stock-home-manifest-and-target-hashes',
    'runtime-and-sam-contract',
    'independent-recovery-rehearsal',
    'home-key-and-foreground',
    'back-navigation-and-application-launch',
    'standby-and-cold-boot',
    'hdmi-and-live-tv',
    'watchdog-and-forced-failure',
    'restore-stock-home',
    'firmware-update-blocking',
)


def _candidate_profile(profile, decision):
    home, identity = profile['home'], profile['identity']
    adapter = ADAPTERS.get(home['implementation'])
    if (not adapter or not home.get('appId') or not home.get('effectiveDirectory') or
            profile.get('redacted') is not True or profile['transport']['kind'] != 'root-ssh' or
            profile['transport']['root'] is not True or home.get('namespaceVerified') is not True or
            home.get('ownershipStatus') != 'ABSENT' or home.get('ownedMounts') or
            home.get('stockManifestSha256') != home.get('effectiveManifestSha256') or
            decision['homeStatus'] != 'HOME_EXPERIMENTAL' or not all(identity.values())):
        return None
    fields = ('appId', 'implementation', 'effectiveDirectory', 'stockManifestSha256',
              'effectiveManifestSha256', 'targetHashes')
    fingerprint = {key: home[key] for key in fields}
    hashes = [home.get('stockManifestSha256'), *home['targetHashes'].values()]
    if adapter == 'native-home-standin':
        if not home.get('nativeEntrypoint'):
            return None
        fingerprint.update(nativeEntrypoint=home['nativeEntrypoint'],
                           nativeEntrypointSha256=home.get('nativeEntrypointSha256'))
        hashes.append(fingerprint['nativeEntrypointSha256'])
    if adapter == 'qml-redirect' and not home['targetHashes']:
        return None
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value) for value in hashes):
        return None
    rule = {
        'schemaVersion': 1,
        'profileId': adapter + '-' + digest({'identity': identity, 'home': fingerprint})[:24],
        'identity': identity,
        'home': fingerprint,
        'applicationMode': {'status': 'NEEDS_DEVICE_VALIDATION', 'testReports': []},
        'homeReplacement': {
            'adapter': adapter, 'status': 'NEEDS_DEVICE_VALIDATION', 'testReports': [],
            'validatedWiiOsCommit': None, 'validatedAdapterVersion': None, 'artifactDigest': None,
            'maintainerApproved': False, 'requiredCapabilities': list(ADAPTER_CAPABILITIES[adapter]),
        },
        'knownIssues': [], 'sources': [],
    }
    return validate_document(rule, 'compatibility-entry')


def qualification_template(report):
    if not isinstance(report, dict) or not isinstance(report.get('deviceProfile'), dict):
        raise ValueError('A diagnostic report containing deviceProfile is required.')
    profile = validate_document(report['deviceProfile'], 'device-profile')
    decision = resolve(profile)
    identity = profile['identity']
    home = profile['home']
    status = decision['homeStatus']
    reasons = list(decision['reasonCodes'])
    existing = status == 'HOME_INSTALLED' and home.get('ownershipStatus') == 'VERIFIED'
    adapter = ADAPTERS.get(home['implementation'])
    return {
        'schemaVersion': 1,
        'qualification': 'NEEDS_DEVICE_VALIDATION',
        'sourceProfileDigest': decision['deviceProfileDigest'],
        'identity': {key: identity.get(key) for key in ('model', 'board', 'firmware', 'sdkVersion', 'architecture')},
        'observedHome': {
            'appId': home.get('appId'),
            'implementation': home.get('implementation'),
            'stockManifestSha256': home.get('stockManifestSha256'),
            'effectiveManifestSha256': home.get('effectiveManifestSha256'),
            'nativeEntrypointSha256': home.get('nativeEntrypointSha256'),
            'targetHashes': home.get('targetHashes'),
        },
        'observedInstallation': 'EXISTING_HOME_VERIFIED' if existing else 'UNQUALIFIED',
        'canActivateNewTakeover': False,
        'candidateProfile': _candidate_profile(profile, decision),
        'requiredAdapterCapabilities': {
            key: profile['capabilities'].get(key, 'unknown')
            for key in ADAPTER_CAPABILITIES.get(adapter, ())
        },
        'reasonCodes': reasons,
        'requiredDeviceTests': [
            {'id': name, 'status': 'NOT_RUN', 'evidence': None} for name in CHECKLIST
        ],
        'validatedAdapterVersion': None,
        'validatedWiiOsCommit': None,
        'reviewedBy': None,
        'maintainerApproved': False,
    }
