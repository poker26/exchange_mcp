# Exchange MCP (hybrid EWS + EAS)

MCP server that talks to an on-premise Exchange mailbox via **two
independent channels** with automatic mutual fallback:

- **EWS** (SOAP over HTTPS, via VPN) — primary channel when the VPN is up
- **EAS** (ActiveSync, direct from internet) — fallback when the VPN is down

A single process exposes the usual `exchange_*` MCP tools. Clients
(n8n, Claude) see a stable contract and don't know which channel served
the request. State (per-folder cursors + Message-ID LRU for dedup) is
shared between the two channels, so channel switches never lose or
duplicate mail.

## Layout

```
Dockerfile
docker-compose.yml
requirements.txt
.env.example
exchange_mcp/
  config.py           # pydantic-settings
  auth.py             # X-API-Key middleware
  state.py            # AtomicJSONState + per-folder cursor + Message-ID LRU
  backends/
    base.py           # MailBackend protocol + DTO
    ews.py            # exchangelib-based driver
    eas.py            # wrapper around the patched eas_client.py
  eas_client.py       # ported EAS WBXML client (with hardening fixes)
  router.py           # MailRouter: preferred/fallback, healthcheck, dedup
  health.py           # GET /health
  mcp_server.py       # FastMCP registration
  rest_api.py         # /api/v1/* REST mirror
  main.py             # FastAPI + FastMCP mount
  tools/
    __init__.py       # ALL_TOOLS
    folders.py
    mail.py
    calendar.py
    contacts.py
    attachments.py
```

## Quick start

```bash
cp .env.example .env
# fill in EXCHANGE_USER, EXCHANGE_PASSWORD, MCP_API_KEY
docker compose up -d
curl http://127.0.0.1:8903/health
```

Endpoints:

- `GET /health` — unauthenticated, shows both channels' status
- `POST /mcp` — MCP transport (requires `X-API-Key` or `Authorization: Bearer ...`)
- `GET /docs` — Swagger for the REST mirror

## Status

v0.1 skeleton. Working:

- `/health` with real EWS + EAS reachability checks
- `exchange_list_folders` (EWS)
- `exchange_get_new_emails` (router: EWS primary, EAS fallback, dedup by
  `InternetMessageId`, per-folder timestamp cursor)

Stubs / TODO:

- `exchange_get_emails` (non-incremental listing)
- `exchange_get_calendar` / `exchange_get_new_events`
- `exchange_get_contacts`
- `exchange_search_emails`
- `exchange_send_email`, `exchange_create_event`
- `exchange_get_attachment`
- REST mirror
- Unit tests

## Design notes

See the plan document that spawned this scaffold
(`/root/.claude/plans/polymorphic-hugging-rabbit.md` in the session
where this was generated). Key decisions:

- State is tracked by **timestamp + Message-ID**, not by native
  SyncKey / SyncState. That lets the two channels share one cursor
  and survives SyncKey resets with zero data loss.
- Preferred backend is decided per-request with a 60-second cached
  healthcheck; a single failure flips preference until the next
  healthcheck clears it.
- EAS hardening (atomic state, retries, `reset_needed` on Status=3/12,
  RLock, narrow excepts) lives in the ported `eas_client.py`. It was
  originally committed on the `eas-mcp-server` repo, branch
  `claude/analyze-email-detection-VU9rq`.
