# Render-only deployment contract

Multibot is hosted as one Render Python web service. The Python application
serves the dashboard, static assets, and API from the same origin. There is no
separate static-site host and no frontend-to-API proxy.

## Canonical service

- Service: `Multibot`
- Runtime: Python 3.12
- Build: `pip install -r requirements.txt`
- Start: `python3 main.py`
- Health/keepalive: `/ping`
- Dashboard: https://multibot-3hsb.onrender.com/dashboard
- Architecture: https://multibot-3hsb.onrender.com/architecture

The checked-in `render.yaml` is aligned to the existing Render service. The
Netlify-style `_redirects` file has been removed; it was not part of the
runtime and must not be reintroduced.

## Required Render environment variables

Set these in the Render service's Environment page before deploying this
configuration:

- `SUPABASE_DB_URL`: Supabase PostgreSQL session-pooler connection string
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `DASHBOARD_API_TOKEN`: a long, randomly generated secret known only to the
  operator

The dashboard asks for the admin token when a protected API returns
`ADMIN_TOKEN_REQUIRED`. The browser stores the token locally for subsequent
requests. Do not put the token in source control, build logs, or public
documentation.

Production requests fail closed when `DASHBOARD_API_TOKEN` is missing. Local
development without a deployment `PORT` retains the existing tokenless
workflow. The public `/ping` and `/api/health` endpoints remain available.

Render supplies `PORT`; do not hard-code it in the Blueprint. The existing
cron-job.org keepalive should call
`https://multibot-3hsb.onrender.com/ping` every 10 minutes. This endpoint does
not trigger scans or change trading state.

## Hosting migration boundary

The external Netlify site has been stopped by the operator. This repository
change removes its obsolete proxy/redirect configuration and points Telegram
and documentation links at the Render service. It does not access or manage
external hosting accounts or DNS.
