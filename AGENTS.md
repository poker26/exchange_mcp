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
| `exchange_create_event` | Создать встречу с `attendees` после выбора слота |
| `exchange_update_event` | Перенести встречу (`start`/`end` в ISO) |
| `exchange_get_calendar` | Детали **календаря организатора** (тема, тело); не заменяет free/busy коллег |

### Удаление события (двухшагово, обязательно)

**Никогда** не вызывайте `exchange_delete_event` без явного согласия пользователя в чате.

1. `exchange_prepare_delete_event(event_id)` — показать пользователю preview (`subject`, `start`, `end`) и `confirmation_id`.
2. Дождаться, пока пользователь **сам напишет** в чате точную фразу из `required_phrase` (по умолчанию **`ДА, УДАЛИТЬ`**).
3. `exchange_delete_event(event_id, confirmation_id, user_confirmation="ДА, УДАЛИТЬ")` — только с той же фразой.

Без шага 1–2 сервер вернёт `CONFIRMATION_EXPIRED_OR_UNKNOWN` или `USER_CONFIRMATION_REQUIRED`.

## Что НЕ использовать для планирования

| Инструмент | Почему |
| --- | --- |
| `exchange_get_new_events` | Incremental sync для n8n/Telegram |
| `exchange_respond_to_event` | Ответ на входящее приглашение |
| `exchange_get_contacts` | Полный список без поиска — неудобен для имён |
| `exchange_search_emails` | Fallback: сверить SMTP по переписке, если GAL дал сомнительный адрес |

## Ограничения (важно)

- **Free/busy** запрашивается у Exchange для любого SMTP; `calendar_status: external` — только когда EWS явно отказал (Gmail/Yandex и т.п.).
- Агент видит **занятость**, не темы чужих встреч (политика Exchange).
- Повторяющиеся серии при `exchange_update_event` пока не поддерживаются (`RECURRENCE_UNSUPPORTED`).
- Окно availability/suggest — **максимум 14 дней**.

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

## Деплой и обновление схемы MCP

После `git pull` на сервере: `docker compose up -d --build`, затем **Reload MCP** в Cursor.

Подробности: `INSTRUCTIONS.md`, RFC: `docs/rfc/0002-meeting-scheduling-availability.md`.
