import hashlib
from importlib.resources import files
import json
import shlex

from installer.errors import InstallerError


def restore_legacy(transport, transaction_id):
    metadata = json.loads(files('home.operations').joinpath('legacy-recovery.json').read_text())
    if transaction_id != metadata['transactionId']:
        raise InstallerError('LEGACY_TRANSACTION_UNKNOWN', 'The legacy transaction is not recognized.', 6)
    if transport.kind != 'root-ssh' or transport.execute('id -u').strip() != '0':
        raise InstallerError('ROOT_RECOVERY_REQUIRED', 'Legacy Home recovery requires authorized Root SSH.', 3)
    base = metadata['base']
    for name, expected in metadata['files'].items():
        content = transport.read(base + '/' + name)
        if hashlib.sha256(content.encode()).hexdigest() != expected:
            raise InstallerError('RECOVERY_SCRIPT_MISMATCH', 'The existing recovery files differ from the reviewed bundle.', 6)
    status = transport.read(base + '/state/status').strip()
    if status not in ('ACTIVE', 'RESTORED'):
        raise InstallerError('LEGACY_STATE_UNKNOWN', 'Inspect the incomplete legacy journal before recovery.', 6)
    transport.execute('sh ' + shlex.quote(base + '/disable-startup.sh'))
    transport.execute('sh ' + shlex.quote(base + '/rollback.sh') + ' --confirm ' + shlex.quote(transaction_id), timeout=30)
    if transport.read(base + '/state/status').strip() != 'RESTORED':
        raise InstallerError('RECOVERY_INCOMPLETE', 'The existing rollback did not confirm restored files.', 6)
    return {'ok': True, 'state': 'LG_HOME_FILES_RESTORED', 'transactionId': transaction_id,
            'homeConfirmed': False, 'reasonCode': 'PHYSICAL_LG_HOME_CHECK_REQUIRED',
            'message': 'Original QML and baseline mounts were checked by the legacy rollback. Verify LG Home on the TV.'}
