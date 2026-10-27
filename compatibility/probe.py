from datetime import datetime, timezone
import hashlib
import json
import re

from compatibility.mountinfo import parse_mountinfo, related_mounts
from compatibility.schema import validate_document
from installer.errors import InstallerError

HOME_IDS = ('com.webos.app.fullhome', 'com.webos.app.home')
TARGETS = ('qml/main.qml', 'qml/UserInterfaceLayer/UIController.qml')


def probe(transport):
    profile = {'schemaVersion': 1, 'capturedAt': datetime.now(timezone.utc).isoformat(),
               'identity': dict.fromkeys(('model', 'board', 'firmware', 'sdkVersion', 'architecture')),
               'transport': {'kind': transport.kind, 'connected': False, 'root': None,
                             'hostFingerprint': None, 'endpoint': transport.connection.endpoint},
               'home': {'appId': None, 'implementation': 'unknown', 'effectiveDirectory': None,
                        'stockManifestSha256': None, 'effectiveManifestSha256': None, 'targetHashes': {},
                        'mountNamespace': None, 'namespaceVerified': False, 'foreignMounts': [],
                        'conflictingHooks': [], 'candidates': []},
               'capabilities': {key: 'unknown' for key in ('ipkInstall', 'lunaApplicationListing',
                    'lunaApplicationLaunch', 'ssapPairing', 'samManifestReload', 'nativeHomeLifecycle', 'webAppManager')},
               'wiiOsInstallation': {'appInstalled': None, 'homeAdapter': None, 'transactionId': None},
               'recovery': {'independentTestPassed': False}, 'observations': [], 'errors': [], 'redacted': True}

    def observe(name, source, call):
        try:
            value = call()
            profile['observations'].append({'field': name, 'source': source, 'status': 'observed'})
            return value
        except (InstallerError, ValueError, KeyError, TypeError) as error:
            profile['errors'].append({'field': name, 'reasonCode': error.code if isinstance(error, InstallerError) else 'INVALID_RESPONSE'})
            return None

    fingerprint = transport.fingerprint()
    uid = transport.execute('id -u').strip()
    if not uid.isdigit():
        raise InstallerError('IDENTITY_UNKNOWN', 'The SSH user identity could not be verified.', 4)
    if transport.kind == 'developer-mode' and uid == '0':
        raise InstallerError('TRANSPORT_PRIVILEGE_MISMATCH', 'Developer Mode unexpectedly has root privileges.', 4)
    profile['transport'].update(connected=True, root=uid == '0', hostFingerprint=fingerprint)
    profile['identity']['architecture'] = observe('identity.architecture', 'ssh_readonly', lambda: transport.execute('uname -m').strip())
    response = observe('identity', 'official_api', lambda: transport.luna(
        'luna://com.webos.service.tv.systemproperty/getSystemInfo',
        {'keys': ['modelName', 'firmwareVersion', 'sdkVersion', 'boardType']}))
    if isinstance(response, dict) and response.get('returnValue') is True:
        for key, field in [('modelName', 'model'), ('boardType', 'board'), ('firmwareVersion', 'firmware'), ('sdkVersion', 'sdkVersion')]:
            value = response.get(key)
            if isinstance(value, str):
                profile['identity'][field] = value[:128]
    binary = 'luna-send-pub' if transport.kind == 'developer-mode' else 'luna-send'
    present = observe('capabilities.ipkInstall', 'ssh_readonly', lambda: transport.execute('command -v ' + binary).strip())
    if present:
        profile['capabilities']['ipkInstall'] = 'available'
    listing = observe('capabilities.lunaApplicationListing', 'runtime_query', lambda: transport.luna(
        'luna://com.webos.applicationManager/listLaunchPoints', {}))
    if isinstance(listing, dict):
        profile['capabilities']['lunaApplicationListing'] = 'available' if listing.get('returnValue') is True else 'unavailable'
    for directory in ('/media/developer/apps/usr/palm/applications/', '/media/cryptofs/apps/usr/palm/applications/'):
        data = observe('wiiOsInstallation', 'manifest', lambda: json.loads(transport.read(directory + 'com.wiios.launcher/appinfo.json')))
        if isinstance(data, dict) and data.get('id') == 'com.wiios.launcher':
            profile['wiiOsInstallation']['appInstalled'] = True
            break
    if transport.kind != 'root-ssh':
        return validate_document(profile, 'device-profile')
    namespace = observe('home.mountNamespace', 'ssh_readonly', lambda: transport.execute('readlink /proc/self/ns/mnt').strip())
    profile['home']['mountNamespace'] = namespace
    mounts = observe('home.mounts', 'mountinfo', lambda: parse_mountinfo(transport.read('/proc/self/mountinfo')))
    namespaces = observe('home.processNamespaces', 'mountinfo', lambda: transport.execute(
        "for name in sam WebAppMgr; do for pid in $(pidof \"$name\"); do printf '%s ' \"$name\"; readlink /proc/\"$pid\"/ns/mnt; done; done"))
    rows = namespaces.splitlines() if namespaces else []
    profile['home']['namespaceVerified'] = bool(namespace and mounts and
        any(row.startswith('sam ') for row in rows) and any(row.startswith('WebAppMgr ') for row in rows) and
        all(row.split(' ', 1)[-1] == namespace for row in rows))
    running = observe('home.running', 'runtime_query', lambda: transport.luna('luna://com.webos.applicationManager/running', {}))
    active = []
    if isinstance(running, dict) and running.get('returnValue') is True:
        active = [entry.get('id') for entry in running.get('running', []) if isinstance(entry, dict) and entry.get('id') in HOME_IDS]
    candidates = []
    for app_id in HOME_IDS:
        directory = '/usr/palm/applications/' + app_id
        text = observe('home.manifest.' + app_id, 'manifest', lambda: transport.read(directory + '/appinfo.json'))
        if text is None:
            continue
        manifest = observe('home.manifestJson.' + app_id, 'manifest', lambda: json.loads(text))
        if not isinstance(manifest, dict) or manifest.get('id') != app_id:
            continue
        manifest_digest = hashlib.sha256(text.encode()).hexdigest()
        implementation = manifest.get('type', 'unknown')
        hashes = {}
        if app_id == 'com.webos.app.fullhome':
            for target in TARGETS:
                content = observe('home.target.' + target, 'ssh_readonly', lambda: transport.execute('sha256sum ' + directory + '/' + target))
                if content and re.fullmatch(r'[a-f0-9]{64}', content.split()[0]):
                    hashes[directory + '/' + target] = content.split()[0]
            implementation = 'qml' if len(hashes) == 2 else 'unknown'
        related = [] if mounts is None else related_mounts(mounts, directory)
        ancestors = [] if mounts is None else [m for m in mounts if directory.startswith(m.target.rstrip('/') + '/') and m.root != '/']
        candidates.append({'appId': app_id, 'implementation': implementation if implementation in ('qml', 'native', 'web', 'flutter') else 'unknown',
                           'effectiveDirectory': directory, 'effectiveManifestSha256': manifest_digest,
                           'stockManifestSha256': manifest_digest if mounts is not None and not related and not ancestors else None,
                           'targetHashes': hashes, 'foreignMounts': [m.to_dict() for m in related + ancestors]})
    profile['home']['candidates'] = candidates
    selected = [c for c in candidates if c['appId'] in active]
    if len(selected) == 1:
        profile['home'].update(selected[0])
        home_namespaces = observe('home.activeNamespace', 'mountinfo', lambda: transport.execute(
            'for pid in $(pidof ' + selected[0]['appId'] + '); do readlink /proc/"$pid"/ns/mnt; done'))
        profile['home']['namespaceVerified'] = bool(profile['home']['namespaceVerified'] and home_namespaces and
            all(value == namespace for value in home_namespaces.splitlines()))
    else:
        profile['home']['namespaceVerified'] = False
    hooks = observe('home.conflictingHooks', 'ssh_readonly', lambda: transport.execute(
        "if [ -d /var/lib/webosbrew/init.d ]; then for file in /var/lib/webosbrew/init.d/*; do [ ! -f \"$file\" ] || basename \"$file\"; done; fi"))
    if hooks:
        profile['home']['conflictingHooks'] = hooks.splitlines()
    return validate_document(profile, 'device-profile')
