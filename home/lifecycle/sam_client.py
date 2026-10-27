from dataclasses import dataclass

from installer.errors import InstallerError


@dataclass(frozen=True)
class ServiceResult:
    operation: str
    transportSucceeded: bool
    serviceAccepted: bool
    effectiveManifestConfirmed: bool = False
    foregroundConfirmed: bool = False


class SamLifecycleClient:
    def __init__(self, contract):
        if contract not in ('register-app-v2', 'register-native-app-v1'):
            raise InstallerError('SAM_CONTRACT_UNKNOWN', 'An exact SAM lifecycle contract is required.', 3)
        self.contract = contract
        self.registered = False
        self.state = 'STARTING'

    def request(self):
        method = 'registerApp' if self.contract == 'register-app-v2' else 'registerNativeApp'
        return {'uri': 'luna://com.webos.applicationManager/' + method, 'payload': {}, 'subscription': True}

    def receive(self, reply):
        if not isinstance(reply, dict) or reply.get('returnValue') is False:
            self.state = 'FAILED'
            self.registered = False
            return 'failed'
        field = 'event' if self.contract == 'register-app-v2' else 'message'
        event = reply.get(field)
        if event == 'registered' and reply.get('returnValue') is True:
            self.registered = True
        elif event in ('close', 'stop'):
            self.state = 'EXITED'
            self.registered = False
        elif event in ('pause', 'suspend'):
            self.state = 'HIDDEN'
        elif event == 'relaunch' and self.registered:
            self.state = 'STARTING'
        return event if event in ('registered', 'close', 'stop', 'pause', 'suspend', 'relaunch') else 'unknown'

    def visibility(self, foreground, heartbeat):
        if self.registered and foreground is True and heartbeat is True:
            self.state = 'VISIBLE'
        return self.state
