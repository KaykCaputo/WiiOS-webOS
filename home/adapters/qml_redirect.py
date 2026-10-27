from home.adapters.base import HomeAdapter
from installer.errors import InstallerError

ORIGINALS = {
    '/usr/palm/applications/com.webos.app.fullhome/qml/main.qml': '1b90a8282283caf27c140aed31c429994f6d4341cd67f443d655c00b5edba1c8',
    '/usr/palm/applications/com.webos.app.fullhome/qml/UserInterfaceLayer/UIController.qml': '50f8b5fefa20be20ab0d0cc6ba44010749e4e87d7b05ab2b030bcdf3e9b4739f'
}


class QmlRedirect(HomeAdapter):
    adapter_id = 'qml-redirect'

    def build_plan(self, profile):
        home = profile['home']
        if home['appId'] != 'com.webos.app.fullhome' or home['implementation'] != 'qml' or home['targetHashes'] != ORIGINALS:
            raise InstallerError('QML_FINGERPRINT_MISMATCH', 'The original QML hashes do not match the legacy fixture.', 3)
        return self.plan_operations(profile, [{'action': 'bind-qml-trial', 'target': path} for path in sorted(ORIGINALS)])
