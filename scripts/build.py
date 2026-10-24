#!/usr/bin/env python3

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('appinfo.json', 'index.html', 'style.css', 'bridge.js', 'channels.js', 'library.js', 'artwork.js', 'audio.js', 'stats.js', 'app.js', 'icon.png')
SOUNDS = ('menu', 'hover', 'select', 'back', 'page', 'start')

def compressed_tar(files):
    buffer = io.BytesIO()
    directories = set()
    for name in files:
        directories.update(str(p) for p in Path(name).parents if str(p) != '.')
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(directories):
            item = tarfile.TarInfo(name)
            item.type = tarfile.DIRTYPE
            item.mode = 0o755
            archive.addfile(item)
        for name, content in sorted(files.items()):
            item = tarfile.TarInfo(name)
            item.size = len(content)
            item.mode = 0o644
            archive.addfile(item, io.BytesIO(content))
    return gzip.compress(buffer.getvalue(), mtime=0)

def ar_archive(members):
    result = bytearray(b'!<arch>\n')
    for name, data in members:
        header = f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'
        result.extend(header.encode('ascii'))
        result.extend(data)
        if len(data) % 2:
            result.extend(b'\n')
    return bytes(result)

def build(root=ROOT, output=None):
    root = Path(root)
    output = Path(output) if output else root / 'dist'
    info = json.loads((root / 'appinfo.json').read_text())
    if not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)+', info['id']):
        raise ValueError('Invalid application ID')
    if not re.fullmatch(r'\d+\.\d+\.\d+', info['version']):
        raise ValueError('Invalid version')
    missing = [name for name in FILES if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(
            'Required WiiOS project files are missing: ' + ', '.join(missing) +
            '\nExtract the complete ZIP and keep the WiiOS-webOS directory structure.'
        )
    files = {name: (root / name).read_bytes() for name in FILES}
    for path in sorted((root / 'assets').glob('*.svg')):
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    manifest = {}
    for sound in SOUNDS:
        matches = [root / 'assets' / 'audio' / (sound + ext) for ext in ('.wav', '.mp3', '.ogg')]
        matches = [path for path in matches if path.is_file()]
        if len(matches) > 1:
            raise ValueError(f'Multiple files for {sound}; keep one format only')
        if matches:
            path = matches[0]
            limit = (25 if sound == 'menu' else 2) * 1024 * 1024
            if not 0 < path.stat().st_size <= limit:
                raise ValueError(f'{path.name}: empty or larger than {limit} bytes')
            relative = path.relative_to(root).as_posix()
            manifest[sound] = relative
            files[relative] = path.read_bytes()
    files['audio-assets.js'] = ('window.WII_AUDIO_ASSETS = ' + json.dumps(manifest, sort_keys=True) + ';\n').encode()

    (root / 'audio-assets.js').write_bytes(files['audio-assets.js'])
    stage = output / 'app'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name, content in files.items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    app_id, version = info['id'], info['version']
    payload = {f'usr/palm/applications/{app_id}/{name}': content for name, content in files.items()}
    payload[f'usr/palm/packages/{app_id}/packageinfo.json'] = json.dumps({'id': app_id, 'version': version, 'app': app_id}).encode()
    installed_size = sum(len(content) for content in payload.values())
    control = (f'Package: {app_id}\nVersion: {version}\nSection: misc\nPriority: optional\n'
               f'Architecture: all\nInstalled-Size: {installed_size}\nMaintainer: WiiOS Community\n'
               'Description: Wii-style offline launcher for LG webOS TV\n'
               'webOS-Package-Format-Version: 2\nwebOS-Packager-Version: 1.0.0\n')
    package = ar_archive([('debian-binary', b'2.0\n'), ('control.tar.gz', compressed_tar({'control': control.encode()})),
                          ('data.tar.gz', compressed_tar(payload))])
    target = output / f'{app_id}_{version}_all.ipk'
    target.write_bytes(package)
    digest = hashlib.sha256(package).hexdigest()
    target.with_suffix('.ipk.sha256').write_text(f'{digest}  {target.name}\n')
    print(f'IPK: {target} ({len(package):,} bytes)')
    print(f'Preview / ares-package: {stage}')
    print('Audio: ' + (', '.join(manifest) if manifest else 'no files included'))
    return target

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Output directory (default: dist)')
    args = parser.parse_args()
    build(output=args.output)
