# Exchange MCP — развёртывание и отладка (EWS)

MCP-сервер для почты Exchange через **EWS** только. Порт: **8903**.

## Локальная копия

`C:\Users\hippo\exchange_mcp` — https://github.com/poker26/exchange_mcp

## Перед запуском

1. В `.env` задайте **`EXCHANGE_PASSWORD`**.
2. **`MCP_API_KEY`** — случайная строка (`openssl rand -hex 32`).
3. EWS доступен по **`EWS_URL`** с хоста, где крутится контейнер (VPN не нужен, если `mail.inplatlabs.ru` резолвится и открыт 443).

## Проверка EWS (на сервере)

```bash
curl -s http://127.0.0.1:8903/health | python3 -m json.tool
```

Успех:

```json
"status": "ok",
"ews": { "ok": true, "last_error": null }
```

Ошибка: `"status": "down: …"` — смотрите `ews.last_error` (пароль, URL, SSL, сеть).

Прямая проверка URL с сервера:

```bash
curl -k -s -o /dev/null -w "%{http_code}\n" https://mail.inplatlabs.ru/EWS/Exchange.asmx
```

Ожидается **401** или **200** (не timeout / connection refused).

## Развёртывание на Debian

```bash
cd /opt/exchange_mcp
git pull
cp .env.example .env
nano .env
```

В `.env`: `EXCHANGE_PASSWORD`, `MCP_API_KEY`, `STATE_DIR=/app/state`, `SERVER_HOST=0.0.0.0`.

```bash
docker compose up -d --build
docker compose logs -f exchange-mcp
```

```bash
curl -s http://127.0.0.1:8903/health
```

## Отладка

| Симптом | Что проверить |
|--------|----------------|
| `down: Unauthorized` | `EXCHANGE_USER`, `EXCHANGE_PASSWORD` |
| SSL / certificate | `SSL_VERIFY=false` или путь к CA |
| timeout | DNS, firewall 443 до `mail.inplatlabs.ru` |
| `401` на curl к EWS | нормально без auth; главное — не timeout |

Логи:

```bash
docker compose logs -f --tail=200 exchange-mcp
```

Состояние: `./state/router_state.json` (курсоры и dedup).

## MCP / Cursor

```json
{
  "mcpServers": {
    "exchange": {
      "type": "http",
      "url": "https://ВАШ_ХОСТ:8903/mcp/",
      "headers": { "X-API-Key": "<MCP_API_KEY>" }
    }
  }
}
```

## Обновление

Windows: правки → `git push`. На сервере:

```bash
cd /opt/exchange_mcp
git pull
docker compose up -d --build
```
