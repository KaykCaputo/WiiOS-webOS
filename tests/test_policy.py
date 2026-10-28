import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from scripts.check_policy import english_findings
from scripts.check_version import check


class PolicyTests(unittest.TestCase):
    def test_ht30_known_non_english_strings_flagged(self):
        self.assertTrue(english_findings('Open configurações'))
        self.assertFalse(english_findings('Open Settings'))

    def test_proprietary_qml_paths_are_forbidden_and_absent(self):
        root = Path(__file__).resolve().parents[1]
        policy = json.loads((root / 'source-policy.json').read_text())
        for name in ('fullhome-integration/bundle/main.qml',
                     'fullhome-integration/bundle/UIController.qml'):
            self.assertIn(name, policy['forbiddenFiles'])
            self.assertFalse((root / name).exists())
        self.assertIn('.qml', policy['forbiddenExtensions'])


class VersionTests(unittest.TestCase):
    def test_ht28_mismatched_versions_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'appinfo.json').write_text('{"version":"1.0.0"}')
            (root / 'package.json').write_text('{"version":"0.9.0"}')
            (root / 'package-lock.json').write_text('{"version":"1.0.0","packages":{"":{"version":"1.0.0"}}}')
            with self.assertRaises(ValueError):
                check(root)
