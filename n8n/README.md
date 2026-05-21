# n8n: Exchange MCP → Telegram + Yandex CalDAV

Файл: `exchange-emails-events-telegram-yandex.json`

## Импорт

1. n8n → **Workflows** → **Import from file**
2. MCP: `http://46.173.19.68:8903/mcp/`, credential **Header Auth Exchange_work**
3. Telegram / Yandex CalDAV — как раньше

## Схема

```
Every 5 min ─┬─ MCP get_new_emails ─ Format ─┬─ TG текст письма
             │                              └─ MCP list/get attachment ─ Attach Binary ─ TG файл
             └─ MCP get_new_events ─ Format ─┬─ TG событие (📅 / ✏️ / ❌)
                                            ├─ CalDAV PUT (новые и изменённые)
                                            └─ CalDAV DELETE (отмена / удаление)
```

## Календарь → Yandex (полная синхronизация)

MCP `exchange_get_new_events` возвращает:

| Поле | Действие в n8n |
|------|----------------|
| `added` | 📅 Telegram + CalDAV PUT |
| `changed` | ✏️ Telegram + CalDAV PUT (время, тема, описание, ссылки) |
| `deleted` | ❌ Telegram + CalDAV DELETE |
| `is_initial: true` | прогрев state, без TG/CalDAV (первый запуск) |

Код Format Events: `format-events.js`. После правок — `python n8n/patch_workflow.py`.

## Вложения

Цепочка в n8n (без MinIO в exchange_mcp):

1. `exchange_list_attachments(item_id)`
2. `exchange_get_attachment` → base64
3. **Attach Binary** → **Telegram sendDocument**

Inline-картинки в HTML пропускаются; файловые вложения до **10 MB** (лимит EWS).

## Отладка MCP-ответа

`content[0].text` может быть объектом или JSON-строкой — Code-ноды поддерживают оба формата.

## Отличия от EAS_MCP

| Было (EAS) | Стало |
|------------|--------|
| HTTP `/api/new_emails` | MCP `exchange_get_new_emails` |
| HTTP `/api/new_events` | MCP `exchange_get_new_events` (added/changed/deleted) |
| CalDAV PUT + DELETE | CalDAV PUT + DELETE (через Format Events) |

Опционально в exchange_mcp остаётся `stage_attachments` + MinIO в `.env` — для n8n **не нужно**.
