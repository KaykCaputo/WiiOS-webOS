import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from installer.application import Artifact
from installer.errors import InstallerError
from installer.version import INSTALLER_VERSION, INSTALLER_BUILD
from installer.install_engine import InstallEngine
from installer.journal import Journal
from installer.transport import Connection, DeveloperModeTransport, RootSSHTransport, trust_host
from compatibility.schema import validate_document


def parser():
    result = argparse.ArgumentParser(prog='wiios-installer', description='Install WiiOS or inspect Home replacement compatibility.')
    result.add_argument('--version', action='version', version=f'WiiOS Installer {INSTALLER_VERSION} ({INSTALLER_BUILD})')
    commands = result.add_subparsers(dest='command', required=True)
    commands.add_parser('build-info', help='Display the exact installer file and confirm full-screen TUI modules')
    bundle = commands.add_parser('prepare-home-bundle', help='Prepare a read-only, offline Home overlay candidate')
    bundle.add_argument('--app-dir', type=Path, required=True)
    bundle.add_argument('--stock-manifest', type=Path, required=True)
    bundle.add_argument('--stock-sha256', required=True)
    bundle.add_argument('--output', type=Path, required=True)
    qualify = commands.add_parser('qualification-template', help='Generate an unapproved device test checklist from diagnostics')
    qualify.add_argument('--diagnostics', type=Path, required=True)
    qualify.add_argument('--output', type=Path, required=True)
    reference = commands.add_parser('detection-reference', help='Save a detection-only QML reference from diagnostics')
    reference.add_argument('--diagnostics', type=Path, required=True)
    reference.add_argument('--output', type=Path, required=True)
    comparison = commands.add_parser('check-detection-reference', help='Compare a read-only diagnostic report with a QML reference')
    comparison.add_argument('--reference', type=Path, required=True)
    comparison.add_argument('--diagnostics', type=Path, required=True)
    connection = argparse.ArgumentParser(add_help=False)
    connection.add_argument('--host')
    connection.add_argument('--transport', choices=['developer-mode', 'root-ssh'], default='developer-mode')
    connection.add_argument('--port', type=int)
    connection.add_argument('--user')
    connection.add_argument('--identity')
    connection.add_argument('--service-pty', action='store_true', help='Request a terminal for Luna calls on firmware that requires it')
    connection.add_argument('--known-hosts', default=str(Path.home() / '.ssh' / 'known_hosts'))
    connection.add_argument('--state-dir', default=str(Path.home() / '.wiios' / 'transactions'))
    connection.add_argument('--ipk', type=Path)
    connection.add_argument('--sha256')
    connection.add_argument('--json', action='store_true')
    for name in ('probe', 'plan', 'install', 'update', 'uninstall', 'diagnose', 'tui', 'trust', 'launch', 'reconcile'):
        command = commands.add_parser(name, parents=[connection])
        if name in ('plan', 'install'):
            command.add_argument('--mode', choices=['app', 'home'], default='app')
        if name in ('install', 'update'):
            command.add_argument('--approve-plan')
            command.add_argument('--plan-file', type=Path)
        if name == 'tui':
            command.add_argument('--text-mode', action='store_true', help='Use the explicit line-oriented installer instead of the full-screen TUI')
        if name == 'plan':
            command.add_argument('--output', type=Path)
            command.add_argument('--new-trial', action='store_true', help='Generate a separate approval nonce for a second Home trial')
        if name == 'diagnose':
            command.add_argument('--export', type=Path, required=True)
        if name == 'reconcile':
            command.add_argument('--transaction', required=True)
        if name == 'trust':
            command.add_argument('--fingerprint', required=True)
    home = commands.add_parser('home').add_subparsers(dest='home_command', required=True)
    home.add_parser('status', parents=[connection])
    home.add_parser('audit-legacy-recovery', parents=[connection], help='Read-only verification of existing legacy QML rollback readiness')
    trial = home.add_parser('trial', parents=[connection])
    trial.add_argument('--plan-file', type=Path, required=True)
    trial.add_argument('--approve-plan', required=True)
    trial.add_argument('--home-bundle', type=Path, required=True)
    trial.add_argument('--sam-protocol', choices=['sam-block-release-v1'])
    trial.add_argument('--native-contract', choices=['register-app-v2', 'register-native-app-v1'])
    trial.add_argument('--wam-launch', type=Path)
    verification = home.add_parser('verify', parents=[connection])
    verification.add_argument('--transaction', required=True)
    verification.add_argument('--home-key-confirmed', action='store_true')
    persist = home.add_parser('persist', parents=[connection])
    persist.add_argument('--transaction', required=True)
    persist.add_argument('--rehearsal', required=True)
    persist.add_argument('--approve-plan', required=True)
    persist.add_argument('--home-key-confirmed', action='store_true')
    finalize = home.add_parser('finalize', parents=[connection])
    finalize.add_argument('--transaction', required=True)
    finalize.add_argument('--home-key-confirmed', action='store_true')
    stock = home.add_parser('confirm-stock', parents=[connection])
    stock.add_argument('--transaction', required=True)
    stock.add_argument('--lg-home-confirmed', action='store_true')
    restore = home.add_parser('restore', parents=[connection])
    restore.add_argument('--transaction', required=True)
    return result


