from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

from scripts.build import build, build_installer
from scripts.prepare_release import build_release


class DistributionTests(unittest.TestCase):
    def test_local_release_replaces_same_version_packages_and_keeps_previous_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            root = Path(__file__).resolve().parents[1]
            version = json.loads((root / 'appinfo.json').read_text())['version']
            current = output / f'com.wiios.launcher_{version}_all.ipk'
            previous = output / 'com.wiios.launcher_0.0.1_all.ipk'
            current.write_bytes(b'stale')
            previous.write_bytes(b'previous')
            with redirect_stdout(io.StringIO()):
                build_release(output, 'KaykCaputo/WiiOS-webOS', 'test-revision')
            manifest = json.loads((output / 'build-manifest.json').read_text())
            self.assertEqual(previous.read_bytes(), b'previous')
            self.assertTrue(current.read_bytes().startswith(b'!<arch>\n'))
            self.assertIn('home-chooser-api/' + current.name, manifest['artifacts'])
            for path, digest in manifest['artifacts'].items():
                self.assertEqual(hashlib.sha256((output / path).read_bytes()).hexdigest(), digest)

    def test_source_archive_without_git_builds_installer_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'WiiOS-webOS'
            root.mkdir()
            source = Path(__file__).resolve().parents[1]
            for folder in ('installer', 'compatibility', 'home', 'assets'):
                shutil.copytree(source / folder, root / folder,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for name in ('appinfo.json', 'package.json', 'package-lock.json', 'index.html',
                         'style.css', 'bridge.js', 'channels.js', 'library.js', 'artwork.js', 'thumbnails.js', 'performance.js',
                         'audio.js', 'stats.js', 'home-chooser.js', 'ssap-provider.js', 'app.js', 'home-runtime.js', 'icon.png', 'LICENSE', 'NOTICE'):
                shutil.copy2(source / name, root / name)
            output = root / 'dist'
            with redirect_stdout(io.StringIO()):
                package = build(root=root, output=output)
                build_installer(root, output, package)
            manifest = json.loads((output / 'build-manifest.json').read_text())
            self.assertIsNone(manifest['wiiOsCommit'])
            self.assertIsNone(manifest['workingTreeDirty'])
            self.assertIn('app.js', manifest['sourceHashes'])
            self.assertNotIn('dist/wiios-installer.pyz', manifest['sourceHashes'])
            self.assertEqual(subprocess.run([sys.executable, str(output / 'wiios-installer.pyz'), '--help'],
                                            capture_output=True, timeout=10).returncode, 0)

    def test_release_is_reproducible_and_installer_runs_outside_checkout(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with redirect_stdout(io.StringIO()):
                package = build(output=first)
                repeated = build(output=second)
            self.assertEqual(package.read_bytes(), repeated.read_bytes())
            installer = Path(first) / 'wiios-installer.pyz'
            self.assertEqual(installer.read_bytes(), (Path(second) / installer.name).read_bytes())
            manifest = json.loads((Path(first) / 'build-manifest.json').read_text())
            self.assertEqual(manifest['artifacts'][package.name], hashlib.sha256(package.read_bytes()).hexdigest())
            self.assertEqual(manifest['artifacts'][installer.name], hashlib.sha256(installer.read_bytes()).hexdigest())
            self.assertEqual(manifest['verifiedProfiles'], [])
            version = json.loads((Path(__file__).resolve().parents[1] / 'appinfo.json').read_text())['version']
            assets = (Path(__file__).resolve().parents[1] / 'audio-assets.js').read_text()
            self.assertIn('window.WIIOS_VERSION = ' + json.dumps(version), assets)
            result = subprocess.run([sys.executable, str(installer), '--help'], cwd=second, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('wiios-installer', result.stdout)
            code = 'import sys; sys.path.insert(0, sys.argv[1]); from compatibility.resolver import load_verified; assert load_verified() == []'
            subprocess.run([sys.executable, '-c', code, str(installer)], cwd=second, check=True, timeout=10)
