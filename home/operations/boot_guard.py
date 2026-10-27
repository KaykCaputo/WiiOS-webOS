from compatibility.signatures import profile_digest


def boot_allowed(profile, plan, payload_digest, disabled, failure_count, recovery_ready):
    if disabled or failure_count >= 2 or not recovery_ready:
        return False
    if payload_digest != plan['artifactDigest'] or profile_digest(profile) != plan['deviceProfileDigest']:
        return False
    home = profile['home']
    return (profile['transport']['root'] is True and home['namespaceVerified'] is True and
            not home['foreignMounts'] and not home['conflictingHooks'])
