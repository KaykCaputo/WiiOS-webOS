from copy import deepcopy
import unittest

from compatibility.detection_reference import create_detection_reference, compare_detection_reference, EXPECTED_TARGETS
from compatibility.resolver import resolve
from compatibility.tests.fixtures import profile


def diagnostic():
    device = profile()
    device['home'].update(ownershipStatus='VERIFIED', namespaceVerified=True,
                          recognizedHooks=['99-wiios-fullhome', '98-wiios-metrics'],
                          ownedMounts=[{'target': target} for target in EXPECTED_TARGETS],
                          targetHashes={target: 'a' * 64 for target in EXPECTED_TARGETS[:2]})
    device['wiiOsInstallation'].update(appInstalled=True, homeAdapter='qml-redirect', transactionId='synthetic-test')
    return {'deviceProfile': device, 'compatibility': resolve(device), 'pendingTransactions': []}


class DetectionReferenceTests(unittest.TestCase):
    def test_existing_home_creates_detection_only_reference(self):
        reference = create_detection_reference(diagnostic())
        self.assertEqual(reference['qualification'], 'DETECTION_ONLY')
        self.assertFalse(reference['takeoverApproved'])
        self.assertFalse(reference['independentRecoveryRehearsed'])
        self.assertTrue(compare_detection_reference(reference, diagnostic())['ok'])
        self.assertNotIn('transport', reference)

    def test_firmware_change_is_detected(self):
        reference = create_detection_reference(diagnostic())
        new = diagnostic()
        new['deviceProfile']['identity']['firmware'] = 'DIFFERENT'
        new['compatibility'] = resolve(new['deviceProfile'])
        result = compare_detection_reference(reference, new)
        self.assertEqual(result['status'], 'MISMATCH')
        self.assertEqual(result['changedFields'], ['identity'])

    def test_foreign_mount_is_rejected(self):
        altered = diagnostic()
        altered['deviceProfile']['home']['foreignMounts'] = [{'target': 'mock'}]
        altered['compatibility'] = resolve(altered['deviceProfile'])
        with self.assertRaises(ValueError):
            create_detection_reference(altered)

    def test_unverified_namespace_is_rejected(self):
        altered = diagnostic()
        altered['deviceProfile']['home']['namespaceVerified'] = False
        altered['compatibility'] = resolve(altered['deviceProfile'])
        self.assertEqual(compare_detection_reference(create_detection_reference(diagnostic()), altered)['status'], 'NOT_MATCHED')

    def test_reference_tampering_is_rejected(self):
        reference = create_detection_reference(diagnostic())
        reference['takeoverApproved'] = True
        with self.assertRaises(ValueError):
            compare_detection_reference(reference, diagnostic())

    def test_missing_mount_fails_closed(self):
        altered = diagnostic()
        altered['deviceProfile']['home']['ownedMounts'].pop()
        altered['compatibility'] = resolve(altered['deviceProfile'])
        with self.assertRaises(ValueError):
            create_detection_reference(altered)

    def test_status_edited_without_new_profile_digest_is_rejected(self):
        altered = diagnostic()
        altered['compatibility']['deviceProfileDigest'] = '0' * 64
        with self.assertRaises(ValueError):
            create_detection_reference(altered)

    def test_pending_transaction_is_rejected(self):
        altered = diagnostic()
        altered['pendingTransactions'] = [{'transactionId': 'synthetic-pending'}]
        with self.assertRaises(ValueError):
            create_detection_reference(altered)
