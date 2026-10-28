from compatibility.resolver import resolve
from compatibility.schema import validate_document


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
        'reasonCodes': reasons,
        'requiredDeviceTests': [
            {'id': name, 'status': 'NOT_RUN', 'evidence': None} for name in CHECKLIST
        ],
        'validatedAdapterVersion': None,
        'validatedWiiOsCommit': None,
        'reviewedBy': None,
        'maintainerApproved': False,
    }
