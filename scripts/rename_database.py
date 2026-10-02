"""Rename the original Compose database/role in place, with an encrypted backup.

Run once before rebuilding existing installations. Leaves web/bot stopped so
the operator can build and start the matching application release.
"""
import hashlib
import json
import secrets
import subprocess
from backup_database import ROOT, create_backup

LEGACY = 'pocket'  # Only used to recognize and upgrade existing installations.
TARGET = 'budgenta'


def sql(user, statement, database='postgres', *, check=True):
    result = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'db', 'psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
         '-U', user, '-d', database], input=statement, text=True, capture_output=True, cwd=ROOT)
    if check and result.returncode:
        raise RuntimeError('Database operation failed. Services remain stopped; no database output or secrets logged.')
    return result


def fingerprint(user, database):
    """Compare encrypted rows without printing them or writing them to disk."""
    tables = sql(user, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;", database).stdout.splitlines()
    digest = hashlib.sha256()
    for table in tables:
        identifier = '"' + table.replace('"', '""') + '"'
        rows = sql(user, f'SELECT row_to_json(t)::text FROM public.{identifier} t ORDER BY row_to_json(t)::text;', database).stdout
        digest.update(table.encode() + b'\0' + rows.encode() + b'\0')
    return digest.digest()


def main():
    user = next((name for name in (TARGET, LEGACY) if sql(name, 'SELECT 1;', check=False).returncode == 0), None)
    if user is None:
        raise RuntimeError('Start the existing Compose db service first. Its local socket must allow administrative access.')
    state = json.loads(sql(user, """SELECT json_build_object(
        'old_db', EXISTS(SELECT 1 FROM pg_database WHERE datname='pocket'),
        'new_db', EXISTS(SELECT 1 FROM pg_database WHERE datname='budgenta'),
        'old_role', EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pocket'),
        'new_role', EXISTS(SELECT 1 FROM pg_roles WHERE rolname='budgenta'));""").stdout)
    if state == dict(old_db=False, new_db=True, old_role=False, new_role=True):
        print('Database and role already use Budgenta; no changes needed.')
        return
    if state != dict(old_db=True, new_db=False, old_role=True, new_role=False):
        raise RuntimeError('Conflicting or partial database names. Refusing to overwrite existing databases or roles.')
    if sql(user, "SELECT rolpassword LIKE 'SCRAM-SHA-256$%' FROM pg_authid WHERE rolname='pocket';").stdout.strip() != 't':
        raise RuntimeError('Convert the existing role password to SCRAM before renaming; an MD5 password cannot survive a role rename.')
    stopped = subprocess.run(['docker', 'compose', 'stop', 'web', 'bot'], cwd=ROOT, capture_output=True)
    if stopped.returncode:
        raise RuntimeError('Could not stop web/bot; no database changes made.')
    create_backup(LEGACY, LEGACY)
    before = fingerprint(LEGACY, LEGACY)
    admin = 'budgenta_rename_' + secrets.token_hex(8)
    sql(LEGACY, f'CREATE ROLE {admin} LOGIN SUPERUSER;')
    try:
        # Connect as a different session user: PostgreSQL prohibits renaming
        # the current one. No password is assigned to this temporary role.
        sql(admin, 'BEGIN; ALTER DATABASE pocket RENAME TO budgenta; ALTER ROLE pocket RENAME TO budgenta; COMMIT;')
        if before != fingerprint(TARGET, TARGET):
            raise RuntimeError('Record verification failed. Keep services stopped and recover from the encrypted backup.')
    finally:
        cleanup_user = TARGET if sql(TARGET, 'SELECT 1;', check=False).returncode == 0 else LEGACY
        sql(cleanup_user, f'DROP ROLE {admin};')
    print('Database and role renamed to budgenta. All stored rows verified unchanged.')
    print('Web/bot remain stopped. Run docker compose --profile telegram up --build -d.')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
