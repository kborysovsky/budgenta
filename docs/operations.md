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

## Backups and recovery

Install the backend dependencies on the host, then run:

```sh
.venv/bin/python scripts/backup_database.py
```

The script reads root `.env`, calls `pg_dump` inside the Compose database container, and encrypts the dump in memory with the first Fernet key. It writes a mode-0600 `.sql.fernet` file under `backups/`; plaintext is not written to disk. It assumes the supplied Compose service/database/user names (`db` / `pocket` / `pocket`). Adapt it when using externally managed PostgreSQL.

Keep backup files off-host and keep the encryption keys and `IDENTITY_HASH_KEY` separately. No automatic backup schedule is configured. Set an operational schedule appropriate to how much data you can afford to lose, and periodically test recovery.

Restore into a separate database first. Decrypt the outer Fernet backup using a retained key, then feed the SQL into `psql` for that database. Avoid plaintext temporary files or shell history containing keys. The financial fields inside the SQL are also encrypted and still require the original application keys. Start an isolated instance with those keys, verify balances and record counts, and only then switch the production application to the restored database. Do not run a second polling worker with the production bot token during recovery testing.

`docker compose stop` and ordinary rebuilds retain the named PostgreSQL volume. `docker compose down -v` removes it and is destructive.

## Scheduled jobs and Telegram

### Budgenta branding

The website uses `frontend/public/budgenta-mark.svg`, with a matching favicon, Apple touch icon, and Telegram avatar. The shared `BrandLogo.vue` component supplies the website wordmark. To apply the bot's display name, descriptions, and profile photo using your root `.env`, run once from the repository root:

```sh
.venv/bin/python scripts/update_bot_branding.py
```

This updates the configured bot's public profile through the Telegram Bot API and sends no chat messages. It verifies that the token matches `TELEGRAM_BOT_USERNAME` first. The bot's existing @username remains unchanged; username changes are managed through BotFather and must also be reflected in `.env`. See [Telegram profile photo API](https://core.telegram.org/bots/api#setmyprofilephoto).

Legacy internal database/user names, login cookie identifiers, and encryption markers retain their original values for compatibility with existing deployments. The Budgenta rebrand requires no database migration or new encryption keys.

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
