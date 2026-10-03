# Operations

[Back to README](../README.md)

## Processes and entry points

| Process | Native entry point | Docker target |
| --- | --- | --- |
| Web API and built Vue assets | `uvicorn backend.web.main:app` | `web` |
| Telegram polling and scheduled jobs | `python -m backend.bot` | `bot` |
| PostgreSQL | Managed by Compose | `postgres:17-alpine` |

Run native commands from the repository root. Uvicorn loads `.env` when started with `--env-file .env`; the bot entry point loads the root `.env` before database imports. Environment variables supplied by the host or Compose take precedence. Compose selects each image's target and supplies the database connection string. The bot image does not include the frontend build.

The website binds to localhost. A host-level reverse proxy can forward the public HTTPS origin to `127.0.0.1:8000`. Configure the proxy for your deployment environment, including certificate renewal. Set `APP_ORIGIN` to the browser-facing origin, and `COOKIE_SECURE=true`. PostgreSQL has no published host port.

## Upgrade

1. Preserve `.env` and create an encrypted backup using `scripts/backup_database.py`.
2. Run the tests and frontend build described in the README.
3. Run `docker compose --profile telegram up --build -d`.
4. Check `docker compose ps` and `docker compose logs --tail 100 web bot`.
5. Open the site, sign in, and check balances and report previews.

Startup applies transactional, versioned migrations. PostgreSQL serializes migration startup with an advisory lock. Never regenerate identity or encryption keys during an upgrade. The package reorganization changes Python import/launch paths only and needs no new database migration. Update external service definitions referencing `app.main:app` or `app.bot` to `backend.web.main:app` or `backend.bot`.

For a code rollback, retain the prior release/image and its configuration. A rollback across a database migration may also need a compatible database restore; do not assume older application code supports a newer schema.

### Upgrade from the original database name

Fresh installations create the `budgenta` database and role automatically. Existing PostgreSQL volumes retain their original database/role names even when Compose environment variables change. For an installation originally created with the `pocket` names, keep its database service running and execute this once **before rebuilding the application services**:

```sh
.venv/bin/python scripts/rename_database.py
docker compose --profile telegram up --build -d
```

The script stops web/bot, creates an encrypted backup, and renames the database and role in one transaction. A temporary local administrator role allows renaming the original session user; it is removed afterwards. The script compares every encrypted table row before/after and refuses conflicting names or an old MD5 password. The supplied PostgreSQL 17 setup uses SCRAM passwords, which survive the rename. Database/role identities, ownership, encryption keys, and stored records are preserved. Repeating the script after a successful rename is a no-op. Do not remove the PostgreSQL volume.

The script leaves web/bot stopped so you can start the matching release. Application migration 7 replaces the old encrypted key-check marker, including historical schema-version records. Old marker strings remain only in compatibility code and migration tests. The container OS user is now `budgenta`, and cookies use `budgenta_session` and `budgenta_login`; sign in again through Telegram after upgrading.

If a native `.env` or external client has a PostgreSQL `DATABASE_URL` using the old role/database, change both to `budgenta` without changing its password. Compose supplies the new URL automatically. To back up a still-unmigrated installation manually, use `scripts/backup_database.py --user pocket --database pocket`. Rollback after application migration 7 requires the pre-upgrade backup and matching old code/configuration; old code cannot validate the new marker.

### Budget Limits upgrade (schema 8)

Take a backup before upgrading both web and bot. Migration 8 creates `budget_limits` and `budget_alert_states`, and adds nullable `budget_id` / `budget_context` fields to the notification outbox. Existing ledger rows and report notifications are retained. New category names, limits, currencies, inclusion settings, alert state, and notification context are encrypted; category/month lookup keys use keyed hashes. Existing users start with the feature and all report inclusions disabled.

Budget evaluation runs in the existing bot scheduler under the same per-user database lock as financial writes. Threshold reservations and outbox messages commit together, preventing duplicate enqueueing across competing checks. No additional worker or cron job is needed. The website calculates statistics on request; the bot must be running for notifications. For alert troubleshooting, check the global feature switch, the individual limit, notification settings, the user's report timezone, fresh rates, and whether a threshold has already been delivered. Do not reset alert history merely to retry an interrupted transport delivery.

Authenticated APIs: `GET /api/budget-limits?month=YYYY-MM`, `POST /api/budget-limits/settings`, `POST /api/budget-limits`, and `POST /api/budget-limits/{id}/edit`, `/delete`, `/reset-alerts`. Creation/edit fields are `category`, decimal-string `amount`, `currency`, `enabled`, and `expense_currencies` (`null` for all, otherwise a nonempty list). Settings fields are `enabled` and `notifications_enabled`. Each report section has an `include_budgets` flag. All endpoints enforce user ownership, and mutations require the configured Origin. Changing feature settings uses the dedicated endpoint so a stale report form cannot overwrite them.

