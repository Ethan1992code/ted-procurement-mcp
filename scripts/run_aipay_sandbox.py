"""Local-only sandbox entry; reads the protected config, never prints its contents."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from starlette.applications import Starlette
from starlette.routing import Route
from ted_procurement_mcp.aipay import PaymentConfig, AlipayGateway, PaidSearch, SANDBOX
from ted_procurement_mcp.aipay_store import SQLitePaymentStore
from ted_procurement_mcp.service import ProcurementService
from ted_procurement_mcp.ted_client import TedClient


def build_app():
    if os.getenv("VERCEL"):
        raise RuntimeError("Local sandbox entry is not permitted on Vercel")
    config = json.loads((ROOT / ".alipay-local" / "sandbox.json").read_text(encoding="utf-8"))
    for name, value in config.items():
        if name.startswith("ALIPAY_"):
            os.environ[name] = value
    cfg = PaymentConfig.from_env()
    if cfg.gateway != SANDBOX or cfg.service_id != "api_mock_service_id":
        raise RuntimeError("Only the exact sandbox configuration is permitted")
    paid = PaidSearch(cfg, AlipayGateway(cfg),
        SQLitePaymentStore(ROOT / ".alipay-local" / "orders.sqlite3"), ProcurementService(TedClient()))
    return Starlette(routes=[Route("/aipay/search", paid.handle, methods=["GET"])])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(build_app(), host="127.0.0.1", port=8765, access_log=False, log_level="warning")
