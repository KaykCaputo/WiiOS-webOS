import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from compatibility.legacy import BASE, HOOK


RECOVERY_NAMES = ('common.sh', 'rollback.sh', 'config.sh',
                  'disable-startup.sh', HOOK)
RECOVERY_FILES = {
    name: '#!/bin/sh\n# synthetic recovery fixture: ' + name + '\n'
    for name in RECOVERY_NAMES
}


def recovery_metadata():
    return {
        'schemaVersion': 1,
        'transactionId': 'diag-3e891511b377',
        'base': BASE,
        'files': {name: hashlib.sha256(content.encode()).hexdigest()
                  for name, content in RECOVERY_FILES.items()},
    }


def patch_recovery_metadata(testcase, module):
    temporary = tempfile.TemporaryDirectory()
    testcase.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    (root / 'legacy-recovery.json').write_text(json.dumps(recovery_metadata()))
    patched = patch(module + '.files', return_value=root)
    patched.start()
    testcase.addCleanup(patched.stop)
