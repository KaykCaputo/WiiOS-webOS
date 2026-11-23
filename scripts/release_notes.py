import argparse
import json
import re
import subprocess


RELEASE_TAG = re.compile(r'v(\d+)\.(\d+)\.(\d+)\Z')
CHANGES_HEADING = re.compile(r"^## What's Changed[ \t]*$", re.MULTILINE)
MARKDOWN_CHARACTERS = re.compile(r'([\\`*_\[\]<>])')


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def previous_release(tags, tag, ancestors):
    version = tuple(map(int, RELEASE_TAG.fullmatch(tag).groups()))
    candidates = {}
    for candidate in set(tags).intersection(ancestors):
        match = RELEASE_TAG.fullmatch(candidate)
        if match:
            candidates[candidate] = tuple(map(int, match.groups()))
    return max((name for name, value in candidates.items() if value < version),
               default=None, key=candidates.get)


def format_notes(repository, commits, generated):
    entries = []
    for sha, subject in commits:
        label = MARKDOWN_CHARACTERS.sub(r'\\\1', subject) or '(no subject)'
        entries.append(f'- {label} ([{sha[:7]}](https://github.com/{repository}/commit/{sha}))')
    history = '\n'.join(entries) if entries else 'No new commits.'
    native = CHANGES_HEADING.sub('## Merged Pull Requests', generated.strip(), count=1)
    return f"## What's Changed\n\n{history}\n\n{native}\n"


def release_notes(repository, tag, target):
    releases = f'repos/{repository}/releases'
    published_tags = command('gh', 'api', '--paginate', releases,
                             '--jq', '.[] | select(.draft == false and .prerelease == false) | .tag_name').splitlines()
    ancestors = command('git', 'tag', '--merged', target).splitlines()
    previous = previous_release(published_tags, tag, ancestors)
    revision = f'{previous}..{target}' if previous else target
    history = command('git', 'log', '--reverse', '--topo-order', '--format=%H%x09%s', revision)
    commits = [line.partition('\t')[::2] for line in history.splitlines()]
    args = ['gh', 'api', '--method', 'POST', f'{releases}/generate-notes',
            '-f', f'tag_name={tag}', '-f', f'target_commitish={target}']
    if previous:
        args.extend(('-f', f'previous_tag_name={previous}'))
    generated = json.loads(command(*args))
    return format_notes(repository, commits, generated['body'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate GitHub release notes with a complete commit list.')
    parser.add_argument('repository')
    parser.add_argument('tag')
    parser.add_argument('target')
    args = parser.parse_args()
    if not RELEASE_TAG.fullmatch(args.tag):
        parser.error('Expected a release tag in vMAJOR.MINOR.PATCH format.')
    print(release_notes(args.repository, args.tag, args.target), end='')
