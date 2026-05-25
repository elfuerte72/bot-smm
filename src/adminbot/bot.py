from __future__ import annotations

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    KeyboardButton,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from loguru import logger

from src.bot.middleware import OwnerOnlyMiddleware
from src.config import settings

router = Router()

_WELCOME_TEXT = (
    "Это admin-панель SMM-бота. Нажми кнопку ниже, чтобы открыть Mini App.\n\n"
    "Если кнопки нет — проверь, что MINI_APP_URL настроен и доступен по HTTPS."
)


def _webapp_keyboard() -> ReplyKeyboardMarkup | None:
    """Reply-клавиатура с одной кнопкой, открывающей Mini App.

    Возвращает None, если ``MINI_APP_URL`` не задан — kbd-кнопку с пустым
    URL Telegram отклонит. В этом случае /start всё равно отвечает текстом.
    """
    url = settings.mini_app_url
    if not url:
        return None
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📊 Статистика",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    kb = _webapp_keyboard()
    if kb is None:
        await message.answer(
            "Mini App не настроен: MINI_APP_URL пуст. Сообщи разработчику."
        )
        return
    await message.answer(_WELCOME_TEXT, reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    kb = _webapp_keyboard()
    await message.answer(
        "Команды:\n"
        "  /start — открыть Mini App\n"
        "  /help — эта справка\n\n"
        "Все остальные действия — внутри Mini App.",
        reply_markup=kb,
    )


def build_admin_bot() -> tuple[Bot, Dispatcher]:
    """Создаёт второй (admin) Bot+Dispatcher.

    ADMIN_BOT_TOKEN — отдельный бот, созданный через @BotFather. Он же
    подписывает initData, который проверяет webapp.auth.validate_init_data.
    Middleware ``OwnerOnlyMiddleware`` тот же, что у main-бота, чтобы
    исключить случайных пользователей.
    """
    if not settings.admin_bot_token:
        raise RuntimeError("ADMIN_BOT_TOKEN не задан, admin-бот не может стартовать")
    bot = Bot(
        token=settings.admin_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    owner_mw = OwnerOnlyMiddleware(settings.allowed_user_ids)
    dp.message.middleware(owner_mw)
    dp.callback_query.middleware(owner_mw)
    dp.include_router(router)
    return bot, dp


async def setup_admin_menu_buttons(bot: Bot) -> None:
    """Ставит каждому allowed-юзеру MenuButtonWebApp.

    Делается best-effort: если юзер не начинал диалог с ботом или приватность
    не позволяет — ловим исключение и идём дальше. Фолбэк — Reply-клавиатура
    в /start (она ставится при первом сообщении пользователя).
    Также вешает default-команды /start, /help в меню бота.
    """
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Открыть Mini App"),
            BotCommand(command="help", description="Помощь"),
        ]
    )

    url = settings.mini_app_url
    if not url:
        logger.info("MINI_APP_URL пуст, menu button не ставится")
        return

    button = MenuButtonWebApp(text="📊 Статистика", web_app=WebAppInfo(url=url))
    for user_id in sorted(settings.allowed_user_ids):
        try:
            await bot.set_chat_menu_button(chat_id=user_id, menu_button=button)
            logger.info("admin-bot: menu button установлен для user_id={}", user_id)
        except TelegramAPIError as e:
            # Самое частое — пользователь ещё не делал /start. Это нормально,
            # фолбэк — клавиатура при первом /start.
            logger.warning(
                "admin-bot: не удалось поставить menu button для {}: {}", user_id, e
            )
