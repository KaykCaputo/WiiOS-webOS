from compatibility.resolver import resolve
from compatibility.signatures import digest, profile_digest
from installer.errors import InstallerError
from installer.plan import seal_plan


class HomeAdapter:
    adapter_id = ''
    version = '1'

    def evaluate(self, profile):
        return resolve(profile)

    def build_plan(self, profile):
        raise InstallerError('HOME_PROFILE_REQUIRED', 'A qualified adapter profile is required.', 3)

    def plan_operations(self, profile, operations):
        return seal_plan({'schemaVersion': 1, 'deviceProfileDigest': profile_digest(profile),
            'mode': 'home-replacement', 'action': 'install', 'adapter': self.adapter_id,
            'artifactDigest': digest(operations), 'version': self.version,
            'operations': operations, 'reverseOperations': [dict(item, action='restore-owned-' + item['action']) for item in reversed(operations)],
            'expectedMounts': [], 'expectedHomeManifestDigest': profile['home']['effectiveManifestSha256'],
            'trialTimeoutSeconds': 180, 'requiresRoot': True, 'requiresInteractiveApproval': True, 'profileId': None})

    def stage(self, plan, context):
        self.check_context(plan, context)
        return context.stage()

    def activate(self, plan, context):
        self.check_context(plan, context)
        return context.activate()

    def verify(self, plan, context):
        self.check_context(plan, context)
        return context.verify()

    def commit(self, plan, context):
        self.check_context(plan, context)
        return context.commit(context.prior_restoration_proof, plan['approvalDigest'])

    def check_context(self, plan, context):
        if plan != context.plan or plan['adapter'] != self.adapter_id:
            raise InstallerError('ADAPTER_PLAN_MISMATCH', 'The adapter transaction does not match the approved plan.', 8)

    def restore(self, transaction, context):
        return context.recover(transaction)

    def recover(self, transaction, context):
        return context.recover(transaction)
