# Security policy

Budgenta is an early-stage, self-hosted budgeting application. Security fixes target the latest `main` branch. Review [the security model and deployment requirements](docs/security.md) before hosting real financial data.

## Reporting a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/kborysovsky/budgenta/security/advisories/new). If that feature is unavailable, contact the maintainer through the contact details on their GitHub profile before sharing details. Do not publish credentials, financial records, or an exploit against a live instance in a public issue.

Include the affected commit, reproduction steps using synthetic data, expected behavior, and observed impact. Please test only instances you own or are authorized to assess.

## Scope and limitations

Financial values are encrypted on the server before database storage. This is not end-to-end or zero-knowledge encryption: the server operator and anyone with the server's keys can decrypt them. Telegram retains messages sent through the bot. Dependencies, operating system updates, HTTPS, backups, and secret handling are shared responsibilities of each deployment's operator.

Automated tests and dependency scans reduce risk; they are not a penetration test, certification, or guarantee against compromise.
