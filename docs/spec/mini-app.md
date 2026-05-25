# Spec: Telegram Mini App — админская панель статистики SMM-бота

> **Статус:** Phase 3 — Implement. Tasks 1-11 готовы (11 — code-only, без локального docker build). Task 12 (deploy) ждёт домен и ADMIN_BOT_TOKEN от пользователя.
> **Связан с:** Plan-файл `/Users/penkin/.claude/plans/mini-app-ethereal-kite.md`.
> **История:** см. git log этого файла.

## Прогресс реализации

| # | Задача | Статус | Коммиты |
|---|---|---|---|
| 1 | расширение БД и WAL | ✅ DONE | `8948d5e` (taskwork), `76a3dc1` (FK ON fixup) |
| 2 | audit-события в handlers | ✅ DONE | `c360fcf`, `76a3dc1` (fail-soft + порядок mutate→audit) |
| 3 | reaction handler + allowed_updates | ✅ DONE | `d23d4bb`, `76a3dc1` (chat-id filter) |
| 4 | channel snapshot scheduler job | ✅ DONE | `7950626`, `859ce15` (review fixup) |
| 5 | FastAPI skeleton + auth | ✅ DONE | `5d5b31b`, `859ce15` (HMAC порядок) |
| 6 | FastAPI: posts/channel/reactions routes | ✅ DONE | `d878a5c`, `859ce15` (GROUP BY, status alias) |
| 7 | admin bot | ✅ DONE | `8554ede` |
| 8 | TaskGroup-оркестрация в main.py | ✅ DONE | `75156aa` |
| 9 | frontend bootstrap | ✅ DONE | `e148ea7` |
| 10 | frontend pages | ✅ DONE | `35b3b5b` |
| 11 | Dockerfile multi-stage | ⚠️ CODE-ONLY | `e828cfd` |
| 12 | deploy в Dokploy | 🚧 BLOCKED (нужен вход пользователя) | — |

**Текущая БД-схема и runtime-поведение (актуально на момент Task 3+fixup):**
- 7 таблиц (4 старых + `draft_events`, `post_reactions`, `channel_snapshots`).
- `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=10s`.
- `PRAGMA foreign_keys=ON` в каждом `get_conn()` (через `@asynccontextmanager`).
- `record_draft_event` пишется во всех 5 точках спека через fail-soft `_audit()` helper в handlers.
- Reactions handler фильтрует только канал из `settings.channel_id` (id или `@username`).
- `send_preview_to_users` возвращает `(draft_id, sent_count)`; `cb_regenerate` пишет
  `regenerated_from` только при `sent_count > 0`.

### Что прочитать новой сессии перед продолжением

1. Этот файл целиком — он же source of truth, обновляется при каждом изменении scope.
2. `CLAUDE.md` (project root) — стиль кода, инварианты антибота, layered архитектура.
3. `git log --oneline 87d5720..HEAD` — ровно те коммиты, что добавили mini-app слой.
4. Перед стартом любой следующей таски — `uv run ruff check src/` и smoke по предыдущей таске
   (см. **Verify**-блоки выше).

### Незавершённые решения, нужные перед Task 4-12

- **Task 4:** `CHANNEL_SNAPSHOT_INTERVAL_MINUTES = 60` — решение пользователя
  от 2026-05-25. 24 точки/день, 168 точек на 7-дневном sparkline, нагрузка
  на Bot API копеечная. Дефолт в `config.py` и `.env.example` ставить 60;
  если потом график окажется слишком плоский — снизим до 15 одной правкой
  `.env`, переменная только в job-trigger'е.
- **Task 5+:** домен Mini App и `ADMIN_BOT_TOKEN` (новый бот через @BotFather)
  пока не созданы — это блокирует Task 7 (admin bot) и Task 12 (deploy).
  См. **Open Questions** ниже.

## Объекты ревью

- [x] Объективы и пользовательские истории
- [x] Tech Stack и версии
- [x] Команды (build/dev/lint/test)
- [x] Структура проекта после изменений
- [x] Code Style (Python + TSX примеры)
- [x] Testing Strategy
- [x] Boundaries (Always/Ask first/Never)
- [x] Success Criteria — измеримые, testable
- [x] Open Questions — то, что нужно от пользователя

## Допущения (assumptions)

1. Скоуп — только то, что согласовано в предыдущей беседе: отдельный admin-бот, FastAPI+React+Vite+TS, 3 новые таблицы, без MTProto/user-сессии. Список подписчиков канала, поиск/фильтр по ним, просмотры постов — **вне scope** (Bot API не даёт).
2. Хостинг — тот же Dokploy, тот же контейнер. Traefik в Dokploy терминирует HTTPS.
3. Сохраняется существующее поведение: cron, edit, regenerate, approve, reject, кеширование SYSTEM_PROMPT, антибот-постпроцессор тире — всё работает как раньше.
4. Реакции собираются только для постов, опубликованных **после** деплоя фичи (`message_reaction_count` update не присылается ретроактивно).
5. Spec — living document; обновляется при каждом изменении scope. Коммитится с кодом, ссылается из PR.

---

## Objective

**Что строим.** Telegram Mini App «Админ-панель SMM-бота» — отдельный второй Telegram-бот, кнопка которого открывает встроенный веб-интерфейс. В нём — статистика по сгенерированным постам (с историей правок), общая динамика канала и реакции на опубликованные посты.

**Почему сейчас.** Текущий бот не сохраняет историю изменений драфтов (теряется payload до правки) и не агрегирует реакции с канала. Админам приходится копаться в SQLite руками, чтобы понять, что и кто менял. Mini App даёт единое место для аналитики и снимает рутину.

**Пользовательские истории.**
- *Как админ канала,* я открываю Mini App в отдельном боте и вижу список всех сгенерированных постов с фильтром по статусу и периоду, чтобы быстро найти конкретный пост.
- *Как админ,* я кликаю на пост и вижу его текст + полный timeline событий (создан → отредактирован с диффом → одобрен), чтобы понять, как менялся черновик.
- *Как админ,* я вижу текущее число подписчиков канала и график динамики за 7 дней, чтобы оценивать рост.
- *Как админ,* я вижу топ-10 и анти-топ-10 постов по реакциям, чтобы понимать, что заходит аудитории.
- *Как админ,* я уверен, что никто кроме меня и доверенных пользователей не может открыть Mini App, даже если случайно узнает URL.

