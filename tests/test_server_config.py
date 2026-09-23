from pathlib import Path

from ted_procurement_mcp.server import build_store_from_env
from ted_procurement_mcp.storage import SQLiteNoticeStore, SupabaseNoticeStore


def test_build_store_prefers_supabase_when_configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret")
    monkeypatch.delenv("VERCEL", raising=False)
    store = build_store_from_env()
    assert isinstance(store, SupabaseNoticeStore)


def test_build_store_uses_sqlite_locally(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("TED_DB_PATH", str(tmp_path / "ted.db"))
    store = build_store_from_env()
    assert isinstance(store, SQLiteNoticeStore)


def test_build_store_does_not_pretend_vercel_tmp_is_durable(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert build_store_from_env() is None
