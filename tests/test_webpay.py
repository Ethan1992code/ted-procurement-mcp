import asyncio
from types import SimpleNamespace
import pytest
from ted_procurement_mcp.webpay import WebCheckout, parse_notification, session_hash

class Store:
    def __init__(self): self.calls=[]
    async def run(self,action,data):
        self.calls.append((action,data))
        if action in ('get','internal_get'): return {'id':'WEB'+'a'*32,'amount':'1.99','state':'PENDING'}
        return {'state':'PAID'}

def test_notification_rejects_duplicates():
    with pytest.raises(ValueError): parse_notification(b'app_id=a&app_id=b')

@pytest.mark.parametrize('field,value',[('seller_id','wrong'),('total_amount','0.01'),('out_trade_no','')])
def test_notification_business_mismatch(field,value):
    store=Store()
    gateway=SimpleNamespace(config=SimpleNamespace(seller_id='seller'),verify_notification=lambda p:True)
    c=WebCheckout(gateway,store,None)
    p={'seller_id':'seller','total_amount':'1.99','out_trade_no':'WEB'+'a'*32,'trade_status':'TRADE_SUCCESS','trade_no':'trade'}
    p[field]=value
    assert not asyncio.run(c.notify(p))
    assert not any(a=='paid' for a,d in store.calls)

@pytest.mark.parametrize('extra',[{'refund_fee':'1.99'},{'gmt_refund':'today'},{'out_biz_no':'refund'}])
def test_refund_notification_never_grants_access(extra):
    store=Store()
    c=WebCheckout(SimpleNamespace(config=SimpleNamespace(seller_id='seller'),verify_notification=lambda p:True),store,None)
    p={'seller_id':'seller','total_amount':'1.99','out_trade_no':'WEB'+'a'*32,'trade_status':'TRADE_SUCCESS',**extra}
    assert asyncio.run(c.notify(p))
    assert not any(a=='paid' for a,d in store.calls)

def test_bad_signature_never_touches_database():
    store=Store(); c=WebCheckout(SimpleNamespace(verify_notification=lambda p:False),store,None)
    assert not asyncio.run(c.notify({}))
    assert not store.calls

def test_session_requires_unguessable_token():
    with pytest.raises(ValueError): session_hash('123')
    assert len(session_hash('a'*64))==64

def test_preview_cannot_charge(monkeypatch):
    monkeypatch.delenv('WEBPAY_ENABLED',raising=False)
    from starlette.testclient import TestClient
    from ted_procurement_mcp.server import create_http_app
    with TestClient(create_http_app()) as c:
        assert c.get('/shop').status_code==200
        assert c.post('/shop/create',json={'keywords':'pumps'}).status_code==503
        assert c.post('/shop/notify',content='trade_status=TRADE_SUCCESS').status_code==503
        assert c.get('/shop/result').status_code==200
