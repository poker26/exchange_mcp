# RFC 0003: календарные приглашения — forward, участники, детали события

| Поле | Значение |
| --- | --- |
| **Репозиторий** | [poker26/exchange_mcp](https://github.com/poker26/exchange_mcp) |
| **Статус** | Implemented |
| **Дата** | 2026-06-01 |
| **Зависимости** | exchangelib ≥ 5.4, RFC 0001 (update event) |

## Контекст

Exchange MCP умеет читать календарь, создавать/обновлять/удалять события и отвечать на приглашения. Не хватало операций Outlook: **переслать приглашение**, **добавить участника**, **получить полный список участников**.

`exchange_forward_email` не работает для calendar item (`item is not an email message`).

## Новые MCP-инструменты

### `exchange_forward_event`

Пересылает календарное событие как meeting forward (кнопки Accept/Tentative/Decline у получателя).

| Параметр | Обяз. | Описание |
| --- | --- | --- |
| `event_id` | да | id из `exchange_get_calendar` |
| `to` | да | SMTP получателей |
| `body` | нет | Комментарий к пересылке |
| `body_is_html` | нет | default false |
| `dry_run` | нет | default false — preview без отправки |
| `recurrence_scope` | нет | `single_occurrence` (default) или `series` |

### `exchange_update_event_attendees`

Добавляет/удаляет участников с рассылкой meeting update.

| Параметр | Обяз. | Описание |
| --- | --- | --- |
| `event_id` | да | id события |
| `add_required` | нет | email → RequiredAttendees |
| `add_optional` | нет | email → OptionalAttendees |
| `remove` | нет | удалить по email |
| `send_meeting_invitations` | нет | `to_changed` (default), `to_all`, `save_only` |
| `comment` | нет | зарезервировано (MVP: не меняет body) |
| `dry_run` | нет | preview изменений |
| `recurrence_scope` | нет | `single_occurrence` или `series` |

### `exchange_get_event`

Детали одного события с `required_attendees`, `optional_attendees`, `resources`, `is_meeting`.

## Коды ошибок

| Код | Условие |
| --- | --- |
| `EVENT_NOT_FOUND` | нет item по id |
| `NOT_A_CALENDAR_ITEM` | не CalendarItem |
| `NOT_ORGANIZER` | правка участников не организатором |
| `CAN_FORWARD_ONLY` | forward недоступен для этого типа |
| `INSUFFICIENT_PERMISSIONS` | EWS отказ по правам |
| `RECURRENCE_SCOPE_REQUIRED` | нужен occurrence id или `series` |
| `NO_ATTENDEE_CHANGES` | пустой запрос на update attendees |
| `INVALID_SEND_MEETING` | неверный alias рассылки |
| `EWS_FAULT` | прочий сбой EWS |

## Агенты

См. **`AGENTS.md`** — раздел «Календарные приглашения».
