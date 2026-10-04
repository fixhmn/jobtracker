from datetime import UTC, datetime, timedelta

import httpx
import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, GetMe
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from bot.api_client import ApiClient
from bot.main import make_dispatcher


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_key="test-key-" + "x" * 24, database_path=tmp_path / "test.db", owner_telegram_id=123
    )


@pytest.fixture
def app(settings, clock):
    return create_app(settings, clock)


@pytest.fixture
def client(app, settings):
    with TestClient(app, headers={"X-API-Key": settings.api_key}) as client:
        yield client


@pytest.fixture
def job(client):
    response = client.post(
        "/applications",
        json={
            "company": "Example Co",
            "position": "Python Developer",
            "url": "https://example.com/jobs?id=1&utm_source=test#details",
            "salary_min": 75000,
            "salary_max": 90000,
        },
    )
    assert response.status_code == 201
    return response.json()


class TelegramSession(BaseSession):
    """Collect replies and return Telegram-shaped results without network access."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, GetMe):
            return User(id=987, is_bot=True, first_name="Tracker", username="tracker_bot")
        return Message(
            message_id=len(self.calls),
            date=datetime.now(UTC),
            chat=Chat(id=123, type="private"),
            text=getattr(method, "text", ""),
        )

    async def stream_content(
        self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True
    ):
        yield b""


@pytest.fixture
async def bot_setup(client, app, settings):
    api = ApiClient("http://test", settings.api_key, transport=httpx.ASGITransport(app=app))
    session = TelegramSession()
    bot = Bot(
        "987:TEST_TOKEN", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dispatcher = make_dispatcher(settings, api)
    counter = 0

    async def send(text=None, callback=None, user_id=123, chat_type="private"):
        nonlocal counter
        counter += 1
        user = User(id=user_id, is_bot=False, first_name="User")
        message = Message(
            message_id=counter,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type=chat_type),
            from_user=user,
            text=text,
        )
        if callback:
            update = Update(
                update_id=counter,
                callback_query=CallbackQuery(
                    id=str(counter),
                    from_user=user,
                    chat_instance="test",
                    message=message,
                    data=callback,
                ),
            )
        else:
            update = Update(update_id=counter, message=message)
        return await dispatcher.feed_update(bot, update)

    yield send, session
    await api.close()
    await bot.session.close()
    await dispatcher.storage.close()
