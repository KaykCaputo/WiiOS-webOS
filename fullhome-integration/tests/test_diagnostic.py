import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare', ROOT / 'prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

class Generator(unittest.TestCase):
    @unittest.skipUnless((ROOT.parent / "fullhome-original.tar").is_file(), "Original firmware fixture is not distributed")
    def test_exact_firmware_and_instrumentation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'bundle'
            manifest = prepare.prepare(ROOT.parent / 'fullhome-original.tar', out, 'diag-test01')
            self.assertEqual(manifest['kind'], 'diagnostic-only')
            diff = (out / 'diagnostic.diff').read_text()
            for event in ('main.completed', 'main.appLaunched', 'controller.executeLaunch', 'lifecycle.register'):
                self.assertIn(event, diff)
            for addition in (line for line in diff.splitlines() if line.startswith('+')):
                self.assertNotIn('launchApp(', addition)
                self.assertNotIn('Qt.quit', addition)
            for entry in manifest['files']:
                self.assertEqual(hashlib.sha256((out / entry['name']).read_bytes()).hexdigest(), entry['patched_sha256'])
            for path in out.glob('*.sh'):
                subprocess.run(['sh', '-n', str(path)], check=True)

    def test_corrupt_backup_refused_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, out = Path(tmp) / 'bad.tar', Path(tmp) / 'out'
            with tarfile.open(archive, 'w') as f:
                entry = tarfile.TarInfo('qml/main.qml'); entry.size = 3
                f.addfile(entry, io.BytesIO(b'bad'))
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                prepare.prepare(archive, out)
            self.assertFalse(out.exists())

    def test_token_injection_refused(self):
        with self.assertRaises(ValueError):
            prepare.instrument({}, 'bad;echo nope')

class Rollback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = self.base / 'state'; self.state.mkdir()
        self.mountinfo = self.base / 'mountinfo'
        self.token = 'diag-test01'
        self.original = self.base / 'original'; self.original.write_text('original')
        digest = hashlib.sha256(b'original').hexdigest()
        (self.base / 'config.sh').write_text(f"TOKEN={self.token}\nEXPECTED_BASE={self.base}\nTARGET_1={self.original}\nTARGET_2={self.original}\nORIGINAL_1={digest}\nORIGINAL_2={digest}\n")

        common = (ROOT / 'common.sh').read_text().replace('LOCK=/var/lib/webosbrew/wiios-fullhome-diag/operation-lock', f'LOCK={self.base}/lock').replace('MOUNTINFO=/proc/self/mountinfo', f'MOUNTINFO={self.mountinfo}')
        common += '\nidentity() { printf "45877:9000\\n"; }\n'
        (self.base / 'common.sh').write_text(common)
        (self.base / 'rollback.sh').write_bytes((ROOT / 'rollback.sh').read_bytes())
        (self.state / 'boot-id').write_text(Path('/proc/sys/kernel/random/boot_id').read_text())
        (self.state / 'namespace').write_text(os.readlink('/proc/self/ns/mnt') + '\n')
        (self.state / 'status').write_text('ACTIVE\n')
        self.target = '/tmp/checkpoint/com.webos.app.fullhome'
        self.baseline = '231 29 179:53 /var/lib/webosbrew/wiios-fullhome/no-checkpoint ' + self.target + ' rw,nosuid,relatime - ext4 /dev/mmcblk0p53 rw,data=ordered\n'
        self.own = '400 231 179:53 /var/lib/webosbrew/wiios-fullhome-diag/diag-test01/mask-tmp ' + self.target + ' ro,nosuid,relatime - ext4 /dev/mmcblk0p53 rw,data=ordered\n'
        self.mountinfo.write_text(self.baseline + self.own)
        fields = {'3.target': self.target, '3.source': '/var/lib/webosbrew/wiios-fullhome-diag/diag-test01/mask-tmp', '3.coordinates': '179:53 /var/lib/webosbrew/wiios-fullhome-diag/diag-test01/mask-tmp', '3.inode': '45877:9000', '3.intent': 'ready', '3.before': self.baseline.rstrip(), '3.owned': self.own.rstrip()}
        for name, text in fields.items(): (self.state / name).write_text(text + '\n')
        self.bin = self.base / 'bin'; self.bin.mkdir()

        stub = '#!/usr/bin/env python3\nfrom pathlib import Path\nimport sys\nb=Path(' + repr(str(self.base)) + ')\nwith (b/"calls").open("a") as f: f.write(" ".join(sys.argv[1:])+"\\n")\nif (b/"busy").exists(): sys.exit(32)\np=b/"mountinfo"\np.write_text("".join(x for x in p.read_text().splitlines(True) if not x.startswith("400 ")))\n'
        (self.bin / 'umount').write_text(stub); (self.bin / 'umount').chmod(0o755)

    def run_rollback(self):
        env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'])
        return subprocess.run(['sh', str(self.base / 'rollback.sh'), '--confirm', self.token], env=env, capture_output=True, text=True)

    def assert_refused_without_umount(self):
        result = self.run_rollback()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.base / 'calls').exists(), result.stdout)

    def test_same_device_ext4_baseline_is_preserved(self):
        result = self.run_rollback()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.mountinfo.read_text(), self.baseline)
        self.assertEqual((self.base / 'calls').read_text(), '-n ' + self.target + '\n')
        self.assertEqual(self.run_rollback().returncode, 0)
        self.assertEqual(len((self.base / 'calls').read_text().splitlines()), 1)

    def test_foreign_overmount_refused(self):
        self.mountinfo.write_text(self.baseline + self.own + '401 400 179:53 /foreign ' + self.target + ' rw - ext4 /dev/mmcblk0p53 rw\n')
        self.assert_refused_without_umount()

    def test_foreign_nested_mount_refused(self):
        self.mountinfo.write_text(self.baseline + self.own + '401 400 0:18 / ' + self.target + '/nested rw - tmpfs tmpfs rw\n')
        self.assert_refused_without_umount()

    def test_mount_id_reused_refused(self):
        self.mountinfo.write_text(self.baseline + self.own.replace('400 231', '405 231'))
        self.assert_refused_without_umount()

    def test_reboot_refused(self):
        (self.state / 'boot-id').write_text('other-boot\n')
        self.assert_refused_without_umount()

    def test_namespace_change_refused(self):
        (self.state / 'namespace').write_text('other-namespace\n')
        self.assert_refused_without_umount()

    def test_busy_is_not_forced_or_retried(self):
        (self.base / 'busy').touch()
        result = self.run_rollback()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.base / 'calls').read_text(), '-n ' + self.target + '\n')
        self.assertEqual(self.mountinfo.read_text(), self.baseline + self.own)
        self.assertEqual((self.state / 'status').read_text(), 'ACTIVE\n')

    def test_crash_between_bind_and_journal_recovered_by_unique_source(self):
        (self.state / '3.owned').unlink()
        self.assertEqual(self.run_rollback().returncode, 0)
        self.assertEqual(self.mountinfo.read_text(), self.baseline)

    def test_crash_before_mount_does_not_unmount_baseline(self):
        self.mountinfo.write_text(self.baseline)
        (self.state / '3.owned').unlink()
        self.assertEqual(self.run_rollback().returncode, 0)
        self.assertFalse((self.base / 'calls').exists())

    def test_unknown_mount_does_not_unmount(self):
        self.mountinfo.write_text(self.baseline + self.own.replace('/diag-test01/mask-tmp', '/someone-else/mask-tmp'))
        self.assert_refused_without_umount()

if __name__ == '__main__': unittest.main()
