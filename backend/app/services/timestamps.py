from datetime import datetime, timezone


def parse_published_at(value: str | None) -> datetime | None:
    """Interpret timezone-less source dates as UTC; reject unusable dates."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def published_sort_key(value: str | None) -> datetime:
    return parse_published_at(value) or datetime.min.replace(tzinfo=timezone.utc)