**Что значит «успех» (high-level).** Спустя 1 неделю после деплоя я открываю Mini App с телефона, всё рендерится мгновенно, я вижу свежие данные и могу принимать решения о контенте без SQLite-клиента.

---

## Tech Stack

### Backend
- Python `3.12+` (как в проекте)
- `uv` для зависимостей (как в проекте)
- `aiogram` `>=3.13` (есть)
- `aiosqlite` `>=0.20` (есть; добавляем WAL)
- `apscheduler` `>=3.10` (есть; добавляем snapshot job)
- **Новое:** `fastapi` `>=0.115`, `uvicorn[standard]` `>=0.32`

### Frontend (новое)
- `Node.js 20` (только для build-стадии Docker)
- `react` `^18.3.0`
- `react-dom` `^18.3.0`
- `react-router-dom` `^6.27.0`
- `vite` `^5.4.0`
- `typescript` `^5.6.0`

**Принципиальные не-зависимости:** TanStack Query, SWR, Chart.js, recharts, MUI — намеренно не используем (overkill, разрастают бандл). Графики — SVG руками; запросы — `fetch` + `useState`/`useEffect`.

### Infra
- Docker (multi-stage)
- Dokploy (как сейчас) + Traefik (HTTPS auto через Let's Encrypt)
- SQLite (как сейчас, общий том `/data/smm.db`, переключаем в WAL)

---

## Commands

### Python (backend и боты)
```bash
# Установка / обновление зависимостей
uv sync

# Запуск всех сервисов (main bot + admin bot + FastAPI)
uv run python -m src.main

# Линт и автоформат
uv run ruff check src/
uv run ruff format src/

# Точечно проверить генератор постов (без Telegram)
uv run python -m src.agent.news_agent

# Подписать тестовый initData локально (одноразовый скрипт, не коммитим)
uv run python scripts/sign_init_data.py <USER_ID>
```

### Frontend (Mini App)
```bash
# Установка
cd frontend && npm ci

# Dev (vite на :5173, проксирует /api на :8000)
npm run dev

# Production build (→ ../src/webapp/static/ при сборке Docker; локально → ./dist)
npm run build

# Тип-чек (без эмита)
npm run typecheck

# Линт фронта (eslint)
npm run lint
```

### Docker
```bash
# Полная сборка (3 stage)
docker build -t smm-bot .

# Запуск локально
docker run --rm -p 8000:8000 -v $(pwd)/data:/data --env-file .env smm-bot

# Health-check вручную
curl http://localhost:8000/api/health
```

### Локальный e2e (нужен HTTPS-туннель)
```bash
# Cloudflare Tunnel (рекомендуется — стабильный URL)
cloudflared tunnel --url http://localhost:8000

# Альтернатива: ngrok
ngrok http 8000
```

---

## Project Structure

```
.
├── src/                          ← Python-приложение
│   ├── main.py                   [Modified] TaskGroup на 3 сервиса
│   ├── config.py                 [Modified] +5 env-переменных
│   ├── scheduler.py              [Modified] +snapshot job, +gen_mode
│   ├── agent/                    [Unchanged] LLM-логика
│   ├── bot/
│   │   ├── handlers.py           [Modified] +record_draft_event в 5 точках
│   │   ├── middleware.py         [Reused]   OwnerOnlyMiddleware для обоих ботов
│   │   ├── keyboards.py          [Unchanged]
│   │   └── reactions.py          [New]      message_reaction_count handler
│   ├── adminbot/                 [New]      второй бот для Mini App
│   │   ├── __init__.py
│   │   └── bot.py                build_admin_bot() + setup_admin_menu_buttons()
│   ├── webapp/                   [New]      FastAPI и фронт-статика
│   │   ├── server.py             build_webapp(main_bot) → FastAPI
│   │   ├── auth.py               validate_init_data() (HMAC по ADMIN_BOT_TOKEN)
│   │   ├── deps.py               get_current_user dependency
│   │   ├── routes/
│   │   │   ├── health.py
│   │   │   ├── me.py
│   │   │   ├── posts.py
│   │   │   ├── channel.py
│   │   │   └── reactions.py
│   │   └── static/               [Generated at build, gitignored]
│   ├── storage/
│   │   ├── db.py                 [Modified] +DDL, +WAL
│   │   └── repo.py               [Modified] +8 функций
│   ├── media/                    [Unchanged]
│   └── utils/                    [Unchanged]
│
├── frontend/                     [New]
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api.ts                fetch wrapper + X-Telegram-Init-Data header
│       ├── telegram.ts           window.Telegram.WebApp типы и хелперы
│       ├── styles.css            CSS-переменные Telegram-темы
│       ├── pages/
│       │   ├── Posts.tsx
│       │   ├── PostDetail.tsx
│       │   ├── Channel.tsx
│       │   └── Reactions.tsx
│       └── components/
│           ├── Layout.tsx
│           ├── PostCard.tsx
│           ├── Sparkline.tsx     pure SVG, ~30 строк
│           └── Spinner.tsx
│
├── docs/
│   └── spec/
│       └── mini-app.md           ← этот документ
│
├── scripts/                      [New, gitignored или явно ignored секреты]
│   └── sign_init_data.py         dev-only, подписывает initData для curl-тестов
│
├── data/                         [Volume] SQLite
├── Dockerfile                    [Modified] multi-stage (node → python deps → runtime)
├── .dockerignore                 [Modified] +frontend/node_modules, +static
├── .gitignore                    [Modified] +frontend/node_modules, +frontend/dist, +src/webapp/static
├── .env.example                  [Modified] +5 переменных
├── pyproject.toml                [Modified] +fastapi, +uvicorn
└── README.md / CLAUDE.md         [Modified] обновить раздел архитектуры
```

---

## Code Style

### Python — наследуем CLAUDE.md проекта

Ruff: `E, F, I, B, UP, ASYNC`, line-length 100, target-version `py312`. `from __future__ import annotations` сверху каждого модуля. Loguru с placeholder-стилем `"{}"`. Async везде. Без эмодзи в коде/комментах. Параметризованные SQL.

**Пример нового файла** (`src/webapp/auth.py`, упрощённо для иллюстрации):

```python
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status
from loguru import logger

from src.config import settings

_INIT_DATA_TTL_SEC = 86_400  # 24 часа


def validate_init_data(init_data: str) -> dict[str, object]:
    """Проверяет подпись Telegram WebApp initData. Возвращает user-объект.

    Подпись HMAC-SHA256 считается по ADMIN_BOT_TOKEN — это бот, через
    которого открыт Mini App. Spec: https://core.telegram.org/bots/webapps
    """
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no hash")

    auth_date = int(pairs.get("auth_date", "0"))
    if time.time() - auth_date > _INIT_DATA_TTL_SEC:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "init_data expired")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(
        b"WebAppData", settings.admin_bot_token.encode(), hashlib.sha256
    ).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad hash")

    user = json.loads(pairs["user"])
    if int(user["id"]) not in settings.allowed_user_ids:
        logger.warning("Mini App: deny user {} (not in allowed)", user.get("id"))
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return user


async def get_current_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
) -> dict[str, object]:
    return validate_init_data(x_telegram_init_data)
```

### TypeScript / React

- TS strict mode (`"strict": true` в tsconfig).
- Функциональные компоненты с типизацией пропсов через `interface Props`.
- Имена компонентов в `PascalCase`, хуков в `camelCase`.
- Никаких `any` без явного `// eslint-disable` + объяснения.
- CSS-переменные Telegram-темы (`var(--tg-theme-bg-color)`) вместо хардкода цветов.

**Пример** (`frontend/src/api.ts`):

```typescript
const initData = window.Telegram?.WebApp?.initData ?? "";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
      "X-Telegram-Init-Data": initData,
    },
  });
  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, public body: string) {
    super(`API ${status}: ${body}`);
  }
}
```

---

## Testing Strategy

В проекте сейчас тестов нет (см. `CLAUDE.md`: «Тестов в репо нет»). Не вводим pytest/vitest в рамках этого изменения — это отдельный scope. Вместо этого:

### Тип 1 — Ручная проверка через checkpoint'ы

Каждый из 12 шагов реализации (см. секцию **Tasks**) заканчивается checkpoint'ом: команда + ожидаемый результат. Не идём дальше без зелёного checkpoint'а.

### Тип 2 — Тестовый клиент для backend

Скрипт `scripts/sign_init_data.py` (dev-only, не коммитится — в `.gitignore`) подписывает `initData` локально, чтобы дёргать FastAPI через `curl` без Telegram-клиента. Используется для smoke-тестов всех `/api/*` эндпоинтов.

### Тип 3 — End-to-end через HTTPS-туннель

Для тестов в реальном Telegram-клиенте (без деплоя) — `cloudflared tunnel` или `ngrok`, `MINI_APP_URL` подменяется на туннель, кнопку Mini App переустанавливаем через `/setmenubutton` в @BotFather.

### Тип 4 — После деплоя (smoke)

Жёсткий список из 8 проверок (см. секцию **Verification end-to-end**): health, открытие Mini App, все 4 страницы, поведение реакций, отсутствие SQLITE_BUSY, adversarial 401/403.

### Зачем не вводим автотесты прямо сейчас

- Текущая кодовая база — без pytest, добавление тестов = отдельный scope (фикстуры, моки aiogram, FastAPI TestClient).
- Логика FastAPI тривиальна (CRUD-обёртка над SQLite), цена бага низкая.
- Mini App — внутренний инструмент на 1–2 пользователя; падение не блокирует основной flow бота.
- Когда тесты будут вводиться — приоритеты: `validate_init_data` (security-critical), `record_draft_event` (audit-critical), `upsert_post_reactions` (concurrency).

---

## Boundaries

### Always (всегда делаем)

- `uv run ruff check src/` локально перед коммитом.
- `from __future__ import annotations` в каждом новом Python-модуле.
- Параметризованные SQL-запросы (через `?`, не строковая конкатенация).
- `loguru` с placeholder-форматом `"{}"`, без f-strings внутри `logger.X(...)`.
- Async везде в backend (aiogram, aiosqlite, httpx, anthropic, FastAPI).
- В каждом новом FastAPI-эндпоинте — `Depends(get_current_user)`, кроме `/api/health`.
- В TS — `strict: true`, без `any`.
- Сохранять историю изменений через `record_draft_event` во ВСЕХ 5 точках (создание, edit, regenerate, approve, reject).
- `MIN_APP_URL` — только HTTPS. HTTP не допускается даже в dev (Telegram отвергает).
- Сохранять `Co-Authored-By: Claude ...` в коммитах, сделанных совместно с агентом.

### Ask first (спрашиваем перед действием)

- Добавление новых dependencies в `pyproject.toml` / `frontend/package.json` (любые сверх перечисленных в Tech Stack).
- Изменение существующих таблиц (`drafts`, `published`, `app_settings`, `api_usage`).
- Изменение `SYSTEM_PROMPT` (инвалидирует кеш Anthropic).
- Любая правка `_strip_dashes` / антибот-постпроцессора — модель срывается на тире, ломали уже.
- Деплой в продакшен (`git push` в main + Dokploy redeploy).
- Изменение схемы публичных API-эндпоинтов после первого деплоя (ломает фронт).
- `git push --force` — никогда без явного разрешения.

### Never (никогда без явного разрешения)

- Коммитить `.env`, секреты, `scripts/sign_init_data.py` с реальным токеном.
- Включать debug-режим / dev-backdoor для пропуска валидации initData в FastAPI (риск утечки в прод).
- Убирать `_strip_dashes` или ослаблять антибот-фильтры — модель тут же начинает «—»-стиль.
- Ломать инвариант `claim_for_publish` (атомарный CAS draft→publishing) — это защита от двойной публикации.
- Менять `OwnerOnlyMiddleware` так, чтобы он пропускал неаутентифицированных.
- Использовать MTProto user-сессию без отдельного согласования — это меняет threat-model проекта.
- Добавлять эмодзи в Python-код / Python-комментарии (CLAUDE.md). В UI-строках Telegram эмодзи допустимы.
- Делать `git commit --no-verify` или обход pre-commit хуков.

---

## Architecture (выжимка)

Три параллельных сервиса в одном `python -m src.main` процессе, оркестратор — `asyncio.TaskGroup` (3.12+):

```
                ┌──────────────────────────────────────┐
                │       python -m src.main             │
                │   (asyncio.TaskGroup, SIGTERM-aware) │
                └────────┬──────────┬─────────┬────────┘
                         │          │         │
              ┌──────────▼──┐  ┌────▼────┐  ┌─▼────────────┐
              │  main bot   │  │admin bot│  │  FastAPI     │
              │  (polling)  │  │(polling)│  │  + uvicorn   │
              │             │  │         │  │  :8000       │
              │ - posts     │  │ /start →│  │ /api/*       │
              │ - reactions │  │ Mini App│  │ static/      │
              │   handler   │  │ button  │  │  (React SPA) │
              └──────┬──────┘  └─────────┘  └──────┬───────┘
                     │                             │
                     │     ┌─────────────────┐     │
                     └────►│  SQLite (WAL)   │◄────┘
                           │  /data/smm.db   │
                           └─────────────────┘

                     ┌──────────────────────┐
                     │  APScheduler         │
                     │  (in main process)   │
                     │  - cron генерация    │
                     │  - snapshot канала   │
                     │    каждые 60 мин     │
                     └──────────────────────┘
```

**Внешнее**: Traefik (Dokploy) → HTTPS → uvicorn :8000. Mini App открывается в admin-боте через `MenuButtonWebApp`, грузит `https://<домен>/` → раздаётся как SPA, обращается к `/api/*` через `fetch` с заголовком `X-Telegram-Init-Data`.

---

## Database schema (расширение)

```sql
-- Полный аудит действий с драфтом
CREATE TABLE IF NOT EXISTS draft_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,  -- created|edited|regenerated_from|approved|rejected
    actor_user_id INTEGER,     -- NULL для cron
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_draft_events_draft ON draft_events(draft_id, created_at);
CREATE INDEX IF NOT EXISTS idx_draft_events_type_at ON draft_events(event_type, created_at DESC);

-- Агрегированные реакции (анонимные в каналах)
CREATE TABLE IF NOT EXISTS post_reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_message_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    total_count INTEGER NOT NULL DEFAULT 0,
    reactions_json TEXT NOT NULL DEFAULT '[]',  -- [{"emoji":"👍","count":5}, ...]
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tg_message_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_post_reactions_total ON post_reactions(total_count DESC);

-- Динамика подписчиков (snapshot каждые 60 мин)
CREATE TABLE IF NOT EXISTS channel_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    channel_id TEXT NOT NULL,
    member_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_snapshots_ts ON channel_snapshots(channel_id, ts DESC);
```

В `init_db()` после `executescript`:
```python
await conn.execute("PRAGMA journal_mode=WAL")
await conn.execute("PRAGMA synchronous=NORMAL")
```
В `get_conn()`: `aiosqlite.connect(settings.db_path, timeout=10.0)`.

### Payload по типам `event_type`

| `event_type` | `payload_json` |
|---|---|
| `created` | `{"mode": "auto\|topic\|url", "topic": str?, "source_url": str, "title": str}` |
| `edited` | `{"old_text": str, "new_text": str, "diff_unified": str}` |
| `regenerated_from` | `{"new_draft_id": int, "new_title": str}` |
| `approved` | `{"tg_message_id": int, "channel_id": str}` |
| `rejected` | `{"reason": "manual_reject\|regenerate_replaced"}` |

---

## API contract (FastAPI)

Заголовок `X-Telegram-Init-Data` обязателен для всех `/api/*` кроме `/api/health`. На 401/403 фронт делает `tg.close()`.

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/health` | `{"status":"ok","db":"ok"}` |
| GET | `/api/me` | `{"id":int,"username":str?,"is_owner":bool}` |
| GET | `/api/posts/stats` | `{"total":int,"draft":int,"publishing":int,"published":int,"rejected":int}` |
| GET | `/api/posts?status=&period=24h\|7d\|30d\|all&search=&offset=0&limit=20` | `{"items":[Post],"total":int}` |
| GET | `/api/posts/{draft_id}` | `{"draft":{...},"events":[Event],"published":{...}?,"reactions":{...}?}` |
| GET | `/api/channel/stats` | `{"channel_id":str,"title":str,"member_count":int,"snapshots":[Snapshot]}` |
| GET | `/api/posts/reactions/top?limit=10` | `[Reaction]` |
| GET | `/api/posts/reactions/bottom?limit=10` | `[Reaction]` (только posts опубликованы ≥24ч) |

Только GET. POST/PUT/DELETE — 405.

---

## Integration points в существующем коде

В `src/bot/handlers.py` добавить вызовы `repo.record_draft_event(...)` в этих точках:

| Где | Что |
|---|---|
| `_persist_draft` (после `save_draft`, ~720) | `created`; нужно прокинуть `actor_user_id` и `gen_mode` через цепочку `_run_generation → send_preview_to_users → _persist_draft`. |
| `cb_approve` (после `mark_published`, ~471) | `approved`, `actor=cq.from_user.id`. |
| `cb_regenerate` (после `mark_rejected`, ~493) | `rejected` с `reason=regenerate_replaced`. После генерации нового — `regenerated_from` на старый draft_id с `{new_draft_id}`. |
| `cb_reject` (после `mark_rejected`, ~566) | `rejected` с `reason=manual_reject`. |
| `on_edit_text` (до `update_draft_text`, ~591) | `edited` с `old_text`/`new_text`/`diff_unified` (через `difflib.unified_diff`). |

В `src/scheduler.py` — `cron_generate` передаёт `gen_mode="auto", actor_user_id=None`.

---

## Phase 2 — Plan (high-level)

Зависимости компонентов и порядок:

```
1. БД (DDL + WAL)          ─┐
2. record_draft_event +    ─┤ Без этого нечего показывать
   integration в handlers ──┘
                            │
3. message_reaction_count  ─┤ Идёт после #1 (нужна таблица)
   handler                  │
                            │
4. channel snapshot job    ─┤ Зависит от #1
                            │
5. FastAPI skeleton + auth ─┤ Зависит от #1 (читает из БД)
                            │
6. FastAPI: все routes     ─┤ Зависит от #5
                            │
7. Admin bot               ─┤ Независим от #5,#6, но проще тестировать вместе
                            │
8. main.py TaskGroup       ─┤ Зависит от #3 (allowed_updates), #5,#6,#7
                            │
9. Frontend bootstrap      ─┤ Может идти параллельно с backend (#5-#8)
                            │
10. Frontend pages         ─┤ Зависит от #9 и стабильного API (#6)
                            │
11. Dockerfile multi-stage ─┤ Зависит от #10 (нужен bundle)
                            │
12. Deploy                 ─┘ Финал
```

**Что можно делать параллельно:** #9 фронт-bootstrap может стартовать сразу после Phase 1 spec'а и поверх mock'нутого API; #10 frontend pages должны идти после стабилизации #6.

**Риски и митигация:**
- *Риск:* `SQLITE_BUSY` при concurrent reads — **митигация:** WAL + `busy_timeout=10s` на коннекте.
- *Риск:* `MessageReactionCountUpdated` не приходит — **митигация:** в Step 3 проверяем checkpoint: реакция со стороннего аккаунта → строка в БД. Если нет — проверяем (a) `allowed_updates`, (b) `bot is channel admin`, (c) `chat.id match`.
- *Риск:* фронт-бандл > 200KB — **митигация:** без chart-библиотек, без TanStack/SWR, lazy-route'ы через `React.lazy`.
- *Риск:* admin-bot не может поставить menu button (пользователь не делал /start) — **митигация:** best-effort, ловим exception, фолбэк — кнопка в `ReplyKeyboardMarkup` после `/start`.
- *Риск:* graceful shutdown ломается при SIGTERM от Docker — **митигация:** `loop.add_signal_handler` + `server.should_exit = True` + `dp.stop_polling()`, в `finally` чистим session.

---

## Phase 3 — Tasks (ordered, with acceptance criteria)

### Task 1: расширение БД и WAL — ✅ DONE (`8948d5e`, `76a3dc1`)
- **Acceptance:** новые таблицы `draft_events`, `post_reactions`, `channel_snapshots` созданы; `PRAGMA journal_mode` возвращает `wal`; существующие данные не повреждены.
- **Verify:** удалить локальный `data/smm.db`, перезапустить, `sqlite3 data/smm.db ".schema"` показывает 7 таблиц. Запросить `PRAGMA journal_mode` — `wal`.
- **Files:** `src/storage/db.py`, `src/storage/repo.py` (+ `record_draft_event` / `upsert_post_reactions` / `add_channel_snapshot`).
- **Изменение vs первоначальный план:** в fixup `76a3dc1` `get_conn()` переделан в `@asynccontextmanager` и каждый коннект ставит `PRAGMA foreign_keys=ON` — без этого `ON DELETE CASCADE` на `draft_events.draft_id` был бы no-op (SQLite по умолчанию не enforces FK).

### Task 2: audit-события в handlers — ✅ DONE (`c360fcf`, `76a3dc1`)
- **Acceptance:** в `draft_events` появляется запись при каждом из 5 действий; `actor_user_id` корректен (None для cron); diff в `edited` payload отличается от пустого.
- **Verify:** сгенерировать `/generate auto` → отредактировать → одобрить → `SELECT * FROM draft_events WHERE draft_id=N ORDER BY id` — 3 строки `created/edited/approved` с корректным `actor`.
- **Files:** `src/bot/handlers.py`, `src/scheduler.py` (передача `gen_mode="auto"`).
- **Изменение vs первоначальный план:**
  - Все 5 точек идут через fail-soft helper `_audit()` (handlers.py): exception в записи аудита логируется, но не валит пользовательский flow.
  - В `on_edit_text` порядок mutate→audit: сначала `update_draft_text`, потом `_audit`, чтобы не оставалось фантомного `edited`-события при сбое update.
  - `_EDIT_TEXT_MAX_LEN = 4000` — cap на длину текста при правке (Telegram caption 1024, но payload хранит old+new+diff, поэтому даём запас).
  - `send_preview_to_users` теперь возвращает `(draft_id, sent_count)`; `cb_regenerate` пишет `regenerated_from` только при `sent_count > 0` и оборачивает send_preview в `try/except` с user-visible сообщением.

### Task 3: reaction handler + allowed_updates — ✅ DONE (`d23d4bb`, `76a3dc1`)
- **Acceptance:** `message_reaction_count` event → upsert в `post_reactions`; реакция от другого юзера на пост канала отражается в БД ≤ 2 мин.
- **Verify:** опубликовать пост через бот → реагировать на него со второго аккаунта → `SELECT * FROM post_reactions WHERE tg_message_id=M` — строка с обновлённым `total_count`.
- **Files:** `src/bot/reactions.py` (new), `src/main.py` (router include + `allowed_updates`).
- **Изменение vs первоначальный план:**
  - `_is_target_channel(event)` фильтрует только канал из `settings.channel_id`. Сравниваем и numeric id, и `@username` — формат настройки не фиксирован.
  - `OwnerOnlyMiddleware` не покрывает `message_reaction_count` observer (он подключён только к `dp.message` / `dp.callback_query`). Это OK для анонимных реакций (нет `from_user`), но важно помнить, если в будущем добавим `message_reaction` (per-user).
  - `allowed_updates` собирается через `dp.resolve_used_update_types()`, что делает список устойчивым к добавлению новых router'ов.

### Task 4: channel snapshot scheduler job — ✅ DONE (`7950626`)
- **Acceptance:** job запускается раз в `CHANNEL_SNAPSHOT_INTERVAL_MINUTES` минут (default 60); первая запись добавляется сразу при старте; `member_count` совпадает с `getChatMemberCount`.
- **Verify:** старт бота → подождать 30s → `SELECT * FROM channel_snapshots ORDER BY ts DESC LIMIT 1` — корректное число подписчиков.
- **Files:** `src/scheduler.py`, `src/config.py`, `.env.example`.
- **Изменение vs первоначальный план:**
  - `_apply_times` теперь удаляет только `cron_generate_*`-job'ы (был `remove_all_jobs`), иначе `/cron`-rescheduling сносил бы snapshot.
  - `channel_snapshot` fail-soft: исключения и в `getChatMemberCount`, и в `add_channel_snapshot` логируются, но не валят job — лучше пропустить тик sparkline, чем уронить периодическую задачу.
  - Дефолт `CHANNEL_SNAPSHOT_INTERVAL_MINUTES = 60` в `config.py`; в `.env.example` добавлена строка.

### Task 5: FastAPI skeleton + auth — ✅ DONE (`5d5b31b`)
- **Acceptance:** `fastapi`, `uvicorn[standard]` установлены; `/api/health` без auth = 200; `/api/me` без header = 401; со старым/битым `auth_date` = 401; с user_id вне allowed = 403.
- **Verify:** TestClient прогнал 8 кейсов (health/no-header/empty/bad-hash/not-allowed/owner/expired/POST→405), все зелёные.
- **Files:** `pyproject.toml`, `src/webapp/{__init__,server,auth,deps}.py`, `src/webapp/routes/{health,me}.py`, `src/config.py`, `.env.example`, `.gitignore`.
- **Изменение vs первоначальный план:**
  - `get_current_user` принимает `Header(default=None)` и сам поднимает 401 вместо дефолтного pydantic 422 — фронт ждёт 401, чтобы делать `tg.close()`.
  - `validate_init_data` дополнительно отвергает запрос, если `ADMIN_BOT_TOKEN` пуст (dev без токена не должен пропускать API).
  - `CurrentUser` вынесен в `deps.py` как `Annotated[..., Depends]` — будут переиспользовать все будущие роуты (B008-чистая инъекция).
  - `server.build_webapp` отключает `/docs`, `/redoc`, `/openapi.json` (внутренний инструмент, схема не нужна).
  - SPA-static/assets-mount условный: `src/webapp/static/` есть только после Vite build в multi-stage Docker, в dev фронт идёт через `vite dev` на :5173.

### Task 6: FastAPI — posts/channel/reactions routes — ✅ DONE (`d878a5c`)
- **Acceptance:** все 8 эндпоинтов отвечают 200 с корректной схемой; SQL — параметризованный, нет инъекций; ответ для `/api/posts/stats` совпадает с прямым SQL `GROUP BY status`.
- **Verify:** TestClient прогнал 15 кейсов — stats/list/detail/top/bottom/channel + SQL-injection probe (`search=' OR 1=1 --` → 0 строк), 404, 405, 401 без auth, 422 на bad-status/limit=0. Все зелёные.
- **Files:** `src/webapp/routes/{posts,channel,reactions}.py`, `src/webapp/server.py`, `src/storage/repo.py` (+6 функций), `src/scheduler.py` (сохранение `channel_title`).
- **Изменение vs первоначальный план:**
  - Порядок `include_router` в `server.py`: reactions → posts. Иначе `/posts/reactions/top` ловится через `/posts/{draft_id}` и 422.
  - `list_posts` использует `json_extract(d.raw_json, '$.title')` для поиска по черновикам (JSON1 встроен в SQLite на проде).
  - Channel stats возвращает `member_count` из последнего snapshot, а не blocking-вызов `get_chat_member_count` — WebApp не должен синхронно дёргать Telegram на каждый запрос.
  - `channel_snapshot` job дополнительно best-effort сохраняет `app_settings['channel_title']` — нужен `/api/channel/stats`. Сбой `get_chat` не валит snapshot.
  - Все Query-параметры валидируются через pydantic (regex для status/period, `ge=/le=` для limit/offset/days) — bad-input отдаёт 422, защита от подбора через `limit ≤ 100`, `offset ≤ 10000`.

### Task 7: admin bot — ✅ DONE (`8554ede`)
- **Acceptance:** `/start` отвечает с `ReplyKeyboardMarkup` + `KeyboardButton(web_app=...)`; неаутентифицированный юзер игнорируется (как в main-боте); menu button ставится best-effort.
- **Verify:** smoke прошёл (factory, middleware, handler-count, URL в keyboard, пустой URL → fallback на текст). Полный e2e ждёт Task 8 (TaskGroup) + Task 12 (deploy) + туннель.
- **Files:** `src/adminbot/__init__.py`, `src/adminbot/bot.py`.
- **Изменение vs первоначальный план:**
  - При пустом `MINI_APP_URL` `/start` показывает текстовое предупреждение без клавиатуры — Telegram отклоняет `KeyboardButton(web_app=WebAppInfo(url=""))`.
  - `setup_admin_menu_buttons` ловит конкретно `TelegramAPIError`, чтобы не глотать `KeyboardInterrupt`/`CancelledError`.
  - Подключение в `main.py` (запуск polling параллельно с main-ботом и FastAPI) — Task 8.

### Task 8: TaskGroup-оркестрация в main.py — ✅ DONE
- **Acceptance:** все три сервиса стартуют параллельно; SIGTERM (Docker) → graceful shutdown ≤ 5s; падение любого сервиса роняет весь процесс с не-нулевым кодом; в логах видно имена всех трёх задач.
- **Verify:** smoke `_run_webapp` с моком shutdown_event прошёл (~0.5с до set, uvicorn делает Application shutdown complete, finally вышел). `_run_main_bot`/`_run_admin_bot` собраны по той же схеме (asyncio.wait на polling + stop-watch). Полный e2e — после деплоя (Task 12).
- **Files:** `src/main.py` (rewrite).
- **Изменение vs первоначальный план:**
  - `ADMIN_BOT_TOKEN` пуст → admin-бот и webapp пропускаются с warning, main-бот стартует один. Это даёт возможность поднять прод поэтапно: сначала main-бот, потом — Mini App.
  - Каждый сервис использует пару tasks: `polling_task` (или `serve_task`) + `stop_task` (ждёт `shutdown_event`). Внешнее cancellation → отмена polling/serve, в `finally` чистим session/scheduler.
  - `_install_signal_handlers` ловит и `SIGTERM` (Docker), и `SIGINT` (Ctrl+C). Повторный сигнал не дёргает второй shutdown — только лог.
  - uvicorn запущен через `Server(Config(...))` напрямую, без `run()`. `log_level` — lowercase из settings, `access_log=False`, чтобы не дублировать loguru.

### Task 9: frontend bootstrap — ✅ DONE
- **Acceptance:** `npm ci` устанавливает зависимости из lockfile; `npm run dev` поднимает Vite на :5173 с proxy `/api → :8000`; placeholder-страница рендерится.
- **Verify:** `npm install` сгенерировал lockfile (225 пакетов); `npm run typecheck` зелёный; `npm run lint` зелёный; `npm run build` → 46.4 KB gz (с большим запасом до P1 = 200 KB gz); `npm run dev` → :5173 отдаёт index.html (HTTP 200), proxy `/api → :8000` сконфигурирован.
- **Files:** `frontend/package.json`, `package-lock.json`, `tsconfig.{json,app,node}.json`, `vite.config.ts`, `eslint.config.js`, `index.html`, `src/{main.tsx,App.tsx,api.ts,telegram.ts,styles.css,vite-env.d.ts}`.
- **Изменение vs первоначальный план:**
  - Конфиг TS разбит на `tsconfig.app.json` (src/) + `tsconfig.node.json` (vite.config.ts) — стандартный шаблон Vite + React 18, чтобы Node-API в конфиге не пролезали в браузерный код.
  - ESLint 9 flat config (`eslint.config.js`), без prettier — Open Question 6.
  - В `styles.css` — CSS-переменные Telegram-темы (`--tg-bg`, `--tg-button` и т.п.), fallback на тёмные цвета (Telegram-default).
  - Placeholder-страница App.tsx уже стучится в `/api/health` — это и есть live-проверка proxy.

### Task 10: frontend pages — ✅ DONE
- **Acceptance:** 4 страницы (Posts, PostDetail, Channel, Reactions) функциональны на реальных данных; `npm run build` успешен; bundle ≤ 200KB gzipped; Telegram-тема применяется через CSS-vars.
- **Verify:** `npm run build` → суммарно ~62.5 KB gz (вендор 55 + 4 lazy-чанка страниц 1–2 KB каждый + CSS 0.74 + ErrorView 0.48). Огромный запас до P1 = 200 KB gz. `npm run typecheck` и `npm run lint` зелёные. Реальный e2e (страницы на данных) ждёт Task 12.
- **Files:** `frontend/src/pages/{Posts,PostDetail,Channel,Reactions}.tsx`, `frontend/src/components/{Layout,PostCard,Sparkline,Spinner,ErrorView}.tsx`, `frontend/src/types.ts`, `frontend/src/App.tsx` (rewrite на BrowserRouter + lazy).
- **Изменение vs первоначальный план:**
  - `React.lazy` для каждой страницы — экономит ~10 KB gz на главном чанке и даёт быстрый initial paint. Suspense fallback — Spinner.
  - `ErrorView` — отдельный компонент, переиспользуется во всех страницах. На 401/403 закрывает Mini App через `tg.close()`.
  - `PostDetail` отображает полный `formatted_text` (HTML с `<b>`, `<a>`, `<code>`, `<blockquote>` — наш SYSTEM_PROMPT). Для этого backend `repo.get_post_detail` доп. возвращает `formatted_text` в post-объекте (в list-ответе остаётся только preview из соображений размера).
  - Поиск в `Posts` дебаунсится на 300мс — иначе на каждый символ улетал бы запрос.
  - `Sparkline` — pure SVG ~50 строк, без chart-библиотек (как в Tech Stack). Считает min/max и линейный масштаб.
  - Дата в `formatDate` интерпретирует ISO без `Z` как UTC (SQLite даты без таймзоны) — иначе браузер берёт local TZ и таймстампы съезжают.

### Task 11: Dockerfile multi-stage — ⚠️ CODE-ONLY
- **Acceptance:** 3 stage (node → python deps → runtime); финальный образ ≤ 250MB; bundle React в `/app/src/webapp/static/`; healthcheck бьёт `/api/health`; non-root `app:app`.
- **Verify:** ⚠️ Локальный `docker build` НЕ запускался: Docker daemon выключен в момент работы. Файлы написаны по спеку. **Реальная сборка случится при Task 12 в Dokploy** — если что-то сломается, fixup-коммит. Sanity-check Dockerfile-синтаксиса визуальный (multistage + final FROM + non-root + HEALTHCHECK присутствуют).
- **Files:** `Dockerfile`, `.dockerignore`.
- **Изменение vs первоначальный план:**
  - Stage 1 — `node:20-alpine` для размера (~50 MB) → `npm ci --no-audit --no-fund --prefer-offline` → `vite build`.
  - Stage 2 — `python:3.12-slim` + uv binary из `ghcr.io/astral-sh/uv:latest` → `uv sync --frozen --no-dev --no-install-project` (один слой инвалидируется только при изменении lockfile).
  - Stage 3 — `python:3.12-slim` (~150 MB база) + venv (Stage 2) + `src/` + `frontend/dist → src/webapp/static`. Без uv в runtime — меньше attack surface, меньше слой.
  - HEALTHCHECK через `python -c "urllib.request.urlopen(/api/health)"` — stdlib, без curl/wget в slim-образе. `start-period=20s` чтобы uvicorn успел подняться до первой проверки.
  - `WEBAPP_HOST=0.0.0.0` и `WEBAPP_PORT=8000` зашиты в ENV образа — Dokploy может переопределить через env-vars.

### Task 12: deploy в Dokploy — 🚧 BLOCKED
- **Acceptance:** Mini App открывается в admin-боте на телефоне; все 4 страницы грузятся; реальные данные.
- **Verify:** ручной e2e на телефоне; `curl https://<домен>/api/health` → 200; @BotFather `/setmenubutton` для admin-бота указывает на `MINI_APP_URL`; Traefik dashboard показывает router.
- **Files:** конфиг Dokploy (env-vars + Traefik labels).
- **Что ещё нужно от пользователя (Open Questions 1–2 + 3):**
  1. Выбрать домен Mini App (например `stats.aibromotion.tech`). Прописать в Dokploy → Traefik labels.
  2. Создать новый бот через @BotFather (`/newbot`) → положить токен в `ADMIN_BOT_TOKEN` (Dokploy env).
  3. В `.env` Dokploy установить: `ADMIN_BOT_TOKEN=...`, `MINI_APP_URL=https://<домен>`, остальные старые переменные оставить.
  4. Включить EXPOSE 8000 в Dokploy + Traefik label `traefik.http.routers.smmbot.rule=Host(\`<домен>\`)` + `traefik.http.services.smmbot.loadbalancer.server.port=8000` + автo-HTTPS Let's Encrypt.
  5. Redeploy.
  6. После старта — @BotFather `/setmenubutton` для **admin-бота** → текст «📊 Статистика», URL `https://<домен>` (best-effort `set_chat_menu_button` ставит то же из кода для allowed-юзеров; menu button у Telegram per-bot, поэтому BotFather-вариант покрывает всех).
- **Smoke на телефоне** (`Verification end-to-end` ниже — 12 пунктов).

---

## Phase 4 — Implementation guidance

При реализации каждого task:

1. **Загружай в контекст только нужное** (skill `context-engineering`): этот spec + 1-2 файла, которые правишь. Не вытягивай весь репозиторий.
2. **Incremental** (skill `incremental-implementation`): каждый task — atomic commit. Не смешивай разные task'и в одном коммите.
3. **TDD/проверки** (skill `test-driven-development`): для критичных мест (`validate_init_data`, `record_draft_event`) — сначала checkpoint (write the curl/sql that proves correctness), потом код.
4. **Stop на красном checkpoint'е**. Не двигайся дальше, пока текущий task не зелёный.

---

## Success Criteria

Все измеримы, проверяются после Task 12 (deploy).

### Функциональные

- F1: Mini App открывается только из admin-бота, только для `user.id ∈ allowed_user_ids`. Сторонний пользователь, угадавший URL, получает 401/403 на `/api/me` и UI закрывается.
- F2: При выполнении `/generate` → edit → approve в `draft_events` присутствуют 3 события с корректным `actor_user_id` и `payload`.
- F3: При реакции на канал-пост со стороннего аккаунта счётчик в `post_reactions.total_count` обновляется ≤ 2 мин.
- F4: На странице Channel виден текущий `member_count` (совпадает с `getChatMemberCount`) и sparkline за 7 дней.
- F5: На странице Reactions топ-10 отсортирован по `total_count DESC`, анти-топ — по `ASC` среди постов опубликованных ≥ 24ч назад.
- F6: На странице PostDetail для отредактированного драфта виден `diff_unified` в timeline.
- F7: Существующая функциональность (cron, edit, regenerate, approve, reject, OG-картинки, антибот-фильтры) работает без регрессий.

### Производительность

- P1: Bundle frontend ≤ 200KB gzipped (`du -sh dist/assets/*.js` + gz).
- P2: TTI Mini App (time to interactive) на 4G мобильном Telegram ≤ 1.5s после `tg.ready()`.
- P3: API p95 ≤ 100ms на типичном объёме (1000 драфтов, 200 published, 50K reaction events). Замер `time curl ...` × 10.
- P4: Docker-образ ≤ 250MB.
- P5: Никаких `SQLITE_BUSY` в логах за 24 часа production-работы (WAL + busy_timeout справляются).

### Безопасность

- S1: Без `X-Telegram-Init-Data` → 401.
- S2: С битой подписью → 401.
- S3: С `auth_date` старше 24ч → 401.
- S4: С `user.id` вне allowed → 403.
- S5: POST/PUT/DELETE на любой `/api/*` → 405.
- S6: SQL-инъекция в `?search=' OR 1=1 --` не выдаёт лишнее (параметризация).
- S7: `scripts/sign_init_data.py` не закоммичен в git (проверка через `git ls-files`).
- S8: `.env` не закоммичен (уже в `.gitignore` — подтверждаем).

### Стабильность

- St1: `docker compose restart smm-bot` — все три сервиса в логе старта; нет `orphan asyncio task` warnings.
- St2: Падение любого из 3 сервисов → процесс с не-нулевым exit code → Dokploy рестартует.
- St3: SIGTERM от Docker → graceful exit за ≤ 5s, без `Task was destroyed but pending` ошибок.

---

## Open Questions (нужен вход от пользователя)

1. **Домен для Mini App.** На каком домене будет жить (`mini-app.example.com`?). Нужно настроить Traefik labels в Dokploy.
2. **ADMIN_BOT_TOKEN.** Создать нового бота через @BotFather, ввести username и токен в `.env`. До этого Task 7 и далее не запускаются.
3. **Локальный тестовый туннель** — `cloudflared` или `ngrok`? (Влияет только на dev-flow, не на прод).
4. ~~**CHANNEL_SNAPSHOT_INTERVAL_MINUTES** — оставить 60 или сделать чаще (например 15)? Чем чаще, тем плотнее sparkline, но больше нагрузка на Bot API. Рекомендую 60 для старта.~~ **RESOLVED 2026-05-25: 60 мин.**
5. **Старые посты без реакций** — показывать `—` или `0`? Рекомендую `—` (нет записи в `post_reactions`), чтобы отличать «реально 0 реакций» от «не трекалось».
6. **Eslint в frontend** — стандартный preset `@typescript-eslint/recommended` ок, или добавить prettier? Рекомендую без prettier (vite + eslint достаточно).

---

## Verification end-to-end

После Task 12 (deploy) — финальный smoke-чеклист:

```
□ curl https://<домен>/api/health → 200
□ Открыть admin-бота на телефоне → menu button «Статистика»
□ Mini App грузится за ≤ 2с, UI отзывчивый
□ /api/me возвращает мой user-id, is_owner=true
□ Posts: пагинация, фильтр по статусу, поиск — работают
□ PostDetail: timeline событий, diff в edited
□ Channel: member_count + sparkline за 7 дней
□ Reactions: top/bottom, корректная сортировка
□ Реакция со стороннего аккаунта → счётчик обновился ≤ 2 мин
□ /generate в main-боте → одобрить → новый пост виден в Mini App
□ docker logs: нет SQLITE_BUSY, нет orphan task warnings
□ Adversarial: POST /api/posts → 405; bad initData → 401; not-in-allowed → 403
```

Все 12 пунктов зелёные → spec считается реализованным.

---

## Изменения spec'а

При любой смене scope, требований или решений — **сначала обновить этот файл**, потом код. Привязка к PR: каждый PR ссылается на конкретную секцию spec'а (например, "implements Task 3").
