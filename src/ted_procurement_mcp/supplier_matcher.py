from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import Any

from .query_builder import normalise_country_codes


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[\w+-]+", text or "", flags=re.UNICODE) if len(t) > 1]


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            pass
    return None


def _cpv_match(actual: list[str], wanted: list[str]) -> bool:
    for target in wanted:
        prefix = target[:-1] if target.endswith("*") else target
        if any(code == target or str(code).startswith(prefix) for code in actual):
            return True
    return False


def match_notice_to_profile(
    notice: dict[str, Any],
    profile: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    notice_countries = set(normalise_country_codes(notice.get("buyer_countries") or []))
    excluded = set(normalise_country_codes(profile.get("excluded_countries") or []))
    if notice_countries.intersection(excluded):
        return {
            "score": 0,
            "excluded_market": True,
            "components": {},
            "constraints_to_verify": ["Tender eligibility", "technical specification", "delivery terms"],
        }

    components = {
        "product_match": 0,
        "cpv_match": 0,
        "country_match": 0,
        "freshness": 0,
        "open_deadline": 0,
        "certification_mention": 0,
    }
    haystack = " ".join([
        str(notice.get("title") or ""),
        " ".join(notice.get("descriptions") or []),
    ]).lower()

    product_tokens = list(dict.fromkeys(
        token for product in (profile.get("products") or []) for token in _tokens(product)
    ))
    if product_tokens:
        matched = sum(1 for token in product_tokens if token in haystack)
        components["product_match"] = min(30, math.floor(30 * matched / len(product_tokens) + 0.5))

    cpv_codes = profile.get("cpv_codes") or []
    if cpv_codes and _cpv_match(notice.get("cpv_codes") or [], cpv_codes):
        components["cpv_match"] = 25

    targets = set(normalise_country_codes(profile.get("target_countries") or []))
    if targets and notice_countries.intersection(targets):
        components["country_match"] = 15

    published = _parse_date(notice.get("publication_date"))
    if published:
        age = (today - published).days
        if age <= 7:
            components["freshness"] = 10
        elif age <= 30:
            components["freshness"] = 7
        elif age <= 90:
            components["freshness"] = 3

    deadlines = [_parse_date(v) for v in notice.get("deadlines") or []]
    if any(d and d >= today for d in deadlines):
        components["open_deadline"] = 10

    certifications = [str(c).strip().lower() for c in profile.get("certifications") or [] if str(c).strip()]
    if certifications and any(cert in haystack for cert in certifications):
        components["certification_mention"] = 10

    return {
        "score": max(0, min(100, sum(components.values()))),
        "excluded_market": False,
        "components": components,
        "constraints_to_verify": [
            "Tender eligibility",
            "technical specification",
            "required certifications",
            "MOQ/quantity fit",
            "delivery lead time",
            "payment and contract terms",
        ],
    }
