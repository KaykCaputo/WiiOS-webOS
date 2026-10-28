from copy import deepcopy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from compatibility.resolver import resolve
from compatibility.tests.fixtures import entry, profile
from home.adapters.native_standin import NativeHomeStandin
from installer.errors import InstallerError
from installer.install_engine import InstallEngine
from installer.journal import Journal


class FakePackage:
    version = '0.3.35'
    digest = 'c' * 64


class QualifiedPlanningTests(unittest.TestCase):
    def setUp(self):
        self.device = profile()
        self.device['recovery']['independentTestPassed'] = True
        self.rule = entry(self.device)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        conn = SimpleNamespace(endpoint=self.device['transport']['endpoint'])
        self.engine = InstallEngine(SimpleNamespace(connection=conn, kind='root-ssh'),
            Journal(self.tmp.name), FakePackage(), probe_device=lambda _: deepcopy(self.device),
            application=Mock())

    def test_home_trial_plan_requires_exact_qualification(self):
        def qualified(device, artifact_digest=None):
            return resolve(device, [self.rule], artifact_digest)
        with patch('installer.install_engine.resolve', side_effect=qualified):
            plan = self.engine.plan(mode='home')
        self.assertEqual(plan['mode'], 'home-replacement')
        self.assertEqual(plan['profileId'], self.rule['profileId'])
        self.assertEqual(plan['artifactDigest'], self.engine.artifact.digest)
        self.assertTrue(plan['requiresInteractiveApproval'])
        self.assertEqual(plan['adapter'], 'qml-redirect')
        self.assertEqual(len(plan['operations']), 2)
        with self.assertRaises(InstallerError) as raised:
            self.engine.apply(plan, plan['approvalDigest'])
        self.assertEqual(raised.exception.code, 'HOME_NOT_RELEASE_QUALIFIED')
        self.engine.application.install.assert_not_called()

    def test_planning_fails_after_firmware_change(self):
        def qualified(device, artifact_digest=None):
            return resolve(device, [self.rule], artifact_digest)
        self.device['identity']['firmware'] = 'CHANGED'
        with patch('installer.install_engine.resolve', side_effect=qualified):
            with self.assertRaises(InstallerError):
                self.engine.plan(mode='home')

    def test_native_requires_explicit_entrypoint_and_digest(self):
        device = profile()
        device['home'].update(appId='com.webos.app.home', implementation='native',
            effectiveDirectory='/usr/palm/applications/com.webos.app.home')
        device['capabilities'].update(nativeHomeLifecycle='available', webAppManager='available')
        with self.assertRaises(InstallerError):
            NativeHomeStandin().build_plan(device)
        device['home'].update(nativeEntrypoint='/usr/palm/applications/com.webos.app.home/bin/home',
            nativeEntrypointSha256='e' * 64)
        planned = NativeHomeStandin().build_plan(device)
        self.assertEqual(planned['operations'][0]['action'], 'verify-native-entrypoint')
        self.assertTrue(planned['requiresRoot'])

    def test_native_qualification_rule_cannot_omit_entrypoint_digest(self):
        device = profile()
        device['home'].update(appId='com.webos.app.home', implementation='native',
            effectiveDirectory='/usr/palm/applications/com.webos.app.home',
            nativeEntrypoint='/usr/palm/applications/com.webos.app.home/bin/home',
            nativeEntrypointSha256='e' * 64)
        device['capabilities'].update(nativeHomeLifecycle='available', webAppManager='available')
        device['recovery']['independentTestPassed'] = True
        rule = entry(device)
        rule['home']['appId'] = 'com.webos.app.home'
        rule['home']['implementation'] = 'native'
        rule['home']['effectiveDirectory'] = '/usr/palm/applications/com.webos.app.home'
        rule['homeReplacement']['adapter'] = 'native-home-standin'
        self.assertNotEqual(resolve(device, [rule], 'c' * 64)['homeStatus'], 'HOME_ELIGIBLE')
        rule['home']['nativeEntrypoint'] = device['home']['nativeEntrypoint']
        rule['home']['nativeEntrypointSha256'] = device['home']['nativeEntrypointSha256']
        rule['homeReplacement']['nativeContract'] = 'register-native-app-v1'
        rule['homeReplacement']['wamLaunchSha256'] = 'f' * 64
        self.assertEqual(resolve(device, [rule], 'c' * 64)['homeStatus'], 'HOME_ELIGIBLE')
