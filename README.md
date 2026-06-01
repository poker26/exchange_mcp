# Exchange MCP (EWS)

MCP server for an on-premise Exchange mailbox via **EWS** (Exchange Web
Services, HTTPS). No ActiveSync fallback.

Clients (n8n, Claude) use `exchange_*` tools. Incremental mail uses a
per-folder timestamp cursor and Message-ID LRU for deduplication.

## Layout

```
Dockerfile
docker-compose.yml
requirements.txt
.env.example
exchange_mcp/
  config.py
  auth.py
  state.py
  backends/
    base.py
    ews.py
  router.py           # MailRouter (EWS only)
  health.py           # GET /health
  mcp_server.py
  main.py
  tools/
```

Legacy EAS code (`eas_client.py`, `backends/eas.py`) remains in the tree
but is **not used**.

## Quick start

```bash
cp .env.example .env
# fill in EXCHANGE_PASSWORD, MCP_API_KEY (openssl rand -hex 32)
docker compose up -d --build
curl http://127.0.0.1:8903/health
```

Подробнее: **`INSTRUCTIONS.md`**.

Endpoints:

- `GET /health` — EWS reachability (no auth)
- `POST /mcp` — MCP transport (`X-API-Key` or `Authorization: Bearer …`)

## Status (v0.6)

Working (EWS):

- Mail: list/new/get/search/send, mark read, delete, move, reply, forward
- Calendar: get/new/create/update, respond (accept/decline/tentative)
- Calendar delete: single occurrence or entire series (`delete_series`)
- Scheduling: search contacts, get availability, suggest meeting times (see `AGENTS.md`)
- Meeting invites: forward event, update attendees, get event detail (RFC 0003)
- Contacts, folders, list/download attachments (10 MB cap)

Calendar update: see `docs/rfc/0001-calendar-update-reschedule.md`.

Run tests: `pytest`

TODO: REST mirror.

## Design notes

- State: **timestamp cursor + Message-ID LRU**, not EWS SyncState.
- EWS is reachable over HTTPS from the host running the container (VPN
  no longer required for this deployment).
