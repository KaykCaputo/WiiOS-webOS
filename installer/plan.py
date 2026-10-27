from compatibility.schema import validate_document
from compatibility.signatures import digest, profile_digest
from installer.errors import InstallerError
import re


def seal_plan(plan):
    content = {key: value for key, value in plan.items() if key not in ('approvalDigest', 'transactionId')}
    plan = dict(content, transactionId=digest(content))
    plan['approvalDigest'] = digest(plan)
    return validate_document(plan, 'change-plan')


def check_plan(plan, approval_digest, profile):
    validate_document(plan, 'change-plan')
    if seal_plan(plan) != plan or plan['approvalDigest'] != approval_digest:
        raise InstallerError('APPROVAL_DIGEST_MISMATCH', 'The plan approval does not match.', 8)
    if profile_digest(profile) != plan['deviceProfileDigest']:
        raise InstallerError('DEVICE_STATE_CHANGED', 'Device identity or safety conditions changed. Generate a new plan.', 8)


def fresh_trial(plan, trial_nonce):
    if plan['mode'] != 'home-replacement' or not re.fullmatch(r'[a-f0-9]{32}', trial_nonce):
        raise InstallerError('INVALID_TRIAL', 'A fresh Home trial requires a new 128-bit nonce.', 2)
    updated = seal_plan(dict(plan, trialNonce=trial_nonce))
    if updated['transactionId'] == plan['transactionId']:
        raise InstallerError('TRIAL_ALREADY_USED', 'Choose a new nonce for the separate trial.', 8)
    return updated


def app_plan(profile, artifact, action='install'):
    return seal_plan({'schemaVersion': 1, 'deviceProfileDigest': profile_digest(profile),
        'mode': 'app-only', 'action': action, 'adapter': None, 'artifactDigest': artifact.digest,
        'version': artifact.version, 'operations': [{'action': action + '-ipk', 'target': 'com.wiios.launcher'}],
        'reverseOperations': [], 'expectedMounts': [], 'expectedHomeManifestDigest': None,
        'trialTimeoutSeconds': 0, 'requiresRoot': False, 'requiresInteractiveApproval': False, 'profileId': None})
