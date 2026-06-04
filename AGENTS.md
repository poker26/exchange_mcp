# Exchange MCP — руководство для AI-агентов

Документ описывает **календарное планирование встреч** через MCP-сервер `exchange_mcp`. Читайте его, когда пользователь просит назначить, перенести или подобрать время созвона.

## Типичный запрос пользователя

> «Назначь встречу с Ивановым и Петровым на 45 минут на этой неделе, когда всем удобно.»

## Рекомендуемый pipeline

```
1. exchange_search_contacts("иванов")     → email (+ emails[] если несколько)
2. exchange_search_contacts("петров")     → email
   └─ если emails[] содержит разные домены (instant-pay.ru vs fin-frame.ru):
      • предпочитайте домен организатора (поле email уже выбрано автоматически)
      • при сомнении: exchange_search_emails("from:фамилия") → сверить адрес
      • или уточните у пользователя
3. exchange_suggest_meeting_times(...)    → 3–5 слотов
4. Спросить пользователя / выбрать слот
5. exchange_create_event(..., attendees=[...])
```

Для **переноса** уже существующей встречи после согласования:

```
exchange_update_event(event_id, start=..., end=...)
```

## Инструменты планирования (RFC 0002)

### `exchange_search_contacts`

**Когда:** нужно превратить имя человека в SMTP-адрес.

| Параметр | Описание |
| --- | --- |
| `query` | Подстрока имени или email, **минимум 2 символа** |
| `max_items` | 1–50, по умолчанию 20 |

**Ответ:** `contacts[]` с полями `email` (предпочтительный SMTP), `emails` (все адреса из GAL), `display_name`, `id`.

**Ошибки:** `QUERY_TOO_SHORT`.

Если несколько совпадений — **уточните у пользователя**, не угадывайте email.

GAL иногда возвращает устаревший домен (`@instant-pay.ru` вместо `@fin-frame.ru`). Поле `email` уже предпочитает домен организатора; если сомневаетесь — проверьте через `exchange_search_emails` или спросите пользователя.

---

### `exchange_suggest_meeting_times` (основной)

**Когда:** подобрать общее свободное время для нескольких участников.

| Параметр | Описание |
| --- | --- |
| `attendees` | Список email; организатор (ящик MCP) добавляется автоматически |
| `date_from`, `date_to` | ISO-окно поиска; **не больше 14 суток** |
| `duration_minutes` | Длительность 15–480 |
| `timezone` | IANA, по умолчанию `Europe/Moscow` (или `CALENDAR_TIMEZONE` в `.env`) |
| `max_suggestions` | Сколько слотов вернуть (1–20, default 5) |
| `working_hours_start` / `working_hours_end` | Локальные границы дня, default `09:00`–`18:00` |
| `working_days` | Например `["monday","tuesday",...]`; default пн–пт |
| `buffer_minutes` | Отступ вокруг занятых блоков |

**Ответ:**

- `suggestions[]` — `{ start, end, score, all_attendees_free }`
- `partial: true` — у части участников нет данных (внешний домен, not_found)
- `unresolved_attendees[]` — проблемные ящики

**Правила для агента:**

- Показывайте пользователю **2–5 лучших слотов** в его часовом поясе.
- Если `all_attendees_free: false` при `partial: true` — предупредите, что данные неполные.
- **Не создавайте** встречу без явного выбора пользователя.

---

### `exchange_get_availability` (опционально)

**Когда:** нужна сырая занятость (отладка, кастомная логика), а не готовые слоты.

Возвращает `attendees[].busy[]` с `status`: `busy`, `tentative`, `oof`, `working_elsewhere`, `no_data`.

Per-attendee проблемы — в `errors[]`, запрос не падает целиком.

---

### Уже существующие инструменты

| Инструмент | Роль |
| --- | --- |
| `exchange_create_event` | Создать встречу; при `attendees` по умолчанию рассылает meeting request (`to_all`). Проверка: `get_event` → `is_meeting: true` |
| `exchange_update_event` | Перенести встречу (`start`/`end` в ISO) |
| `exchange_get_calendar` | Детали **календаря организатора** (тема, тело); не заменяет free/busy коллег |

### Удаление события (двухшагово, обязательно)

**Никогда** не вызывайте `exchange_delete_event` без явного согласия пользователя в чате.

1. `exchange_prepare_delete_event(event_id)` — показать пользователю preview (`subject`, `start`, `end`) и `confirmation_id`.
   - Для **одного occurrence** серии — `event_id` конкретного экземпляра из `exchange_get_calendar`.
   - Для **всей серии** — `delete_series=true` и id master-события.
2. Дождаться, пока пользователь **сам напишет** в чате точную фразу из `required_phrase` (по умолчанию **`ДА, УДАЛИТЬ`**).
3. `exchange_delete_event(event_id, confirmation_id, user_confirmation="ДА, УДАЛИТЬ", delete_series=...)` — с теми же `event_id` и `delete_series`, что в prepare.

Без шага 1–2 сервер вернёт `CONFIRMATION_EXPIRED_OR_UNKNOWN` или `USER_CONFIRMATION_REQUIRED`.

