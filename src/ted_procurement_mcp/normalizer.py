from __future__ import annotations

from collections.abc import Iterable
from typing import Any


DEFAULT_NOTICE_FIELDS = [
    "publication-number",
    "publication-date",
    "notice-title",
    "buyer-name",
    "buyer-country",
    "buyer-email",
    "buyer-internet-address",
    "classification-cpv",
    "form-type",
    "notice-type",
    "description-proc",
    "description-lot",
    "deadline-receipt-tender-date-lot",
    "deadline-receipt-request-date-lot",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "estimated-value-lot",
    "estimated-value-cur-lot",
]

AWARD_FIELDS = DEFAULT_NOTICE_FIELDS + [
    "winner-name",
    "winner-country",
    "winner-email",
    "tender-value",
    "tender-value-cur",
    "result-value-notice",
    "result-value-cur-notice",
]


def extract_notice_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("notices", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = payload.get("data")
    if isinstance(nested, dict):
        return extract_notice_rows(nested)
    return []


def extract_total(payload: dict[str, Any]) -> int:
    for key in ("totalNoticeCount", "total", "totalCount", "count"):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return len(extract_notice_rows(payload))


def _flatten(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        # Prefer English when TED returns language maps, otherwise preserve all values.
        for key in ("eng", "en", "ENG", "EN"):
            if key in value:
                primary = _flatten(value[key])
                if primary:
                    return primary
        result: list[Any] = []
        for child in value.values():
            result.extend(_flatten(child))
        return result
    if isinstance(value, (list, tuple, set)):
        result: list[Any] = []
        for child in value:
            result.extend(_flatten(child))
        return result
    return [value]


def _strings(value: Any) -> list[str]:
    result: list[str] = []
    for item in _flatten(value):
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _first(value: Any) -> str | None:
    values = _strings(value)
    return values[0] if values else None


def _numbers(value: Any) -> list[float]:
    result: list[float] = []
    for item in _flatten(value):
        if isinstance(item, bool):
            continue
        try:
            number = float(str(item).replace(",", ""))
        except (TypeError, ValueError):
            continue
        result.append(number)
    return result


def _urls(value: Any) -> list[str]:
    urls: list[str] = []
    for text in _strings(value):
        if text.startswith(("http://", "https://")) and text not in urls:
            urls.append(text)
    return urls


def _value_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pairs = [
        ("procedure", "estimated-value-proc", "estimated-value-cur-proc"),
        ("lot", "estimated-value-lot", "estimated-value-cur-lot"),
    ]
    for level, amount_key, currency_key in pairs:
        amounts = _numbers(row.get(amount_key))
        currencies = _strings(row.get(currency_key))
        for idx, amount in enumerate(amounts):
            currency = currencies[min(idx, len(currencies) - 1)] if currencies else None
            record = {"level": level, "amount": amount, "currency": currency}
            if record not in records:
                records.append(record)
    return records


def _result_value_records(row: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pairs = [
        ("tender", "tender-value", "tender-value-cur"),
        ("notice_result", "result-value-notice", "result-value-cur-notice"),
    ]
    for level, amount_key, currency_key in pairs:
        amounts = _numbers(row.get(amount_key))
        currencies = _strings(row.get(currency_key))
        for idx, amount in enumerate(amounts):
            currency = currencies[min(idx, len(currencies) - 1)] if currencies else None
            records.append({"level": level, "amount": amount, "currency": currency})
    return records


def normalise_notice(row: dict[str, Any]) -> dict[str, Any]:
    link_values: list[str] = []
    for key in ("links", "url", "urls", "ted-url", "notice-url"):
        link_values.extend(_urls(row.get(key)))

    deadlines: list[str] = []
    for key in (
        "deadline-receipt-tender-date-lot",
        "deadline-receipt-request-date-lot",
        "deadline",
    ):
        for value in _strings(row.get(key)):
            if value not in deadlines:
                deadlines.append(value)

    return {
        "publication_number": _first(row.get("publication-number")),
        "publication_date": _first(row.get("publication-date")),
        "title": _first(row.get("notice-title")) or _first(row.get("title-proc")),
        "buyer_names": _strings(row.get("buyer-name")),
        "buyer_countries": _strings(row.get("buyer-country")),
        "buyer_emails": _strings(row.get("buyer-email")),
        "buyer_websites": _urls(row.get("buyer-internet-address")),
        "cpv_codes": _strings(row.get("classification-cpv")),
        "descriptions": list(
            dict.fromkeys(
                _strings(row.get("description-proc"))
                + _strings(row.get("description-lot"))
            )
        ),
        "form_type": _first(row.get("form-type")),
        "notice_type": _first(row.get("notice-type")),
        "deadlines": deadlines,
        "estimated_values": _value_records(row),
        "winner_names": _strings(row.get("winner-name")),
        "winner_countries": _strings(row.get("winner-country")),
        "winner_emails": _strings(row.get("winner-email")),
        "result_values": _result_value_records(row),
        "ted_urls": list(dict.fromkeys(link_values)),
        "source": "TED",
    }
