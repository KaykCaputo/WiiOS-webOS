import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    version = json.loads((root / 'appinfo.json').read_text())['version']
    package = json.loads((root / 'package.json').read_text())
    lock = json.loads((root / 'package-lock.json').read_text())
    if package['version'] != version or lock['version'] != version or lock['packages']['']['version'] != version:
        raise ValueError('Version mismatch: appinfo.json is the version source. Run scripts/sync_version.py.')
    return version


if __name__ == '__main__':
    print('Version: ' + check())
