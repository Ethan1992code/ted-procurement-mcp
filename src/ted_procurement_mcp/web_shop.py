"""Public storefront preview. No payment is initiated until web checkout is ready."""
from pathlib import Path
import secrets
import os
import logging
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from .webpay import build_checkout, parse_notification


def register_web_shop(server, service):
    try:
        checkout=build_checkout(service)
    except Exception as exc:
        logging.getLogger(__name__).error('Web checkout initialization failed: %s',type(exc).__name__)
        checkout=None
    base=os.environ.get('WEBPAY_BASE_URL','').rstrip('/')
    headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}

    @server.custom_route('/shop', methods=['GET'])
    async def shop(request):
        page=Path(__file__).with_name('shop.html').read_text(encoding='utf-8')
        if checkout:
            page=page.replace('网页版 · 准备开放','网页版')
            page=page.replace('网页付款正在接入。当前页面不收款，暂不能提交查询。','支付前请确认关键词。未匹配到结果也按一次检索收费。')
            page=page.replace('class="pay" disabled','class="pay" id="checkout"')
            page=page.replace('支付 ¥1.99 并查询 · 暂未开放','支付 ¥1.99 并查询')
            page=page.replace('当前为页面预览，付款与订单功能尚未开放。','请使用同一浏览器保留订单并查看结果。')
        response=HTMLResponse(page,
            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                     'Referrer-Policy': 'no-referrer',
                     'Content-Security-Policy': "default-src 'none'; connect-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
        if not request.cookies.get('ted_web_session'):
            response.set_cookie('ted_web_session',secrets.token_hex(32),secure=True,httponly=True,samesite='lax',max_age=2592000)
        return response

    @server.custom_route('/shop/create',methods=['POST'])
    async def create(request):
        if not checkout: return JSONResponse({'error':'网页收款暂未开放'},503,headers=headers)
        if request.headers.get('origin')!=base: return JSONResponse({'error':'请从查询页面操作'},403,headers=headers)
        try:
            body=await request.body()
            if len(body)>2048: raise ValueError('Too large')
            import json
            data=json.loads(body)
            o=await checkout.create(data.get('keywords'),request.cookies.get('ted_web_session'),data.get('request_id',''))
            if not o: raise ValueError('Conflicting request')
            return JSONResponse({'order':o['id']},headers=headers)
        except ValueError:
            return JSONResponse({'error':'请输入1至200字关键词；不要修改已有订单的关键词'},400,headers=headers)
        except Exception:
            return JSONResponse({'error':'暂时无法建立订单，请稍后重试'},503,headers=headers)

    @server.custom_route('/shop/pay',methods=['POST'])
    async def pay(request):
        if not checkout: return PlainTextResponse('网页收款暂未开放',503,headers=headers)
        if request.headers.get('origin')!=base: return PlainTextResponse('Forbidden',403,headers=headers)
        try:
            from urllib.parse import parse_qs
            raw=await request.body()
            if len(raw)>512: raise ValueError('Too large')
            order_id=parse_qs(raw.decode()).get('order',[''])[0]
            o=await checkout.get(order_id,request.cookies.get('ted_web_session'))
            if not o or o['state']!='PENDING': return PlainTextResponse('请回订单页确认状态，不要重复付款',409,headers=headers)
            return HTMLResponse(checkout.gateway.form(o),headers=headers)
        except Exception:
            return PlainTextResponse('暂时无法打开收银台。请保留订单并稍后重试。',503,headers=headers)

    @server.custom_route('/shop/notify',methods=['POST'])
    async def notify(request):
        try:
            if not checkout: return PlainTextResponse('fail',503,headers=headers)
            params=parse_notification(await request.body())
            ok=await checkout.notify(params)
            return PlainTextResponse('success' if ok else 'fail',200 if ok else 400,headers=headers)
        except Exception as exc:
            logging.getLogger(__name__).warning('Web notification rejected: %s',type(exc).__name__)
            return PlainTextResponse('fail',400,headers=headers)

    @server.custom_route('/shop/status',methods=['GET'])
    async def status(request):
        if not checkout: return JSONResponse({'error':'网页收款暂未开放'},503,headers=headers)
        try:
            data=await checkout.status(request.query_params.get('order',''),request.cookies.get('ted_web_session'))
            return JSONResponse(data or {'error':'订单不存在，请使用下单时的浏览器'},200 if data else 404,headers=headers)
        except Exception as exc:
            logging.getLogger(__name__).warning('Web status unavailable: %s',type(exc).__name__)
            return JSONResponse({'error':'暂时无法确认结果，请保留订单稍后刷新；不要重复付款'},503,headers=headers)

    @server.custom_route('/shop/result',methods=['GET'])
    async def result(request):
        return HTMLResponse(Path(__file__).with_name('shop_result.html').read_text(encoding='utf-8'),headers={**headers,
            'Content-Security-Policy':"default-src 'none'; connect-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"})