def create_engine(args):
    if not args.host or not args.port or not args.user:
        raise InstallerError('CONNECTION_REQUIRED', 'Supply --host, --port, and --user, or use the interactive TUI.', 2)
    connection = Connection(args.host, args.port, args.user, args.identity, args.known_hosts, args.transport, args.service_pty)
    transport = (DeveloperModeTransport if args.transport == 'developer-mode' else RootSSHTransport)(connection)
    artifact = Artifact(args.ipk, args.sha256) if args.ipk else None
    return InstallEngine(transport, Journal(args.state_dir), artifact)


def write_report(path, value):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise InstallerError('UNSAFE_REPORT_PATH', 'The report path must not be a symlink.', 2)
    with path.open('w') as stream:
        path.chmod(0o600)
        json.dump(value, stream, indent=2)
        stream.write('\n')


def dispatch(args, engine):
    if args.command == 'probe':
        return engine.probe()
    if args.command == 'trust':
        return trust_host(engine.transport.connection, args.fingerprint)
    if args.command == 'plan':
        plan = engine.plan(mode=args.mode)
        if args.mode == 'home' and args.new_trial:
            import secrets
            from installer.plan import fresh_trial
            plan = fresh_trial(plan, secrets.token_hex(16))
        if args.output:
            write_report(args.output, plan)
        return plan
    if args.command in ('install', 'update'):
        mode = getattr(args, 'mode', 'app')
        plan = json.loads(args.plan_file.read_text()) if args.plan_file else engine.plan(mode=mode, action=args.command)
        validate_document(plan, 'change-plan')
        if plan['mode'] == 'home-replacement' and not args.approve_plan:
            raise InstallerError('APPROVAL_REQUIRED', 'Home replacement requires approval of the exact plan.', 8)
        return engine.apply(plan, args.approve_plan or plan['approvalDigest'])
    if args.command == 'reconcile':
        return engine.reconcile_transaction(args.transaction)
    if args.command == 'uninstall':
        return engine.uninstall()
    if args.command == 'launch':
        return engine.application.launch()
    if args.command == 'diagnose':
        report = engine.diagnose()
        write_report(args.export, report)
        return {'ok': True, 'report': str(args.export), 'qualification': 'NEEDS_DEVICE_VALIDATION'}
    if args.command == 'home':
        if args.home_command == 'status':
            return engine.diagnose()
        if args.home_command == 'audit-legacy-recovery':
            from home.operations.legacy_audit import audit_legacy_recovery
            return audit_legacy_recovery(engine.transport, engine.probe())
        if args.home_command == 'trial':
            launch_payload = json.loads(args.wam_launch.read_text()) if args.wam_launch else None
            return engine.home_trial(json.loads(args.plan_file.read_text()), args.approve_plan,
                                     args.home_bundle, args.sam_protocol, args.native_contract, launch_payload)
        if args.home_command == 'persist':
            return engine.home_trial_state(args.transaction, 'persist', args.home_key_confirmed,
                                           args.rehearsal, args.approve_plan)
        if args.home_command == 'finalize':
            return engine.home_trial_state(args.transaction, 'finalize', args.home_key_confirmed)
        if args.home_command == 'confirm-stock':
            return engine.home_trial_state(args.transaction, 'confirm-stock', args.lg_home_confirmed)
        if args.home_command == 'verify':
            return engine.home_trial_state(args.transaction, 'verify', args.home_key_confirmed)
        return engine.restore(args.transaction)
    if args.command == 'tui':
        if args.text_mode:
            from installer.tui import run
            return run(engine)
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise InstallerError('TERMINAL_REQUIRED', 'The full-screen interface needs a real terminal. Run with --text-mode for an explicit line-oriented menu.', 2)
        try:
            from installer.fullscreen import run_fullscreen
        except ImportError as error:
            raise InstallerError('TUI_UNAVAILABLE', 'Full-screen terminal support is unavailable. Run with --text-mode to use the legacy menu.', 2) from error
        return run_fullscreen(engine)
    raise InstallerError('INVALID_COMMAND', 'Unknown command.', 2)


