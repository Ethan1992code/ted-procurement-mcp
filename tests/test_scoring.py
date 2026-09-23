from datetime import date

from ted_procurement_mcp.scoring import score_opportunity


def test_score_opportunity_is_explainable_and_capped():
    notice = {
        "title": "Supply of GPS tracker devices for field teams",
        "cpv_codes": ["32522000"],
        "buyer_countries": ["DEU"],
        "publication_date": "2026-09-15",
        "deadlines": ["2026-10-10"],
    }
    result = score_opportunity(
        notice,
        product="GPS tracker",
        requested_cpv=["32522000"],
        requested_countries=["DE"],
        today=date(2026, 9, 16),
    )
    assert result["score"] == 100
    assert result["components"] == {
        "keyword_match": 35,
        "cpv_match": 25,
        "country_match": 15,
        "freshness": 15,
        "open_deadline": 10,
    }


def test_score_opportunity_partial_keyword_and_stale_notice():
    notice = {
        "title": "Supply of GPS receivers",
        "cpv_codes": [],
        "buyer_countries": [],
        "publication_date": "2026-05-01",
        "deadlines": ["2026-06-01"],
    }
    result = score_opportunity(
        notice,
        product="GPS tracker",
        today=date(2026, 9, 16),
    )
    assert result["components"]["keyword_match"] == 18
    assert result["components"]["freshness"] == 0
    assert result["components"]["open_deadline"] == 0
    assert result["score"] == 18


def test_cpv_prefix_matches_child_code():
    notice = {
        "title": "IT equipment",
        "cpv_codes": ["30213000"],
        "buyer_countries": [],
        "publication_date": "2026-09-10",
        "deadlines": [],
    }
    result = score_opportunity(
        notice,
        product="equipment",
        requested_cpv=["302*"],
        today=date(2026, 9, 16),
    )
    assert result["components"]["cpv_match"] == 25


def test_keyword_score_uses_notice_descriptions_when_title_is_generic():
    notice = {
        "title": "Framework agreement",
        "descriptions": ["Purchase of GPS tracker devices for field operations"],
        "cpv_codes": [],
        "buyer_countries": [],
        "publication_date": "2026-09-15",
        "deadlines": [],
    }
    result = score_opportunity(
        notice,
        product="GPS tracker",
        today=date(2026, 9, 16),
    )
    assert result["components"]["keyword_match"] == 35
