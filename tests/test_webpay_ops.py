import asyncio
import json
from types import SimpleNamespace
import pytest
from ted_procurement_mcp.webpay_ops import WebOperations

OID='WEB'+'a'*32
class Store:
    def __init__(self,state='PAID'):
        self.order={'id':OID,'state':state,'amount':'1.99','trade_no':'trade'}
        self.calls=[]
    async def run(self,action,data):
        self.calls.append(action)
        if action=='refund_prepare':
            self.order.update(state='REFUNDING',refund_request_id='RF'+OID)
        elif action=='refunded': self.order['state']='REFUNDED'
        elif action=='close_prepare': self.order['state']='CLOSING'
        elif action=='closed': self.order['state']='CLOSED'
        return self.order.copy()
class Client:
    def __init__(self,responses): self.responses=iter(responses);self.requests=[]
    def execute(self,request):
        self.requests.append(request)
        result=next(self.responses)
        if isinstance(result,Exception): raise result
        return json.dumps(result)
def ops(responses,state='PAID'):
    store=Store(state);client=Client(responses)
    return WebOperations(SimpleNamespace(store=store,gateway=SimpleNamespace(client=client))),store,client

def test_refund_requires_specific_confirmation_before_any_lookup():
    o,s,c=ops([])
    with pytest.raises(ValueError):asyncio.run(o.operate('refund',OID))
    assert s.calls==[] and c.requests==[]

def test_timeout_retry_reuses_refund_id_and_amount():
    o,s,c=ops([TimeoutError(),{'code':'10000','fund_change':'N'}])
    with pytest.raises(TimeoutError):asyncio.run(o.operate('refund',OID,True))
    r=asyncio.run(o.operate('refund',OID,True))
    assert r['state']=='REFUNDING'
    fields=[x.biz_model.to_alipay_dict() for x in c.requests]
    assert fields[0]==fields[1]
    assert fields[0]['refund_amount']=='1.99'
    assert 'refunded' not in s.calls

@pytest.mark.parametrize('status',['REFUND_PROCESSING',None])
def test_refund_query_does_not_guess_success(status):
    o,s,c=ops([{'code':'10000','refund_status':status}])
    s.order.update(state='REFUNDING',refund_request_id='RF'+OID)
    assert asyncio.run(o.operate('refund-query',OID))['state']=='REFUNDING'
    assert 'refunded' not in s.calls

@pytest.mark.parametrize('amount',['1.99','0.01'])
def test_refund_query_checks_response_identity_and_amount(amount):
    o,s,c=ops([{'code':'10000','refund_status':'REFUND_SUCCESS','out_trade_no':OID,'out_request_no':'RF'+OID,'refund_amount':amount}])
    s.order.update(state='REFUNDING',refund_request_id='RF'+OID)
    if amount=='1.99':assert asyncio.run(o.operate('refund-query',OID))['state']=='REFUNDED'
    else:
        with pytest.raises(ValueError):asyncio.run(o.operate('refund-query',OID))
        assert 'refunded' not in s.calls

def test_not_found_close_remains_uncertain():
    o,s,c=ops([{'code':'40004','sub_code':'ACQ.TRADE_NOT_EXIST'}],'PENDING')
    assert asyncio.run(o.operate('close',OID,True))['state']=='CLOSING'
    assert 'closed' not in s.calls

def test_successful_close_is_persisted():
    o,s,c=ops([{'code':'10000','out_trade_no':OID}],'PENDING')
    assert asyncio.run(o.operate('close',OID,True))['state']=='CLOSED'
