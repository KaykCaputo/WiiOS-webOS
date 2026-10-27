import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def profile_projection(profile):
    return {key: profile.get(key) for key in (
        'schemaVersion', 'identity', 'transport', 'home', 'capabilities', 'recovery'
    )}


def profile_digest(profile):
    projection = profile_projection(profile)
    projection['transport'] = {key: profile.get('transport', {}).get(key) for key in (
        'kind', 'root', 'hostFingerprint', 'endpoint'
    )}
    return digest(projection)
