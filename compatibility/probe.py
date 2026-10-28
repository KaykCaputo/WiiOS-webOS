from datetime import datetime, timezone
import hashlib
import json
import re

from compatibility.discovery import HOME_IDS, choose_home, classify_home, sam_registration
from compatibility.legacy import inspect_legacy, recognized_auxiliary_hooks
from compatibility.mountinfo import parse_mountinfo, related_mounts
from compatibility.schema import validate_document
from installer.errors import InstallerError

TARGETS = ('qml/main.qml', 'qml/UserInterfaceLayer/UIController.qml')


def probe(transport):
    profile = {'schemaVersion': 1, 'capturedAt': datetime.now(timezone.utc).isoformat(),
               'identity': dict.fromkeys(('model', 'board', 'firmware', 'sdkVersion', 'architecture')),
               'transport': {'kind': transport.kind, 'connected': False, 'root': None,
                             'hostFingerprint': None, 'endpoint': transport.connection.endpoint},
               'home': {'appId': None, 'implementation': 'unknown', 'effectiveDirectory': None,
                        'stockManifestSha256': None, 'effectiveManifestSha256': None, 'targetHashes': {},
                        'nativeEntrypoint': None, 'nativeEntrypointSha256': None,
                        'mountNamespace': None, 'namespaceVerified': False, 'selectionEvidence': None, 'foreignMounts': [],
                        'conflictingHooks': [], 'ownedMounts': [], 'recognizedHooks': [], 'ownershipStatus': 'ABSENT', 'ownershipReasonCode': None, 'ownershipFailureCheck': None, 'candidates': []},
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
        status = observe('capabilities.installService', 'runtime_query', lambda: transport.luna(
            'luna://com.webos.appInstallService/status', {'subscribe': False}))
        profile['observations'].append({'field': 'capabilities.ipkInstall',
            'source': 'read-only-install-service-status',
            'status': 'service-reachable' if isinstance(status, dict) and status.get('returnValue') is True else 'permission-unverified'})
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
        entries = running.get('running', [])
        if isinstance(entries, list):
            active = [entry.get('id') for entry in entries if isinstance(entry, dict) and entry.get('id') in HOME_IDS]
    hook_names = observe('home.startupHooks', 'ssh_readonly', lambda: transport.execute(
        "if [ -d /var/lib/webosbrew/init.d ]; then for file in /var/lib/webosbrew/init.d/*; do [ ! -f \"$file\" ] || basename \"$file\"; done; fi"))
    hook_list = hook_names.splitlines() if hook_names else []
    ownership = inspect_legacy(transport, mounts, namespace, hook_list)
    owned_ids = set(ownership['ownedMounts'])
    profile['home']['ownedMounts'] = [m.to_dict() for m in mounts or [] if m.mountId in owned_ids]
    profile['home']['recognizedHooks'] = ownership['recognizedHooks'] + recognized_auxiliary_hooks(transport, hook_list)
    profile['home']['ownershipStatus'] = ownership['status']
    profile['home']['ownershipReasonCode'] = ownership['reasonCode']
    profile['home']['ownershipFailureCheck'] = ownership['failureCheck']
    if ownership['status'] == 'VERIFIED':
        profile['wiiOsInstallation']['homeAdapter'] = 'qml-redirect'
        profile['wiiOsInstallation']['transactionId'] = ownership['transactionId']
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
            implementation = 'qml' if len(hashes) == 2 else implementation
        implementation, implementation_evidence = classify_home(app_id, manifest, hashes)
        sam_response = observe('home.sam.' + app_id, 'runtime_query', lambda: transport.luna(
            'luna://com.webos.applicationManager/getAppInfo', {'id': app_id}))
        registration = sam_registration(app_id, sam_response)
        type_mismatch = bool(registration['registered'] and registration['type'] and
            (registration['type'] != implementation if implementation != 'qml' else registration['type'] != 'native'))
        related = [] if mounts is None else related_mounts(mounts, directory)
        ancestors = [] if mounts is None else [m for m in mounts if directory.startswith(m.target.rstrip('/') + '/') and m.root != '/']
        native_executable = None
        native_digest = None
        main = manifest.get('main')
        if implementation == 'native' and isinstance(main, str):
            if main.startswith('./'):
                main = main[2:]
            if (main and not main.startswith('/') and '..' not in main.split('/') and
                    re.fullmatch(r'[A-Za-z0-9_./-]+', main)):
                native_executable = directory + '/' + main
            elif (main.startswith(directory + '/') and '..' not in main.split('/') and
                  re.fullmatch(r'[A-Za-z0-9_./-]+', main)):
                native_executable = main
            if native_executable:
                check = observe('home.nativeEntrypoint.' + app_id, 'ssh_readonly',
                    lambda: transport.execute('sha256sum ' + native_executable))
                if check and re.fullmatch(r'[a-f0-9]{64}', check.split()[0]):
                    native_digest = check.split()[0]
        candidates.append({'appId': app_id, 'implementation': implementation if implementation in ('qml', 'native', 'web', 'flutter') else 'unknown',
                           'effectiveDirectory': directory, 'implementationEvidence': implementation_evidence,
                           'sam': registration, 'samTypeMismatch': type_mismatch, 'effectiveManifestSha256': manifest_digest,
                           'stockManifestSha256': manifest_digest if mounts is not None and not related and not ancestors else None,
                           'targetHashes': hashes, 'nativeEntrypoint': native_executable,
                           'nativeEntrypointSha256': native_digest, 'foreignMounts': [m.to_dict() for m in related + ancestors if m.mountId not in owned_ids]})
    profile['home']['candidates'] = candidates
    chosen, selection = choose_home(candidates, active)
    if chosen is None and ownership['status'] == 'VERIFIED':
        owned_home = next((candidate for candidate in candidates
            if candidate['appId'] == 'com.webos.app.fullhome'
            and candidate['implementation'] == 'qml'
            and candidate['sam']['registered']
            and candidate['sam']['homeRole']
            and not candidate['samTypeMismatch']
            and not candidate['foreignMounts']), None)
        if owned_home is not None:
            chosen, selection = owned_home, 'verified-wiios-qml-ownership'
    profile['home']['selectionEvidence'] = selection
    if chosen is not None:
        profile['home'].update({key: chosen[key] for key in (
            'appId', 'implementation', 'effectiveDirectory', 'effectiveManifestSha256',
            'stockManifestSha256', 'targetHashes', 'nativeEntrypoint', 'nativeEntrypointSha256', 'foreignMounts')})
    profile['home']['conflictingHooks'] = [name for name in hook_list if name not in profile['home']['recognizedHooks']]
    return validate_document(profile, 'device-profile')
