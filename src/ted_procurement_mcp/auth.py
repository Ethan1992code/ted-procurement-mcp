from __future__ import annotations

import hashlib
import hmac
from datetime import date
from typing import Any


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class ApiKeyGate:
    def __init__(self, store: Any) -> None:
        self.store = store

    def authorize(self, raw_key: str | None, *, today: date | None = None) -> dict[str, Any]:
        if not raw_key:
            return {"allowed": False, "reason": "missing_api_key"}
        key_hash = hash_api_key(raw_key)
        row = self.store.get_api_key(key_hash)
        if not row or not hmac.compare_digest(str(row.get("key_hash") or ""), key_hash):
            return {"allowed": False, "reason": "invalid_api_key"}
        if not bool(row.get("enabled")):
            return {"allowed": False, "reason": "disabled_api_key"}

        today = today or date.today()
        count = self.store.increment_api_usage(key_hash, today.isoformat())
        quota = int(row.get("daily_quota") or 0)
        if quota > 0 and count > quota:
            return {"allowed": False, "reason": "quota_exceeded", "remaining": 0}
        return {
            "allowed": True,
            "name": row.get("name"),
            "remaining": max(0, quota - count) if quota > 0 else None,
        }
