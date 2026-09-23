from datetime import date

from ted_procurement_mcp.supplier_matcher import match_notice_to_profile


def test_supplier_matcher_rewards_product_cpv_country_and_certification_mentions():
    notice = {
        "title": "GPS tracker devices with CE compliance",
        "descriptions": ["Supply of GPS dog tracking units. CE documentation required."],
        "cpv_codes": ["32522000"],
        "buyer_countries": ["DEU"],
        "publication_date": "2026-09-15",
        "deadlines": ["2026-10-20"],
    }
    profile = {
        "profile_id": "factory-a",
        "products": ["GPS tracker"],
        "cpv_codes": ["32522000"],
        "target_countries": ["DE"],
        "certifications": ["CE"],
        "excluded_countries": [],
    }
    result = match_notice_to_profile(notice, profile, today=date(2026, 9, 16))
    assert result["score"] >= 90
    assert result["components"]["product_match"] > 0
    assert result["components"]["certification_mention"] > 0


def test_supplier_matcher_excluded_country_zeroes_score():
    notice = {"title": "GPS tracker", "buyer_countries": ["DEU"], "cpv_codes": ["32522000"]}
    profile = {"profile_id": "factory-a", "products": ["GPS"], "excluded_countries": ["DE"]}
    result = match_notice_to_profile(notice, profile)
    assert result["score"] == 0
    assert result["excluded_market"] is True
