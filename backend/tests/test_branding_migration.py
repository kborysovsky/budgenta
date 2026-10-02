"""Upgrade existing encrypted databases without re-encrypting financial rows."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from backend.core.encryption import encrypt, decrypt, identity_key
from backend.core.schemas import NewAccount
from backend.persistence.migrations import migrate, VERSION, KEY_CHECK_PREFIX, LEGACY_KEY_CHECK_PREFIX
from backend.persistence.models import User
from backend.services import budget


def legacy_database():
    engine = create_engine('sqlite://')
    migrate(engine)
    with Session(engine) as db:
        db.add(User(id=1, telegram_id=123, name='Migration test'))
        db.commit()
        budget.create_account(db, 1, NewAccount(name='Cash', kind='cash', currency='USD', opening_balance='123.45'))
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM schema_versions'))
        for version in (5, 6):
            conn.execute(text('INSERT INTO schema_versions VALUES (:version, :check)'),
                         {'version': version, 'check': encrypt(LEGACY_KEY_CHECK_PREFIX + identity_key(0))})
    return engine


def snapshot(engine):
    with engine.connect() as conn:
        return {name: conn.execute(text(f'SELECT * FROM {name} ORDER BY id')).all()
                for name in ('users', 'accounts', 'account_groups', 'entries')}


def test_v6_rename_preserves_encrypted_records_and_is_repeatable():
    engine = legacy_database()
    before = snapshot(engine)
    migrate(engine)
    migrate(engine)
    assert snapshot(engine) == before
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT max(version) FROM schema_versions')) == VERSION
        assert all(decrypt(value) == KEY_CHECK_PREFIX + identity_key(0)
                   for value in conn.scalars(text('SELECT key_check FROM schema_versions')))
    with Session(engine) as db:
        assert budget.accounts(db, 1)[0]['balance'] == '123.450000'


def test_rename_rejects_wrong_identity_key_without_changing_records(monkeypatch):
    engine = legacy_database()
    before = snapshot(engine)
    monkeypatch.setenv('IDENTITY_HASH_KEY', 'a-different-secret-that-is-long-enough-for-tests')
    with pytest.raises(RuntimeError, match='Invalid encryption key'):
        migrate(engine)
    assert snapshot(engine) == before
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT max(version) FROM schema_versions')) == 6


def test_new_schema_rejects_legacy_sentinel():
    engine = legacy_database()
    migrate(engine)
    with engine.begin() as conn:
        conn.execute(text('UPDATE schema_versions SET key_check=:check WHERE version=:version'),
                     {'check': encrypt(LEGACY_KEY_CHECK_PREFIX + identity_key(0)), 'version': VERSION})
    with pytest.raises(RuntimeError, match='Invalid encryption key'):
        migrate(engine)
