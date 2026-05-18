# SMM Bot

Telegram-бот для SMM. По кнопке генерирует пост про AI / новые AI-продукты / бизнес-новости техкомпаний на русском, без эмодзи, со ссылкой на источник и OG-картинкой. Использует Anthropic Claude Sonnet с native `web_search` для поиска инфоповодов.

## Быстрый старт

```bash
cp .env.example .env
# заполни TELEGRAM_BOT_TOKEN, OWNER_ID, CHANNEL_ID, ANTHROPIC_API_KEY

uv sync
uv run python -m src.main
```

### Получить OWNER_ID и CHANNEL_ID

- `OWNER_ID` — твой Telegram user id, можно узнать через `@userinfobot`.
- `CHANNEL_ID` — id канала. Сделай бота админом канала, отправь в канал любое сообщение, посмотри в `getUpdates` или используй `@username_to_id_bot`. Формат: `-100xxxxxxxxxx` или `@channelname`.

## Команды бота

- `/start` — приветствие, проверка владельца.
- `/generate` — запустить генерацию поста. Бот пришлёт превью с кнопками:
  - **Approve** — опубликовать в канал.
  - **Regenerate** — сгенерировать другую новость (исключая текущий источник).
  - **Edit** — отредактировать текст вручную (следующее сообщение станет новым телом поста).

## Стиль постов

Полностью задаётся в `src/agent/prompts.py` — это главное место для итераций над «голосом канала».

## Деплой через Dokploy

1. Создай Application → Docker.
2. Привяжи репозиторий или загрузи код.
3. Build: `Dockerfile`.
4. Environment variables: всё из `.env.example`.
5. Volume: `/data` → SQLite сохраняется между рестартами.
6. Старт.

## Проверка отдельных компонентов (без Telegram)

```bash
# Сгенерировать черновик в stdout
uv run python -m src.agent.news_agent

# Проверить OG-image экстрактор
uv run python -m src.media.og_image https://techcrunch.com/...
```
