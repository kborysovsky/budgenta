"""Create an encrypted pg_dump without writing plaintext to disk."""
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import dotenv_values

root=Path(__file__).resolve().parents[1]
values=dotenv_values(root/'.env')
cipher=Fernet(values['DATA_ENCRYPTION_KEYS'].split(',')[0].strip().encode())
result=subprocess.run(['docker','compose','exec','-T','db','pg_dump','-U','pocket','--no-owner','--no-acl','pocket'],cwd=root,capture_output=True)
if result.returncode:
    raise SystemExit('Database backup failed. No database output or credentials were printed.')
folder=root/'backups'; folder.mkdir(exist_ok=True,mode=0o700)
path=folder/('budgenta-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sql.fernet')
with open(path,'xb') as f:
    os.chmod(path,0o600)
    f.write(cipher.encrypt(result.stdout))
print('Encrypted backup saved:',path.relative_to(root))
