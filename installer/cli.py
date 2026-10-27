import argparse
import json
from pathlib import Path
import sys

from installer.application import Artifact
from installer.errors import InstallerError
from installer.install_engine import InstallEngine
from installer.journal import Journal
from installer.transport import Connection, DeveloperModeTransport, RootSSHTransport, trust_host
from compatibility.schema import validate_document


def parser():
    result = argparse.ArgumentParser(prog='wiios-installer', description='Install WiiOS or inspect Home replacement compatibility.')
    commands = result.add_subparsers(dest='command', required=True)
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
        if name == 'plan':
            command.add_argument('--output', type=Path)
        if name == 'diagnose':
            command.add_argument('--export', type=Path, required=True)
        if name == 'reconcile':
            command.add_argument('--transaction', required=True)
        if name == 'trust':
            command.add_argument('--fingerprint', required=True)
    home = commands.add_parser('home').add_subparsers(dest='home_command', required=True)
    home.add_parser('status', parents=[connection])
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
        return engine.restore(args.transaction)
    if args.command == 'tui':
        import sys
        if sys.stdin.isatty() and sys.stdout.isatty():
            try:
                from installer.fullscreen import run_fullscreen
                return run_fullscreen(engine)
            except ImportError:
                pass
        from installer.tui import run
        return run(engine)
    raise InstallerError('INVALID_COMMAND', 'Unknown command.', 2)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'tui':
            from installer.tui import configure_connection
            configure_connection(args)
        result = dispatch(args, create_engine(args))
        print(json.dumps(result, indent=2))
        return 0
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