## Backups and recovery

Install the backend dependencies on the host, then run:

```sh
.venv/bin/python scripts/backup_database.py
```

The script reads root `.env`, calls `pg_dump` inside the Compose database container, and encrypts the dump in memory with the first Fernet key. It writes a mode-0600 `.sql.fernet` file under `backups/`; plaintext is not written to disk. It assumes the supplied Compose service/database/user names (`db` / `budgenta` / `budgenta`). Adapt it when using externally managed PostgreSQL.

Keep backup files off-host and keep the encryption keys and `IDENTITY_HASH_KEY` separately. Compose does not install backup timers automatically. Configure a schedule appropriate to how much data you can afford to lose, and periodically test recovery. The [weekly off-host backup procedure](#weekly-backups-from-a-vps-to-your-computer) below provides a verified local copy.

Restore into a separate database first. Decrypt the outer Fernet backup using a retained key, then feed the SQL into `psql` for that database. Avoid plaintext temporary files or shell history containing keys. The financial fields inside the SQL are also encrypted and still require the original application keys. Start an isolated instance with those keys, verify balances and record counts, and only then switch the production application to the restored database. Do not run a second polling worker with the production bot token during recovery testing.

`docker compose stop` and ordinary rebuilds retain the named PostgreSQL volume. `docker compose down -v` removes it and is destructive.

## Scheduled jobs and Telegram

### Budgenta branding

The website uses `frontend/public/budgenta-mark.svg`, with a matching favicon, Apple touch icon, and Telegram avatar. The shared `BrandLogo.vue` component supplies the website wordmark. To apply the bot's display name, descriptions, and profile photo using your root `.env`, run once from the repository root:

```sh
.venv/bin/python scripts/update_bot_branding.py
```

This updates the configured bot's public profile through the Telegram Bot API and sends no chat messages. It verifies that the token matches `TELEGRAM_BOT_USERNAME` first. The bot's existing @username remains unchanged; username changes are managed through BotFather and must also be reflected in `.env`. See [Telegram profile photo API](https://core.telegram.org/bots/api#setmyprofilephoto).

Database/role names, the container user, and browser cookie identifiers use `budgenta`. Existing installations must run the [database rename](#upgrade-from-the-original-database-name) before restarting with the new Compose settings. Schema migration 7 updates the encrypted key-check marker without changing financial records or encryption keys. Existing browser sessions and pending login challenges need a fresh Telegram sign-in.

### Worker operation

Keep the `bot` service running. Its polling loop checks schedules approximately every 25 seconds, sends queued notifications, and processes incoming messages. One worker holds a PostgreSQL advisory lock; a second worker exits rather than poll concurrently.

The worker preserves conversation state and update receipts. Financial writes are protected against update redelivery. Notifications may repeat if Telegram accepts a message immediately before the process crashes, but a saved financial transaction is not repeated. Report schedules and savings rules have different catch-up behavior, documented in the [user guide](user-guide.md).

An existing Telegram webhook conflicts with polling. `scripts/check_integrations.py` reports whether one is present; remove it intentionally through Telegram before using this worker. The script does not change webhook settings or send messages.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError: app` after upgrading | Update the old entry point/import. Run from the repository root using `backend.web.main:app` or `backend.bot`. |
| Website loads but saves return 403 | Match `APP_ORIGIN` exactly to the browser origin, including scheme and port. |
| Login or scheduled reports do not arrive | Confirm `bot` is running, the token and username match, and no webhook or other worker is using the bot. |
| Login cookie is missing locally | Use `COOKIE_SECURE=false` on local HTTP; use `true` with public HTTPS. |
| Startup rejects encryption/identity keys | Restore the keys for this database. Creating new keys does not recover existing records. |
| Website shows partial USD totals | Inspect the provider status/timestamps and excluded currencies. Try the integration check; a missing quote does not remove stored funds. |
| Currency appears in Accounts but not Overview | Check Reports → Dashboard exclusions/account selection and Accounts → Page settings visibility. |
| Native API starts but Vue page is missing | Run Vite separately or build `frontend/dist`; verify `STATIC_DIR` if overridden. |
| Scheduled job did not run while the host was off | Restart the worker and inspect catch-up rules; local scheduling requires the host to run. |

Never include `.env`, Telegram request URLs containing tokens, decrypted dumps, or encryption keys in issue reports. Logs intentionally avoid raw Telegram errors because request URLs contain credentials.

## Moving to Git and a VPS

Follow the [VPS deployment guide](deployment.md) for DNS, HTTPS, firewall, reverse-proxy limits, and launch checks. The repository is [kborysovsky/budgenta](https://github.com/kborysovsky/budgenta) and uses the [MIT license](../LICENSE).

The application only supports Telegram sign-in. The former local-workspace button, endpoint, and configuration switch have been removed; old local-workspace sessions are rejected. Existing local test records are retained separately in the database and are not transferred into a Telegram account.

Commit the source code and `.env.example`. `.env`, local credential/tooling directories, generated assets, database files, backups, and screenshots are ignored. If secrets were committed previously, adding an ignore rule does not remove them from Git history.

Clone the repository on the VPS, create its private `.env`, configure the public HTTPS origin and secure cookies, and run `docker compose --profile telegram up --build -d`. Stop the old host's worker before starting the same bot on the VPS. Git does not carry your local PostgreSQL volume: use the encrypted backup/recovery procedure above if you want to retain existing records, along with the matching encryption and identity keys. A fresh database can use newly generated keys.

## Weekly backups from a VPS to your computer

`scripts/pull_vps_backup.py` requests a fresh encrypted dump from a VPS, checks its size and SHA-256 checksum, and authenticates/decrypts it in memory using the retained local `DATA_ENCRYPTION_KEYS`. It atomically saves only the encrypted file as `backups/budgenta-vps-<UTC timestamp>.sql.fernet`, with mode 0600. `.vps-backup-last-success.json` records the last successful verification. Local copies are retained until you remove them; the VPS's own retention policy is independent.

Use a dedicated SSH key without an interactive passphrase for the scheduled job. Restrict that key on the VPS to this exact export operation by adding an authorized-keys entry (adjust the repository path):

```text
restrict,command="cd /opt/budgenta && /opt/budgenta/.venv/bin/python /opt/budgenta/scripts/export_backup.py" ssh-ed25519 <public-key> budgenta-backup-local
```

The forced command accepts only `backup`, creates the dump, and streams its encrypted contents. It cannot be used for an interactive shell or port forwarding. Keep your normal administration key separate. The VPS needs the host backup dependencies, Docker access, and its production `.env`. Verify and pin the VPS SSH host key before scheduling; the pull refuses unknown or changed host keys and does not use an SSH agent or other keys from SSH configuration.

Example local command:

```sh
.venv/bin/python scripts/pull_vps_backup.py \
  --host budgenta@YOUR_VPS \
  --identity-file ~/.ssh/budgenta_backup_ed25519
```

Install a user systemd service with that command, an absolute repository working directory, `Type=oneshot`, `UMask=0077`, `TimeoutStartSec=6min`, `Restart=on-failure`, and `RestartSec=1h`. Set `StartLimitIntervalSec=0` in its `[Unit]` section so hourly retries can continue. The matching timer can run Sundays at 15:00 Buenos Aires time:

```ini
[Timer]
OnCalendar=Sun *-*-* 15:00:00 America/Argentina/Buenos_Aires
Persistent=true
AccuracySec=1min
Unit=budgenta-vps-backup.service

[Install]
WantedBy=timers.target
```

```sh
systemctl --user daemon-reload
systemctl --user enable --now budgenta-vps-backup.timer
systemctl --user start budgenta-vps-backup.service
systemctl --user list-timers budgenta-vps-backup.timer
journalctl --user -u budgenta-vps-backup.service -n 20
```

The computer must be running and have network access. `Persistent=true` catches a missed scheduled run when the user timer next starts, normally at login; user lingering can also start it at boot. Failed exports retry hourly while the user manager is running. Keep the local `.env` encryption keys current when rotating production keys, and preserve the identity key for recovery. This task copies the production database; it does not start the local app or Telegram worker and does not synchronize the local database.

To disable the job and any pending retries:

```sh
systemctl --user disable --now budgenta-vps-backup.timer
systemctl --user stop budgenta-vps-backup.service
```


## Monthly report downloads

`GET /api/reports/{YYYY-MM}/export.csv` and `/export.xlsx` require the signed-in owner and use the saved monthly report filters. The shared `backend.services.monthly_export` service prepares the same tables for both serializers. CSV uses standard-library quoting, UTF-8 BOM, exact decimal strings, and formula-prefix escaping for text cells. Excel uses pinned [XlsxWriter](https://xlsxwriter.readthedocs.io/workbook.html) with in-memory assembly and explicit string writes, disabling automatic formulas and hyperlinks. Files are attachment responses with `Cache-Control: no-store`; no temporary plaintext report is written on the server. This feature requires the updated Python dependencies but no database migration or extra worker.
