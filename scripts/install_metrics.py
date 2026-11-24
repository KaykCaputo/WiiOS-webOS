#!/usr/bin/env python3
import argparse
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from installer.errors import InstallerError
from installer.helper import deploy_helper


def main():
    parser = argparse.ArgumentParser(description='Install or update the local WiiOS app/images and metrics helper over root SSH.')
    parser.add_argument('--host', required=True, help='Target TV hostname or IPv4 address')
    parser.add_argument('--remove', action='store_true', help='Stop this collector and remove its own startup hook')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', args.host):
        parser.error('Invalid hostname')
    def remote(command, data=None, timeout=20):
        result = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5', 'root@' + args.host, command], input=data, capture_output=True, timeout=timeout)
        if result.returncode:
            raise SystemExit((result.stdout + result.stderr).decode(errors='replace'))
        return result.stdout.decode(errors='replace')
    try:
        result = deploy_helper(remote, remove=args.remove)
    except InstallerError as error:
        raise SystemExit(str(error)) from error
    if args.remove:
        print('Owned startup hook removed; files and logs kept for inspection.')
    else:
        print('WiiOS TV helper installed; active helper fingerprints verified.')
        if 'imageApps' in result:
            print('Apps with image candidates: ' + str(result['imageApps']))

if __name__ == '__main__':
    main()
