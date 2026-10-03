# Translations

English is the source language and fallback. `ru.json`, `uk.json`, and `es.json` contain Russian, Ukrainian, and Spanish translations shared by the Vue frontend and Python bot/report renderer. Translations are local files, not a network service. No language is inferred from browser or Telegram metadata.

- Frontend: `frontend/src/i18n.js` exposes reactive `locale`, `t`, number formatting locale, and explicit category/quote display helpers. Vue templates also have `$t`, `$category`, `$quote`, and `$error` helpers.
- Backend: `backend/core/i18n.py` uses a `ContextVar` scope around a user's bot interaction or report generation. Scopes reset on success and exceptions, keeping concurrent users independent. Public quote caches remain language-neutral.
- Storage: `ReportPreferences.language` and `hidden_categories` live in the existing encrypted preferences payload. No schema migration is needed. Dedicated mutations merge under the existing per-user write lock. Saving a stale report form cannot undo a language or category change.
- API: `POST /api/preferences/language` takes `{"language":"ru"}`. Category management uses `GET /api/categories/manage` and `POST /api/categories/change` with `{"kind":"expense","name":"Grocery","removed":true}`. Existing authentication, origin checks, and ownership rules apply.

## Editing translations

Use the English source phrase as the key. Keep named placeholders such as `{currency}`, `{name}`, and `{amount}` identical across languages. Values are inserted as text; never use HTML in a translation. Translate complete sentences where possible. Escape newlines as `\n` in JSON. Preserve leading/trailing spaces when they belong to a message fragment.

Call translation helpers only for application-owned labels. Translate built-in category labels while retaining their canonical stored values. Do not translate user names, account names, custom categories, or notes. Do not localize enum values, API paths, identifiers, or numbers before doing arithmetic. A language switch must not create a financial write.

To add a language, add a catalog, extend the frontend and backend language registries and schema, and include it in the catalog and flow tests. Both Docker stages copy the root `locales/` directory. Build the frontend from the repository checkout so that the shared catalog imports can resolve.

Run:

```bash
python -m pytest -q
node --test frontend/tests/*.test.js
npm --prefix frontend run build
```

Tests cover catalog completeness and placeholders, user isolation, localized transactions/transfers/exchanges, scheduled reports, category canonicalization, encrypted preference storage, and category removal without rewriting history.
