"""Fetch and authenticate an encrypted VPS snapshot; never write plaintext SQL."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def verify_export(data, cipher):
    header, separator, encrypted = data.partition(b'\n')
    if not separator or len(header) > 1024:
        raise ValueError('Invalid backup export header.')
    metadata = json.loads(header)
    if not isinstance(metadata, dict):
        raise ValueError('Invalid backup metadata.')
    name = metadata.get('name', '')
    if not isinstance(name, str) or not re.fullmatch(r'budgenta-\d{8}T\d{12}Z\.sql\.fernet', name):
        raise ValueError('Invalid backup filename.')
    digest = hashlib.sha256(encrypted).hexdigest()
    if metadata.get('size') != len(encrypted) or metadata.get('sha256') != digest:
        raise ValueError('Backup size or checksum verification failed.')
    # Authentication proves the download is complete and usable with retained
    # application keys. The decrypted dump exists in memory only.
    dump = cipher.decrypt(encrypted)
    if b'-- PostgreSQL database dump' not in dump[:1024]:
        raise ValueError('Backup does not contain a PostgreSQL dump.')
    return name.replace('budgenta-', 'budgenta-vps-', 1), encrypted, digest


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.budgenta-download-', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def pull(host, identity_file, *, output=None, env_file=None):
    output = Path(output or ROOT / 'backups')
    values = dotenv_values(env_file or ROOT / '.env')
    keys = values.get('DATA_ENCRYPTION_KEYS', '')
    if not keys:
        raise ValueError('DATA_ENCRYPTION_KEYS is required to verify the backup.')
    cipher = MultiFernet([Fernet(key.strip().encode()) for key in keys.split(',') if key.strip()])
    command = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
               '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=3', '-i', str(identity_file), '--', host, 'backup']
    result = subprocess.run(command, capture_output=True, timeout=300)
    if result.returncode:
        raise RuntimeError('VPS backup connection or export failed. Check SSH access and the VPS backup service.')
    name, encrypted, digest = verify_export(result.stdout, cipher)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = output / name
    atomic_write(path, encrypted)
    status = {'file': name, 'sha256': digest, 'verified_at': datetime.now(timezone.utc).isoformat()}
    atomic_write(output / '.vps-backup-last-success.json', (json.dumps(status, indent=2) + '\n').encode())
    print('Verified encrypted VPS backup saved:', path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='SSH user@host for the VPS')
    parser.add_argument('--identity-file', required=True, type=Path, help='Restricted backup SSH private key')
    parser.add_argument('--output', type=Path, default=ROOT / 'backups')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env', help='Local file containing the retained encryption keys')
    args = parser.parse_args()
    try:
        pull(args.host, args.identity_file, output=args.output, env_file=args.env_file)
    except InvalidToken:
        raise SystemExit('Backup authentication failed. Retain the correct encryption keys; no downloaded backup was saved.') from None
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        raise SystemExit('VPS backup failed. No unverified backup replaced a valid copy. Check connectivity, key configuration, and the export command.') from None


if __name__ == '__main__':
    main()
