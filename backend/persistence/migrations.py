"""Transactional, repeatable migration from the original plaintext schema."""
from sqlalchemy import inspect, text
from backend.persistence.database import Base
from backend.persistence import models   # register tables
from backend.core.encryption import Encrypted, PREFIX, cipher, encrypt, decrypt, identity_key

VERSION = 7
KEY_CHECK_PREFIX = 'budgenta-encryption-check:'
# Compatibility only: deployed schemas through v6 used the original name.
LEGACY_KEY_CHECK_PREFIX = 'pocket-encryption-check:'

def migrate(engine):
    cipher()
    identity_key(0)
    with engine.begin() as conn:
        if conn.dialect.name == 'postgresql':
            conn.execute(text('SELECT pg_advisory_xact_lock(76243102)'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, key_check TEXT NOT NULL)'))
        current = conn.execute(text('SELECT version, key_check FROM schema_versions ORDER BY version DESC')).first()
        if current:
            expected = KEY_CHECK_PREFIX + identity_key(0)
            accepted = {expected}
            if current.version < 7:
                accepted.add(LEGACY_KEY_CHECK_PREFIX + identity_key(0))
            if decrypt(current.key_check) not in accepted:
                raise RuntimeError('Invalid encryption key.')
            if current.version >= VERSION:
                return
            # Rewrite historical sentinels as well; all live metadata now uses
            # Budgenta. Keep the original encryption and identity keys.
            conn.execute(text('UPDATE schema_versions SET key_check=:check'), {'check': encrypt(expected)})
        Base.metadata.create_all(conn)
        upgrade_entry_columns(conn)
        upgrade_groups(conn)
        upgrade_management(conn)
        if current and current.version >= 2:
            if current.version < 3:
                backfill_links(conn)
            conn.execute(text('INSERT INTO schema_versions (version, key_check) VALUES (:version, :check)'), {'version': VERSION, 'check': encrypt(KEY_CHECK_PREFIX+identity_key(0))})
            return
        user_columns = {c['name'] for c in inspect(conn).get_columns('users')}
        if 'telegram_key' not in user_columns:
            conn.execute(text('ALTER TABLE users ADD COLUMN telegram_key VARCHAR(64)'))
        for table in Base.metadata.sorted_tables:
            encrypted = [c.name for c in table.columns if isinstance(c.type, Encrypted)]
            if not encrypted:
                continue
            # Original VARCHAR/NUMERIC/DATE columns must accept ciphertext.
            if conn.dialect.name == 'postgresql':
                for column in encrypted:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ALTER COLUMN "{column}" TYPE TEXT USING "{column}"::text'))
            pk = list(table.primary_key.columns)[0].name
            rows = conn.execute(text(f'SELECT * FROM "{table.name}"')).mappings().all()
            for row in rows:
                values = {}
                for column in encrypted:
                    value = row[column]
                    if value is not None:
                        if str(value).startswith(PREFIX):
                            decrypt(value)  # also verify the key on existing encrypted data
                        else:
                            values[column] = encrypt(value)
                if table.name == 'users':
                    identity = row['telegram_id']
                    identity = decrypt(identity) if str(identity).startswith(PREFIX) else identity
                    values['telegram_key'] = identity_key(identity)
                if values:
                    assignments = ', '.join(f'"{c}" = :{c}' for c in values)
                    conn.execute(text(f'UPDATE "{table.name}" SET {assignments} WHERE "{pk}" = :row_id'), {**values, 'row_id': row[pk]})
        backfill_links(conn)
        conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_key ON users (telegram_key)'))
        conn.execute(text('INSERT INTO schema_versions (version, key_check) VALUES (:version, :check)'), {'version': VERSION, 'check': encrypt(KEY_CHECK_PREFIX+identity_key(0))})


def upgrade_entry_columns(conn):
    columns = {c['name'] for c in inspect(conn).get_columns('entries')}
    additions = {'operation_id': 'VARCHAR(36)', 'debt_id': 'INTEGER REFERENCES debts(id)', 'deleted': 'BOOLEAN NOT NULL DEFAULT FALSE', 'reversal_issue': 'TEXT'}
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(text(f'ALTER TABLE entries ADD COLUMN {name} {definition}'))
    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_entries_operation_id ON entries (operation_id)'))


def backfill_links(conn):
    from collections import defaultdict
    from decimal import Decimal
    from uuid import uuid4
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from backend.persistence.models import Entry, Account, Debt
    with Session(bind=conn, join_transaction_mode='create_savepoint') as db:
        rows = db.execute(select(Entry, Account).join(Account).order_by(Account.user_id, Entry.id)).all()
        debts = db.scalars(select(Debt)).all()
        repayment_candidates = defaultdict(list)
        for index, (entry, account) in enumerate(rows):
            if entry.operation_id:
                continue
            entry.operation_id = str(uuid4())
            if entry.kind == 'transfer':
                following = rows[index+1] if index+1 < len(rows) else None
                if following:
                    other, target = following
                    valid = (not other.operation_id and other.kind == 'transfer' and other.date == entry.date and other.amount == -entry.amount and entry.amount < 0 and target.id != account.id and target.user_id == account.user_id and target.currency == account.currency and entry.note == f'Transfer with {target.name}' and other.note == f'Transfer with {account.name}')
                else:
                    valid = False
                if valid:
                    other.operation_id = entry.operation_id
                else:
                    entry.reversal_issue = 'Legacy transfer links are ambiguous. This transaction needs review before it can be safely deleted.'
            elif entry.kind == 'expense' and entry.category == 'Debts' and entry.note.startswith('Repayment: '):
                matches = [d for d in debts if d.user_id == account.user_id and d.currency == account.currency and d.name == entry.note[len('Repayment: '):]]
                entry.reversal_issue = 'Legacy debt payment links are ambiguous. This transaction needs review before it can be safely deleted.'
                if len(matches) == 1:
                    repayment_candidates[matches[0].id].append(entry)
        for debt in debts:
            candidates = repayment_candidates.get(debt.id, [])
            if candidates and sum((-e.amount for e in candidates), Decimal(0)) == debt.paid:
                for entry in candidates:
                    entry.debt_id = debt.id
                    entry.reversal_issue = None
        db.commit()


def upgrade_groups(conn):
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from backend.persistence.models import Account, AccountGroup
    columns = {c['name'] for c in inspect(conn).get_columns('accounts')}
    if 'group_id' not in columns:
        conn.execute(text('ALTER TABLE accounts ADD COLUMN group_id INTEGER REFERENCES account_groups(id)'))
    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_accounts_group_id ON accounts (group_id)'))
    # Raw SQL also supports the original unencrypted schema; the outer migration
    # encrypts those rows afterwards. Existing encrypted names are copied as-is.
    rows = conn.execute(text('SELECT id, user_id, name, kind FROM accounts WHERE group_id IS NULL')).mappings().all()
    for row in rows:
        group_id = conn.execute(text('INSERT INTO account_groups (user_id, name, kind) VALUES (:user_id, :name, :kind) RETURNING id'), dict(row)).scalar_one()
        conn.execute(text('UPDATE accounts SET group_id=:group_id WHERE id=:id'), {'id': row['id'], 'group_id': group_id})


def upgrade_management(conn):
    for table in ('account_groups','debts','goals','savings_rules'):
        columns = {c['name'] for c in inspect(conn).get_columns(table)}
        if 'archived' not in columns:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN archived BOOLEAN NOT NULL DEFAULT FALSE'))
