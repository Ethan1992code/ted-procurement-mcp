import asyncio
import base64
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from ted_procurement_mcp.aipay import (PaidSearch, PaymentConfig, SANDBOX, PRODUCTION,
                                     encoded, parse_proof, build_paid_search, AlipayGateway)


class TestOrders:
    """Controller test double only; database transitions tested against PostgreSQL separately."""
    __test__ = False

    def __init__(self):
        self.orders = {}

    async def run(self, action, data):
        key = data["out_trade_no"]
        if action == "create":
            self.orders[key] = {**deepcopy(data), "state": "PENDING_PAYMENT"}
        o = self.orders.get(key)
        if not o:
            return None
        if action == "claim":
            if o["state"] in ("PENDING_CONFIRM", "FULFILLED"):
                return deepcopy(o)
            if datetime.fromisoformat(o["pay_before"]) <= datetime.now(timezone.utc):
                return None
            if o["state"] == "GENERATING":
                return {"busy": True}
            o.update(state="GENERATING", trade_no=data["trade_no"])
        elif action == "save":
            o.update(state="PENDING_CONFIRM", result=data["result"])
        elif action == "complete":
            o.update(state="FULFILLED")
        return deepcopy(o)


@pytest.fixture
def setup():
    cfg = SimpleNamespace(amount="1.00", seller_id="2088000000000000", seller_name="test",
                          app_id="123", service_id="api_mock_service_id")
    gateway = SimpleNamespace(sign=lambda _: "test-signature", verify=AsyncMock(), confirm=AsyncMock(return_value=True))
    service = SimpleNamespace(search_procurements=AsyncMock(return_value={"notices": [{"title": "test-only"}]}))
    store = TestOrders()
    handler = PaidSearch(cfg, gateway, store, service)
    client = TestClient(Starlette(routes=[Route("/aipay/search", handler.handle)]))
    bill = client.get("/aipay/search?keywords=pumps")
    order = next(iter(store.orders.values()))
    gateway.verify.return_value = {"code": "10000", "active": True, "trade_no": "trade1",
        "out_trade_no": order["out_trade_no"], "amount": "1.00", "resource_id": order["resource_id"]}
    proof = encoded({"protocol": {"trade_no": "trade1", "payment_proof": "test-only-proof"}})
    return client, gateway, service, store, bill, {"Payment-Proof": proof}


def test_bill_no_unpaid_delivery(setup):
    client, gateway, service, store, bill, headers = setup
    assert bill.status_code == 402
    envelope = json.loads(base64.urlsafe_b64decode(bill.headers["Payment-Needed"] + "=="))
    assert envelope["protocol"]["amount"] == "1.00"
    assert envelope["protocol"]["seller_sign_type"] == "RSA2"
    assert bill.headers["cache-control"] == "no-store"
    service.search_procurements.assert_not_called()


@pytest.mark.parametrize("field,value", [("active", False), ("active", "true"), ("code", "40004"),
    ("amount", "0.01"), ("amount", None), ("trade_no", "other"), ("resource_id", "other"),
    ("out_trade_no", "missing")])
def test_bad_verified_fields_never_deliver(setup, field, value):
    client, gateway, service, store, bill, headers = setup
    gateway.verify.return_value[field] = value
    assert client.get("/aipay/search?keywords=pumps", headers=headers).status_code == 402
    service.search_procurements.assert_not_called()
    gateway.confirm.assert_not_called()


