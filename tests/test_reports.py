from datetime import timedelta

import httpx
import pytest

from bot.api_client import ApiClient, ApiError
from reports.summary import build_summary, cell, fetch_pages


async def test_report_uses_api_and_excludes_private_fields(app, client, settings, job, clock):
    client.patch(
        f"/applications/{job['id']}",
        json={"company": "Example | <script>", "status": "Applied", "notes": "private note"},
    )
    for text, offset in [("secret reminder", -1), ("later", 8)]:
        client.post(
            f"/applications/{job['id']}/reminders",
            json={"text": text, "due_at": (clock.now + timedelta(days=offset)).isoformat()},
        )
    api = ApiClient("http://test", settings.api_key, transport=httpx.ASGITransport(app=app))
    try:
        report = await build_summary(api, settings, now=clock.now)
    finally:
        await api.close()
    assert "| Applied | 1 |" in report
    assert r"Example \| &lt;script&gt;" in report
    assert "| pending | Yes |" in report
    assert "#2" not in report
    for private in ("private note", "secret reminder", job["url"], settings.api_key):
        assert private not in report


async def test_empty_report_and_invalid_key(app, client, settings, clock):
    api = ApiClient("http://test", settings.api_key, transport=httpx.ASGITransport(app=app))
    try:
        report = await build_summary(api, settings, now=clock.now)
        assert "Total saved jobs: 0" in report
        assert "No unfinished follow-ups" in report
        api.client.headers["X-API-Key"] = "wrong"
        with pytest.raises(ApiError) as error:
            await build_summary(api, settings, now=clock.now)
        assert error.value.status == 401
    finally:
        await api.close()


async def test_report_pagination_and_limit():
    class FakeApi:
        async def request(self, method, path, params):
            return {
                "total": 101,
                "items": list(range(params["offset"], min(101, params["offset"] + 100))),
            }

    assert await fetch_pages(FakeApi(), "/applications") == list(range(101))

    class TooMany:
        async def request(self, *args, **kwargs):
            return {"total": 5001, "items": []}

    with pytest.raises(ValueError, match="5000"):
        await fetch_pages(TooMany(), "/applications")


@pytest.mark.parametrize("days", [0, 31])
async def test_invalid_report_window(settings, days):
    with pytest.raises(ValueError, match="1 and 30"):
        await build_summary(None, settings, days=days)


def test_markdown_cell_is_one_line_and_not_a_link():
    assert cell("[click](https://example.com)\n| **test**") == (
        r"\[click\](https://example.com) \| \*\*test\*\*"
    )
