from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import datetime

from app.schemas.article import NormalizedArticle
from app.services.timestamps import parse_published_at as _parse_published_at

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def publication_times_eligible(left: datetime | None, right: datetime | None, max_gap_hours: float) -> bool:
    """Hard eligibility gate for new persistent memberships, anchored to primary."""
    if left is None or right is None or left.utcoffset() is None or right.utcoffset() is None:
        return False
    return abs((left - right).total_seconds()) <= max_gap_hours * 3600


def normalize_title(title: str) -> str:
    tokens = _WORD_RE.findall(title.lower())
    return " ".join(tokens)


def _token_set(title: str) -> set[str]:
    normalized = normalize_title(title)
    if not normalized:
        return set()
    return set(normalized.split())


def title_similarity(left: str, right: str) -> float:
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)

    if not left_normalized or not right_normalized:
        return 0.0

    sequence_score = SequenceMatcher(None, left_normalized, right_normalized).ratio()

    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    overlap_score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)

    return (sequence_score * 0.65) + (overlap_score * 0.35)


def time_proximity_score(left: str | None, right: str | None) -> float:
    left_dt = _parse_published_at(left)
    right_dt = _parse_published_at(right)

    if left_dt is None or right_dt is None:
        return 0.0

    hours_apart = abs((left_dt - right_dt).total_seconds()) / 3600

    if hours_apart <= 2:
        return 1.0
    if hours_apart <= 6:
        return 0.8
    if hours_apart <= 12:
        return 0.6
    if hours_apart <= 24:
        return 0.4
    if hours_apart <= 48:
        return 0.2
    return 0.0


def category_overlap_score(left_categories: list[str], right_categories: list[str]) -> float:
    left_tokens = {value.strip().lower() for value in left_categories if value.strip()}
    right_tokens = {value.strip().lower() for value in right_categories if value.strip()}

    if not left_tokens or not right_tokens:
        return 0.0

    return len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)


def similarity_score(left: NormalizedArticle, right: NormalizedArticle) -> int:
    title_score = title_similarity(left.title, right.title)
    time_score = time_proximity_score(left.published_at, right.published_at)
    categories_score = category_overlap_score(left.categories, right.categories)

    weighted = (title_score * 0.6) + (time_score * 0.25) + (categories_score * 0.15)
    return max(0, min(100, round(weighted * 100)))
