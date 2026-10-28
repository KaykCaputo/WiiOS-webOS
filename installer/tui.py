import json
import shutil

from installer.errors import InstallerError


def configure_connection(args, read=input, write=print):
    if args.host and args.port and args.user:
        return args
    write('Connect to TV')
    write('1 Developer Mode\n2 Root SSH')
    selection = read('Select the authorized transport [1]: ').strip()
    if selection not in ('', '1', '2'):
        raise InstallerError('INVALID_TRANSPORT', 'Select Developer Mode or Root SSH.', 2)
    args.transport = 'root-ssh' if selection == '2' else 'developer-mode'
    args.host = args.host or read('TV address: ').strip()
    default_port = 22 if args.transport == 'root-ssh' else 9922
    args.port = args.port or int(read(f'SSH port [{default_port}]: ').strip() or str(default_port))
    default_user = 'root' if args.transport == 'root-ssh' else 'prisoner'
    args.user = args.user or read(f'SSH username [{default_user}]: ').strip() or default_user
    args.identity = args.identity or read('Private key path, or Enter to use your SSH agent: ').strip() or None
    return args


def run(engine, read=input, write=print):
    write('WiiOS Installer')
    write('Welcome and Prerequisites')
    write('Use a release IPK and an authorized Developer Mode or Root SSH connection.')
    write('OpenSSH: ' + ('Available' if shutil.which('ssh') else 'Unavailable'))
    write('Host validation: Linux automated tests; macOS and Windows NEEDS_DEVICE_VALIDATION.')
    write('Connect to TV: ' + engine.transport.connection.endpoint)
    write('Transport: ' + engine.transport.kind)
    if hasattr(engine.transport, 'fingerprint'):
        try:
            write('Trusted SSH fingerprint: ' + engine.transport.fingerprint())
        except InstallerError:
            from installer.transport import trust_host
            write('No trusted SSH key was found in ' + engine.transport.connection.known_hosts)
            write('If regular SSH already works, restart with --known-hosts ~/.ssh/known_hosts and the correct port.')
            write('Verify the fingerprint through an independent trusted channel before approving a new key.')
            fingerprint = read('Enter the verified SHA256 fingerprint, or Enter to cancel: ').strip()
            if not fingerprint:
                return {'ok': False, 'reasonCode': 'HOST_KEY_UNTRUSTED'}
            trust_host(engine.transport.connection, fingerprint)
    write('Enter a menu number. Enter 0 or Escape followed by Enter to go back.')
    while True:
        write('\nInstallation Mode')
        write('1 Install WiiOS as an Application\n2 Inspect Compatibility\n3 Replace LG Home with WiiOS')
        write('4 Update WiiOS\n5 Restore LG Home\n6 Uninstall WiiOS\n7 Export Diagnostics\n8 Launch WiiOS\n9 Reconcile Interrupted Installation\n0 Exit')
        try:
            choice = read('Select: ').strip()
            if choice in ('0', '\x1b'):
                return {'ok': True, 'state': 'CLOSED'}
            if choice in ('1', '3', '4'):
                if not engine.artifact:
                    from installer.application import Artifact
                    engine.artifact = Artifact(read('Release IPK path: ').strip())
                plan = engine.plan(mode='home' if choice == '3' else 'app', action='update' if choice == '4' else 'install')
                write('Integration Strategy: ' + (plan['adapter'] or 'App-only; LG Home remains unchanged'))
                write('Change Plan\n' + json.dumps(plan, indent=2))
                write('Approval: confirm the device and the exact changes above.')
                if read('Type the plan digest to apply, or press Enter to cancel: ').strip() != plan['approvalDigest']:
                    write('Cancelled before mutation.')
                    continue
                write('Progress: installing the approved package. The connection has finite timeouts.')
                write('Validation\n' + json.dumps(engine.apply(plan, plan['approvalDigest']), indent=2))
                write('Check the UI on the TV. Installation success does not confirm Home replacement.')
            elif choice == '2':
                report = engine.diagnose()
                write('Device Fingerprint\n' + json.dumps(report['deviceProfile'], indent=2))
                write('Compatibility Analysis\n' + json.dumps(report['compatibility'], indent=2))
            elif choice == '5':
                write('Recovery and Uninstall')
                transaction = read('Transaction ID: ').strip()
                if read('Type RESTORE to confirm recovery on this device: ') == 'RESTORE':
                    write(json.dumps(engine.restore(transaction), indent=2))
            elif choice == '6':
                if read('Type UNINSTALL to remove WiiOS after Home recovery checks: ') == 'UNINSTALL':
                    write(json.dumps(engine.uninstall(), indent=2))
            elif choice == '7':
                from installer.cli import write_report
                path = read('Diagnostic report path: ').strip()
                write_report(path, engine.diagnose())
                write('Diagnostic report saved.')
            elif choice == '8':
                write(json.dumps(engine.application.launch(), indent=2))
            elif choice == '9':
                pending = engine.reconcile()
                write('Pending Transactions\n' + json.dumps(pending, indent=2))
                if pending:
                    transaction = read('Transaction ID to reconcile, or Enter to cancel: ').strip()
                    if transaction:
                        write(json.dumps(engine.reconcile_transaction(transaction), indent=2))
            else:
                write('Select a listed menu number.')
        except InstallerError as error:
            write(error.code + ': ' + str(error))
        except (EOFError, KeyboardInterrupt):
            write('Cancelled. Pending transactions remain available for reconciliation.')
            return {'ok': False, 'reasonCode': 'CANCELLED'}
