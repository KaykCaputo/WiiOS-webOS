import json
from importlib.resources import files

from compatibility.schema import validate_document
from compatibility.signatures import profile_digest

ADAPTERS = {'qml': 'qml-redirect', 'native': 'native-home-standin',
            'web': 'home-directory-takeover', 'flutter': 'home-directory-takeover'}


def load_verified():
    directory = files('compatibility').joinpath('profiles', 'verified')
    return [validate_document(json.loads(p.read_text()), 'compatibility-entry')
            for p in sorted(directory.iterdir(), key=lambda path: path.name) if p.name.endswith('.json')]


def resolve(profile, entries=None, artifact_digest=None):
    validate_document(profile, 'device-profile')
    entries = load_verified() if entries is None else entries
    transport, home, capabilities = (profile[key] for key in ('transport', 'home', 'capabilities'))
    decision = {'schemaVersion': 1, 'deviceProfileDigest': profile_digest(profile),
                'preferredProductMode': 'home-replacement', 'selectedMode': 'app-only',
                'selectedHomeAdapter': None, 'homeStatus': 'UNKNOWN',
                'appStatus': 'APP_ELIGIBLE' if capabilities.get('ipkInstall') == 'available' else 'UNKNOWN',
                'reasonCodes': [], 'candidateAdapters': [], 'requiresApproval': False, 'profileId': None}
    candidate = ADAPTERS.get(home['implementation'])
    candidates = [(candidate, home.get('appId'))] if candidate else []
    for observed in home.get('candidates', []):
        adapter = ADAPTERS.get(observed.get('implementation'))
        key = (adapter, observed.get('appId'))
        if adapter and key not in candidates:
            candidates.append(key)
    decision['candidateAdapters'] = [
        {'id': adapter, 'homeAppId': app_id, 'status': 'HOME_EXPERIMENTAL'}
        for adapter, app_id in candidates
    ]
    candidate_conflicts = any(observed.get('foreignMounts') for observed in home.get('candidates', []))
    if home['foreignMounts'] or home.get('conflictingHooks') or candidate_conflicts:
        decision.update(homeStatus='CONFLICT', reasonCodes=['HOME_OWNERSHIP_CONFLICT'])
    elif transport['kind'] != 'root-ssh' or transport['root'] is not True:
        decision.update(homeStatus='BLOCKED', reasonCodes=['HOME_ROOT_REQUIRED'])
    elif home.get('appId') is None and candidates:
        decision.update(reasonCodes=['HOME_ACTIVE_ID_UNCONFIRMED'])
    elif home.get('namespaceVerified') is not True:
        decision.update(reasonCodes=['HOME_NAMESPACE_UNVERIFIED'])
    else:
        for entry in entries:
            validate_document(entry, 'compatibility-entry')
            qualification = entry['homeReplacement']
            expected = entry['home']
            if (qualification['status'] != 'HOME_CONFIRMED' or not qualification['maintainerApproved'] or
                    not qualification['testReports'] or not qualification['validatedWiiOsCommit'] or
                    qualification['validatedAdapterVersion'] != '1' or qualification['adapter'] != candidate or not artifact_digest or
                    qualification['artifactDigest'] != artifact_digest):
                continue
            if any(not value or profile['identity'].get(key) != value for key, value in entry['identity'].items()):
                continue
            if any(home.get(key) != value or value is None for key, value in expected.items()):
                continue
            if any(capabilities.get(key) != 'available' for key in qualification['requiredCapabilities']):
                continue
            if profile.get('recovery', {}).get('independentTestPassed') is not True:
                decision['reasonCodes'] = ['RECOVERY_NOT_TESTED']
                return decision
            decision.update(selectedMode='home-replacement', selectedHomeAdapter=qualification['adapter'],
                            homeStatus='HOME_ELIGIBLE', requiresApproval=True, profileId=entry['profileId'])
            return decision
        decision.update(homeStatus='HOME_EXPERIMENTAL' if candidate else 'UNKNOWN',
                        reasonCodes=['HOME_FINGERPRINT_NOT_VERIFIED'])
    return decision
