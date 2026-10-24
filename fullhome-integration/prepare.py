#!/usr/bin/env python3

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import tarfile
import time

ROOT = Path(__file__).resolve().parent
EXPECTED = {
    'qml/main.qml': '1b90a8282283caf27c140aed31c429994f6d4341cd67f443d655c00b5edba1c8',
    'qml/UserInterfaceLayer/UIController.qml': '50f8b5fefa20be20ab0d0cc6ba44010749e4e87d7b05ab2b030bcdf3e9b4739f',
}
TARGET = '/usr/palm/applications/com.webos.app.fullhome/'

def replace_once(text, needle, replacement):
    if text.count(needle) != 1:
        raise ValueError('Unsupported insertion point: ' + needle)
    return text.replace(needle, replacement, 1)

def instrument(originals, token):
    if not re.fullmatch(r'[a-z0-9-]{6,48}', token):
        raise ValueError('Invalid session token')
    main, ctrl = (originals[key].decode() for key in EXPECTED)
    trace = '''
    property int wiiosTraceSequence: 0
    function wiiosTrace(eventName, fields) {
        try {
            if (wiiosTraceSequence >= 500) return;
            wiiosTraceSequence++;
            var c = typeof uiController !== "undefined" ? uiController : null;
            var p = c && c.homeLaunchParams ? c.homeLaunchParams.parameters : null;
            var record = {
                token: "@TOKEN@", event: eventName, sequence: wiiosTraceSequence,
                time: new Date().getTime(), fields: fields || {},
                tempMode: c ? c.tempMode : null,
                currentMode: c ? c.currentMode : null,
                state: c ? c.stateAboutToChange : null,
                isBootingHome: c ? c.isBootingHome : null,
                homeKey: c ? c.homeLaunchByHomeKey : null,
                activateType: p ? p.activateType : null,
                launchType: p ? p.launchType : null
            };
            var line = "WIIOS_DIAG " + JSON.stringify(record);
            console.warn(line);
            rootWindow.printLog(line);
        } catch (error) {
            console.warn("WIIOS_DIAG @TOKEN@ trace-error " + String(error));
        }
    }
'''.replace('@TOKEN@', token)
    main = replace_once(main, '    id: rootWindow\n', '    id: rootWindow\n' + trace)
    main = replace_once(main, '        onStart: {', '        onStart: {\n            rootWindow.wiiosTrace("lifecycle.start", {mode: mode});')
    main = replace_once(main, '        onRegisterAppResponse: {', '''        onRegisterAppResponse: {
            rootWindow.wiiosTrace("lifecycle.register", {
                event: response.event,
                activateType: response.parameters ? response.parameters.activateType : null,
                launchType: response.parameters ? response.parameters.launchType : null
            });''')
    main = replace_once(main, '        onLifeStatusChanged: {', '        onLifeStatusChanged: {\n            rootWindow.wiiosTrace("lifecycle.status", {status: status});')
    main = replace_once(main, '        rootWindow.launchParams = JSON.parse(launchParams);', '''        rootWindow.launchParams = JSON.parse(launchParams);
        rootWindow.wiiosTrace("main.appLaunched", {
            restored: bRestored, device: isDevice, reason: rootWindow.launchParams.reason,
            activateType: rootWindow.launchParams.parameters ? rootWindow.launchParams.parameters.activateType : null,
            launchType: rootWindow.launchParams.parameters ? rootWindow.launchParams.parameters.launchType : null,
            snapshot: rootWindow.launchParams.parameters ? rootWindow.launchParams.parameters.snapshot : null
        });''')
    main = replace_once(main, '    Component.onCompleted: {', '    Component.onCompleted: {\n        rootWindow.wiiosTrace("main.completed", {});')
    ctrl = replace_once(ctrl, '    id: root\n', '    id: root\n\n    Component.onCompleted: rootWindow.wiiosTrace("controller.completed", {})\n')
    ctrl = replace_once(ctrl, '    onHomeLaunchByHomeKeyChanged: {', '    onHomeLaunchByHomeKeyChanged: {\n        rootWindow.wiiosTrace("controller.homeKeyChanged", {value: homeLaunchByHomeKey});')
    ctrl = replace_once(ctrl, '    function executeLaunch(mode, extraParam, isBootingHome) {', '''    function executeLaunch(mode, extraParam, isBootingHome) {
        rootWindow.wiiosTrace("controller.executeLaunch", {
            mode: mode, bootArgument: isBootingHome,
            extraParamType: typeof extraParam
        });''')
    ctrl = replace_once(ctrl, '    function goToState(state) {', '    function goToState(state) {\n        rootWindow.wiiosTrace("controller.goToState", {nextState: state});')
    return dict(zip(EXPECTED, (main.encode(), ctrl.encode())))

def prepare(backup, output, token=None, redirect_trial=False):
    token = token or ('diag-' + secrets.token_hex(6))
    originals = {}
    with tarfile.open(backup) as archive:
        for name, expected in EXPECTED.items():
            matches = [member for member in archive.getmembers() if member.name == name]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 1024 * 1024:
                raise ValueError('Invalid backup member: ' + name)
            data = archive.extractfile(matches[0]).read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Firmware hash mismatch: ' + name)
            originals[name] = data
    patches = instrument(originals, token)
    deadline = int(time.time()) + 600 if redirect_trial else 0
    if redirect_trial:
        from redirect import add_redirect
        patches = add_redirect(patches, deadline * 1000)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    base = '/var/lib/webosbrew/wiios-fullhome-diag/' + token
    manifest = {'token': token, 'kind': 'redirect-trial' if redirect_trial else 'diagnostic-only', 'base': base, 'deadline': deadline, 'files': []}
    config = {'TOKEN': token, 'EXPECTED_BASE': base, 'DEADLINE': str(deadline)}
    diff = ''
    for number, (name, data) in enumerate(patches.items(), 1):
        filename = Path(name).name
        (output / filename).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        config.update({f'TARGET_{number}': TARGET + name, f'FILE_{number}': filename,
                       f'ORIGINAL_{number}': EXPECTED[name], f'PATCHED_{number}': digest})
        manifest['files'].append({'name': filename, 'target': TARGET + name, 'original_sha256': EXPECTED[name], 'patched_sha256': digest})
        diff += ''.join(difflib.unified_diff(originals[name].decode().splitlines(True), data.decode().splitlines(True), 'original/' + name, 'diagnostic/' + name))
    (output / 'config.sh').write_text(''.join(key + '=' + shlex.quote(value) + '\n' for key, value in config.items()))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'diagnostic.diff').write_text(diff)
    for name in ['common.sh', 'activate.sh', 'rollback.sh', 'watchdog.sh', 'status.sh']:
        (output / name).write_bytes((ROOT / name).read_bytes())
    print(json.dumps({'bundle': str(output), 'token': token, 'remote': base}, indent=2))
    return manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--redirect-trial', action='store_true', help='Redirect trial, expires 10 minutes after generation')
    args = parser.parse_args()
    prepare(args.backup, args.output, redirect_trial=args.redirect_trial)
