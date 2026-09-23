"""Durable A2M orders. All transitions execute atomically in Supabase."""
from __future__ import annotations

import httpx
import asyncio
import json
import sqlite3
import time
from datetime import datetime


class SQLitePaymentStore:
    """Durable single-host order storage; never selected by the Vercel app."""
    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS payment_orders (id TEXT PRIMARY KEY, trade_no TEXT UNIQUE, payload TEXT NOT NULL)")

    async def run(self, action, data):
        return await asyncio.to_thread(self._run, action, data)

    def _run(self, action, data):
        with sqlite3.connect(self.path, timeout=15) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if action == "create":
                order = {**data, "state": "PENDING_PAYMENT", "trade_no": None}
                conn.execute("INSERT INTO payment_orders(id,payload) VALUES (?,?)",
                             (data["out_trade_no"], json.dumps(order)))
                return order
            row = conn.execute("SELECT payload FROM payment_orders WHERE id=?", (data["out_trade_no"],)).fetchone()
            if not row:
                return None
            order = json.loads(row[0])
            if action == "get":
                return order
            if action == "claim":
                from .aipay import money
                if (money(order["amount"]) != money(data["amount"])
                    or order["resource_id"] != data["resource_id"]
                    or not data.get("trade_no") or not data.get("lease_token")
                    or order["trade_no"] not in (None, data["trade_no"])
                    or order["state"] == "CANCELLED"):
                    return None
                if order["state"] in ("PENDING_CONFIRM", "FULFILLED"):
                    return order
                if datetime.fromisoformat(order["pay_before"]).timestamp() <= time.time():
                    return None
                if order["state"] == "GENERATING" and order["lease_until"] > time.time():
                    return {"busy": True}
                order.update(state="GENERATING", trade_no=data["trade_no"],
                             lease_token=data["lease_token"], lease_until=time.time()+90)
            elif action == "save":
                if (order["state"] != "GENERATING" or order["lease_token"] != data.get("lease_token")
                    or order["trade_no"] != data.get("trade_no") or data.get("result") is None):
                    return None
                order.update(state="PENDING_CONFIRM", result=data["result"], lease_token=None, lease_until=None)
            elif action == "complete":
                if order["state"] not in ("PENDING_CONFIRM", "FULFILLED") or order["trade_no"] != data.get("trade_no"):
                    return None
                order["state"] = "FULFILLED"
            else:
                raise ValueError("Unknown order transition")
            try:
                conn.execute("UPDATE payment_orders SET trade_no=?,payload=? WHERE id=?",
                    (order["trade_no"], json.dumps(order), data["out_trade_no"]))
            except sqlite3.IntegrityError:
                return None
            return order


class SupabasePaymentStore:
    def __init__(self, url: str, service_key: str):
        self.url = url.rstrip("/") + "/rest/v1/rpc/ted_aipay_order"
        self.headers = {"apikey": service_key, "Authorization": "Bearer " + service_key}

    async def run(self, action: str, data: dict) -> dict | None:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(self.url, headers=self.headers,
                                         json={"p_action": action, "p_data": data})
            response.raise_for_status()
            result = response.json()
            if result is not None and not isinstance(result, dict):
                raise RuntimeError("Unexpected payment storage response")
            return result
