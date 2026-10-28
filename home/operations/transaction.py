from copy import deepcopy

from installer.errors import InstallerError


class HomeTransaction:
    def __init__(self, plan, backend):
        self.plan, self.backend = deepcopy(plan), backend
        self.prior_restoration_proof = None
        self.record = {'schemaVersion': 1, 'transactionId': plan['transactionId'], 'plan': deepcopy(plan),
                       'state': 'PLAN_APPROVED', 'events': [], 'ownership': [], 'health': {}}

    def persist(self):
        self.backend.write_device_journal(deepcopy(self.record))

    def operation(self, operation):
        event = {'operation': deepcopy(operation), 'state': 'INTENT'}
        self.record['events'].append(event)
        self.persist()
        receipt = self.backend.execute(operation)
        event.update(state='APPLIED', receipt=receipt)
        self.persist()
        return receipt

    def stage(self):
        if self.record['state'] != 'PLAN_APPROVED':
            raise InstallerError('INVALID_TRANSITION', 'Only a new approved transaction can be staged.', 5)
        self.backend.preflight(self.plan)
        self.persist()
        try:
            self.operation({'action': 'stage-immutable-payload', 'artifactDigest': self.plan['artifactDigest']})
            if not self.backend.integrity(self.plan):
                raise InstallerError('STAGING_DIGEST_MISMATCH', 'Staged payload integrity failed.', 5)
            self.record['state'] = 'STAGED'
            self.persist()
            return deepcopy(self.record)
        except (Exception, KeyboardInterrupt):
            self.restore()
            raise

    def activate(self):
        if self.record['state'] != 'STAGED':
            raise InstallerError('INVALID_TRANSITION', 'Activation requires a staged transaction.', 5)
        self.backend.preflight(self.plan)
        try:
            watchdog = self.operation({'action': 'arm-independent-watchdog',
                                       'seconds': self.plan['trialTimeoutSeconds']})
            if watchdog.get('armed') is not True or watchdog.get('recoverySelfTestPassed') is not True:
                raise InstallerError('WATCHDOG_NOT_PROVEN', 'Independent recovery must be tested before activation.', 3)
            self.record['state'] = 'TRIAL_ACTIVE'
            self.persist()
            for operation in self.plan['operations']:
                self.operation(operation)
            return deepcopy(self.record)
        except (Exception, KeyboardInterrupt):
            self.restore()
            raise

    def verify(self):
        if self.record['state'] != 'TRIAL_ACTIVE':
            raise InstallerError('INVALID_TRANSITION', 'Verification requires an active trial.', 5)
        try:
            health = self.backend.health(self.plan)
            self.record['health'] = health
            if not all(health.get('H' + str(level)) is True for level in range(5)):
                raise InstallerError('HOME_HEALTH_FAILED', 'Home registration, heartbeat, visibility, or Home-key verification failed.', 5)
            self.record['state'] = 'LIVE_VERIFIED'
            self.persist()
            return deepcopy(self.record)
        except (Exception, KeyboardInterrupt):
            self.restore()
            raise

    def commit(self, restoration_proof, approval_digest):
        if self.record['state'] != 'LIVE_VERIFIED' or approval_digest != self.plan['approvalDigest']:
            raise InstallerError('PERSISTENCE_APPROVAL_REQUIRED', 'Persistence requires approval of a live verified trial.', 8)
        expected = ('deviceProfileDigest', 'artifactDigest', 'adapter')
        if (not restoration_proof or restoration_proof.get('state') != 'RESTORED' or
                restoration_proof.get('stockHomeVerified') is not True or
                restoration_proof.get('transactionId') == self.record['transactionId'] or
                any(restoration_proof.get(key) != self.plan.get(key) for key in expected)):
            raise InstallerError('RESTORATION_REHEARSAL_REQUIRED', 'A separate completed restoration rehearsal is required.', 3)
        self.backend.preflight_persistence(self.plan, self.record)
        try:
            self.record['bootIdBeforePersistence'] = self.backend.reboot_identity()
            self.record['restorationProof'] = deepcopy(restoration_proof)
            self.persist()
            self.operation({'action': 'enable-guarded-boot-hook'})
            self.record['state'] = 'PERSISTENCE_PENDING'
            self.persist()
            return deepcopy(self.record)
        except (Exception, KeyboardInterrupt):
            self.restore()
            raise

    def finalize(self):
        if self.record['state'] != 'PERSISTENCE_PENDING':
            raise InstallerError('BOOT_VERIFICATION_NOT_PENDING', 'No guarded Home boot is awaiting qualification.', 8)
        if self.backend.reboot_identity() == self.record.get('bootIdBeforePersistence'):
            raise InstallerError('BOOT_NOT_RESTARTED', 'Restart the TV and validate Home before finalizing.', 3)
        try:
            health = self.backend.health(self.plan)
            self.record['health'] = health
            if not all(health.get('H' + str(level)) is True for level in range(5)):
                raise InstallerError('BOOT_HEALTH_FAILED', 'The first guarded boot did not pass all health checks.', 5)
            self.operation({'action': 'disarm-trial-watchdog'})
            self.record['state'] = 'COMMITTED'
            self.persist()
            return deepcopy(self.record)
        except (Exception, KeyboardInterrupt):
            self.restore()
            raise

    def restore(self):
        if self.record['state'] in ('RESTORED', 'STOCK_FILES_RESTORED'):
            return self.verify_restoration()
        self.record['state'] = 'ROLLING_BACK'
        self.persist()
        try:
            for event in reversed(self.record['events']):
                if event['state'] == 'RESTORED':
                    continue
                self.backend.restore_owned(event, self.record)
                event['state'] = 'RESTORED'
                self.persist()
            return self.verify_restoration()
        except (Exception, KeyboardInterrupt):
            self.record['state'] = 'MANUAL_RECOVERY_REQUIRED'
            self.persist()
            raise

    def verify_restoration(self):
        if self.backend.verify_stock_files(self.plan) is not True:
            raise InstallerError('STOCK_FILES_UNCONFIRMED', 'Original LG files and mounts have not been verified.', 6)
        verified = self.backend.verify_stock(self.plan) is True
        self.record['stockFilesRestored'] = True
        self.record['stockHomeVerified'] = verified
        self.record['state'] = 'RESTORED' if verified else 'STOCK_FILES_RESTORED'
        self.persist()
        return deepcopy(self.record)

    def recover(self, record):
        if record['transactionId'] != self.plan['transactionId'] or record['plan'] != self.plan:
            raise InstallerError('JOURNAL_MISMATCH', 'The device journal does not match this transaction.', 6)
        self.record = deepcopy(record)
        self.backend.verify_recovery_identity(self.record)
        return self.restore()

    def restoration_proof(self):
        if self.record['state'] != 'RESTORED' or not self.record.get('stockHomeVerified'):
            raise InstallerError('RESTORATION_NOT_VERIFIED', 'No completed restoration rehearsal exists.', 6)
        return dict({key: self.plan[key] for key in ('deviceProfileDigest', 'artifactDigest', 'adapter')},
                    state='RESTORED', stockHomeVerified=True, transactionId=self.record['transactionId'])
