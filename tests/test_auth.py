from datetime import date

from ted_procurement_mcp.auth import ApiKeyGate, hash_api_key


class MemoryAuthStore:
    def __init__(self, row):
        self.row = row
        self.count = 0

    def get_api_key(self, key_hash):
        return self.row if key_hash == self.row["key_hash"] else None

    def increment_api_usage(self, key_hash, usage_date):
        self.count += 1
        return self.count


def test_api_key_gate_accepts_valid_key_and_counts_usage():
    raw = "ted_live_secret"
    row = {"key_hash": hash_api_key(raw), "name": "client-a", "daily_quota": 2, "enabled": True}
    gate = ApiKeyGate(MemoryAuthStore(row))
    first = gate.authorize(raw, today=date(2026, 9, 16))
    assert first["allowed"] is True
    assert first["remaining"] == 1


def test_api_key_gate_rejects_over_quota_without_exposing_raw_key():
    raw = "ted_live_secret"
    store = MemoryAuthStore({"key_hash": hash_api_key(raw), "name": "client-a", "daily_quota": 1, "enabled": True})
    gate = ApiKeyGate(store)
    gate.authorize(raw, today=date(2026, 9, 16))
    result = gate.authorize(raw, today=date(2026, 9, 16))
    assert result["allowed"] is False
    assert result["reason"] == "quota_exceeded"
    assert raw not in repr(result)
