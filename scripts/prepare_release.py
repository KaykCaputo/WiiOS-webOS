import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZipInfo

from installer.application import Artifact
from scripts.build import ROOT, build


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


def build_release(output, repository, revision=None):
    output = Path(output)
    with TemporaryDirectory(prefix='wiios-release-') as directory:
        stage = Path(directory)
        package = build(output=stage)
        chooser = build(output=stage, home_chooser=True)
        chooser_api = build(output=stage, home_chooser_api=True)
        manifest_path = stage / 'build-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        prepare_release(stage, repository, revision or manifest['wiiOsCommit'] or 'master')
        manifest = json.loads(manifest_path.read_text())
        app_id = 'com.wiios.launcher'
        alias = stage / f"{app_id}_{manifest['version']}_home_chooser_all.ipk"
        shutil.copyfile(chooser, alias)
        digest = manifest['artifacts'][f"{app_id}_{manifest['version']}_homebrew_all.ipk"]
        alias.with_suffix('.ipk.sha256').write_text(f'{digest}  {alias.name}\n')
        catalog = stage / f'{app_id}.manifest.json'
        entry = json.loads((stage / f'{app_id}.homebrew.manifest.json').read_text())
        entry['ipkUrl'] = alias.name
        catalog.write_text(json.dumps(entry, indent=2) + '\n')
        manifest['artifacts'].update({
            alias.name: digest,
            catalog.name: hashlib.sha256(catalog.read_bytes()).hexdigest(),
            chooser_api.relative_to(stage).as_posix(): hashlib.sha256(chooser_api.read_bytes()).hexdigest(),
        })
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        files = [file for file in stage.iterdir() if file.is_file() and file != manifest_path]
        files.extend((chooser_api, chooser_api.with_suffix('.ipk.sha256'), manifest_path))
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
