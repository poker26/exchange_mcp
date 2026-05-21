# RFC 0001: перенос и обновление календарных событий (EWS)

| Поле | Значение |
| --- | --- |
| **Репозиторий** | [poker26/exchange_mcp](https://github.com/poker26/exchange_mcp) |
| **Статус** | Implemented |
| **Дата** | 2026-05-21 |
| **Затронутые области** | `exchange_mcp/tools/calendar.py`, `exchange_mcp/router.py`, `exchange_mcp/backends/ews.py`, MCP-схема инструментов |

## Резюме

Сервер поддерживает обновление существующего элемента календаря через MCP-инструмент `exchange_update_event` (EWS `UpdateItem` / exchangelib `save()`).

## Публичный контракт MCP

### Инструмент: `exchange_update_event`

См. docstring в `exchange_mcp/tools/calendar.py`.

#### Упрощённые значения для `send_meeting_invitations`

| Алиас MCP | exchangelib |
| --- | --- |
| `to_all` (по умолчанию) | `SendToAllAndSaveCopy` |
| `to_changed` | `SendToChangedAndSaveCopy` |
| `save_only` | `SendToNone` |

#### Успешный ответ

```json
{
  "backend": "ews",
  "status": "updated",
  "event": { }
}
```

#### Коды ошибок

| Код | Условие |
| --- | --- |
| `INVALID_TIME_RANGE` | `end` ≤ `start` после нормализации |
| `EVENT_NOT_FOUND` | элемент не найден |
| `NOT_A_CALENDAR_ITEM` | объект не календарный |
| `RECURRENCE_UNSUPPORTED` | повторяющиеся события (MVP) |
| `EWS_FAULT` | прочий сбой EWS |
| `INVALID_SEND_MEETING` | неизвестный алиас рассылки |
| `NO_FIELDS_TO_UPDATE` | не передано ни одного поля для изменения |
| `FIELD_TOO_LONG` | превышен лимит `subject` / `body` |

Полная спецификация хранится в MinIO: `rfc/exchange_mcp/0001-calendar-update-reschedule.md`.