## Календарные приглашения (RFC 0003)

### Переслать встречу коллеге (полноценный invite)

**Не используйте** `exchange_forward_email` для событий календаря — будет ошибка `not an email message`.

```
1. exchange_get_calendar(...) или exchange_get_event(event_id)  → найти встречу
2. exchange_search_contacts("моисеев")  → email
3. exchange_forward_event(event_id, to=[email], dry_run=true)   → показать preview
4. После согласия: exchange_forward_event(..., dry_run=false)
```

### Добавить участника во встречу

```
1. exchange_get_event(event_id)  → текущие required_attendees / optional_attendees
2. exchange_update_event_attendees(
     event_id,
     add_required=["new@fin-frame.ru"],
     send_meeting_invitations="to_changed",
     dry_run=true
   )
3. После согласия: то же с dry_run=false
```

По умолчанию `send_meeting_invitations=to_changed` — уведомление только новым/изменённым, без спама всех.

### `exchange_get_event`

Детали **одного** события: участники с ролями, `response` (accepted/decline/…), `is_meeting`, `location`, `body`.

### `exchange_forward_event` / `exchange_update_event_attendees`

| Параметр | Описание |
| --- | --- |
| `dry_run` | `true` — preview, без отправки в Exchange |
| `recurrence_scope` | `single_occurrence` (default) или `series` |

| Код ошибки | Значение |
| --- | --- |
| `NOT_ORGANIZER` | Менять участников может только организатор |
| `CAN_FORWARD_ONLY` | Объект нельзя переслать как meeting |
| `INSUFFICIENT_PERMISSIONS` | EWS отказал по правам |
| `NO_ATTENDEE_CHANGES` | Пустой запрос на изменение участников |

## Что НЕ использовать для планирования

| Инструмент | Почему |
| --- | --- |
| `exchange_get_new_events` | Incremental sync для n8n/Telegram |
| `exchange_respond_to_event` | Ответ на входящее приглашение |
| `exchange_get_contacts` | Полный список без поиска — неудобен для имён |
| `exchange_search_emails` | Fallback: сверить SMTP по переписке, если GAL дал сомнительный адрес |
| `exchange_forward_email` | Только письма; для встреч — `exchange_forward_event` |

## Ограничения (важно)

- **Free/busy** запрашивается у Exchange для любого SMTP; `calendar_status: external` — только когда EWS явно отказал (Gmail/Yandex и т.п.).
- Агент видит **занятость**, не темы чужих встреч (политика Exchange).
- **`recurrence_role`** в ответах календаря: `single`, `occurrence`, `exception`, `series_master`.
- `exchange_update_event` работает для одиночных событий и отдельных occurrence; правило повторения (RRULE) не редактируется.
- Окно availability/suggest — **максимум 14 дней**.
- **`ORG_ACCEPTED_DOMAINS`** в `.env` — список «своих» SMTP-доменов для выбора email в `search_contacts` (default: домен организатора).

## Пример вызовов

**Поиск:**

```json
{ "query": "наумов", "max_items": 10 }
```

**Подбор слотов на неделю, 45 минут:**

```json
{
  "attendees": ["colleague@fin-frame.ru"],
  "date_from": "2026-05-19",
  "date_to": "2026-05-23",
  "duration_minutes": 45,
  "timezone": "Europe/Moscow",
  "max_suggestions": 5
}
```

**Создание после выбора:**

```json
{
  "subject": "Созвон с коллегой",
  "start": "2026-05-20T11:00:00+03:00",
  "end": "2026-05-20T11:45:00+03:00",
  "attendees": ["colleague@fin-frame.ru"]
}
```

## Коды ошибок scheduling

| Код | Значение |
| --- | --- |
| `QUERY_TOO_SHORT` | Короткий поиск контактов |
| `INVALID_TIME_RANGE` | Неверное окно или > 14 дней |
| `INVALID_ATTENDEE` | Пустой или невалидный email |
| `TOO_MANY_ATTENDEES` | Больше 100 участников |
| `INVALID_DURATION` | duration вне 15–480 |
| `INVALID_TIMEZONE` | Неизвестная IANA TZ |
| `EWS_FAULT` | Сбой Exchange (на уровне запроса) |

## Коды ошибок календаря (delete/update)

| Код | Значение |
| --- | --- |
| `RECURRENCE_SCOPE_REQUIRED` | Удаление master-серии без `delete_series=true` |
| `DELETE_SERIES_MISMATCH` | `delete_series` в delete не совпал с prepare |
| `CONFIRMATION_EXPIRED_OR_UNKNOWN` | Нет или протух `confirmation_id` |
| `USER_CONFIRMATION_REQUIRED` | Пользователь не написал фразу подтверждения |

После `git pull` на сервере: `docker compose up -d --build`, затем **Reload MCP** в Cursor.

Подробности: `INSTRUCTIONS.md`, RFC: `docs/rfc/0002-meeting-scheduling-availability.md`, `docs/rfc/0003-calendar-invitations-forward-attendees.md`.
