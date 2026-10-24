import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wiios_build', ROOT / 'scripts/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PackageTest(unittest.TestCase):
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
                names = set(archive.getnames())
                prefix = 'usr/palm/applications/com.wiios.launcher/'
                self.assertIn(prefix + 'artwork.js', names)
                self.assertIn(prefix + 'library.js', names)
                for sound in ('menu', 'hover', 'select', 'back', 'page', 'start'):
                    paths = sorted((ROOT / 'assets/audio').glob(sound + '.*'))
                    self.assertEqual(len(paths), 1)
                    name = 'assets/audio/' + paths[0].name
                    self.assertIn(prefix + name, names)
                    self.assertEqual(archive.extractfile(prefix + name).read(), paths[0].read_bytes())
                app = json.load(archive.extractfile(prefix + 'appinfo.json'))
                self.assertEqual(app['version'], '0.3.30')
                self.assertFalse(any('/assets/apps/' in item for item in names))


if __name__ == '__main__':
    unittest.main()
