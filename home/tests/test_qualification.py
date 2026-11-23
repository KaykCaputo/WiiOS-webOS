import unittest

from compatibility.qualification import CHECKLIST, qualification_template
from compatibility.resolver import resolve
from compatibility.tests.fixtures import profile


class QualificationTemplateTests(unittest.TestCase):
    def test_diagnostic_export_never_approves_firmware(self):
        report = {'deviceProfile': profile()}
        result = qualification_template(report)
        self.assertEqual(result['qualification'], 'NEEDS_DEVICE_VALIDATION')
        self.assertFalse(result['canActivateNewTakeover'])
        self.assertFalse(result['maintainerApproved'])
        self.assertEqual(len(result['requiredDeviceTests']), len(CHECKLIST))
        self.assertTrue(all(test['status'] == 'NOT_RUN' for test in result['requiredDeviceTests']))
        candidate = result['candidateProfile']
        self.assertEqual(candidate['homeReplacement']['adapter'], 'qml-redirect')
        self.assertEqual(resolve(report['deviceProfile'], [candidate], 'c' * 64)['selectedMode'], 'app-only')
        self.assertNotIn('transport', candidate)

    def test_candidate_fingerprint_is_stable_and_requires_stock_home(self):
        device = profile()
        report = {'deviceProfile': device}
        first = qualification_template(report)['candidateProfile']['profileId']
        device['capturedAt'] = '2026-11-23T00:00:00Z'
        self.assertEqual(qualification_template(report)['candidateProfile']['profileId'], first)
        device['home']['effectiveManifestSha256'] = 'b' * 64
        self.assertIsNone(qualification_template(report)['candidateProfile'])

    def test_web_and_flutter_candidates_require_manifest_reload(self):
        for implementation in ('web', 'flutter'):
            device = profile()
            device['home'].update(appId='com.webos.app.home', implementation=implementation,
                effectiveDirectory='/usr/palm/applications/com.webos.app.home', targetHashes={})
            candidate = qualification_template({'deviceProfile': device})['candidateProfile']
            self.assertEqual(candidate['homeReplacement']['adapter'], 'home-directory-takeover')
            self.assertEqual(candidate['homeReplacement']['requiredCapabilities'], ['samManifestReload'])

    def test_missing_profile_rejected(self):
        with self.assertRaises(ValueError):
            qualification_template({'ok': True})
