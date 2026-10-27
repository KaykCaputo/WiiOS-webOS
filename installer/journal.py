import json
import os
from pathlib import Path
import re
import tempfile

from compatibility.signatures import canonical
from installer.errors import InstallerError


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser()
        if self.directory.is_symlink():
            raise InstallerError('UNSAFE_JOURNAL', 'The journal directory must not be a symlink.', 2)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, transaction_id):
        if not re.fullmatch(r'[a-f0-9]{64}', transaction_id):
            raise InstallerError('INVALID_TRANSACTION', 'Invalid transaction ID.', 2)
        return self.directory / (transaction_id + '.json')

    def save(self, transaction):
        target = self.path(transaction['transactionId'])
        descriptor, name = tempfile.mkstemp(prefix='.pending-', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(canonical(transaction) + b'\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
            if os.name == 'posix':
                directory = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def read(self, transaction_id):
        path = self.path(transaction_id)
        if path.is_symlink() or not path.is_file():
            raise InstallerError('JOURNAL_NOT_FOUND', 'No trustworthy transaction journal was found.', 6)
        value = json.loads(path.read_text())
        if value.get('transactionId') != transaction_id:
            raise InstallerError('JOURNAL_MISMATCH', 'The journal identity does not match.', 6)
        return value

    def pending(self):
        result = []
        for path in sorted(self.directory.glob('*.json')):
            transaction = self.read(path.stem)
            if transaction.get('state') not in ('COMMITTED', 'RESTORED'):
                result.append(transaction)
        return result
