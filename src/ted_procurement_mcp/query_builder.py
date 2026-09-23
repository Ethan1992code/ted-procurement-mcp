from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable


ISO2_TO_ISO3 = {
    "AT": "AUT", "BE": "BEL", "BG": "BGR", "HR": "HRV", "CY": "CYP",
    "CZ": "CZE", "DE": "DEU", "DK": "DNK", "EE": "EST", "ES": "ESP",
    "FI": "FIN", "FR": "FRA", "GR": "GRC", "EL": "GRC", "HU": "HUN",
    "IE": "IRL", "IT": "ITA", "LT": "LTU", "LU": "LUX", "LV": "LVA",
    "MT": "MLT", "NL": "NLD", "PL": "POL", "PT": "PRT", "RO": "ROU",
    "SE": "SWE", "SI": "SVN", "SK": "SVK", "IS": "ISL", "LI": "LIE",
    "NO": "NOR", "CH": "CHE", "GB": "GBR", "UK": "GBR",
}


def normalise_country_codes(codes: Iterable[str] | None) -> list[str]:
    if not codes:
        return []
    result: list[str] = []
    for raw in codes:
        code = raw.strip().upper()
        if not code:
            continue
        if len(code) == 2:
            code = ISO2_TO_ISO3.get(code, code)
        if code not in result:
            result.append(code)
    return result


def _date_token(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    cleaned = re.sub(r"[^0-9]", "", str(value))
    if len(cleaned) != 8:
        raise ValueError(f"date must resolve to YYYYMMDD, got {value!r}")
    return cleaned


def _keyword_expression(value: str) -> str:
    # TED expert syntax treats parentheses/quotes as operators; for a supplier-facing
    # helper we intentionally turn free input into a safe implicit-AND token group.
    cleaned = re.sub(r"[^\w*.+-]+", " ", value, flags=re.UNICODE)
    tokens = [token for token in cleaned.split() if token]
    if not tokens:
        raise ValueError("keywords must contain at least one searchable token")
    return " ".join(tokens)


def _cpv_expression(codes: Iterable[str]) -> str:
    safe: list[str] = []
    for raw in codes:
        code = raw.strip()
        if not re.fullmatch(r"[0-9]{2,8}\*?", code):
            raise ValueError(f"invalid CPV code/prefix: {raw!r}")
        safe.append(code)
    if not safe:
        return ""
    if len(safe) == 1:
        return f"classification-cpv = {safe[0]}"
    return f"classification-cpv = ({' OR '.join(safe)})"


def build_procurement_query(
    *,
    keywords: str | None = None,
    cpv_codes: Iterable[str] | None = None,
    buyer_countries: Iterable[str] | None = None,
    date_from: date | datetime | str | None = None,
    date_to: date | datetime | str | None = None,
    form_type: str | None = None,
    buyer_name: str | None = None,
    publication_number: str | None = None,
) -> str:
    clauses: list[str] = []

    if keywords:
        clauses.append(f"FT ~ ({_keyword_expression(keywords)})")

    if cpv_codes:
        cpv_clause = _cpv_expression(cpv_codes)
        if cpv_clause:
            clauses.append(cpv_clause)

    countries = normalise_country_codes(buyer_countries)
    if countries:
        clauses.append(f"buyer-country IN ({' '.join(countries)})")

    if date_from and date_to:
        clauses.append(
            f"publication-date = ({_date_token(date_from)} <> {_date_token(date_to)})"
        )
    elif date_from:
        clauses.append(f"publication-date >= {_date_token(date_from)}")
    elif date_to:
        clauses.append(f"publication-date <= {_date_token(date_to)}")

    if form_type:
        form = re.sub(r"[^a-z-]", "", form_type.lower())
        if not form:
            raise ValueError("invalid form_type")
        clauses.append(f"form-type = {form}")

    if buyer_name:
        name = _keyword_expression(buyer_name)
        clauses.append(f'buyer-name ~ "{name}"' if " " in name else f"buyer-name ~ {name}")

    if publication_number:
        number = re.sub(r"[^0-9-]", "", publication_number)
        if not number:
            raise ValueError("invalid publication number")
        clauses.append(f"publication-number = {number}")

    return " AND ".join(clauses) if clauses else "OJ = ()"
