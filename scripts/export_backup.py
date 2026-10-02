"""Export a fresh encrypted snapshot over a restricted SSH connection."""
import contextlib
import hashlib
import io
import json
import os
import sys
from backup_database import create_backup


def main():
    # Use as an authorized_keys forced command; never execute client input.
    if os.getenv('SSH_ORIGINAL_COMMAND') != 'backup':
        raise SystemExit('Only the backup export command is permitted.')
    with contextlib.redirect_stdout(io.StringIO()):
        path = create_backup()
    payload = path.read_bytes()
    header = {'name': path.name, 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    sys.stdout.buffer.write(json.dumps(header).encode() + b'\n' + payload)
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Backup export failed; no database contents or credentials were printed.') from None
