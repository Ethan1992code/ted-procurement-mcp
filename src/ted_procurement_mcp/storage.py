from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class SQLiteNoticeStore:
    """Small durable warehouse for local/self-hosted deployments."""

    def __init__(self, path: str | Path = "ted_procurement.db") -> None:
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notices (
                    publication_number TEXT PRIMARY KEY,
                    publication_date TEXT,
                    title TEXT,
                    buyer_names_json TEXT NOT NULL,
                    buyer_countries_json TEXT NOT NULL,
                    cpv_codes_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notices_publication_date
                    ON notices(publication_date);
                CREATE TABLE IF NOT EXISTS supplier_profiles (
                    profile_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_state (
                    sync_key TEXT PRIMARY KEY,
                    iteration_next_token TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_hash TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    daily_quota INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_usage (
                    key_hash TEXT NOT NULL,
                    usage_date TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(key_hash, usage_date)
                );
                """
            )

    def upsert_notices(self, notices: list[dict[str, Any]]) -> int:
        written = 0
        now = _utc_now()
        with self._connect() as conn:
            for notice in notices:
                number = notice.get("publication_number")
                if not number:
                    continue
                conn.execute(
                    """
                    INSERT INTO notices (
                        publication_number, publication_date, title,
                        buyer_names_json, buyer_countries_json, cpv_codes_json,
                        payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(publication_number) DO UPDATE SET
                        publication_date=excluded.publication_date,
                        title=excluded.title,
                        buyer_names_json=excluded.buyer_names_json,
                        buyer_countries_json=excluded.buyer_countries_json,
                        cpv_codes_json=excluded.cpv_codes_json,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        number,
                        notice.get("publication_date"),
                        notice.get("title"),
                        _json(notice.get("buyer_names") or []),
                        _json(notice.get("buyer_countries") or []),
                        _json(notice.get("cpv_codes") or []),
                        _json(notice),
                        now,
                    ),
                )
                written += 1
        return written

    def list_notices_since(self, date_from: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM notices
                WHERE publication_date >= ?
                ORDER BY publication_date DESC, publication_number DESC
                LIMIT ?
                """,
                (date_from, limit),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def upsert_supplier_profile(self, profile: dict[str, Any]) -> None:
        profile_id = str(profile.get("profile_id") or "").strip()
        if not profile_id:
            raise ValueError("profile_id is required")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO supplier_profiles(profile_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (profile_id, _json(profile), _utc_now()),
            )

    def get_supplier_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json FROM supplier_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return json.loads(row["profile_json"]) if row else None

    def set_sync_state(self, sync_key: str, token: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state(sync_key, iteration_next_token, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(sync_key) DO UPDATE SET
                    iteration_next_token=excluded.iteration_next_token,
                    updated_at=excluded.updated_at
                """,
                (sync_key, token, _utc_now()),
            )

    def get_sync_state(self, sync_key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT iteration_next_token FROM sync_state WHERE sync_key = ?",
                (sync_key,),
            ).fetchone()
        return row["iteration_next_token"] if row else None

    def put_api_key(self, raw_key: str, *, name: str, daily_quota: int = 1000, enabled: bool = True) -> str:
        from .auth import hash_api_key

        key_hash = hash_api_key(raw_key)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys(key_hash, name, daily_quota, enabled, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key_hash) DO UPDATE SET
                    name=excluded.name,
                    daily_quota=excluded.daily_quota,
                    enabled=excluded.enabled
                """,
                (key_hash, name, daily_quota, int(enabled), _utc_now()),
            )
        return key_hash

    def get_api_key(self, key_hash: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT key_hash, name, daily_quota, enabled FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
        return dict(row) if row else None

    def increment_api_usage(self, key_hash: str, usage_date: date | str) -> int:
        usage_date = usage_date.isoformat() if isinstance(usage_date, date) else str(usage_date)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_usage(key_hash, usage_date, request_count)
                VALUES (?, ?, 1)
                ON CONFLICT(key_hash, usage_date) DO UPDATE SET
                    request_count=request_count + 1
                """,
                (key_hash, usage_date),
            )
            row = conn.execute(
                "SELECT request_count FROM api_usage WHERE key_hash=? AND usage_date=?",
                (key_hash, usage_date),
            ).fetchone()
        return int(row["request_count"])

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            notice_count = conn.execute("SELECT COUNT(*) AS n FROM notices").fetchone()["n"]
            profile_count = conn.execute("SELECT COUNT(*) AS n FROM supplier_profiles").fetchone()["n"]
            latest = conn.execute("SELECT MAX(publication_date) AS d FROM notices").fetchone()["d"]
        return {
            "backend": "sqlite",
            "notice_count": int(notice_count),
            "supplier_profile_count": int(profile_count),
            "latest_publication_date": latest,
        }


class SupabaseNoticeStore:
    """Production warehouse adapter using Supabase PostgREST over HTTPS."""

    def __init__(
        self,
        url: str,
        service_role_key: str,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
            },
        )

    def _raise(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase REST returned HTTP {response.status_code}: {response.text[:1000]}")

    def upsert_notices(self, notices: list[dict[str, Any]]) -> int:
        rows = []
        for notice in notices:
            number = notice.get("publication_number")
            if not number:
                continue
            rows.append({
                "publication_number": number,
                "publication_date": notice.get("publication_date"),
                "title": notice.get("title"),
                "buyer_names": notice.get("buyer_names") or [],
                "buyer_countries": notice.get("buyer_countries") or [],
                "cpv_codes": notice.get("cpv_codes") or [],
                "payload": notice,
            })
        if not rows:
            return 0
        response = self.client.post(
            self.base + "/notices?on_conflict=publication_number",
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=rows,
        )
        self._raise(response)
        return len(rows)

    def list_notices_since(self, date_from: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        response = self.client.get(
            self.base + "/notices",
            params={
                "select": "payload",
                "publication_date": f"gte.{date_from}",
                "order": "publication_date.desc",
                "limit": str(limit),
            },
        )
        self._raise(response)
        return [row.get("payload") or {} for row in response.json()]

    def upsert_supplier_profile(self, profile: dict[str, Any]) -> None:
        response = self.client.post(
            self.base + "/supplier_profiles?on_conflict=profile_id",
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json={"profile_id": profile["profile_id"], "profile": profile},
        )
        self._raise(response)

    def get_supplier_profile(self, profile_id: str) -> dict[str, Any] | None:
        response = self.client.get(
            self.base + "/supplier_profiles",
            params={"select": "profile", "profile_id": f"eq.{profile_id}", "limit": "1"},
        )
        self._raise(response)
        rows = response.json()
        return (rows[0].get("profile") or {}) if rows else None

    def set_sync_state(self, sync_key: str, token: str | None) -> None:
        response = self.client.post(
            self.base + "/sync_state?on_conflict=sync_key",
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json={"sync_key": sync_key, "iteration_next_token": token},
        )
        self._raise(response)

    def get_sync_state(self, sync_key: str) -> str | None:
        response = self.client.get(
            self.base + "/sync_state",
            params={"select": "iteration_next_token", "sync_key": f"eq.{sync_key}", "limit": "1"},
        )
        self._raise(response)
        rows = response.json()
        return rows[0].get("iteration_next_token") if rows else None

    def put_api_key(
        self,
        raw_key: str,
        *,
        name: str,
        daily_quota: int = 1000,
        enabled: bool = True,
    ) -> str:
        from .auth import hash_api_key

        key_hash = hash_api_key(raw_key)
        response = self.client.post(
            self.base + "/api_keys?on_conflict=key_hash",
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json={
                "key_hash": key_hash,
                "name": name,
                "daily_quota": int(daily_quota),
                "enabled": bool(enabled),
            },
        )
        self._raise(response)
        return key_hash

    def get_api_key(self, key_hash: str) -> dict[str, Any] | None:
        response = self.client.get(
            self.base + "/api_keys",
            params={"select": "key_hash,name,daily_quota,enabled", "key_hash": f"eq.{key_hash}", "limit": "1"},
        )
        self._raise(response)
        rows = response.json()
        return rows[0] if rows else None

    def increment_api_usage(self, key_hash: str, usage_date: date | str) -> int:
        # Production-safe atomic increment lives in the SQL function created by schema/supabase.sql.
        response = self.client.post(
            self.base.replace("/rest/v1", "/rest/v1/rpc/increment_api_usage"),
            json={"p_key_hash": key_hash, "p_usage_date": str(usage_date)},
        )
        self._raise(response)
        value = response.json()
        return int(value)

    def stats(self) -> dict[str, Any]:
        response = self.client.get(self.base + "/warehouse_stats", params={"select": "*", "limit": "1"})
        if response.status_code < 400:
            rows = response.json()
            if rows:
                return {"backend": "supabase", **rows[0]}
        return {"backend": "supabase", "notice_count": None, "supplier_profile_count": None, "latest_publication_date": None}
