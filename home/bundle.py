import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

from home.manifest import staged_web_home
from installer.errors import InstallerError


FILE_LIMIT = 26 * 1024 * 1024
BUNDLE_LIMIT = 50 * 1024 * 1024
ASSET_PATTERN = re.compile(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*')


def _inside(directory, name):
    if not isinstance(name, str) or not ASSET_PATTERN.fullmatch(name):
        raise InstallerError('HOME_ASSET_PATH_INVALID', 'The asset path contains unsafe characters.', 3)
    components = PurePosixPath(name).parts
    if any(part in ('', '.', '..') for part in components):
        raise InstallerError('HOME_ASSET_PATH_INVALID', 'The asset path escapes the application.', 3)
    target = directory.joinpath(*components)
    for node in (directory, *[directory.joinpath(*components[:index]) for index in range(1, len(components) + 1)]):
        if node.is_symlink():
            raise InstallerError('HOME_ASSET_SYMLINK', 'Symlinks are not permitted in the Home bundle.', 3)
    return target


def prepare_web_home(source, stock_manifest, expected_sha256, destination):
    source, destination = Path(source), Path(destination)
    if not source.is_dir() or source.is_symlink() or not (source / 'appinfo.json').is_file():
        raise InstallerError('SOURCE_APP_INVALID', 'A complete built WiiOS app directory is required.', 3)
    if destination.exists() or destination.is_symlink():
        raise InstallerError('HOME_BUNDLE_EXISTS', 'The output destination must not exist.', 3)
    candidate = staged_web_home(stock_manifest, expected_sha256)
    appinfo = json.loads((source / 'appinfo.json').read_text())
    if appinfo.get('id') != 'com.wiios.launcher' or not re.fullmatch(r'\d+\.\d+\.\d+', appinfo.get('version', '')):
        raise InstallerError('SOURCE_APP_ID_MISMATCH', 'The input is not a WiiOS release app.', 3)
    files = {}
    size = 0
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source).as_posix()
        _inside(source, relative)
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise InstallerError('HOME_ASSET_TYPE_INVALID', 'The bundle includes an unsupported asset type.', 3)
        if relative == 'appinfo.json':
            continue
        if path.stat().st_size > FILE_LIMIT:
            raise InstallerError('HOME_ASSET_TOO_LARGE', 'A Home asset exceeds its size limit.', 3)
        size += path.stat().st_size
        if size > BUNDLE_LIMIT:
            raise InstallerError('HOME_BUNDLE_TOO_LARGE', 'The complete Home bundle exceeds its size limit.', 3)
        files[relative] = path.read_bytes()
    if 'index.html' not in files or 'app.js' not in files or 'bridge.js' not in files:
        raise InstallerError('HOME_BUNDLE_INCOMPLETE', 'Required WiiOS Home assets are absent.', 3)
    files['appinfo.json'] = candidate['content']
    manifest = {'schemaVersion': 1, 'sourceAppId': 'com.wiios.launcher',
                'sourceVersion': appinfo['version'], 'homeAppId': candidate['appId'],
                'stockManifestSha256': expected_sha256, 'homeManifestSha256': candidate['sha256'],
                'files': {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(files.items())}}
    destination.mkdir(mode=0o700, parents=True)
    try:
        for relative, data in sorted(files.items()):
            target = _inside(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (destination / 'wiios-home-bundle.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        verify_web_home(destination, manifest)
    except BaseException:
        import shutil
        shutil.rmtree(destination)
        raise
    return manifest


def verify_web_home(directory, expected):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or not isinstance(expected, dict):
        raise InstallerError('HOME_BUNDLE_INVALID', 'The staged Home bundle is invalid.', 3)
    actual = {}
    for path in directory.rglob('*'):
        relative = path.relative_to(directory).as_posix()
        _inside(directory, relative)
        if path.is_file():
            if relative == 'wiios-home-bundle.json':
                continue
            actual[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected.get('files') != actual:
        raise InstallerError('HOME_BUNDLE_HASH_MISMATCH', 'Staged Home files differ from the verified bundle.', 8)
    contents = json.loads((directory / 'appinfo.json').read_text())
    if (contents.get('id') != expected.get('homeAppId') or contents.get('type') != 'web' or
            'home' not in contents.get('appCategory', [])):
        raise InstallerError('HOME_ROLE_MISMATCH', 'The staged Home manifest lost its Home identity.', 8)
    return True
