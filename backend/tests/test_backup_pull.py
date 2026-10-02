import hashlib
import json
from pathlib import Path
import stat
from types import SimpleNamespace
from cryptography.fernet import Fernet, InvalidToken
import pytest
from scripts import pull_vps_backup as backup


NAME = 'budgenta-20261002T230000123456Z.sql.fernet'


def export(cipher, name=NAME):
    encrypted = cipher.encrypt(b'--\n-- PostgreSQL database dump\n--\nCREATE TABLE example (id int);')
    header = {'name':name,'size':len(encrypted),'sha256':hashlib.sha256(encrypted).hexdigest()}
    return json.dumps(header).encode()+b'\n'+encrypted


def test_pull_authenticates_encrypts_and_saves_private_copy(tmp_path, monkeypatch):
    key=Fernet.generate_key(); cipher=Fernet(key)
    env=tmp_path/'.env';env.write_text('DATA_ENCRYPTION_KEYS='+key.decode())
    payload=export(cipher)
    def run(command, **kwargs):
        assert 'IdentityAgent=none' in command and 'StrictHostKeyChecking=yes' in command
        assert command[-3:]==['--','backup@example.invalid','backup']
        assert kwargs['timeout']==300 and kwargs['capture_output']
        return SimpleNamespace(returncode=0,stdout=payload)
    monkeypatch.setattr(backup.subprocess,'run',run)
    output=tmp_path/'backups'
    path=backup.pull('backup@example.invalid',tmp_path/'key',output=output,env_file=env)
    assert path.name=='budgenta-vps-20261002T230000123456Z.sql.fernet'
    assert path.read_bytes()==payload.partition(b'\n')[2]
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert stat.S_IMODE(output.stat().st_mode)==0o700
    status=json.loads((output/'.vps-backup-last-success.json').read_text())
    assert status['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert not list(output.glob('.budgenta-download-*'))
    assert b'CREATE TABLE' not in path.read_bytes()


@pytest.mark.parametrize('damage',['truncated','checksum','path','foreign_key','not_dump'])
def test_rejects_unusable_exports(damage):
    cipher=Fernet(Fernet.generate_key()); data=export(cipher)
    if damage=='truncated':data=data[:-10]
    elif damage=='checksum':data=data[:-1]+b'x'
    elif damage=='path':data=export(cipher,'../../secrets')
    elif damage=='foreign_key':data=export(Fernet(Fernet.generate_key()))
    else:
        encrypted=cipher.encrypt(b'not a database dump')
        data=json.dumps({'name':NAME,'size':len(encrypted),'sha256':hashlib.sha256(encrypted).hexdigest()}).encode()+b'\n'+encrypted
    with pytest.raises((ValueError,InvalidToken)):backup.verify_export(data,cipher)


def test_failed_download_keeps_previous_backup(tmp_path,monkeypatch):
    key=Fernet.generate_key();env=tmp_path/'.env';env.write_text('DATA_ENCRYPTION_KEYS='+key.decode())
    output=tmp_path/'backups';output.mkdir();old=output/'previous.sql.fernet';old.write_bytes(b'keep')
    monkeypatch.setattr(backup.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=255,stdout=b''))
    with pytest.raises(RuntimeError):backup.pull('backup@example.invalid',tmp_path/'key',output=output,env_file=env)
    assert old.read_bytes()==b'keep' and len(list(output.iterdir()))==1
