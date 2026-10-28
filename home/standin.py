import hashlib
from importlib import resources
import json
import re
import shlex

from installer.errors import InstallerError


CONTRACTS = {
    'register-app-v2': 'registerApp',
    'register-native-app-v1': 'registerNativeApp'
}


def render_standin(home_app_id, launch_payload, contract, payload_file):
    if (home_app_id != 'com.webos.app.home' or contract not in CONTRACTS or
            not isinstance(payload_file, str) or not re.fullmatch(r'/var/lib/wiios/home-transactions/[a-f0-9]{64}/bundle/wam-launch.json', payload_file)):
        raise InstallerError('NATIVE_HOME_CONTRACT_INVALID', 'The native Home lifecycle is not qualified.', 3)
    if not isinstance(launch_payload, dict) or len(json.dumps(launch_payload)) > 8192 or (
            launch_payload.get('id') != home_app_id and launch_payload.get('appId') != home_app_id):
        raise InstallerError('WEBAPP_LAUNCH_PAYLOAD_INVALID', 'The web application launch payload must match the Home identity.', 3)
    encoded = json.dumps(launch_payload, sort_keys=True, separators=(',', ':')).encode()
    lifecycle = resources.files('home').joinpath('native_lifecycle.js').read_text()
    body = ('#!/bin/sh\nset -eu\nPATH=/usr/bin:/usr/sbin:/bin:/sbin\nexec node -e ' +
            shlex.quote(lifecycle) + ' ' + ' '.join(shlex.quote(value) for value in
            (home_app_id, payload_file, contract)) + '\n')
    return {'script': body.encode(), 'launchPayload': encoded,
            'sha256': hashlib.sha256(body.encode()).hexdigest(),
            'launchSha256': hashlib.sha256(encoded).hexdigest()}
