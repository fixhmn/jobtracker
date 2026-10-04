import asyncio
import logging
import signal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from app.config import Settings
from bot.api_client import ApiClient, ApiError
from bot.formatting import reminder_buttons, reminder_text

logger = logging.getLogger(__name__)


async def deliver_one(api, bot, settings):
    # Claim one item so a slow Telegram request cannot exhaust a whole batch's leases.
    items = await api.request("POST", "/internal/reminders/claim")
    if not items:
        return False
    item = items[0]
    result = {"lease_token": item["lease_token"], "success": False}
    try:
        await bot.send_message(
            settings.owner_telegram_id,
            reminder_text(item, settings.timezone),
            reply_markup=reminder_buttons(item["id"]),
        )
        result["success"] = True
    except TelegramRetryAfter as error:
        result.update(error="Telegram rate limit", retry_after=min(error.retry_after, 86400))
    except (TelegramForbiddenError, TelegramBadRequest):
        result.update(error="Telegram rejected the message; check chat access", permanent=True)
    except (TelegramNetworkError, TelegramServerError):
        result["error"] = "Telegram is temporarily unavailable"
    await api.request("POST", f"/internal/reminders/{item['id']}/delivery", json=result)
    logger.info("Reminder %s: %s", item["id"], "sent" if result["success"] else "delivery failed")
    return True


async def main():
    settings = Settings.from_env(telegram=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows console signals are handled by asyncio.run.
            pass
    api = ApiClient(settings.api_base_url, settings.api_key)
    bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        while not stop.is_set():
            try:
                if await deliver_one(api, bot, settings):
                    continue
            except ApiError as error:
                logger.warning("Worker request failed (status %s)", error.status)
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                pass
    finally:
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
