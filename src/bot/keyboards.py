from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сгенерировать пост", callback_data="menu:generate")],
            [
                InlineKeyboardButton(text="📊 Статус", callback_data="menu:status"),
                InlineKeyboardButton(text="⏰ Расписание", callback_data="menu:cron"),
            ],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
        ]
    )


def preview_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Опубликовать", callback_data=f"approve:{draft_id}"),
            ],
            [
                InlineKeyboardButton(text="Перегенерировать", callback_data=f"regen:{draft_id}"),
                InlineKeyboardButton(text="Редактировать", callback_data=f"edit:{draft_id}"),
            ],
            [
                InlineKeyboardButton(text="Отклонить", callback_data=f"reject:{draft_id}"),
            ],
        ]
    )


def edit_cancel_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена правки", callback_data=f"editcancel:{draft_id}")]
        ]
    )


def generation_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Авто", callback_data="gen:auto")],
            [InlineKeyboardButton(text="⚙️ Ручная настройка", callback_data="gen:manual")],
        ]
    )


def manual_config_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Своя тема", callback_data="gen:topic")],
            [InlineKeyboardButton(text="🔗 По ссылке", callback_data="gen:url")],
            [InlineKeyboardButton(text="← Назад", callback_data="gen:back")],
        ]
    )
