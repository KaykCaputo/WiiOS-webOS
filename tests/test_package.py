import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wiios_build', ROOT / 'scripts/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PackageTest(unittest.TestCase):
    def test_home_chooser_variant_has_an_opt_in_manifest_and_keeps_the_app_id(self):
        with tempfile.TemporaryDirectory() as dest:
            standard = build.build(output=dest)
            original = standard.read_bytes()
            candidate = build.build(output=dest, home_chooser=True)
            self.assertEqual(candidate.name, standard.name)
            self.assertEqual(candidate.parent, standard.parent / 'home-chooser')
            self.assertEqual(standard.read_bytes(), original)
            source = json.loads((standard.parent / 'app/appinfo.json').read_bytes())
            staged = json.loads((candidate.parent / 'app/appinfo.json').read_bytes())
            self.assertEqual(staged, dict(source, appCategory=['home']))
            flag = 'window.WIIOS_HOME_CHOOSER = true;'
            self.assertIn(flag, (candidate.parent / 'app/audio-assets.js').read_text())
            self.assertNotIn(flag, (standard.parent / 'app/audio-assets.js').read_text())

    def test_build_rejects_an_entrypoint_asset_missing_from_the_package(self):
        files = tuple(name for name in build.FILES if name != 'home-runtime.js')
        with tempfile.TemporaryDirectory() as dest, mock.patch.object(build, 'FILES', files):
            with self.assertRaisesRegex(FileNotFoundError, 'home-runtime.js'):
                build.build(output=dest)

    def test_bundles_app_artwork_code_and_all_sounds(self):
        with tempfile.TemporaryDirectory() as dest:
            package = build.build(output=dest)
            raw = package.read_bytes()
            self.assertTrue(raw.startswith(b'!<arch>\n'))
            offset = 8
            members = {}
            while offset < len(raw):
                header = raw[offset:offset + 60]
                size = int(header[48:58])
                members[header[:16].decode().strip().rstrip('/')] = raw[offset + 60:offset + 60 + size]
                offset += 60 + size + (size % 2)
            with tarfile.open(fileobj=io.BytesIO(members['data.tar.gz']), mode='r:gz') as archive:
                self.assertTrue(all(member.mtime == build.IPK_MTIME > 0 for member in archive.getmembers()))
                names = set(archive.getnames())
                prefix = 'usr/palm/applications/com.wiios.launcher/'
                self.assertIn(prefix + 'home-runtime.js', names)
                self.assertIn(prefix + 'artwork.js', names)
                self.assertEqual(archive.extractfile(prefix + 'assets/static.png').read(),
                                 (ROOT / 'assets/static.png').read_bytes())
                self.assertIn(prefix + 'library.js', names)
                for sound in ('menu', 'hover', 'select', 'back', 'page', 'start'):
                    paths = sorted((ROOT / 'assets/audio').glob(sound + '.*'))
                    self.assertEqual(len(paths), 1)
                    name = 'assets/audio/' + paths[0].name
                    self.assertIn(prefix + name, names)
                    self.assertEqual(archive.extractfile(prefix + name).read(), paths[0].read_bytes())
                app = json.load(archive.extractfile(prefix + 'appinfo.json'))
                self.assertEqual(app['version'], json.loads((ROOT / 'appinfo.json').read_text())['version'])
                self.assertFalse(any('/assets/apps/' in item for item in names))


if __name__ == '__main__':
    unittest.main()
