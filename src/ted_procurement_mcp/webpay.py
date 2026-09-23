"""Web checkout with server-side pricing, signed notifications and durable fulfillment."""
import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from urllib.parse import parse_qsl
from .aipay import AlipayGateway, PaymentConfig, money
from .aipay_store import SupabasePaymentStore

class WebGateway:
    def __init__(self, config, base):
        self.config, self.base = config, base
        self.client = AlipayGateway(config).client

    def form(self, order):
        from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest
        from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
        model = AlipayTradePagePayModel()
        model.out_trade_no = order['id']
        model.total_amount = money(order['amount'])
        model.subject = 'TED采购公告检索（最多25条）'
        model.product_code = 'FAST_INSTANT_TRADE_PAY'
        model.timeout_express = '30m'
        request = AlipayTradePagePayRequest(biz_model=model)
        request.notify_url = self.base + '/shop/notify'
        request.return_url = self.base + '/shop/result?order=' + order['id']
        return self.client.page_execute(request, http_method='POST')

    def verify_notification(self, params):
        from alipay.aop.api.util.SignatureUtils import get_sign_content, verify_with_rsa
        if params.get('app_id') != self.config.app_id or params.get('sign_type') != 'RSA2':
            return False
        signed = {k:v for k,v in params.items() if k not in ('sign','sign_type') and v != ''}
        return verify_with_rsa(self.config.public_key, get_sign_content(signed).encode('utf-8'), params.get('sign',''))

    async def query(self, order):
        from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
        from alipay.aop.api.domain.AlipayTradeQueryModel import AlipayTradeQueryModel
        model = AlipayTradeQueryModel()
        model.out_trade_no = order['id']
        response = await asyncio.to_thread(self.client.execute, AlipayTradeQueryRequest(biz_model=model))
        result = json.loads(response)
        return result.get('alipay_trade_query_response', result)

def session_hash(token):
    if not token or not re.fullmatch(r'[a-f0-9]{64}',token):
        raise ValueError('Invalid session')
    return hashlib.sha256(token.encode()).hexdigest()

def parse_notification(body):
    if len(body)>32768:
        raise ValueError('Body too large')
    items = parse_qsl(body.decode('utf-8'), keep_blank_values=True, strict_parsing=True)
    params = dict(items)
    if len(params)!=len(items):
        raise ValueError('Duplicate parameters')
    return params

class WebCheckout:
    def __init__(self, gateway, store, service):
        self.gateway,self.store,self.service = gateway,store,service

    async def create(self, keywords, token, request_id):
        if not isinstance(keywords,str) or not 1<=len(keywords.strip())<=200 or not re.fullmatch(r'[a-f0-9]{32}',request_id):
            raise ValueError('Invalid query')
        return await self.store.run('create', {'id':'WEB'+uuid.uuid4().hex,
            'session_hash':session_hash(token),'request_id':request_id,
            'keywords':keywords.strip(),'amount':self.gateway.config.amount})

    async def get(self, order_id, token):
        if not re.fullmatch(r'WEB[a-f0-9]{32}',order_id): return None
        return await self.store.run('get',{'id':order_id,'session_hash':session_hash(token)})

    async def notify(self, params):
        if not self.gateway.verify_notification(params): return False
        if not re.fullmatch(r'WEB[a-f0-9]{32}', params.get('out_trade_no','')): return False
        o=await self.store.run('internal_get',{'id':params.get('out_trade_no')})
        if (not o or params.get('seller_id')!=self.gateway.config.seller_id
            or money(params.get('total_amount'))!=money(o['amount'])): return False
        if params.get('trade_status') in ('TRADE_SUCCESS','TRADE_FINISHED') and not any(params.get(k) for k in ('out_biz_no','gmt_refund','refund_fee')):
            return bool(await self.store.run('paid',{'id':o['id'],'amount':money(o['amount']),'trade_no':params.get('trade_no')}))
        return True

    async def status(self, order_id, token):
        o=await self.get(order_id,token)
        if not o: return None
        if o['state']=='PENDING':
            q=await self.gateway.query(o)
            if q.get('code')=='10000':
                if q.get('out_trade_no')!=o['id'] or money(q.get('total_amount'))!=money(o['amount']):
                    raise ValueError('Order mismatch')
                if q.get('seller_id') and q['seller_id']!=self.gateway.config.seller_id:
                    raise ValueError('Seller mismatch')
                if q.get('trade_status') in ('TRADE_SUCCESS','TRADE_FINISHED'):
                    o=await self.store.run('paid',{'id':o['id'],'amount':money(o['amount']),'trade_no':q.get('trade_no')})
                elif q.get('trade_status')=='TRADE_CLOSED':
                    o=await self.store.run('closed',{'id':o['id']})
        if not o: raise ValueError('Invalid transition')
        if o['state'] in ('PAID','GENERATING'):
            lease=uuid.uuid4().hex
            claimed=await self.store.run('claim',{'id':o['id'],'lease':lease})
            if claimed and not claimed.get('busy'):
                if claimed['state']=='GENERATING':
                    result=await self.service.search_procurements(keywords=o['keywords'],limit=25)
                    if not isinstance(result,dict) or not isinstance(result.get('notices'),list) or result.get('timed_out'):
                        raise ValueError('Incomplete search')
                    o=await self.store.run('save',{'id':o['id'],'lease':lease,'result':result})
                else: o=claimed
        if not o: raise ValueError('Lease lost')
        return {'id':o['id'],'state':o['state'],'amount':money(o['amount']),
                'keywords':o['keywords'],'result':o.get('result') if o['state']=='READY' else None}

def build_checkout(service):
    if os.getenv('WEBPAY_ENABLED')!='true': return None
    base=os.environ.get('WEBPAY_BASE_URL','').rstrip('/')
    if not re.fullmatch(r'https://[a-zA-Z0-9.-]+',base): raise ValueError('Explicit HTTPS base required')
    config=PaymentConfig.from_env()
    if config.amount!='1.99': raise ValueError('Storefront price mismatch')
    store=SupabasePaymentStore(os.environ['SUPABASE_URL'],os.environ['SUPABASE_SERVICE_ROLE_KEY'])
    store.url=store.url.rsplit('/',1)[0]+'/ted_web_order'
    return WebCheckout(WebGateway(config,base),store,service)
