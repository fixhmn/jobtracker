import asyncio
import os

from aiogram import Bot
from dotenv import load_dotenv


async def main():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Set TELEGRAM_BOT_TOKEN in .env first")
    bot = Bot(token)
    try:
        updates = await bot.get_updates(timeout=10)
        owners = {
            update.message.from_user.id
            for update in updates
            if update.message and update.message.chat.type == "private" and update.message.from_user
        }
        if owners:
            print(
                "Recent private-chat sender IDs:", ", ".join(str(owner) for owner in sorted(owners))
            )
            print("Set OWNER_TELEGRAM_ID to your own ID. Do not choose another sender's ID.")
        else:
            print("No recent private messages. Send /start to your bot and run this command again.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
