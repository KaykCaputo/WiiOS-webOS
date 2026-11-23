import unittest

from scripts.release_notes import format_notes, previous_release


class ReleaseNotesTests(unittest.TestCase):
    def test_range_uses_the_previous_published_ancestor(self):
        tags = ['v0.3.2', 'v0.3.9', 'v0.3.10', 'v0.3.11', 'v0.3.12', 'v0.3.14', 'v0.3.13-rc.1']
        ancestors = ['v0.3.2', 'v0.3.9', 'v0.3.10', 'v0.3.12', 'v0.3.13', 'v0.3.14']
        self.assertEqual(previous_release(tags, 'v0.3.12', ancestors), 'v0.3.10')
        self.assertIsNone(previous_release(tags, 'v0.3.2', ancestors))

    def test_direct_commits_and_github_sections_use_the_same_release_body(self):
        notes = "## What's Changed\n\n- New artwork by @contributor\n\n## New Contributors\n\n- @contributor\n\n**Full Changelog**"
        commits = [('a' * 40, 'cache [artwork]'), ('b' * 40, 'Release WiiOS 0.3.41')]
        result = format_notes('owner/project', commits, notes)
        self.assertTrue(result.startswith("## What's Changed\n\n- cache \\[artwork\\]"))
        self.assertLess(result.index('Release WiiOS 0.3.41'), result.index('## Merged Pull Requests'))
        self.assertIn('/commit/' + 'a' * 40, result)
        self.assertIn('## New Contributors', result)
        self.assertIn('**Full Changelog**', result)
        self.assertEqual(result.count("## What's Changed"), 1)
