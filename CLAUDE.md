# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Что это

Telegram-бот для русскоязычного SMM-канала про AI/tech. По кнопке (или по cron) генерирует пост через Anthropic Claude с native `web_search`, шлёт превью админам, после одобрения публикует в канал с OG-картинкой источника.

## Команды

Зависимости и запуск через `uv` (Python 3.12+):

```bash
uv sync                                  # установить deps из pyproject + uv.lock
uv run python -m src.main                # запустить бота (polling)
uv run ruff check src/                   # линтер (E, F, I, B, UP, ASYNC, line-length 100)
uv run ruff format src/                  # автоформат

# Изолированно проверить отдельные компоненты:
uv run python -m src.agent.news_agent    # один прогон агента → JSON в stdout
uv run python -m src.media.og_image <URL>  # тест OG-image экстрактора
```

Тестов в репо нет. Перед мерджем — `ruff check` обязательно (CI/префлайтов сейчас нет, проверки на разработчике).

## Архитектура

### Слои (data flow)

```
Telegram update
   ↓
OwnerOnlyMiddleware (src/bot/middleware.py)  ← фильтр allowed_user_ids
   ↓
aiogram Router (src/bot/handlers.py)
   ├── /generate, menu:* → меню режимов → _run_generation()
   ├── FSM EditState / CronState / ManualGenState — ожидание текстового ввода
   └── callback approve/regen/edit/reject — работают по draft_id
   ↓
generate_post() (src/agent/news_agent.py)
   ├── build_user_prompt(topic?, source_url?) → три ветки промпта
   ├── Anthropic AsyncAnthropic + web_search_20250305 tool
   ├── _scrub_payload() — детерминированная замена «—»/«–» на «,» (модель регулярно срывается)
   ├── _shrink_draft() — если длина body/title/why_it_matters не прошла валидацию, второй вызов без web_search
   └── валидация через PostDraft (pydantic) → AgentResult
   ↓
send_preview_to_users() → _persist_draft() → _do_send_preview()
   ├── fetch_best_image() (src/media/og_image.py) — httpx + BS4, перекодирование Pillow при IMAGE_PROCESS_FAILED
   └── SQLite (src/storage/repo.py) — draft с status='draft'
   ↓
approve → claim_for_publish() (атомарный CAS draft→publishing) → _publish_to_channel() → mark_published()
```

### Источник правды

- **Стиль постов**: `src/agent/prompts.py` — `SYSTEM_PROMPT` целиком определяет «голос канала», антибот-фильтры (запрет тире, штампы, триады с «и»), HTML-разметку Telegram (`<b>`, `<code>`, `<a>`, `<blockquote>`), структуру (title 40–80, body 400–650 жёсткий потолок 700, why_it_matters 80–180). Модели нужны жёсткие лимиты длины из-за Telegram caption (1024).
- **Конфиг рантайма**: `src/config.py` (pydantic-settings, `.env`). `cron_times` хранится в БД (`app_settings`), `.env` — только seed при первом запуске.
- **Cron-расписание** (`src/scheduler.py`): APScheduler, источник правды — БД, `reschedule_cron_times()` пересобирает job'ы при изменении через `/cron`.

### Anthropic API — ключевые детали

- Модель по умолчанию `claude-sonnet-4-5` (см. `ANTHROPIC_MODEL`).
- `SYSTEM_PROMPT` помечен `cache_control: {type: "ephemeral"}` — кеш 5 мин, повторный `/generate` платит ~10% от input. **Не меняй SYSTEM_PROMPT каждый вызов** — это инвалидирует кеш. Меняется только `user_prompt` (через `build_user_prompt`).
- `web_search_20250305` server tool: `max_uses` из `WEB_SEARCH_MAX_USES`, локализация — `WEB_SEARCH_COUNTRY`.
- Расходы трекаются локально в таблице `api_usage` (`src/agent/pricing.py` + `repo.record_api_usage`), доступны через `/status`.

### Режимы генерации (build_user_prompt)

`generate_post()` принимает три взаимоисключающих набора kwargs:
- **default** — `exclude_urls` + `exclude_topics`, поиск по AI-тематике системного промпта.
- **topic** (`topic="..."`) — override AI-тематики, пользовательская тема/бриф; exclude_*-фильтры остаются.
- **source_url** (`source_url="..."`) — пишем пост по конкретной статье; `exclude_*` обнуляются на уровне `_run_generation` (источник выбран явно).

Cron всегда работает в default-режиме.

### Гонки и идемпотентность

- **Двойная публикация**: оба админа получают один и тот же `draft_id`. `claim_for_publish()` — атомарный `UPDATE ... WHERE status='draft'` с проверкой `cursor.rowcount`. Кто первый — публикует, второй получает «Уже обработано».
- **Перегенерация**: `mark_rejected()` сначала, потом новый `generate_post`. Это гарантирует, что заголовок отвергнутого черновика попадёт в `exclude_topics` следующего вызова и модель не выдаст ту же новость.
- **Антидубль тем**: `repo.recent_topics()` (7 дней, 30 шт) + `recent_source_urls()` (14 дней, 50 шт) подаются в `build_user_prompt`.

### Telegram quirks

- Caption-лимит 1024 — поэтому `body` в схеме ограничен сверху и валидатор отбивает длинные посты. См. `tg_format.fits_caption()` и фолбэки в `_publish_to_channel()` / `_do_send_preview()`.
- `IMAGE_PROCESS_FAILED` от Telegram на JPEG/WebP с подменённым расширением — лечится `media/og_image.normalize_for_telegram()` (Pillow → baseline JPEG). Retry один раз, дальше — фолбэк на текст с `LinkPreviewOptions`.
- Постпроцессор `_strip_dashes` в `news_agent.py` — детерминированная замена тире, не убирай: модель срывается на «—» даже при явном запрете.

### БД

SQLite через `aiosqlite`, файл `./data/smm.db` (в Docker — `/data/smm.db`, volume). Миграции — простой `CREATE TABLE IF NOT EXISTS` + `_ensure_column` для добавления полей (см. `src/storage/db.py`). Таблицы: `drafts`, `published`, `app_settings` (key/value, в т.ч. cron_times), `api_usage`.

### Стиль кода

- Ruff правила: `E, F, I, B, UP, ASYNC`, line-length 100, target-version `py312`. `from __future__ import annotations` во всех модулях.
- Логирование — loguru, формат `"{}"` (не f-strings), уровень из `LOG_LEVEL`.
- Async везде: aiogram, aiosqlite, httpx.AsyncClient, anthropic.AsyncAnthropic.
- Без эмодзи в коде/комментах (кроме UI-строк Telegram, где они нужны для кнопок).

## Деплой

Dockerfile собирается через `uv pip install --system .`, рантайм-пользователь `app:app`, volume `/data` для SQLite. На Dokploy: Application → Docker, переменные из `.env.example`, volume `/data`.

## История изменений и соглашения

- Коммиты в `main` напрямую (push без PR). Стиль сообщений — русский, в imperative или substantive: `feat: ...`, `chore: ...`, `agent: ...`.
- `Co-Authored-By: Claude ...` в коммитах, сделанных совместно с агентом.
