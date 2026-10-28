import unittest

from compatibility.qualification import CHECKLIST, qualification_template
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

    def test_missing_profile_rejected(self):
        with self.assertRaises(ValueError):
            qualification_template({'ok': True})