def build_info():
    executable = Path(sys.argv[0]).resolve()
    packaged = zipfile.is_zipfile(executable)
    module_paths = {'installer/fullscreen.py', 'installer/cli.py', 'installer/version.py'}
    if packaged:
        with zipfile.ZipFile(executable) as archive:
            available = module_paths.issubset(archive.namelist())
    else:
        available = all((Path(__file__).resolve().parents[1] / name).is_file() for name in module_paths)
    return {
        'ok': available,
        'installerVersion': INSTALLER_VERSION,
        'installerBuild': INSTALLER_BUILD,
        'executedFile': str(executable),
        'sha256': hashlib.sha256(executable.read_bytes()).hexdigest() if packaged else None,
        'fullscreenTuiAvailable': available,
        'legacyMenuDefault': False,
    }


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'prepare-home-bundle':
            from home.bundle import prepare_web_home
            result = prepare_web_home(args.app_dir, args.stock_manifest.read_bytes(), args.stock_sha256, args.output)
            print(json.dumps({'ok': True, 'bundle': str(args.output), 'manifest': result}, indent=2))
            return 0
        if args.command == 'qualification-template':
            from compatibility.qualification import qualification_template
            result = qualification_template(json.loads(args.diagnostics.read_text()))
            write_report(args.output, result)
            print(json.dumps({'ok': True, 'report': str(args.output), 'qualification': result['qualification']}, indent=2))
            return 0
        if args.command == 'detection-reference':
            from compatibility.detection_reference import create_detection_reference
            reference = create_detection_reference(json.loads(args.diagnostics.read_text()))
            write_report(args.output, reference)
            print(json.dumps({'ok': True, 'report': str(args.output), 'qualification': reference['qualification'],
                              'takeoverApproved': False}, indent=2))
            return 0
        if args.command == 'check-detection-reference':
            from compatibility.detection_reference import compare_detection_reference
            result = compare_detection_reference(json.loads(args.reference.read_text()),
                                                 json.loads(args.diagnostics.read_text()))
            print(json.dumps(result, indent=2))
            return 0 if result['ok'] else 5
        if args.command == 'build-info':
            result = build_info()
            print(json.dumps(result, indent=2))
            return 0 if result['ok'] else 3
        if args.command == 'tui':
            from installer.tui import configure_connection
            configure_connection(args)
        result = dispatch(args, create_engine(args))
        if args.command != 'tui':
            print(json.dumps(result, indent=2))
        return 0 if result.get('ok', True) else 5
    except InstallerError as error:
        print(json.dumps(error.result()), file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'ok': False, 'reasonCode': 'INVALID_CONFIGURATION',
                          'message': 'Invalid configuration, artifact, or report path.'}), file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print(json.dumps({'ok': False, 'reasonCode': 'CANCELLED',
                          'message': 'Cancelled. Reconcile pending transactions before retrying.'}), file=sys.stderr)
        return 5
