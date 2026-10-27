from compatibility.probe import probe
from compatibility.resolver import resolve
from compatibility.signatures import profile_digest
from installer.application import ApplicationInstaller
from installer.errors import InstallerError
from installer.plan import app_plan, check_plan


class InstallEngine:
    def __init__(self, transport, journal, artifact=None, probe_device=probe, application=None):
        self.transport, self.journal, self.artifact = transport, journal, artifact
        self.probe_device = probe_device
        self.application = application or ApplicationInstaller(transport)

    def probe(self, target=None):
        return self.probe_device(self.transport)

    def diagnose(self):
        profile = self.probe()
        return {'schemaVersion': 1, 'deviceProfile': profile,
                'compatibility': resolve(profile, artifact_digest=self.artifact.digest if self.artifact else None),
                'qualification': 'NEEDS_DEVICE_VALIDATION', 'pendingTransactions': self.reconcile()}

    def plan(self, target=None, mode='app', action='install'):
        if not self.artifact:
            raise InstallerError('ARTIFACT_REQUIRED', 'Select a release IPK with --ipk.', 2)
        profile = self.probe()
        decision = resolve(profile, artifact_digest=self.artifact.digest)
        if mode in ('home', 'home-replacement'):
            code = 7 if decision['homeStatus'] == 'CONFLICT' else 3
            raise InstallerError('HOME_NOT_RELEASE_QUALIFIED',
                'Home activation is unavailable: ' + ', '.join(decision['reasonCodes'] or ['DEVICE_EXECUTOR_NOT_QUALIFIED']), code)
        if mode not in ('app', 'app-only'):
            raise InstallerError('INVALID_MODE', 'Choose app or home mode.', 2)
        if decision['appStatus'] != 'APP_ELIGIBLE':
            raise InstallerError('APP_INSTALL_UNAVAILABLE', 'Application installation capabilities are unknown.', 3)
        return app_plan(profile, self.artifact, action)

    def apply(self, plan, approval_digest):
        current = self.probe()
        check_plan(plan, approval_digest, current)
        if plan['mode'] != 'app-only':
            raise InstallerError('HOME_NOT_RELEASE_QUALIFIED', 'No device executor is release qualified.', 3)
        if not self.artifact or self.artifact.digest != plan['artifactDigest']:
            raise InstallerError('ARTIFACT_CHANGED', 'The selected artifact differs from the approved plan.', 8)
        expected = app_plan(current, self.artifact, plan['action'])
        if expected != plan:
            raise InstallerError('PLAN_OPERATIONS_CHANGED', 'The plan contains unsupported operations.', 8)
        if plan['action'] == 'uninstall':
            return self.uninstall()
        if self.journal.path(plan['transactionId']).exists() or self.journal.path(plan['transactionId']).is_symlink():
            previous = self.journal.read(plan['transactionId'])
            if (previous.get('plan') != plan or previous.get('endpoint') != self.transport.connection.endpoint or
                    previous.get('deviceProfileDigest') != profile_digest(current)):
                raise InstallerError('TRANSACTION_ID_CONFLICT', 'An existing transaction does not match the current plan.', 8)
            if previous.get('state') != 'COMMITTED':
                raise InstallerError('TRANSACTION_RECONCILIATION_REQUIRED',
                    'The previous transaction is incomplete. Reconcile it before retrying.', 6)
            if self.application.version() != plan['version']:
                raise InstallerError('COMMITTED_VERSION_CHANGED',
                    'The recorded installation differs from the installed application.', 8)
            return dict(previous['result'], transactionId=plan['transactionId'], alreadyApplied=True)
        transaction = {'schemaVersion': 1, 'transactionId': plan['transactionId'], 'plan': plan,
                       'deviceProfileDigest': profile_digest(current), 'endpoint': self.transport.connection.endpoint,
                       'state': 'PLAN_APPROVED', 'events': []}
        self.journal.save(transaction)
        try:
            transaction['state'] = 'STAGED'
            transaction['events'].append({'action': 'install-ipk', 'status': 'intent-recorded'})
            self.journal.save(transaction)
            result = self.application.install(self.artifact, plan['transactionId'])
            transaction.update(state='COMMITTED', result=result)
            self.journal.save(transaction)
            return dict(result, transactionId=plan['transactionId'])
        except (Exception, KeyboardInterrupt):
            transaction['state'] = 'RECONCILE_REQUIRED'
            self.journal.save(transaction)
            raise

    def verify(self, transaction_id):
        transaction = self.journal.read(transaction_id)
        if profile_digest(self.probe()) != transaction['deviceProfileDigest']:
            raise InstallerError('DEVICE_STATE_CHANGED', 'The device differs from the recorded transaction.', 8)
        return {'ok': self.application.version() == transaction['plan']['version'],
                'state': transaction['state'], 'uiConfirmed': False, 'homeConfirmed': False}

    def restore(self, transaction_id):
        if transaction_id == 'diag-3e891511b377':
            from home.operations.legacy_recovery import restore_legacy
            return restore_legacy(self.transport, transaction_id)
        transaction = self.journal.read(transaction_id)
        if profile_digest(self.probe()) != transaction['deviceProfileDigest']:
            raise InstallerError('DEVICE_STATE_CHANGED', 'Confirm the device identity before recovery.', 8)
        if transaction['plan']['mode'] == 'app-only':
            return {'ok': True, 'reasonCode': 'APP_ONLY_HOME_UNCHANGED', 'homeConfirmed': False}
        raise InstallerError('HOME_RECOVERY_NOT_QUALIFIED', 'Use the recorded adapter recovery procedure; ownership must be verified.', 6)

    def reconcile(self, target=None):
        endpoint = self.transport.connection.endpoint
        return [{'transactionId': entry['transactionId'], 'state': entry['state'],
                 'reasonCode': 'MANUAL_APP_VERSION_CHECK_REQUIRED'} for entry in self.journal.pending()
                if entry.get('endpoint') == endpoint]

    def reconcile_transaction(self, transaction_id):
        transaction = self.journal.read(transaction_id)
        if transaction.get('endpoint') != self.transport.connection.endpoint:
            raise InstallerError('TRANSACTION_DEVICE_MISMATCH', 'The transaction belongs to another SSH endpoint.', 8)
        if transaction['plan']['mode'] != 'app-only' or transaction['plan']['action'] == 'uninstall':
            raise InstallerError('TRANSACTION_RECONCILIATION_UNAVAILABLE',
                'The transaction must be handled by its independent Home recovery procedure.', 6)
        if transaction['state'] not in ('STAGED', 'RECONCILE_REQUIRED'):
            raise InstallerError('TRANSACTION_NOT_PENDING', 'This transaction does not require reconciliation.', 2)
        profile = self.probe()
        if profile_digest(profile) != transaction['deviceProfileDigest']:
            raise InstallerError('DEVICE_STATE_CHANGED', 'Device identity changed. No transaction was modified.', 8)
        actual = self.application.version()
        expected = transaction['plan']['version']
        if actual != expected:
            return {'ok': False, 'transactionId': transaction_id, 'state': transaction['state'],
                    'reasonCode': 'APP_VERSION_NOT_CONFIRMED', 'expectedVersion': expected,
                    'installedVersion': actual, 'changed': False}
        result = {'ok': True, 'state': 'APP_INSTALLED', 'version': actual, 'changed': True,
                  'uiConfirmed': False, 'reconciled': True}
        transaction.update(state='COMMITTED', result=result)
        transaction['events'].append({'action': 'verify-installed-version', 'status': 'confirmed'})
        self.journal.save(transaction)
        return dict(result, transactionId=transaction_id)

    def uninstall(self):
        profile = self.probe()
        if profile['transport']['kind'] == 'root-ssh' and (
                profile['home']['foreignMounts'] or profile['home']['conflictingHooks'] or
                profile['wiiOsInstallation']['homeAdapter']):
            raise InstallerError('HOME_RESTORE_REQUIRED', 'Restore and verify LG Home before removing WiiOS.', 7)
        return self.application.uninstall()
