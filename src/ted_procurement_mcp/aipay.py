"""Opt-in Alipay A2M paid TED search; no payment credentials or proofs logged."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from starlette.responses import JSONResponse

SANDBOX = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
PRODUCTION = "https://openapi.alipay.com/gateway.do"


def encoded(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False,
        separators=(",", ":")).encode()).rstrip(b"=").decode()


def money(value) -> str:
    if not re.fullmatch(r"\d{1,10}(?:\.\d{1,2})?", str(value)):
        raise ValueError("Invalid amount")
    amount = Decimal(str(value))
    if amount <= 0:
        raise ValueError("Amount must be positive")
    return format(amount, ".2f")


@dataclass(repr=False)
class PaymentConfig:
    gateway: str
    app_id: str
    private_key: str = field(repr=False)
    public_key: str = field(repr=False)
    seller_id: str
    seller_name: str
    service_id: str
    amount: str

    @classmethod
    def from_env(cls):
        names = ["GATEWAY", "APP_ID", "APP_PRIVATE_KEY", "PUBLIC_KEY", "SELLER_ID",
                 "SELLER_NAME", "SERVICE_ID", "SEARCH_PRICE"]
        values = [os.environ.get("ALIPAY_" + name, "") for name in names]
        if not all(values):
            raise ValueError("Payment configuration incomplete")
        cfg = cls(*values)
        if cfg.gateway not in {SANDBOX, PRODUCTION}:
            raise ValueError("Unsupported payment gateway")
        if (cfg.gateway == SANDBOX) != (cfg.service_id == "api_mock_service_id"):
            raise ValueError("Payment environment mismatch")
        if not re.fullmatch(r"2088\d{12}", cfg.seller_id):
            raise ValueError("Invalid seller ID")
        if not cfg.app_id.isdigit():
            raise ValueError("Invalid application ID")
        cfg.amount = money(cfg.amount)
        return cfg


class AlipayGateway:
    def __init__(self, config: PaymentConfig):
        from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
        from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
        from Crypto.PublicKey import RSA
        import rsa
        # Validate raw key material without rewriting configuration or printing it.
        raw = base64.b64decode(config.private_key, validate=True)
        rsa.PrivateKey.load_pkcs1(raw, format="DER")
        self.signing_key = RSA.import_key(raw)
        if not self.signing_key.has_private() or self.signing_key.size_in_bits() < 2048:
            raise ValueError("Invalid signing key")
        RSA.import_key(base64.b64decode(config.public_key, validate=True))
        sdk = AlipayClientConfig()
        sdk.server_url = config.gateway
        sdk.app_id = config.app_id
        sdk.app_private_key = config.private_key
        sdk.alipay_public_key = config.public_key
        sdk.sign_type = "RSA2"
        sdk.charset = "utf-8"
        sdk.skip_sign = False
        sdk.timeout = 10
        self.client = DefaultAlipayClient(sdk, logger=None)

    def sign(self, params: dict) -> str:
        from Crypto.Hash import SHA256
        from Crypto.Signature import pkcs1_15
        content = "&".join(f"{k}={params[k]}" for k in sorted(params))
        return base64.b64encode(pkcs1_15.new(self.signing_key).sign(
            SHA256.new(content.encode("utf-8")))).decode()

    async def verify(self, proof: dict) -> dict:
        from alipay.aop.api.domain.AlipayAipayAgentPaymentVerifyModel import AlipayAipayAgentPaymentVerifyModel
        from alipay.aop.api.request.AlipayAipayAgentPaymentVerifyRequest import AlipayAipayAgentPaymentVerifyRequest
        model = AlipayAipayAgentPaymentVerifyModel()
        model.trade_no = proof["trade_no"]
        model.payment_proof = proof["payment_proof"]
        model.client_session = proof.get("client_session")
        return await self._execute(AlipayAipayAgentPaymentVerifyRequest(model),
                                   "alipay_aipay_agent_payment_verify_response")

    async def confirm(self, trade_no: str) -> bool:
        from alipay.aop.api.domain.AlipayAipayAgentFulfillmentConfirmModel import AlipayAipayAgentFulfillmentConfirmModel
        from alipay.aop.api.request.AlipayAipayAgentFulfillmentConfirmRequest import AlipayAipayAgentFulfillmentConfirmRequest
        model = AlipayAipayAgentFulfillmentConfirmModel()
        model.trade_no = trade_no
        # Confirmation is idempotent for a trade. Retry transient transport/SDK
        # errors on this same trade only, without regenerating a resource or bill.
        for attempt in range(3):
            try:
                data = await self._execute(AlipayAipayAgentFulfillmentConfirmRequest(model),
                                          "alipay_aipay_agent_fulfillment_confirm_response")
                return data.get("code") == "10000"
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))

    async def _execute(self, request, key: str) -> dict:
        # Official SDK validates the response signature; never enable skip_sign.
        for attempt in range(3):
            try:
                raw = await asyncio.to_thread(self.client.execute, request)
                break
            except TypeError as exc:
                # SDK 3.7.1360 concatenates bytes to str for non-200 responses.
                # Inspect ONLY the HTTP status; never log the response body/proof.
                status = None
                tb = exc.__traceback__
                while tb:
                    if tb.tb_frame.f_code.co_name == "do_post":
                        value = getattr(tb.tb_frame.f_locals.get("response"), "status", None)
                        if isinstance(value, int):
                            status = value
                    tb = tb.tb_next
                logging.getLogger(__name__).warning("Alipay upstream HTTP status=%s", status)
                if status not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (attempt + 1))
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid gateway response")
        result = data.get(key, data)
        if not isinstance(result, dict):
            raise ValueError("Invalid gateway response")
        return result


def parse_proof(value: str) -> dict:
    if len(value) > 16384 or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise ValueError("Invalid payment proof")
    data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    protocol, method = data["protocol"], data.get("method", {})
    result = {key: protocol[key] for key in ("trade_no", "payment_proof")}
    if not all(isinstance(v, str) and 0 < len(v) <= 8192 for v in result.values()):
        raise ValueError("Invalid payment proof")
    session = method.get("client_session")
    if session is not None:
        if not isinstance(session, str) or len(session) > 4096:
            raise ValueError("Invalid client session")
        result["client_session"] = session
    return result


def reply(data: dict, status=200, headers=None):
    return JSONResponse(data, status_code=status,
                        headers={"Cache-Control": "no-store", **(headers or {})})


class PaidSearch:
    def __init__(self, config, gateway, store, service):
        self.config, self.gateway, self.store, self.service = config, gateway, store, service

    async def bill(self, resource_id: str):
        cfg = self.config
        order = {"out_trade_no": "TED" + uuid.uuid4().hex, "amount": cfg.amount,
                 "resource_id": resource_id,
                 "pay_before": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}
        signed = {**order, "currency": "CNY", "goods_name": "TED采购检索（最多25条）",
                  "seller_id": cfg.seller_id, "service_id": cfg.service_id}
        bill = {"protocol": {**order, "currency": "CNY", "seller_sign_type": "RSA2",
                             "seller_unique_id": cfg.seller_id,
                             "seller_signature": self.gateway.sign(signed)},
                "method": {"seller_name": cfg.seller_name, "seller_id": cfg.seller_id,
                           "seller_app_id": cfg.app_id, "goods_name": signed["goods_name"],
                           "seller_unique_id_key": "seller_id", "service_id": cfg.service_id}}
        persisted = await self.store.run("create", {**order, "bill": bill})
        if not persisted:
            raise RuntimeError("Order not persisted")
        return reply({"code": "Payment-Needed", **order}, 402, {"Payment-Needed": encoded(bill)})

    async def handle(self, request):
        keywords = request.query_params.get("keywords", "").strip()
        if not keywords or len(keywords) > 200 or set(request.query_params) != {"keywords"}:
            return reply({"code": "INVALID_QUERY", "message": "只接受1至200字的keywords"}, 400)
        # Every byte of the normalized query is bound to the signed, versioned resource.
        resource = "/aipay/search/v1/" + hashlib.sha256(keywords.encode()).hexdigest()
        stage = "bill"
        try:
            header = request.headers.get("Payment-Proof")
            if not header:
                return await self.bill(resource)
            try:
                proof = parse_proof(header)
            except (ValueError, KeyError, TypeError, AttributeError):
                return await self.bill(resource)
            stage = "verify"
            verified = await self.gateway.verify(proof)
            if (verified.get("code") != "10000" or verified.get("active") is not True
                or verified.get("trade_no") != proof["trade_no"]
                or verified.get("resource_id") != resource
                or not isinstance(verified.get("out_trade_no"), str)):
                return await self.bill(resource)
            stage = "order_lookup"
            order = await self.store.run("get", {"out_trade_no": verified["out_trade_no"]})
            try:
                amount_matches = order and money(order["amount"]) == money(verified.get("amount"))
            except ValueError:
                amount_matches = False
            if not amount_matches or order["resource_id"] != resource:
                return await self.bill(resource)
            args = {"out_trade_no": order["out_trade_no"], "amount": money(order["amount"]),
                    "resource_id": resource, "trade_no": proof["trade_no"], "lease_token": uuid.uuid4().hex}
            order = await self.store.run("claim", args)
            if not order:
                return await self.bill(resource)
            if order.get("busy"):
                return reply({"code": "FULFILLMENT_IN_PROGRESS", "message": "使用同一付款凭证稍后重试"},
                             409, {"Retry-After": "5"})
            if order["state"] == "GENERATING":
                stage = "ted_search"
                result = await self.service.search_procurements(keywords=keywords, limit=25)
                if not isinstance(result, dict) or not isinstance(result.get("notices"), list) or result.get("timed_out"):
                    raise RuntimeError("TED result incomplete")
                order = await self.store.run("save", {**args, "result": result})
                if not order:
                    raise RuntimeError("Fulfillment lease lost")
            if order["state"] == "PENDING_CONFIRM":
                stage = "confirm"
                if not await self.gateway.confirm(proof["trade_no"]):
                    return reply({"code": "FULFILLMENT_CONFIRM_PENDING",
                                  "message": "结果已保存，请使用同一付款凭证重试；不要重新付款"}, 502)
                order = await self.store.run("complete", args)
            if not order or order["state"] != "FULFILLED" or order.get("result") is None:
                raise RuntimeError("Fulfillment not confirmed")
            validation = {"trade_no": proof["trade_no"], "out_trade_no": order["out_trade_no"],
                          "resource_id": resource, "validated": True}
            return reply({"content": order["result"], "fulfillment_confirmed": True, **validation},
                         headers={"Payment-Validation": encoded(validation)})
        except Exception as exc:
            # SDK exceptions can contain entire signed responses/proofs. Never echo/log them.
            logging.getLogger(__name__).warning("A2M failure stage=%s type=%s", stage, type(exc).__name__)
            return reply({"code": "PAYMENT_SERVICE_UNAVAILABLE",
                          "message": "暂未交付，请使用同一付款凭证稍后重试；不要重新付款"}, 503)


def build_paid_search(service):
    # No SDK/key loading or database traffic while the feature is disabled.
    if os.getenv("ALIPAY_ENABLED") != "true":
        return None
    from .aipay_store import SupabasePaymentStore
    cfg = PaymentConfig.from_env()
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("Durable payment storage not configured")
    return PaidSearch(cfg, AlipayGateway(cfg), SupabasePaymentStore(url, key), service)


def register_paid_search(server, service):
    try:
        paid = build_paid_search(service)
    except Exception as exc:
        # Log locations and exception types only; exception text may contain secrets.
        frames = []
        tb = exc.__traceback__
        while tb is not None:
            frames.append(f"{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}")
            tb = tb.tb_next
        logging.getLogger(__name__).error("A2M initialization failed type=%s locations=%s",
                                         type(exc).__name__, ",".join(frames))
        paid = None

    @server.custom_route("/aipay/search", methods=["GET"])
    async def paid_search(request):
        if paid is None:
            return reply({"code": "PAYMENT_NOT_CONFIGURED"}, 503)
        return await paid.handle(request)
