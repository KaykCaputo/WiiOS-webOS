import os
from pathlib import Path
import subprocess
import sys
import fcntl
import tempfile
import unittest


class OwnedExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / 'transactions' / ('a' * 64)
        self.source = self.base / 'bundle'
        self.target = self.root / 'applications/com.webos.app.home'
        self.source.mkdir(parents=True)
        self.target.mkdir(parents=True)
        self.mountinfo = self.root / 'mountinfo'
        self.baseline = '1 0 8:1 / / rw - ext4 /dev/root rw\n'
        self.mountinfo.write_text(self.baseline)
        (self.root / 'boot').write_text('a-b-c-d\n')
        (self.root / 'namespace').write_text('mnt:[1]')
        (self.root / 'inode').write_text('100:200')
        self.row = '20 1 8:1 ' + str(self.source) + ' ' + str(self.target) + ' rw - ext4 /dev/root rw\n'
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        stub = '''#!/bin/sh
set -eu
root=$FAKE_KERNEL
name=${0##*/}
case "$name" in
    mount)
        ledger="$root/transactions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/mount-a-b-c-d"
        [ "$(cat "$ledger/status")" = BIND_INTENT ]
        printf "%s" "$FAKE_ROW" >> "$root/mountinfo"
        [ "${CRASH_AFTER_BIND:-0}" != 1 ] || exit 1
        ;;
    umount)
        printf "%s" "$1" > "$root/removed"
        awk -v target="$1" '$5 != target {print}' "$root/mountinfo" > "$root/next"
        mv "$root/next" "$root/mountinfo"
        ;;
    readlink) cat "$root/namespace" ;;
    stat) cat "$root/inode" ;;
    sync) : ;;
esac
'''
        for name in ('mount', 'umount', 'stat', 'readlink', 'sync'):
            path = bin_dir / name
            path.write_text(stub)
            path.chmod(0o700)
        script = Path('home/operations/owned_mount.sh').read_text()
        script = script.replace('/var/lib/wiios/home-transactions', str(self.root / 'transactions'))
        script = script.replace('/usr/palm/applications', str(self.root / 'applications'))
        script = script.replace('/proc/self/mountinfo', str(self.mountinfo))
        script = script.replace('/proc/sys/kernel/random/boot_id', str(self.root / 'boot'))
        self.script = self.root / 'executor.sh'
        self.script.write_text(script)
        self.env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
                        FAKE_KERNEL=str(self.root), FAKE_ROW=self.row)

    def run_action(self, action):
        return subprocess.run(['sh', str(self.script), action, str(self.base), str(self.source), str(self.target)],
                              env=self.env, capture_output=True, timeout=5)

    def bind(self):
        result = self.run_action('bind')
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_owned_mount_restores_and_repeated_restore_is_safe(self):
        self.bind()
        self.assertEqual(self.run_action('restore').returncode, 0)
        self.assertEqual(self.mountinfo.read_text(), self.baseline)
        self.assertEqual(self.run_action('restore').returncode, 0)

    def test_substring_foreign_source_is_never_unmounted(self):
        self.bind()
        self.mountinfo.write_text(self.baseline + self.row.replace(str(self.source), str(self.source) + '-foreign'))
        self.assertNotEqual(self.run_action('restore').returncode, 0)
        self.assertFalse((self.root / 'removed').exists())

    def test_nested_mount_is_never_unmounted(self):
        self.bind()
        with self.mountinfo.open('a') as stream:
            stream.write('21 20 8:1 /other ' + str(self.target) + '/nested rw - ext4 /dev/root rw\n')
        self.assertNotEqual(self.run_action('restore').returncode, 0)
        self.assertFalse((self.root / 'removed').exists())

    def test_boot_namespace_inode_and_mount_id_changes_are_rejected(self):
        self.bind()
        for name, value in (('boot', 'b-b-c-d'), ('namespace', 'mnt:[2]'), ('inode', '100:201')):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text()
                path.write_text(value)
                self.assertNotEqual(self.run_action('restore').returncode, 0)
                self.assertFalse((self.root / 'removed').exists())
                path.write_text(original)
        self.mountinfo.write_text(self.baseline + self.row.replace('20 1 ', '30 1 '))
        self.assertNotEqual(self.run_action('restore').returncode, 0)
        self.assertFalse((self.root / 'removed').exists())

    def test_interrupted_bind_recovers_from_durable_intent(self):
        self.env['CRASH_AFTER_BIND'] = '1'
        self.assertNotEqual(self.run_action('bind').returncode, 0)
        self.assertEqual(self.run_action('restore').returncode, 0)
        self.assertEqual(self.mountinfo.read_text(), self.baseline)

    def test_preexisting_partition_is_not_an_owned_bind(self):
        self.mountinfo.write_text(self.baseline + '20 1 179:53 / ' + str(self.target) + ' rw - ext4 /dev/mmcblk0p53 rw\n')
        self.assertNotEqual(self.run_action('restore').returncode, 0)
        self.assertFalse((self.root / 'removed').exists())

    def test_expired_or_disabled_trial_never_binds(self):
        for marker in ('trial-expired', 'boot-disabled'):
            with self.subTest(marker=marker):
                path = self.base / marker
                path.touch()
                self.assertNotEqual(self.run_action('bind').returncode, 0)
                self.assertEqual(self.mountinfo.read_text(), self.baseline)
                path.unlink()

    def test_sigkill_after_bind_releases_lock_for_recovery(self):
        stub = self.root / 'bin' / 'mount'
        stub.write_text(stub.read_text().replace('[ "${CRASH_AFTER_BIND:-0}" != 1 ] || exit 1',
                                                'kill -KILL "$PPID"'))
        self.assertEqual(self.run_action('bind').returncode, -9)
        self.assertIn(self.row, self.mountinfo.read_text())
        self.assertEqual(self.run_action('restore').returncode, 0)
        self.assertEqual(self.mountinfo.read_text(), self.baseline)

    def test_live_operation_lock_cannot_be_stolen(self):
        lock = self.base / 'mount-operation.lock'
        with lock.open('a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            process = subprocess.Popen(['sh', str(self.script), 'bind', str(self.base), str(self.source), str(self.target)],
                                       env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.2)
                self.assertEqual(self.mountinfo.read_text(), self.baseline)
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                self.assertEqual(process.communicate(timeout=5)[1], b'')
                self.assertEqual(process.returncode, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_unowned_legacy_lock_and_symlink_are_preserved(self):
        lock = self.base / 'mount-operation.lock'
        lock.mkdir()
        self.assertNotEqual(self.run_action('bind').returncode, 0)
        self.assertTrue(lock.is_dir())
        lock.rmdir()
        lock.symlink_to(self.root / 'inode')
        self.assertNotEqual(self.run_action('bind').returncode, 0)
        self.assertTrue(lock.is_symlink())
        self.assertEqual(self.mountinfo.read_text(), self.baseline)
