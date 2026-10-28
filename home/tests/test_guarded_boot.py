import subprocess
import hashlib
import os
import tempfile
import json
from pathlib import Path
from compatibility.tests.fixtures import profile
import unittest

from home.operations.guarded_boot import build_boot_hook
from installer.errors import InstallerError


class GuardedBootTests(unittest.TestCase):
    def setup_hook(self):
        transaction = 'a' * 64
        return build_boot_hook(transaction, '/usr/palm/applications/com.webos.app.home',
                               '/var/lib/wiios/home-transactions/' + transaction + '/bundle',
                               'b' * 64, 'c' * 64, 'com.webos.app.home',
                               file_hashes={'index.html': 'd' * 64, 'appinfo.json': 'c' * 64},
                               profile=profile(), sam_protocol='sam-block-release-v1')

    def test_scripts_are_syntax_valid_and_fail_closed(self):
        artifact = self.setup_hook()
        self.assertIn('boot-enabled', artifact['script'])
        self.assertIn('boot-disabled', artifact['script'])
        self.assertIn('index.html', artifact['script'])
        self.assertIn('boot-failures', artifact['script'])
        self.assertIn('restore.sh', artifact['healthScript'])
        for item in ('script', 'healthScript'):
            subprocess.run(['sh', '-n'], input=artifact[item], text=True, check=True)

    def test_untrusted_identity_and_paths_fail(self):
        with self.assertRaises(InstallerError):
            build_boot_hook('a' * 64, '/etc/shadow',
                            '/var/lib/wiios/home-transactions/' + 'a' * 64 + '/bundle',
                            'b' * 64, 'c' * 64, 'com.webos.app.home',
                            file_hashes={'index.html': 'd' * 64})
        with self.assertRaises(InstallerError):
            build_boot_hook('a' * 64, '/usr/palm/applications/com.webos.app.homeevil',
                            '/var/lib/wiios/home-transactions/' + 'a' * 64 + '/bundle',
                            'b' * 64, 'c' * 64, 'com.webos.app.home',
                            file_hashes={'index.html': 'd' * 64})
        with self.assertRaises(InstallerError):
            build_boot_hook('a' * 64, '/usr/palm/applications/com.webos.app.home',
                            '/var/lib/wiios/home-transactions/' + 'a' * 64 + '/bundle',
                            'b' * 64, 'c' * 64, 'com.webos.app.home',
                            file_hashes={'../../evil': 'd' * 64})

    def test_script_identity_and_integrity_are_reproducible(self):
        self.assertEqual(self.setup_hook(), self.setup_hook())

    def test_monitor_keeps_background_home_and_recovers_visible_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            artifact = self.setup_hook()
            (base / 'boot-enabled').touch()
            (base / 'owned-mount.sh').write_text('#!/bin/sh\nexit 0\n')
            (base / 'restore.sh').write_text('#!/bin/sh\ntouch "' + str(base / 'restored') + '"\n')
            binary = base / 'bin'
            binary.mkdir()
            checks = {'owned-mount.sh': Path('home/operations/owned_mount.sh').read_bytes(),
                      'heartbeat.js': Path('home/operations/heartbeat.js').read_bytes(),
                      'boot-runtime.js': artifact['runtimeScript'], 'boot-profile.json': artifact['profileData']}
            hashes = '#!/bin/sh\ncase "${1##*/}" in\n'
            for name, content in checks.items():
                hashes += name + ') echo "' + hashlib.sha256(content).hexdigest() + '  $1" ;;\n'
            hashes += '*) exit 1 ;;\nesac\n'
            (binary / 'sha256sum').write_text(hashes)
            (binary / 'sleep').write_text('#!/bin/sh\nexit 0\n')
            (binary / 'node').write_text("""#!/bin/sh
set -eu
count=$(cat "$TEST_BASE/count" 2>/dev/null || echo 0)
count=$((count + 1))
echo "$count" > "$TEST_BASE/count"
case "$count" in
    1) state=HOME_SUSPENDED ;;
    2) state=HOME_RESUMING ;;
    3) state=HOME_VISIBLE ;;
    *) exit 1 ;;
esac
[ ! -e "$TEST_BASE/restored" ]
echo "$state" >> "$TEST_BASE/states"
printf '{"state":"%s"}\n' "$state"
""")
            for tool in binary.iterdir():
                tool.chmod(0o700)
            script = artifact['healthScript'].replace('/var/lib/wiios/home-transactions/' + 'a' * 64, temporary)
            result = subprocess.run(['sh'], input=script, text=True, capture_output=True,
                                    env=dict(os.environ, TEST_BASE=temporary,
                                             PATH=str(binary) + os.pathsep + os.environ['PATH']), timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual((base / 'states').read_text().splitlines(),
                             ['HOME_SUSPENDED', 'HOME_RESUMING', 'HOME_VISIBLE'])
            self.assertTrue((base / 'boot-disabled').exists())
            self.assertTrue((base / 'restored').exists())
