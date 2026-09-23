import asyncio
from datetime import datetime, timedelta, timezone
from ted_procurement_mcp.aipay_store import SQLitePaymentStore


def test_durable_claim_unique_trade_and_replay(tmp_path):
    async def check():
        path = tmp_path / "orders.db"
        store = SQLitePaymentStore(path)
        order = {"out_trade_no":"a", "amount":"1.00", "resource_id":"query1", "bill":{},
            "pay_before":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        await store.run("create",order)
        args={**order,"trade_no":"t", "lease_token":"one"}
        results=await asyncio.gather(store.run("claim",args),store.run("claim",{**args,"lease_token":"two"}))
        assert sum(r.get("busy",False) for r in results)==1
        winner=next(r for r in results if not r.get("busy"))["lease_token"]
        await store.run("create",{**order,"out_trade_no":"b"})
        assert await store.run("claim",{**args,"out_trade_no":"b"}) is None
        assert await store.run("save",{**args,"lease_token":"wrong","result":{"value":1}}) is None
        assert (await store.run("save",{**args,"lease_token":winner,"result":{"value":1}}))["state"]=="PENDING_CONFIRM"
        # Reopen the actual file to demonstrate result survives process/object lifetime.
        fresh=SQLitePaymentStore(path)
        assert (await fresh.run("claim",args))["result"]=={"value":1}
        assert (await fresh.run("complete",args))["state"]=="FULFILLED"
        assert (await fresh.run("claim",args))["state"]=="FULFILLED"
    asyncio.run(check())
