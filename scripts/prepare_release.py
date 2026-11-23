import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo

from installer.application import Artifact


def prepare_release(output, repository, revision):
    build_manifest_path = output / 'build-manifest.json'
    build_manifest = json.loads(build_manifest_path.read_text())
    version = build_manifest['version']
    app_id = 'com.wiios.launcher'
    filename = f'{app_id}_{version}_all.ipk'
    source = output / 'home-chooser' / filename
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    checksum = f'{digest}  {filename}\n'
    if source.with_suffix('.ipk.sha256').read_text() != checksum:
        raise ValueError('Home Chooser IPK checksum mismatch.')

    chooser_appinfo = json.loads((source.parent / 'app' / 'appinfo.json').read_text())
    if (chooser_appinfo.get('id') != app_id or 'home' not in chooser_appinfo.get('appCategory', []) or
            Artifact(source, digest).version != version):
        raise ValueError('The Home Chooser package does not match the release.')

    public_ipk = output / f'{app_id}_{version}_homebrew_all.ipk'
    public_ipk.write_bytes(payload)
    public_ipk.with_suffix('.ipk.sha256').write_text(f'{digest}  {public_ipk.name}\n')

    bundle = output / 'wiios-home-chooser.zip'
    with ZipFile(bundle, 'w') as archive:
        archive.writestr(ZipInfo(filename), payload)
        archive.writestr(ZipInfo(f'{filename}.sha256'), checksum)

    catalog = output / f'{app_id}.homebrew.manifest.json'
    manifest = {
        'id': app_id,
        'version': version,
        'type': 'web',
        'title': 'WiiOS',
        'appDescription': 'A customizable channel launcher for LG webOS TVs.',
        'iconUri': f'https://raw.githubusercontent.com/{repository}/{revision}/icon.png',
        'sourceUrl': f'https://github.com/{repository}',
        'rootRequired': False,
        'ipkUrl': public_ipk.name,
        'ipkHash': {'sha256': digest},
    }
    catalog.write_text(json.dumps(manifest, indent=2) + '\n')
    for artifact in (public_ipk, bundle, catalog):
        build_manifest['artifacts'][artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    build_manifest_path.write_text(json.dumps(build_manifest, sort_keys=True, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepare Home Chooser and Homebrew Channel release assets.')
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--repository', required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    prepare_release(args.output, args.repository, args.revision)
