from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any, Iterable

from .query_builder import normalise_country_codes


def _tokens(text: str | None) -> list[str]:
    if not text:
        return []
    return [token.lower() for token in re.findall(r"[\w+-]+", text, flags=re.UNICODE) if len(token) > 1]


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text[:19] if "%H" in fmt else text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    return None


def _cpv_matches(notice_codes: Iterable[str], requested_codes: Iterable[str]) -> bool:
    notice = [str(code).strip() for code in notice_codes if str(code).strip()]
    requested = [str(code).strip() for code in requested_codes if str(code).strip()]
    for wanted in requested:
        prefix = wanted[:-1] if wanted.endswith("*") else wanted
        for actual in notice:
            if actual == wanted or actual.startswith(prefix):
                return True
    return False


def score_opportunity(
    notice: dict[str, Any],
    *,
    product: str,
    requested_cpv: Iterable[str] | None = None,
    requested_countries: Iterable[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return an explainable 0-100 supplier-opportunity relevance score."""

    today = today or date.today()
    components = {
        "keyword_match": 0,
        "cpv_match": 0,
        "country_match": 0,
        "freshness": 0,
        "open_deadline": 0,
    }

    wanted_tokens = list(dict.fromkeys(_tokens(product)))
    haystack = " ".join(
        str(value or "")
        for value in (
            notice.get("title"),
            " ".join(notice.get("descriptions") or []),
            " ".join(notice.get("buyer_names") or []),
        )
    ).lower()
    if wanted_tokens:
        matched = sum(1 for token in wanted_tokens if token in haystack)
        ratio = matched / len(wanted_tokens)
        # Nearest whole point; 17.5 should become 18, not Python's bankers-round 18/17 variance.
        components["keyword_match"] = min(35, math.floor(35 * ratio + 0.5))

    requested_cpv = list(requested_cpv or [])
    if requested_cpv and _cpv_matches(notice.get("cpv_codes") or [], requested_cpv):
        components["cpv_match"] = 25

    requested_country_codes = set(normalise_country_codes(requested_countries))
    notice_country_codes = set(normalise_country_codes(notice.get("buyer_countries") or []))
    if requested_country_codes and requested_country_codes.intersection(notice_country_codes):
        components["country_match"] = 15

    published = _parse_date(notice.get("publication_date"))
    if published:
        age = (today - published).days
        if age <= 7:
            components["freshness"] = 15
        elif age <= 30:
            components["freshness"] = 10
        elif age <= 90:
            components["freshness"] = 5

    deadlines = [_parse_date(value) for value in (notice.get("deadlines") or [])]
    if any(deadline and deadline >= today for deadline in deadlines):
        components["open_deadline"] = 10

    score = max(0, min(100, sum(components.values())))
    return {"score": score, "components": components}
