from ted_procurement_mcp.normalizer import extract_notice_rows, extract_total, normalise_notice


def test_extract_notice_rows_accepts_common_response_keys():
    row = {"publication-number": "1-2026"}
    assert extract_notice_rows({"notices": [row]}) == [row]
    assert extract_notice_rows({"results": [row]}) == [row]
    assert extract_notice_rows({"items": [row]}) == [row]
    assert extract_notice_rows({"data": {"notices": [row]}}) == [row]


def test_extract_total_accepts_ted_and_generic_count_keys():
    assert extract_total({"totalNoticeCount": 12}) == 12
    assert extract_total({"total": 5}) == 5
    assert extract_total({"notices": [{}, {}]}) == 2


def test_normalise_notice_handles_multilingual_and_array_fields():
    row = {
        "publication-number": "123456-2026",
        "publication-date": "2026-09-15",
        "notice-title": {"eng": "GPS tracking equipment", "deu": "GPS Ausrüstung"},
        "buyer-name": ["City A", "Agency B"],
        "buyer-country": ["DEU"],
        "buyer-email": "procurement@example.eu",
        "buyer-internet-address": ["https://buyer.example"],
        "classification-cpv": ["32522000", "38112100"],
        "form-type": "competition",
        "notice-type": ["cn-standard"],
        "description-proc": {"eng": "Outdoor positioning and tracking devices"},
        "description-lot": ["Handheld receivers"],
        "deadline-receipt-tender-date-lot": ["2026-10-15"],
        "estimated-value-proc": 125000,
        "estimated-value-cur-proc": "EUR",
        "winner-name": {"eng": "Winner Ltd"},
        "winner-country": "FRA",
        "links": {"html": "https://ted.europa.eu/example"},
    }

    notice = normalise_notice(row)

    assert notice["publication_number"] == "123456-2026"
    assert notice["title"] == "GPS tracking equipment"
    assert notice["buyer_names"] == ["City A", "Agency B"]
    assert notice["buyer_countries"] == ["DEU"]
    assert notice["cpv_codes"] == ["32522000", "38112100"]
    assert notice["descriptions"] == ["Outdoor positioning and tracking devices", "Handheld receivers"]
    assert notice["deadlines"] == ["2026-10-15"]
    assert notice["estimated_values"][0] == {"level": "procedure", "amount": 125000.0, "currency": "EUR"}
    assert notice["winner_names"] == ["Winner Ltd"]
    assert notice["winner_countries"] == ["FRA"]
    assert notice["ted_urls"] == ["https://ted.europa.eu/example"]
    assert notice["source"] == "TED"
