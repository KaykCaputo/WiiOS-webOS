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
        self.operation({'action': 'stage-immutable-payload', 'artifactDigest': self.plan['artifactDigest']})
        if not self.backend.integrity(self.plan):
            raise InstallerError('STAGING_DIGEST_MISMATCH', 'Staged payload integrity failed.', 5)
        self.record['state'] = 'STAGED'
        self.persist()
        return deepcopy(self.record)

    def activate(self):
        if self.record['state'] != 'STAGED':
            raise InstallerError('INVALID_TRANSITION', 'Activation requires a staged transaction.', 5)
        self.backend.preflight(self.plan)
        watchdog = self.operation({'action': 'arm-independent-watchdog',
                                   'seconds': self.plan['trialTimeoutSeconds']})
        if watchdog.get('armed') is not True or watchdog.get('recoverySelfTestPassed') is not True:
            raise InstallerError('WATCHDOG_NOT_PROVEN', 'Independent recovery must be tested before activation.', 3)
        self.record['state'] = 'TRIAL_ACTIVE'
        self.persist()
        try:
            for operation in self.plan['operations']:
                self.operation(operation)
            return deepcopy(self.record)
        except (Exception, KeyboardInterrupt):
            self.restore()
            raise

    def verify(self):
        if self.record['state'] != 'TRIAL_ACTIVE':
            raise InstallerError('INVALID_TRANSITION', 'Verification requires an active trial.', 5)
        health = self.backend.health(self.plan)
        self.record['health'] = health
        if not all(health.get('H' + str(level)) is True for level in range(5)):
            self.restore()
            raise InstallerError('HOME_HEALTH_FAILED', 'Home registration, heartbeat, visibility, or Home-key verification failed.', 5)
        self.record['state'] = 'LIVE_VERIFIED'
        self.persist()
        return deepcopy(self.record)

    def commit(self, restoration_proof, approval_digest):
        if self.record['state'] != 'LIVE_VERIFIED' or approval_digest != self.plan['approvalDigest']:
            raise InstallerError('PERSISTENCE_APPROVAL_REQUIRED', 'Persistence requires approval of a live verified trial.', 8)
        expected = ('deviceProfileDigest', 'artifactDigest', 'adapter')
        if (not restoration_proof or restoration_proof.get('state') != 'RESTORED' or
                restoration_proof.get('stockHomeVerified') is not True or
                restoration_proof.get('transactionId') == self.record['transactionId'] or
                any(restoration_proof.get(key) != self.plan.get(key) for key in expected)):
            raise InstallerError('RESTORATION_REHEARSAL_REQUIRED', 'A separate completed restoration rehearsal is required.', 3)
        self.backend.preflight(self.plan)
        self.operation({'action': 'enable-guarded-boot-hook'})
        self.record['state'] = 'PERSISTENCE_ENABLED'
        self.persist()
        if not self.backend.reboot_verified(self.plan):
            self.restore()
            raise InstallerError('BOOT_NOT_VERIFIED', 'Reboot and physical validation did not pass.', 5)
        self.operation({'action': 'disarm-trial-watchdog'})
        self.record['state'] = 'COMMITTED'
        self.persist()
        return deepcopy(self.record)

    def restore(self):
        if self.record['state'] == 'RESTORED':
            if self.backend.verify_stock(self.plan) is not True:
                raise InstallerError('STOCK_HOME_UNCONFIRMED', 'LG Home has not been verified.', 6)
            return deepcopy(self.record)
        self.record['state'] = 'ROLLING_BACK'
        self.persist()
        try:
            for event in reversed(self.record['events']):
                if event['state'] == 'RESTORED':
                    continue
                self.backend.restore_owned(event, self.record)
                event['state'] = 'RESTORED'
                self.persist()
            if self.backend.verify_stock(self.plan) is not True:
                raise InstallerError('STOCK_HOME_UNCONFIRMED', 'LG Home has not been verified.', 6)
            self.record['state'] = 'RESTORED'
            self.record['stockHomeVerified'] = True
            self.persist()
            return deepcopy(self.record)
        except (Exception, KeyboardInterrupt):
            self.record['state'] = 'MANUAL_RECOVERY_REQUIRED'
            self.persist()
            raise

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
