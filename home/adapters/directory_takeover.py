from home.adapters.base import HomeAdapter
from installer.errors import InstallerError


class HomeDirectoryTakeover(HomeAdapter):
    adapter_id = 'home-directory-takeover'

    def build_plan(self, profile):
        home = profile['home']
        if home['implementation'] not in ('web', 'flutter') or profile['capabilities']['samManifestReload'] != 'available':
            raise InstallerError('MANIFEST_RELOAD_UNVERIFIED', 'The Home type and manifest refresh contract must be verified.', 3)
        if not home['effectiveDirectory'] or not home['stockManifestSha256']:
            raise InstallerError('HOME_MANIFEST_UNKNOWN', 'The original Home manifest is unknown.', 3)
        target = home['effectiveDirectory']
        return self.plan_operations(profile, [{'action': action, 'target': target} for action in (
            'bind-home-directory', 'refresh-manifest', 'verify-manager-manifest', 'release-old-home', 'launch-home')])
