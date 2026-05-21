# n8n: Exchange MCP → Telegram + Yandex CalDAV

Файл: `exchange-emails-events-telegram-yandex.json`

## Импорт

1. n8n → **Workflows** → **Import from file**
2. MCP: `http://46.173.19.68:8903/mcp/`, credential **Header Auth Exchange_work**
3. S3: credential **S3 account** (ваш MinIO), bucket **`exchange-mail-transit`**
4. Telegram / Yandex CalDAV — как раньше

## Схема

```
Every 5 min ─┬─ MCP get_new_emails ─ Format ─┬─ TG текст письма
             │                              └─ MCP list/get attachment ─ S3 upload ─ TG файл
             └─ MCP get_new_events ─ Format ─┬─ TG событие
                                            └─ CalDAV PUT
```

## Вложения (S3 / MinIO)

Цепочка в n8n (без MinIO в exchange_mcp):

1. `exchange_list_attachments(item_id)`
2. `exchange_get_attachment` → base64
3. **S3 Upload** → transit bucket (архив / TTL на стороне MinIO)
4. **Telegram sendDocument** — из binary (не нужен публичный URL)

Inline-картинки в HTML пропускаются; файловые вложения до **10 MB** (лимит EWS).

## Отладка MCP-ответа

`content[0].text` может быть объектом или JSON-строкой — Code-ноды поддерживают оба формата.

## Отличия от EAS_MCP

| Было (EAS) | Стало |
|------------|--------|
| HTTP `/api/new_emails` | MCP `exchange_get_new_emails` |
| presigned URL из easmcp | S3-нода n8n + ваш **S3 account** |
| ICS из письма | нет |
| CalDAV DELETE | нет (EWS incremental) |

Опционально в exchange_mcp остаётся `stage_attachments` + MinIO в `.env` — для n8n **не нужно**.
