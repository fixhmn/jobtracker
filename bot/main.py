import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, CallbackQuery, Message

from app.config import Settings
from bot.api_client import ApiClient, ApiError
from bot.handlers import make_router
from bot.manage import make_management_router


class OwnerOnly(BaseMiddleware):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        message = event.message if isinstance(event, CallbackQuery) else event
        chat = getattr(message, "chat", None)
        if not user or user.id != self.owner_id or not chat or chat.type != "private":
            if isinstance(event, CallbackQuery):
                await event.answer("This is a private tracker.")
            return None
        try:
            return await handler(event, data)
        except ApiError as error:
            if isinstance(event, CallbackQuery):
                await event.answer()
            if isinstance(message, Message):
                await message.answer(str(error))


def make_dispatcher(settings: Settings, api: ApiClient):
    dispatcher = Dispatcher(settings=settings, api=api)
    middleware = OwnerOnly(settings.owner_telegram_id)
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)
    dispatcher.include_router(make_management_router())
    dispatcher.include_router(make_router())
    return dispatcher


async def main():
    settings = Settings.from_env(telegram=True)
    api = ApiClient(settings.api_base_url, settings.api_key)
    bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = make_dispatcher(settings, api)
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="new", description="Save a job"),
                BotCommand(command="list", description="Your jobs"),
                BotCommand(command="search", description="Find a saved job"),
                BotCommand(command="edit", description="Edit a saved job"),
                BotCommand(command="history", description="Status changes"),
                BotCommand(command="withdraw", description="Mark a job as withdrawn"),
                BotCommand(command="today", description="Today's follow-ups"),
                BotCommand(command="reminders", description="Browse reminders"),
                BotCommand(command="reschedule", description="Move a reminder"),
                BotCommand(command="export", description="Download jobs as CSV"),
                BotCommand(command="stats", description="Last 30 days"),
                BotCommand(command="help", description="All commands"),
                BotCommand(command="cancel", description="Discard the current form"),
            ]
        )
        await dispatcher.start_polling(bot)
    finally:
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
