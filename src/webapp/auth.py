from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status
from loguru import logger

from src.config import settings

_INIT_DATA_TTL_SEC = 86_400  # 24 часа — стандарт для WebApp initData


def validate_init_data(init_data: str) -> dict[str, object]:
    """Проверяет подпись Telegram WebApp initData. Возвращает user-объект.

    HMAC-SHA256 считается по ADMIN_BOT_TOKEN — это бот, через которого
    открыт Mini App. Spec: https://core.telegram.org/bots/webapps

    Порядок проверок (важен — defense in depth по timing):
      1) init_data не пуст и токен бота сконфигурирован;
      2) поле `hash` присутствует;
      3) HMAC совпадает (constant-time через ``hmac.compare_digest``);
      4) `auth_date` свежее (< 24ч);
      5) `user.id` входит в ``settings.allowed_user_ids``.

    HMAC сравнивается ДО парсинга `auth_date` и `user`, чтобы атакующий
    не мог по тайминг-разнице отличить «битый auth_date» от «битый HMAC»
    — оба теперь стоят одинаково (compare_digest всегда). Это гипотетический
    вектор (auth_date публичен в WebApp), но цена меры — ноль.
    """
    if not init_data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty init_data")
    if not settings.admin_bot_token:
        # без токена подписи мы вообще ничего проверить не можем —
        # отдаём 401, чтобы dev-окружение без ADMIN_BOT_TOKEN не пропускало запросы.
        logger.error("ADMIN_BOT_TOKEN не задан, отклоняю initData")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "admin bot not configured")

    # parse_qsl декодирует %XX (в т.ч. %0A → \n) в values. Это могло бы
    # обмануть data_check_string, НО подделать HMAC без знания ADMIN_BOT_TOKEN
    # атакующий не может — поэтому любые манипуляции с payload отвалятся на
    # compare_digest ниже. Инвариант: всё, что прошло HMAC, ≡ тому, что
    # Telegram сам подписал.
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(
        b"WebAppData", settings.admin_bot_token.encode(), hashlib.sha256
    ).digest()
    calc_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad hash")

    # HMAC валиден — payload подписан Telegram'ом. Дальше проверяем
    # бизнес-смысл (свежесть, whitelist).
    auth_date_raw = pairs.get("auth_date", "0")
    try:
        auth_date = int(auth_date_raw)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad auth_date") from e
    if auth_date <= 0 or time.time() - auth_date > _INIT_DATA_TTL_SEC:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "init_data expired")

    user_raw = pairs.get("user")
    if not user_raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no user")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad user json") from e

    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no user id") from e

    if user_id not in settings.allowed_user_ids:
        logger.warning("Mini App: deny user {} (not in allowed)", user_id)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return user


async def get_current_user(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
) -> dict[str, object]:
    """FastAPI dependency: возвращает user-dict из проверенного initData.

    Header optional на уровне сигнатуры, чтобы отсутствующий заголовок
    возвращал 401 (а не 422 от pydantic-валидатора FastAPI). Spec требует
    401 для всех «нет/битая авторизация»-кейсов — фронт ловит status и
    делает ``tg.close()``.
    """
    if not x_telegram_init_data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no init_data header")
    return validate_init_data(x_telegram_init_data)
