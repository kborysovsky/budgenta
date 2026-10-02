# Deploying Budgenta to a VPS

[Back to README](../README.md)

This guide assumes one Ubuntu 24.04 LTS VPS, one hostname such as `budget.example.com`, Docker Compose, and a host-level nginx reverse proxy. The web service, PostgreSQL, and one Telegram worker run together. No VPS or DNS has been configured by the repository itself.

## Prepare the host and DNS

1. Create a normal SSH user with sudo access and an SSH key. Apply OS updates and enable automatic security updates. Keep an active SSH session while changing firewall or SSH settings.
2. Install Docker Engine and its Compose plugin following [Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Use a current Docker release; public access to Docker itself must remain disabled.
3. Allow only your SSH port, TCP 80, and TCP 443 in the VPS firewall. Restrict SSH to your IP where practical. PostgreSQL has no published port; the web container is bound to `127.0.0.1:8000`.
4. Point your subdomain's A record at the VPS IPv4 address. Add an AAAA record only if IPv6 is configured and reachable too.
5. Clone `https://github.com/kborysovsky/budgenta.git`, copy `.env.example` to `.env`, and set its permissions to `0600`.

## Configure and preserve secrets

For an existing database, securely transfer the existing encryption keys and `IDENTITY_HASH_KEY` along with an encrypted database backup. **Do not regenerate these keys**: the restored records require them. Follow [backup and recovery](operations.md#backups-and-recovery). Use a new strong PostgreSQL password on the new host; a new session secret will sign everyone out.

For a fresh database, use the README's key-generation commands and independent random secrets. Do not keep the placeholder database password. Revoke any Telegram bot token previously shared in a chat, screenshot, or commit, then place its replacement only in `.env`.

Set:

```dotenv
APP_ORIGIN=https://budget.example.com
COOKIE_SECURE=true
```

`APP_ORIGIN` must match your public origin exactly, with no path or trailing slash. Public startup rejects HTTP or insecure session cookies. The Telegram bot username and token must be configured. The current browser login uses bot approval, so it does not require embedding Telegram's widget.

## Start the app and enable HTTPS

Stop the previous host's Telegram worker before starting this bot on the VPS. For a data migration, restore and verify the database before allowing users to write to the new instance.

```sh
docker compose --profile telegram up --build -d
docker compose --profile telegram ps
```

Install nginx, Certbot, and the nginx Certbot plugin. Copy [the nginx template](../deploy/nginx.conf) to `/etc/nginx/conf.d/budgenta.conf`, replace `budget.example.com` with your actual hostname, and check `sudo nginx -t` before reloading nginx. The template belongs inside nginx's `http` context; do not copy it into a `server` block.

After DNS resolves to this host and ports 80/443 are reachable:

```sh
sudo certbot --nginx -d budget.example.com --redirect
sudo certbot renew --dry-run
```

Finish HTTPS setup before signing in or sharing the URL. The app sends HSTS for the configured HTTPS origin without applying it to unrelated subdomains.

## Configure the trusted reverse proxy

nginx replaces incoming forwarding headers. Uvicorn must trust only nginx's actual source IP as seen by the web container. For a host-level nginx proxy through Docker's loopback-published port, this is normally the Compose network's bridge gateway. Inspect it without printing container environment secrets:

```sh
docker network inspect finance_default --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

The network name depends on the checkout directory/project name; use `docker network ls` to find the relevant `_default` network. Set the confirmed peer address as `FORWARDED_ALLOW_IPS` in `.env` and recreate the web container. Do not set `*` or trust arbitrary Internet clients. Confirm with requests from two different clients that access logs show their distinct IPs. Otherwise, they share the proxy's API rate limit. The nginx limit already uses its direct client address.

The supplied setup uses one Uvicorn process. App limits are process-local: 240 API requests/minute/IP, 10 login attempts/minute/IP, and 30 Telegram updates/minute/user. A restart resets them. Before adding replicas/workers, use a shared limiter or enforce the complete policy at a trusted edge. These limits are not distributed-denial-of-service protection.

## Verify before opening registration to others

- Open the HTTPS URL and confirm HTTP redirects to it. Sign in through Telegram, sign out, and confirm private API requests return 401 without a session.
- Create two test users and verify each sees only their own accounts. Exercise a small transaction, transfer, deletion/reversal, and a report preview.
- Verify only SSH/80/443 are publicly reachable, secure cookies are present, and PostgreSQL/port 8000 are inaccessible externally.
- Schedule daily encrypted database backups off the VPS and retain the keys separately. Test recovery into a separate database. Server snapshots alone are not a tested database recovery plan.
- Monitor uptime, failed requests, disk usage, and backup failures. Keep the OS, Docker images, and dependencies patched.

This is a single-server early-stage deployment, with no high-availability guarantee or independent penetration test. The security review covers application code and automated tests; the actual VPS, DNS, TLS, firewall, and recovery setup must still be verified after deployment.
