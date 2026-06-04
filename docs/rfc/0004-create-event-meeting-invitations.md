# RFC 0004: `exchange_create_event` отправляет meeting request при `attendees`

| Поле | Значение |
| --- | --- |
| **Статус** | Implemented |
| **Дата** | 2026-06-04 |
| **Приоритет** | High |

## Проблема

`event.save()` вызывался без `send_meeting_invitations` (default `SendToNone`). Событие сохранялось как appointment с локальным списком участников, без рассылки meeting request.

## Решение

- При непустом `attendees`: `save(send_meeting_invitations=SendToAllAndSaveCopy)`, `is_response_requested=True`.
- Параметр `send_meeting_invitations`: `to_all` (default), `to_changed`, `save_only`.
- После save — `refresh()` и ответ через `CalendarEventDetail`.
- Если ожидалась рассылка, но `is_meeting=false` — ошибка `INVITATIONS_NOT_SENT`.

## Ответ API

```json
{
  "status": "created",
  "invitations_sent": true,
  "send_meeting_invitations": "to_all",
  "event": {
    "is_meeting": true,
    "required_attendees": [{"email": "...", "response": "unknown"}],
    "attendees": ["..."]
  }
}
```

## Read API

`exchange_get_calendar` с профилем `full` возвращает участников; при `standard`/`minimal` — `attendees_loaded: false`.
