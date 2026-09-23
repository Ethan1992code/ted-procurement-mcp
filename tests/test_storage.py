from pathlib import Path

from ted_procurement_mcp.storage import SQLiteNoticeStore


def test_sqlite_store_upserts_and_queries_recent_notices(tmp_path: Path):
    store = SQLiteNoticeStore(tmp_path / "ted.db")
    notice = {
        "publication_number": "123-2026",
        "publication_date": "2026-09-16",
        "title": "GPS tracker supply",
        "buyer_names": ["Buyer A"],
        "buyer_countries": ["DEU"],
        "cpv_codes": ["32522000"],
        "source": "TED",
    }
    assert store.upsert_notices([notice]) == 1
    notice["title"] = "Updated GPS tracker supply"
    assert store.upsert_notices([notice]) == 1

    rows = store.list_notices_since("2026-09-15", limit=10)
    assert len(rows) == 1
    assert rows[0]["title"] == "Updated GPS tracker supply"
    assert store.stats()["notice_count"] == 1


def test_sqlite_store_round_trips_supplier_profile(tmp_path: Path):
    store = SQLiteNoticeStore(tmp_path / "ted.db")
    profile = {"profile_id": "factory-a", "products": ["GPS tracker"], "target_countries": ["DE"]}
    store.upsert_supplier_profile(profile)
    assert store.get_supplier_profile("factory-a") == profile
