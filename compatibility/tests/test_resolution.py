from copy import deepcopy
import unittest

from compatibility.mountinfo import parse_mountinfo
from compatibility.resolver import resolve
from compatibility.schema import validate_document
from compatibility.signatures import profile_digest
from compatibility.tests.fixtures import entry, profile


class ResolutionTests(unittest.TestCase):
    def test_ht02_unknown_firmware_never_eligible(self):
        device = profile()
        self.assertEqual(resolve(device)['homeStatus'], 'HOME_EXPERIMENTAL')
        self.assertEqual(resolve(device)['selectedMode'], 'app-only')

    def test_ht03_exact_synthetic_qualification_and_recovery_required(self):
        device = profile()
        rule = entry(device)
        self.assertEqual(resolve(device, [rule], 'c' * 64)['reasonCodes'], ['RECOVERY_NOT_TESTED'])
        device['recovery']['independentTestPassed'] = True
        self.assertEqual(resolve(device, [rule], 'c' * 64)['homeStatus'], 'HOME_ELIGIBLE')

    def test_ht04_modified_qml_rejected(self):
        device = profile()
        rule = entry(device)
        device['home']['targetHashes'][next(iter(device['home']['targetHashes']))] = 'f' * 64
        self.assertNotEqual(resolve(device, [rule], 'c' * 64)['homeStatus'], 'HOME_ELIGIBLE')

    def test_ht05_foreign_mount_wins_over_qualification(self):
        device = profile()
        device['home']['foreignMounts'] = [{'mountId': 1}]
        self.assertEqual(resolve(device, [entry(device)], 'c' * 64)['homeStatus'], 'CONFLICT')

    def test_ht18_no_root_preserves_app_option(self):
        device = profile()
        device['transport'].update(kind='developer-mode', root=False)
        result = resolve(device)
        self.assertEqual(result['appStatus'], 'APP_ELIGIBLE')
        self.assertEqual(result['reasonCodes'], ['HOME_ROOT_REQUIRED'])

    def test_ht21_digest_ignores_time_and_errors_but_binds_safety(self):
        first, second = profile(), profile()
        second.update(capturedAt='2030-01-01', errors=[{'reasonCode': 'TIMEOUT'}])
        second['transport']['connected'] = False
        self.assertEqual(profile_digest(first), profile_digest(second))
        for section, key, value in [('identity', 'firmware', 'changed'), ('home', 'mountNamespace', 'mnt:[2]'),
                                     ('transport', 'hostFingerprint', 'changed'), ('transport', 'root', False)]:
            altered = deepcopy(first)
            altered[section][key] = value
            self.assertNotEqual(profile_digest(first), profile_digest(altered))

    def test_ht35_namespace_unknown_blocks_match(self):
        device = profile()
        device['home']['namespaceVerified'] = False
        self.assertEqual(resolve(device, [entry(device)], 'c' * 64)['reasonCodes'], ['HOME_NAMESPACE_UNVERIFIED'])

    def test_multiple_home_candidates_never_imply_active_home_or_takeover(self):
        device = profile()
        device['home'].update(appId=None, implementation='unknown', namespaceVerified=False)
        device['home']['candidates'] = [
            {'appId': 'com.webos.app.home', 'implementation': 'web', 'foreignMounts': []},
            {'appId': 'com.webos.app.fullhome', 'implementation': 'qml', 'foreignMounts': []}
        ]
        report = resolve(device)
        self.assertEqual(report['selectedMode'], 'app-only')
        self.assertEqual(report['reasonCodes'], ['HOME_ACTIVE_ID_UNCONFIRMED'])
        self.assertEqual({item['id'] for item in report['candidateAdapters']},
                         {'qml-redirect', 'home-directory-takeover'})

    def test_inactive_candidate_foreign_mount_blocks_takeover(self):
        device = profile()
        device['home']['candidates'] = [
            {'appId': 'com.webos.app.home', 'implementation': 'web',
             'foreignMounts': [{'mountId': 23}]}
        ]
        self.assertEqual(resolve(device)['homeStatus'], 'CONFLICT')

    def test_ht37_sdk_does_not_qualify_web_home(self):
        for version in ('9', '10', '11'):
            device = profile()
            device['identity']['sdkVersion'] = version
            device['home']['implementation'] = 'web'
            self.assertEqual(resolve(device)['homeStatus'], 'HOME_EXPERIMENTAL')

    def test_package_digest_and_maintainer_review_cannot_be_inherited(self):
        device = profile()
        device['recovery']['independentTestPassed'] = True
        rule = entry(device)
        self.assertNotEqual(resolve(device, [rule], 'd' * 64)['homeStatus'], 'HOME_ELIGIBLE')
        rule['homeReplacement']['maintainerApproved'] = False
        self.assertNotEqual(resolve(device, [rule], 'c' * 64)['homeStatus'], 'HOME_ELIGIBLE')

    def test_schema_rejects_missing_fields_and_false_as_version(self):
        device = profile()
        del device['home']['targetHashes']
        with self.assertRaises(ValueError):
            validate_document(device, 'device-profile')
        device = profile()
        device['schemaVersion'] = True
        with self.assertRaises(ValueError):
            validate_document(device, 'device-profile')

    def test_mountinfo_decodes_escapes_and_preserves_optional_fields(self):
        mounts = parse_mountinfo('71 30 179:53 /owned\\040path /target\\134name ro shared:8 - ext4 /dev/mmcblk0p53 rw\n')
        self.assertEqual(mounts[0].root, '/owned path')
        self.assertEqual(mounts[0].target, '/target\\name')
        self.assertEqual(mounts[0].optional, ('shared:8',))
        with self.assertRaises(ValueError):
            parse_mountinfo('71 30 invalid')
