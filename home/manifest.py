import hashlib
import json
import re

from installer.errors import InstallerError


HOME_IDS = ('com.webos.app.home', 'com.webos.app.fullhome')


def staged_web_home(stock_manifest, expected_digest, entry_html='index.html'):
    if not isinstance(stock_manifest, bytes) or len(stock_manifest) > 16384:
        raise InstallerError('STOCK_HOME_MANIFEST_INVALID', 'The original Home manifest is missing or oversized.', 3)
    if not re.fullmatch(r'[a-f0-9]{64}', expected_digest or ''):
        raise InstallerError('STOCK_HOME_HASH_REQUIRED', 'An exact stock Home manifest fingerprint is required.', 3)
    if hashlib.sha256(stock_manifest).hexdigest() != expected_digest:
        raise InstallerError('STOCK_HOME_HASH_MISMATCH', 'The Home manifest differs from the approved source.', 8)
    try:
        manifest = json.loads(stock_manifest)
    except (UnicodeError, ValueError) as error:
        raise InstallerError('STOCK_HOME_MANIFEST_INVALID', 'The stock Home manifest is not valid JSON.', 3) from error
    if (not isinstance(manifest, dict) or manifest.get('id') not in HOME_IDS or
            manifest.get('type') not in ('native', 'web', 'flutter') or
            not isinstance(manifest.get('appCategory'), list) or 'home' not in manifest['appCategory'] or
            any(not isinstance(item, str) or len(item) > 64 for item in manifest['appCategory'])):
        raise InstallerError('STOCK_HOME_ROLE_MISMATCH', 'The stock application must be an identified Home.', 3)
    if not isinstance(entry_html, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.html', entry_html):
        raise InstallerError('HOME_ENTRYPOINT_INVALID', 'The staged web entrypoint is invalid.', 3)
    overlay = dict(manifest)
    overlay.update(type='web', main=entry_html, visible=False)
    overlay['appCategory'] = list(dict.fromkeys(manifest['appCategory']))
    if 'home' not in overlay['appCategory']:
        raise InstallerError('HOME_CATEGORY_MISSING', 'The Home category must be retained.', 3)
    payload = (json.dumps(overlay, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode()
    return {'content': payload, 'sha256': hashlib.sha256(payload).hexdigest(),
            'appId': overlay['id'], 'type': 'web', 'appCategory': overlay['appCategory']}
