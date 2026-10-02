# Security and data protection

[Back to README](../README.md)

See [SECURITY.md](../SECURITY.md) for private vulnerability reporting and [the VPS guide](deployment.md) for the required deployment configuration.

## Authentication and isolation

Browser login uses a five-minute, one-use challenge approved in the user's private Telegram chat. A random browser secret is stored in an HttpOnly cookie; only its SHA-256 digest is stored in the database. Completing login requires that browser secret and a Telegram approval, and consumes the challenge under a database row lock. The signed Telegram login endpoint additionally checks Telegram's HMAC signature and rejects data older than five minutes. Local-development login is not available.

Sessions are signed, HttpOnly, SameSite=Lax cookies valid for seven days. Public deployments must use HTTPS and Secure cookies; startup rejects insecure public settings. Every financial endpoint requires a session, and service functions scope object lookups and mutations to its user. Mutation requests must carry the exact configured Origin. Public requests must also use the configured Host. The bot ignores groups and private messages whose sender does not match the chat ID.

Logout removes the browser cookie. Sessions are currently stateless: an already stolen copy remains valid until its seven-day expiry. Rotating `SESSION_SECRET` revokes all sessions. Per-device session revocation is not implemented.

## Browser and abuse protections

Responses include a Content Security Policy that restricts scripts to this origin, blocks framing and plugins, and restricts external resources to Google Fonts. Inline styles remain permitted for Vue's dynamic layout; inline scripts and `eval` are not permitted. Referrer information is suppressed, content sniffing is disabled, and camera/microphone/geolocation permissions are disabled. Private API responses use `Cache-Control: no-store`. HTTPS deployments send HSTS for the app hostname. Public Swagger/OpenAPI routes are disabled.

The app limits request bodies to 256 KiB, counting streamed bytes as well as Content-Length. It permits 240 API requests/minute/IP, with a separate limit of 10 login starts or signed-login attempts/minute/IP. The bot processes up to 30 updates/minute/user; additional messages are silently ignored. Rate-limit state is bounded and process-local; it resets on restart. Configure the trusted reverse proxy correctly to preserve distinct client IPs, and use shared limits before adding workers or replicas. The [nginx template](../deploy/nginx.conf) also limits traffic and slow request bodies. These controls do not stop a distributed denial-of-service attack or sustained storage abuse by many registered users.

The web/bot containers run as a non-root user with Linux capabilities dropped and privilege escalation disabled. PostgreSQL is not exposed on a host port. The web port is bound to localhost. SQL errors suppress bound parameters, and Telegram network failures suppress token-bearing request URLs, including during startup.

## Encryption and operator access

The application encrypts Telegram IDs, display names, account names/types/currencies, monetary amounts, transaction dates/categories/notes, closed months, debts, goals, savings rule amounts/dates, scheduled results, report preferences and bodies, account-group names/types, bot state, and bot reply receipts using authenticated Fernet encryption **before sending them to PostgreSQL**. Randomized ciphertext hides equal values. Telegram identities are located through a keyed HMAC index. Internal row IDs, relationships, row counts, login expiry metadata, update IDs, and record creation timestamps remain visible.

A raw database query or database-only dump cannot reveal financial values without the encryption keys. This is **server-side encryption, not zero-knowledge encryption**: the running app decrypts records, and an operator who controls the server or `.env` can do so too. User authorization prevents ordinary users from accessing one another's data. An attacker who obtains both the database and server secrets can decrypt the data.

Store encryption keys separately from database backups and preserve them securely. Losing the encryption keys loses access to the records. Do not regenerate `IDENTITY_HASH_KEY` for an existing database: it locates users. Startup verifies both key sets and fails if they don't match. `DATA_ENCRYPTION_KEYS` accepts comma-separated Fernet keys for staged rotation: new writes use the first key; keep older keys until old records have been re-encrypted.

Startup runs a transactional, versioned migration that converts the original plaintext fields into ciphertext without changing balances. PostgreSQL serializes schema migration with an advisory lock. `.venv/bin/python scripts/backup_database.py` creates a Fernet-encrypted SQL backup under `backups/` without writing plaintext to disk. Decrypt with a retained encryption key before restoring with PostgreSQL tools; restore into a separate database first. Take and protect backups before upgrades. Old backups, PostgreSQL WAL, and old storage pages may retain earlier plaintext; encryption does not retroactively erase copies. Do not expose old unencrypted backups.

## Verification and remaining work

The October 2026 application review added HTTP regression tests for unauthorized access, forged sessions, cross-user modifications and reports, Origin/Host enforcement, login flooding, actual streamed request limits, secure cookies, and unsafe deployment configuration. Existing tests cover Telegram signature tampering/expiry, browser-bound one-use challenges, encrypted storage, and transaction reversal. npm and Python dependency scans found no known advisories at review time; that result can change.

GitHub Actions runs tests, builds, and dependency audits on pushes/pull requests and weekly. Dependabot checks package, image, and Actions updates. Keep these checks enabled and address alerts. Dependency scans do not audit application logic or certify the server/container OS.

Before public deployment, verify HTTPS, trusted proxy handling, firewall rules, OS updates, monitoring, and off-server encrypted backups with a tested restore. Replace any exposed Telegram token. Keep `.env` readable only by the deployment owner, and keep keys separate from backups. Do not run external forks or untrusted CI code with production secrets. The actual VPS configuration and a live penetration test are outside this code review; the project should not be represented as independently security-audited or zero-knowledge.
