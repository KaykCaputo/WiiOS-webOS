from home.adapters.base import HomeAdapter
from installer.errors import InstallerError


class NativeHomeStandin(HomeAdapter):
    adapter_id = 'native-home-standin'

    def build_plan(self, profile):
        if (profile['home']['implementation'] != 'native' or not profile['identity']['architecture'] or
                profile['capabilities']['nativeHomeLifecycle'] != 'available' or
                profile['capabilities']['webAppManager'] != 'available'):
            raise InstallerError('NATIVE_CONTRACT_UNVERIFIED', 'Native ABI, lifecycle, and WebAppMgr must be verified.', 3)
        home = profile['home']
        if home['appId'] != 'com.webos.app.home' or home['effectiveDirectory'] != '/usr/palm/applications/com.webos.app.home':
            raise InstallerError('NATIVE_HOME_ID_UNVERIFIED', 'The native Home identity and directory must be exact.', 3)
        entrypoint = home.get('nativeEntrypoint')
        entry_digest = home.get('nativeEntrypointSha256')
        if (not isinstance(entrypoint, str) or not entrypoint.startswith(home['effectiveDirectory'] + '/') or
                '..' in entrypoint.split('/') or not isinstance(entry_digest, str) or len(entry_digest) != 64 or
                any(character not in '0123456789abcdef' for character in entry_digest)):
            raise InstallerError('NATIVE_EXECUTABLE_UNQUALIFIED', 'The native Home entrypoint and SHA-256 must be qualified.', 3)
        return self.plan_operations(profile, [
            {'action': 'verify-native-entrypoint', 'target': entrypoint},
            {'action': 'stage-home-standin', 'target': home['effectiveDirectory']},
            {'action': 'bind-native-standin-trial', 'target': entrypoint},
            {'action': 'release-old-home', 'target': home['appId']},
            {'action': 'launch-home', 'target': home['appId']},
            {'action': 'verify-native-home-lifecycle', 'target': home['appId']}
        ])
