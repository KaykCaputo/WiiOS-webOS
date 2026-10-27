import importlib.util
from pathlib import Path
import tempfile
import unittest

from scripts.check_version import check

try:
    from scripts.check_policy import comments, english_findings
except ImportError:
    comments = None


@unittest.skipIf(comments is None, 'Install requirements-dev.txt to run policy parser tests')
class PolicyTests(unittest.TestCase):
    def test_ht29_python_comments_and_docstrings_rejected(self):
        self.assertTrue(comments('a.py', 'value = 1 # explanation\n'))
        self.assertTrue(comments('a.py', 'def sample():\n    """Documentation."""\n    return 1\n'))
        self.assertFalse(comments('a.py', '#!/usr/bin/env python3\nurl = "https://example.test/#anchor"\n'))

    def test_shell_quoting_is_preserved(self):
        self.assertFalse(comments('a.sh', '#!/bin/sh\nprintf "%s" "#value"\nvalue=${name#prefix}\n'))
        self.assertTrue(comments('a.sh', 'echo value # explanation\n'))

    def test_html_comment_detection(self):
        self.assertTrue(comments('a.html', '<!-- explanation -->'))
        self.assertFalse(comments('a.html', '<a href="https://example.test/">Home</a>'))

    def test_ht30_known_non_english_strings_flagged(self):
        self.assertTrue(english_findings('Open configurações'))
        self.assertFalse(english_findings('Open Settings'))


class VersionTests(unittest.TestCase):
    def test_ht28_mismatched_versions_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'appinfo.json').write_text('{"version":"1.0.0"}')
            (root / 'package.json').write_text('{"version":"0.9.0"}')
            (root / 'package-lock.json').write_text('{"version":"1.0.0","packages":{"":{"version":"1.0.0"}}}')
            with self.assertRaises(ValueError):
                check(root)
