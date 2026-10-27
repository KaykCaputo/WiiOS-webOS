from copy import deepcopy

from home.adapters.qml_redirect import ORIGINALS


def profile():
    return {'schemaVersion': 1, 'capturedAt': '2026-01-01T00:00:00Z',
        'identity': {'model': 'SYNTHETIC_MODEL', 'board': 'SYNTHETIC_BOARD', 'firmware': 'TEST_ONLY',
                     'sdkVersion': '4.5', 'architecture': 'armv7l'},
        'transport': {'kind': 'root-ssh', 'connected': True, 'root': True,
                      'hostFingerprint': 'SHA256:synthetic', 'endpoint': 'test@192.0.2.1:22'},
        'home': {'appId': 'com.webos.app.fullhome', 'implementation': 'qml',
                 'effectiveDirectory': '/usr/palm/applications/com.webos.app.fullhome',
                 'stockManifestSha256': 'a' * 64, 'effectiveManifestSha256': 'a' * 64,
                 'targetHashes': dict(ORIGINALS), 'mountNamespace': 'mnt:[1]', 'namespaceVerified': True,
                 'foreignMounts': [], 'conflictingHooks': [], 'candidates': []},
        'capabilities': {'ipkInstall': 'available', 'lunaApplicationListing': 'available',
                         'lunaApplicationLaunch': 'unknown', 'ssapPairing': 'unknown',
                         'samManifestReload': 'unknown', 'nativeHomeLifecycle': 'unknown', 'webAppManager': 'unknown'},
        'wiiOsInstallation': {'appInstalled': None, 'homeAdapter': None, 'transactionId': None},
        'recovery': {'independentTestPassed': False}, 'observations': [], 'errors': [], 'redacted': True}


def entry(device):
    return {'schemaVersion': 1, 'profileId': 'SYNTHETIC_TEST_PROFILE_NOT_HARDWARE',
        'identity': deepcopy(device['identity']), 'home': {key: deepcopy(device['home'][key]) for key in
            ('appId', 'implementation', 'effectiveDirectory', 'stockManifestSha256', 'effectiveManifestSha256', 'targetHashes')},
        'applicationMode': {'status': 'NEEDS_DEVICE_VALIDATION', 'testReports': []},
        'homeReplacement': {'adapter': 'qml-redirect', 'status': 'HOME_CONFIRMED', 'testReports': ['synthetic-only'],
            'validatedWiiOsCommit': 'b' * 40, 'validatedAdapterVersion': '1', 'artifactDigest': 'c' * 64,
            'maintainerApproved': True, 'requiredCapabilities': []}, 'knownIssues': [], 'sources': []}
