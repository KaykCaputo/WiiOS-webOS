from home.adapters.base import HomeAdapter
from installer.errors import InstallerError


class NativeHomeStandin(HomeAdapter):
    adapter_id = 'native-home-standin'

    def build_plan(self, profile):
        if (profile['home']['implementation'] != 'native' or not profile['identity']['architecture'] or
                profile['capabilities']['nativeHomeLifecycle'] != 'available' or
                profile['capabilities']['webAppManager'] != 'available'):
            raise InstallerError('NATIVE_CONTRACT_UNVERIFIED', 'Native ABI, lifecycle, and WebAppMgr must be verified.', 3)
        raise InstallerError('NATIVE_EXECUTABLE_UNQUALIFIED', 'No native executable or interpreter profile is qualified.', 3)
