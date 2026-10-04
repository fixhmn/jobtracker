from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Include a timezone offset, for example -05:00 or Z")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def local_input(text: str, timezone: str) -> datetime:
    """Reject DST gaps and overlaps instead of guessing a reminder's time."""
    naive = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    zone = ZoneInfo(timezone)
    candidates = set()
    for fold in (0, 1):
        local = naive.replace(tzinfo=zone, fold=fold)
        utc = local.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            candidates.add(utc)
    if not candidates:
        raise ValueError(
            "That time does not exist when the clocks move forward. Pick another time."
        )
    if len(candidates) > 1:
        raise ValueError("That time occurs twice when the clocks change. Pick a time after 02:00.")
    return candidates.pop()
