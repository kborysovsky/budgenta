"""Create an encrypted pg_dump without writing plaintext to disk."""
import os
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def create_backup(user='budgenta', database='budgenta'):
    values = dotenv_values(ROOT / '.env')
    cipher = Fernet(values['DATA_ENCRYPTION_KEYS'].split(',')[0].strip().encode())
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'pg_dump', '-U', user,
                             '--no-owner', '--no-acl', database], cwd=ROOT, capture_output=True)
    if result.returncode:
        raise SystemExit('Database backup failed. No database output or credentials were printed.')
    folder = ROOT / 'backups'
    folder.mkdir(exist_ok=True, mode=0o700)
    path = folder / ('budgenta-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sql.fernet')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
        output.write(cipher.encrypt(result.stdout))
    print('Encrypted backup saved:', path.relative_to(ROOT))
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', default='budgenta')
    parser.add_argument('--database', default='budgenta')
    args = parser.parse_args()
    create_backup(args.user, args.database)