def test_confirmation_retry_and_replay_use_saved_result(setup):
    client, gateway, service, store, bill, headers = setup
    gateway.confirm.return_value = False
    assert client.get("/aipay/search?keywords=pumps", headers=headers).status_code == 502
    order = next(iter(store.orders.values()))
    assert order["state"] == "PENDING_CONFIRM"
    order["pay_before"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    gateway.confirm.return_value = True
    first = client.get("/aipay/search?keywords=pumps", headers=headers)
    second = client.get("/aipay/search?keywords=pumps", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["fulfillment_confirmed"] is True
    assert "Payment-Validation" in first.headers
    service.search_procurements.assert_awaited_once()
    assert gateway.confirm.await_count == 2


def test_cross_query_proof_rejected(setup):
    client, gateway, service, store, bill, headers = setup
    assert client.get("/aipay/search?keywords=trucks", headers=headers).status_code == 402
    service.search_procurements.assert_not_called()


def test_expired_order_rejected(setup):
    client, gateway, service, store, bill, headers = setup
    next(iter(store.orders.values()))["pay_before"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert client.get("/aipay/search?keywords=pumps", headers=headers).status_code == 402
    service.search_procurements.assert_not_called()


def test_gateway_exception_redacted(setup):
    client, gateway, service, store, bill, headers = setup
    gateway.verify.side_effect = RuntimeError("secret-payment-proof")
    response = client.get("/aipay/search?keywords=pumps", headers=headers)
    assert response.status_code == 503
    assert "secret" not in response.text
    service.search_procurements.assert_not_called()


def test_ted_failure_not_confirmed(setup):
    client, gateway, service, store, bill, headers = setup
    service.search_procurements.side_effect = RuntimeError("TED failed")
    assert client.get("/aipay/search?keywords=pumps", headers=headers).status_code == 503
    gateway.confirm.assert_not_called()
    assert client.get("/aipay/search?keywords=pumps", headers=headers).status_code == 409


@pytest.mark.parametrize("proof", ["not!base64", encoded({}), encoded({"protocol": []}),
    encoded({"protocol": {"trade_no": 3, "payment_proof": "x"}})])
def test_malformed_proof_rejected(setup, proof):
    client, gateway, service, store, bill, headers = setup
    assert client.get("/aipay/search?keywords=pumps", headers={"Payment-Proof": proof}).status_code == 402
    gateway.verify.assert_not_called()


def test_disabled_does_not_load_credentials(monkeypatch):
    monkeypatch.delenv("ALIPAY_ENABLED", raising=False)
    assert build_paid_search(None) is None
    monkeypatch.setenv("ALIPAY_ENABLED", "true")
    monkeypatch.delenv("ALIPAY_GATEWAY", raising=False)
    with pytest.raises(ValueError):
        build_paid_search(None)


def test_actual_sdk_request_models_and_signing():
    # Ephemeral, synthetic unit-test keys only. Never written or used for payment.
    from Crypto.PublicKey import RSA
    from Crypto.Hash import SHA256
    from Crypto.Signature import pkcs1_15
    key = RSA.generate(2048)
    private = base64.b64encode(key.export_key(format="DER", pkcs=1)).decode()
    public = base64.b64encode(key.public_key().export_key(format="DER")).decode()
    cfg = PaymentConfig(SANDBOX, "123", private, public, "2088000000000000", "test", "api_mock_service_id", "1.00")
    gateway = AlipayGateway(cfg)
    signature = gateway.sign({"b": "2", "a": "1"})
    pkcs1_15.new(key.public_key()).verify(SHA256.new(b"a=1&b=2"), base64.b64decode(signature))
    calls = []
    def execute(request):
        calls.append(request.get_params())
        return '{"code":"10000"}'
    gateway.client.execute = execute
    asyncio.run(gateway.verify({"trade_no": "t", "payment_proof": "p", "client_session": "c"}))
    assert asyncio.run(gateway.confirm("t"))
    assert json.loads(calls[0]["biz_content"]) == {"trade_no": "t", "payment_proof": "p", "client_session": "c"}
    assert json.loads(calls[1]["biz_content"]) == {"trade_no": "t"}


@pytest.mark.parametrize("tamper", [False, True])
def test_sdk_rejects_tampered_signed_response(monkeypatch, tamper):
    import importlib
    from Crypto.PublicKey import RSA
    from Crypto.Hash import SHA256
    from Crypto.Signature import pkcs1_15
    key = RSA.generate(2048)
    cfg = PaymentConfig(SANDBOX, "123",
        base64.b64encode(key.export_key(format="DER", pkcs=1)).decode(),
        base64.b64encode(key.public_key().export_key(format="DER")).decode(),
        "2088000000000000", "test", "api_mock_service_id", "1.00")
    gateway = AlipayGateway(cfg)
    payload = '{"code":"10000","active":true}'
    signature = base64.b64encode(pkcs1_15.new(key).sign(SHA256.new(payload.encode()))).decode()
    if tamper:
        payload = payload.replace('true','false')
    response = ('{"alipay_aipay_agent_payment_verify_response":' + payload + ',"sign":"' + signature + '"}').encode()
    module = importlib.import_module('alipay.aop.api.DefaultAlipayClient')
    monkeypatch.setattr(module, 'do_post', lambda *args: response)
    if tamper:
        with pytest.raises(Exception):
            asyncio.run(gateway.verify({"trade_no":"test", "payment_proof":"test"}))
    else:
        assert asyncio.run(gateway.verify({"trade_no":"test", "payment_proof":"test"}))["active"] is True


def test_confirmation_retry_keeps_same_trade():
    gateway = object.__new__(AlipayGateway)
    gateway._execute = AsyncMock(side_effect=[TypeError("SDK transport error"), {"code":"10000"}])
    assert asyncio.run(gateway.confirm("same-trade")) is True
    assert gateway._execute.await_count == 2
    for call in gateway._execute.call_args_list:
        assert call.args[0].biz_model.trade_no == "same-trade"
