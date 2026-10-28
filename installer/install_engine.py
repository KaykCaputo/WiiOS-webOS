from compatibility.probe import probe
from compatibility.resolver import resolve
from compatibility.signatures import profile_digest
from installer.application import ApplicationInstaller
from installer.errors import InstallerError
from installer.plan import app_plan, check_plan, seal_plan
from home.adapters.qml_redirect import QmlRedirect
from home.adapters.directory_takeover import HomeDirectoryTakeover
from home.adapters.native_standin import NativeHomeStandin


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
            if decision['homeStatus'] != 'HOME_ELIGIBLE':
                code = 7 if decision['homeStatus'] == 'CONFLICT' else 3
                raise InstallerError('HOME_NOT_RELEASE_QUALIFIED',
                    'Home activation is unavailable: ' + ', '.join(decision['reasonCodes'] or ['DEVICE_EXECUTOR_NOT_QUALIFIED']), code)
            if action != 'install':
                raise InstallerError('HOME_UPDATE_NOT_QUALIFIED', 'Home updates require a separate qualified transaction.', 3)
            adapters = {'qml-redirect': QmlRedirect, 'home-directory-takeover': HomeDirectoryTakeover,
                        'native-home-standin': NativeHomeStandin}
            selected = decision['selectedHomeAdapter']
            if selected not in adapters:
                raise InstallerError('HOME_ADAPTER_UNKNOWN', 'The selected Home adapter is unknown.', 3)
            proposal = adapters[selected]().build_plan(profile)
            return seal_plan(dict(proposal, artifactDigest=self.artifact.digest,
                version=self.artifact.version, profileId=decision['profileId']))
        if mode not in ('app', 'app-only'):
            raise InstallerError('INVALID_MODE', 'Choose app or home mode.', 2)
        if decision['appStatus'] != 'APP_ELIGIBLE':
            raise InstallerError('APP_INSTALL_UNAVAILABLE', 'Application installation capabilities are unknown.', 3)
        return app_plan(profile, self.artifact, action)

    def home_trial(self, plan, approval_digest, bundle_directory, sam_protocol=None, native_contract=None, launch_payload=None):
        from pathlib import Path
        import json
        from home.operations.device_backend import DeviceHomeBackend
        from home.operations.native_backend import NativeHomeBackend
        from home.operations.transaction import HomeTransaction
        profile = self.probe()
        check_plan(plan, approval_digest, profile)
        if not self.artifact or self.artifact.digest != plan['artifactDigest']:
            raise InstallerError('ARTIFACT_CHANGED', 'The artifact differs from the approved Home plan.', 8)
        decision = resolve(profile, artifact_digest=self.artifact.digest)
        adapter = decision['selectedHomeAdapter']
        if (decision['homeStatus'] != 'HOME_ELIGIBLE' or
                adapter not in ('home-directory-takeover', 'native-home-standin') or
                plan['adapter'] != adapter or decision['profileId'] != plan['profileId']):
            raise InstallerError('HOME_TRIAL_NOT_QUALIFIED', 'An exact approved Home profile is required.', 3)
        if adapter == 'home-directory-takeover' and sam_protocol != 'sam-block-release-v1':
            raise InstallerError('SAM_REFRESH_UNQUALIFIED', 'An exact qualified SAM refresh protocol is required.', 3)
        if adapter == 'native-home-standin' and (native_contract not in ('register-app-v2', 'register-native-app-v1') or
                                                 not isinstance(launch_payload, dict)):
            raise InstallerError('NATIVE_LIFECYCLE_UNQUALIFIED', 'Native Home requires a qualified lifecycle and WAM payload.', 3)
        from compatibility.resolver import load_verified
        from compatibility.signatures import digest
        rule = next((item for item in load_verified() if item['profileId'] == decision['profileId']), None)
        if not rule:
            raise InstallerError('HOME_PROFILE_MISSING', 'The verified Home profile is unavailable.', 3)
        qualification = rule['homeReplacement']
        if adapter == 'home-directory-takeover' and qualification.get('samProtocol') != sam_protocol:
            raise InstallerError('SAM_PROTOCOL_CHANGED', 'The SAM protocol differs from the approved profile.', 8)
        if adapter == 'native-home-standin' and (
                qualification.get('nativeContract') != native_contract or
                qualification.get('wamLaunchSha256') != digest(launch_payload)):
            raise InstallerError('NATIVE_PAYLOAD_CHANGED', 'The native launch contract differs from the verified profile.', 8)
        directory = Path(bundle_directory)
        manifest = json.loads((directory / 'wiios-home-bundle.json').read_text())
        if (manifest.get('sourceAppId') != 'com.wiios.launcher' or
                manifest.get('sourceVersion') != self.artifact.version or
                {key: value for key, value in manifest.get('files', {}).items() if key != 'appinfo.json'} !=
                self.artifact.app_payload_checksums()):
            raise InstallerError('HOME_BUNDLE_ARTIFACT_MISMATCH', 'The Home bundle is not derived from the approved IPK.', 8)
        if adapter == 'native-home-standin':
            backend = NativeHomeBackend(self.transport, profile, plan, directory, manifest, native_contract, launch_payload)
        else:
            backend = DeviceHomeBackend(self.transport, profile, plan, directory, manifest, sam_protocol)
        current = self.plan(mode='home')
        if plan.get('trialNonce'):
            from installer.plan import fresh_trial
            current = fresh_trial(current, plan['trialNonce'])
        if current != plan:
            raise InstallerError('HOME_PLAN_CHANGED', 'Generate a new plan for this device.', 8)
        if self.journal.path(plan['transactionId']).exists():
            raise InstallerError('HOME_TRANSACTION_ALREADY_EXISTS', 'The existing Home transaction must be recovered first.', 8)
        host_record = {'schemaVersion': 1, 'transactionId': plan['transactionId'], 'plan': plan,
                       'profile': profile, 'bundleManifest': manifest, 'bundleDirectory': str(directory.resolve()),
                       'samProtocol': sam_protocol, 'nativeContract': native_contract,
                       'launchPayload': launch_payload, 'endpoint': self.transport.connection.endpoint,
                       'state': 'TRIAL_PENDING'}
        self.journal.save(host_record)
        transaction = HomeTransaction(plan, backend)
        try:
            transaction.stage()
            transaction.activate()
            host_record['state'] = 'TRIAL_ACTIVE'
            self.journal.save(host_record)
            return {'ok': True, 'transactionId': plan['transactionId'], 'state': 'TRIAL_ACTIVE',
                    'trialTimeoutSeconds': plan['trialTimeoutSeconds'], 'persistent': False,
                    'homeConfirmed': False}
        except BaseException:
            host_record['state'] = 'RECONCILE_REQUIRED'
            self.journal.save(host_record)
            raise

    def import_device_recovery(self, transaction_id):
        import json
        from compatibility.schema import validate_document
        self.journal.path(transaction_id)
        if self.transport.kind != 'root-ssh' or self.transport.execute('id -u').strip() != '0':
            raise InstallerError('ROOT_RECOVERY_REQUIRED', 'Device journal recovery requires authorized Root SSH.', 3)
        record = json.loads(self.transport.execute('cat /var/lib/wiios/home-transactions/' + transaction_id + '/journal.json'))
        plan = validate_document(record['plan'], 'change-plan')
        metadata = record.get('recoveryMetadata', {})
        profile = metadata.get('profile')
        if (record.get('transactionId') != transaction_id or plan['transactionId'] != transaction_id or
                not isinstance(profile, dict) or profile_digest(profile) != plan['deviceProfileDigest']):
            raise InstallerError('DEVICE_RECOVERY_INVALID', 'The device recovery journal identity is invalid.', 8)
        actual = self.transport.luna('luna://com.webos.service.tv.systemproperty/getSystemInfo',
                                     {'keys': ['modelName', 'boardType']})
        if (actual.get('returnValue') is not True or not profile['identity'].get('model') or
                not profile['identity'].get('board') or
                actual.get('modelName') != profile['identity']['model'] or
                actual.get('boardType') != profile['identity']['board']):
            raise InstallerError('DEVICE_RECOVERY_IDENTITY_MISMATCH', 'Device identity could not be verified for recovery.', 8)
        self.journal.save({'schemaVersion': 1, 'transactionId': transaction_id, 'plan': plan,
            'profile': profile, 'bundleManifest': metadata.get('bundleManifest'), 'bundleDirectory': '.',
            'samProtocol': metadata.get('samProtocol'), 'nativeContract': metadata.get('nativeContract'),
            'launchPayload': metadata.get('launchPayload'), 'endpoint': self.transport.connection.endpoint,
            'state': record['state']})

    def home_trial_state(self, transaction_id, action, physical_confirmation=False, rehearsal_id=None, approval_digest=None):
        import json
        from pathlib import Path
        from home.operations.device_backend import DeviceHomeBackend
        from home.operations.native_backend import NativeHomeBackend
        from home.operations.transaction import HomeTransaction
        if not self.journal.path(transaction_id).exists() and action == 'restore':
            self.import_device_recovery(transaction_id)
        host_record = self.journal.read(transaction_id)
        if (host_record.get('endpoint') != self.transport.connection.endpoint or
                host_record['plan']['mode'] != 'home-replacement'):
            raise InstallerError('HOME_TRANSACTION_DEVICE_MISMATCH', 'The Home transaction belongs to a different device.', 8)
        directory = Path(host_record['bundleDirectory'])
        manifest = host_record.get('bundleManifest')
        if manifest is None:
            remote_record = json.loads(self.transport.execute(
                'cat /var/lib/wiios/home-transactions/' + transaction_id + '/journal.json'))
            if remote_record.get('plan') != host_record['plan']:
                raise InstallerError('RECOVERY_METADATA_MISMATCH', 'The remote recovery plan changed.', 8)
            manifest = remote_record.get('recoveryMetadata', {}).get('bundleManifest')
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict):
            raise InstallerError('RECOVERY_METADATA_MISSING', 'Use the independent device recovery executor; bundle metadata is missing.', 6)
        if host_record['plan']['adapter'] == 'native-home-standin':
            backend = NativeHomeBackend(self.transport, host_record['profile'], host_record['plan'],
                                        directory, manifest, host_record['nativeContract'],
                                        host_record['launchPayload'], physical_confirmation)
        else:
            backend = DeviceHomeBackend(self.transport, host_record['profile'], host_record['plan'],
                                        directory, manifest, host_record['samProtocol'], physical_confirmation)
        transaction = HomeTransaction(host_record['plan'], backend)
        record = backend.read_device_journal()
        for event in record.get('events', []):
            if event['operation']['action'] == 'arm-independent-watchdog' and event.get('receipt'):
                backend.receipts['watchdog'] = event['receipt']

        if action == 'confirm-stock':
            if not physical_confirmation or record['state'] not in ('STOCK_FILES_RESTORED', 'RESTORED'):
                raise InstallerError('STOCK_CONFIRMATION_REQUIRED', 'Restore first, then confirm LG Home works using the physical remote.', 8)
            backend.physical_stock_confirmed = True
            transaction.record = record
            result = transaction.verify_restoration()
            host_record['state'] = result['state']
            host_record['stockHomeVerified'] = result['stockHomeVerified']
            self.journal.save(host_record)
            return {'ok': result['stockHomeVerified'], 'state': result['state'], 'stockHomeVerified': result['stockHomeVerified']}
        if action == 'restore':
            result = transaction.recover(record)
            host_record['state'] = result['state']
            host_record['stockHomeVerified'] = result.get('stockHomeVerified') is True
            self.journal.save(host_record)
            return {'ok': True, 'transactionId': transaction_id, 'state': result['state'],
                    'stockHomeVerified': result.get('stockHomeVerified') is True}
        if action == 'verify':
            transaction.record = record
            if record['state'] != 'TRIAL_ACTIVE':
                raise InstallerError('HOME_TRIAL_NOT_ACTIVE', 'The Home trial is not active.', 6)
            result = transaction.verify()
            host_record['state'] = result['state']
            self.journal.save(host_record)
            return {'ok': True, 'state': result['state'], 'health': result['health'],
                    'persistent': False, 'transactionId': transaction_id}
        if action in ('persist', 'finalize'):
            from compatibility.resolver import load_verified
            rule = next((value for value in load_verified()
                         if value['profileId'] == host_record['plan']['profileId']), None)
            if (not rule or rule['homeReplacement']['status'] != 'HOME_CONFIRMED' or
                    rule['homeReplacement'].get('bootProtocol') != 'webosbrew-init-v1' or
                    not rule['homeReplacement']['maintainerApproved']):
                raise InstallerError('BOOT_PROFILE_UNQUALIFIED', 'Guarded persistence requires a physically validated boot protocol.', 3)
            current = self.probe()
            identity = host_record['profile']['identity']
            if current['identity'] != identity:
                raise InstallerError('BOOT_DEVICE_CHANGED', 'Device identity or firmware changed since trial approval.', 8)
            transaction.record = record
            if action == 'persist':
                if not physical_confirmation:
                    raise InstallerError('PHYSICAL_HOME_CONFIRMATION_REQUIRED', 'Confirm the physical Home key before enabling boot persistence.', 8)
                if (not rehearsal_id or rehearsal_id == transaction_id or
                        not approval_digest or approval_digest != host_record['plan']['approvalDigest']):
                    raise InstallerError('RESTORE_REHEARSAL_REQUIRED', 'A separate restored trial and exact plan approval are mandatory.', 8)
                previous = self.journal.read(rehearsal_id)
                if (previous.get('endpoint') != host_record['endpoint'] or
                        previous.get('state') != 'RESTORED' or
                        previous.get('stockHomeVerified') is not True):
                    raise InstallerError('RESTORE_REHEARSAL_UNVERIFIED', 'The previous trial has no verified LG Home restoration.', 8)
                verified_previous = self.transport.execute(
                    'cat /var/lib/wiios/home-transactions/' + rehearsal_id + '/journal.json')
                remote_previous = json.loads(verified_previous)
                old_plan = previous['plan']
                for value in (old_plan, remote_previous['plan']):
                    if any(value.get(key) != host_record['plan'].get(key)
                           for key in ('deviceProfileDigest', 'artifactDigest', 'adapter')):
                        raise InstallerError('RESTORE_REHEARSAL_MISMATCH', 'The rehearsal used a different firmware or payload.', 8)
                if (remote_previous.get('transactionId') != rehearsal_id or
                        remote_previous.get('state') != 'RESTORED' or
                        remote_previous.get('stockHomeVerified') is not True):
                    raise InstallerError('RESTORE_REHEARSAL_REMOTE_UNVERIFIED', 'The TV did not record a completed restoration rehearsal.', 8)
                proof = dict({key: old_plan[key] for key in ('deviceProfileDigest', 'artifactDigest', 'adapter')},
                             state='RESTORED', stockHomeVerified=True, transactionId=rehearsal_id)
                result = transaction.commit(proof, approval_digest)
                host_record['state'] = result['state']
                self.journal.save(host_record)
                return {'ok': True, 'transactionId': transaction_id,
                        'state': result['state'], 'restartRequired': True, 'persistent': False}
            if not physical_confirmation:
                raise InstallerError('PHYSICAL_HOME_CONFIRMATION_REQUIRED', 'Verify Home after the reboot before finalizing.', 8)
            result = transaction.finalize()
            host_record['state'] = result['state']
            self.journal.save(host_record)
            return {'ok': True, 'transactionId': transaction_id, 'state': result['state'],
                    'health': result['health'], 'persistent': True}
        raise InstallerError('HOME_ACTION_INVALID', 'Unknown Home trial operation.', 2)

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
        import json
        from importlib.resources import files
        legacy = json.loads(files('home.operations').joinpath('legacy-recovery.json').read_text())
        if transaction_id == legacy['transactionId']:
            from home.operations.legacy_recovery import restore_legacy
            return restore_legacy(self.transport, transaction_id)
        transaction = self.journal.read(transaction_id)
        if transaction['plan']['mode'] == 'home-replacement':
            return self.home_trial_state(transaction_id, 'restore')
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
