# Exchange MCP — развёртывание и отладка

Гибридный MCP-сервер (EWS + EAS) для почты Exchange. Порт по умолчанию: **8903**.

## Локальная копия

Репозиторий: `C:\Users\hippo\exchange_mcp` (клон с https://github.com/poker26/exchange_mcp).

## Перед запуском

1. Откройте `.env` и задайте **`EXCHANGE_PASSWORD`** (пароль доменной учётки).
2. При необходимости смените **`MCP_API_KEY`** (`openssl rand -hex 32` на Linux или любой генератор на Windows).
3. На **прод-сервере** (Debian) контейнер использует `network_mode: host` и VPN — EWS доступен через tun0, EAS — напрямую из интернета.

## Развёртывание на прод-сервере (Debian)

Выполните на сервере (не на Windows):

```bash
cd /opt
git clone https://github.com/poker26/exchange_mcp.git
cd exchange_mcp
cp .env.example .env
nano .env
```

В `.env` на сервере:

- `EXCHANGE_PASSWORD` — рабочий пароль
- `MCP_API_KEY` — длинный случайный ключ
- `STATE_DIR=/app/state` (как в `.env.example`)
- `SERVER_HOST=0.0.0.0`

Сборка и запуск:

```bash
docker compose up -d --build
docker compose logs -f exchange-mcp
```

Проверка (на сервере):

```bash
curl -s http://127.0.0.1:8903/health | python3 -m json.tool
```

Ожидаемый ответ: `status` = `ok` или `degraded` (один из каналов), блок `channels.ews` / `channels.eas` с `"ok": true/false`.

## Отладка

### Health

```bash
curl -s http://127.0.0.1:8903/health
```

- **EWS `ok: false`** — нет VPN / неверный `EWS_URL` / пароль / SSL.
- **EAS `ok: false`** — хост недоступен, неверный `EXCHANGE_USER` / пароль, блокировка устройства `EAS_DEVICE_ID`.
- **`degraded`** — работает один канал; роутер использует fallback.

### MCP (с API-ключом)

```bash
curl -s -H "X-API-Key: ВАШ_MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  http://127.0.0.1:8903/mcp/
```

### Инструменты (через клиент MCP)

| Инструмент | Статус v0.1 |
|------------|-------------|
| `exchange_list_folders` | работает (EWS) |
| `exchange_get_new_emails` | работает (EWS + EAS, dedup) |
| `exchange_get_emails` | ограниченно (окно ~31 день) |
| `exchange_send_email` | EWS |
| остальные | заглушки |

### Логи

```bash
docker compose logs -f --tail=200 exchange-mcp
```

### Состояние (курсоры / dedup)

Каталог `./state` на хосте (volume): `router_state.json`, `eas_internal_state.json`.

Сброс курсора для папки — удалить запись папки в `router_state.json` (осторожно: возможен повтор старых писем).

## Cursor / Claude (`mcp.json`)

```json
{
  "mcpServers": {
    "exchange": {
      "type": "http",
      "url": "https://ВАШ_ХОСТ:8903/mcp/",
      "headers": {
        "X-API-Key": "<MCP_API_KEY из .env>"
      }
    }
  }
}
```

## n8n MCP Client

- URL: `http://<host>:8903/mcp/` (слэш в конце)
- Transport: HTTP Streamable
- Header: `X-API-Key: <ключ>`

## Обновление после `git pull` на сервере

```bash
cd /opt/exchange_mcp
git pull
docker compose up -d --build
```

На Windows после правок: `git push`, на сервере — `git pull` и пересборка контейнера.

## Локальная разработка (Windows)

Полный доступ к Exchange с рабочей станции обычно **недоступен** (EWS через VPN). Для проверки импортов:

```powershell
cd C:\Users\hippo\exchange_mcp
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
$env:PYTHONPATH = "C:\Users\hippo\exchange_mcp"
.venv\Scripts\python -c "from exchange_mcp.main import create_app; create_app()"
```

Запуск HTTP-сервера локально — только если есть VPN к `mail.inplatlabs.ru`; иначе отладка на Debian.
