import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from installer.application import Artifact
from scripts.build import ROOT, build


def prepare_release(output, repository, revision):
    build_manifest_path = output / 'build-manifest.json'
    build_manifest = json.loads(build_manifest_path.read_text())
    version = build_manifest['version']
    app_id = 'com.wiios.launcher'
    filename = f'{app_id}_{version}_all.ipk'
    source = output / filename
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if (source.with_suffix('.ipk.sha256').read_text() != f'{digest}  {filename}\n' or
            build_manifest['artifacts'][filename] != digest):
        raise ValueError('WiiOS IPK checksum mismatch.')
    appinfo = json.loads((output / 'app' / 'appinfo.json').read_text())
    if 'home' not in appinfo.get('appCategory', []) or Artifact(source, digest).version != version:
        raise ValueError('The WiiOS IPK does not match the release.')

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
        'ipkUrl': filename,
        'ipkHash': {'sha256': digest},
    }
    alias = output / f'{app_id}.manifest.json'
    for artifact in (catalog, alias):
        artifact.write_text(json.dumps(manifest, indent=2) + '\n')
        build_manifest['artifacts'][artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    build_manifest_path.write_text(json.dumps(build_manifest, sort_keys=True, indent=2) + '\n')


def build_release(output, repository, revision=None):
    output = Path(output)
    with TemporaryDirectory(prefix='wiios-release-') as directory:
        stage = Path(directory)
        package = build(output=stage)
        manifest_path = stage / 'build-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        prepare_release(stage, repository, revision or manifest['wiiOsCommit'] or 'master')
        files = [file for file in stage.iterdir() if file.is_file() and file != manifest_path]
        files.append(manifest_path)
        output.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.refresh-', dir=output) as pending:
            for file in files:
                target = Path(pending) / file.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
            for file in files:
                relative = file.relative_to(stage)
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                (Path(pending) / relative).replace(target)
        print(f'Release: {output.resolve()} ({package.name})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Prepare Home Chooser and Homebrew Channel release assets.')
    parser.add_argument('--build', action='store_true', help='Build and refresh the complete local release.')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repository', default='KaykCaputo/WiiOS-webOS')
    parser.add_argument('--revision')
    args = parser.parse_args()
    if args.build:
        build_release(args.output or ROOT / 'release', args.repository, args.revision)
    else:
        if not args.revision:
            parser.error('--revision is required when preparing existing packages.')
        prepare_release(args.output or Path('dist'), args.repository, args.revision)
