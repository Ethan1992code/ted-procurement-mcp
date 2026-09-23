"""Operator-only commands. Never mounted as public HTTP routes.

Refunds are full-order only. A persisted request ID is reused after uncertainty.
Production mutations require explicit confirmation of the specific order.
"""
import argparse
import asyncio
import importlib
import json
import re
from .webpay import build_checkout
from .aipay import money


class WebOperations:
    def __init__(self, checkout):
        self.checkout = checkout

    async def request(self, method, fields):
        name = 'Alipay' + ''.join(p.capitalize() for p in method.split('.'))
        cls = getattr(importlib.import_module('alipay.aop.api.request.' + name + 'Request'), name + 'Request')
        model_cls = getattr(importlib.import_module('alipay.aop.api.domain.' + name + 'Model'), name + 'Model')
        request = cls(biz_model=model_cls.from_alipay_dict(fields))
        raw = await asyncio.to_thread(self.checkout.gateway.client.execute, request)
        data = json.loads(raw)
        return data.get('alipay_' + method.replace('.', '_') + '_response', data)

    async def operate(self, action, order_id, confirmed=False):
        if not re.fullmatch(r'WEB[a-f0-9]{32}', order_id):
            raise ValueError('Invalid order ID')
        if action in ('refund', 'close') and not confirmed:
            raise ValueError('Explicit order confirmation required')
        store = self.checkout.store
        order = await store.run('internal_get', {'id': order_id})
        if not order:
            raise ValueError('Order not found')
        if action in ('refund', 'refund-query'):
            if action == 'refund':
                order = await store.run('refund_prepare', {'id': order_id})
            if not order or not order.get('refund_request_id'):
                raise ValueError('Order not eligible for refund')
            if order['state'] == 'REFUNDED':
                return {'state': 'REFUNDED'}
            fields = {'out_trade_no': order_id, 'out_request_no': order['refund_request_id']}
            if action == 'refund':
                fields['refund_amount'] = money(order['amount'])
                await self.request('trade.refund', fields)
                # Even an accepted response is reconciled by a later query.
                return {'state': 'REFUNDING', 'next': 'Wait at least 10 seconds, then refund-query'}
            response = await self.request('trade.fastpay.refund.query', fields)
            if response.get('code') == '10000' and response.get('refund_status') == 'REFUND_SUCCESS':
                if (response.get('out_trade_no') != order_id
                    or response.get('out_request_no') != order['refund_request_id']
                    or money(response.get('refund_amount')) != money(order['amount'])):
                    raise ValueError('Refund response mismatch')
                saved = await store.run('refunded', {'id': order_id, 'refund_request_id': order['refund_request_id']})
                if not saved:
                    raise ValueError('Refund state persistence failed')
                return {'state': 'REFUNDED'}
            return {'state': 'REFUNDING', 'code': response.get('code'), 'sub_code': response.get('sub_code')}
        if action == 'close':
            if order['state'] == 'CLOSED':
                return {'state': 'CLOSED'}
            order = await store.run('close_prepare', {'id': order_id})
            if not order:
                raise ValueError('Only unpaid orders may be closed')
            response = await self.request('trade.close', {'out_trade_no': order_id})
            if response.get('code') == '10000' and response.get('out_trade_no') == order_id:
                saved = await store.run('closed', {'id': order_id})
                if not saved:
                    raise ValueError('Close state persistence failed')
                return {'state': saved['state']}
            # Not-found/timeout is not proof of closure; a previously issued
            # signed form may still reach Alipay. Keep payment disabled locally.
            return {'state': 'CLOSING', 'code': response.get('code'), 'sub_code': response.get('sub_code')}
        raise ValueError('Unknown operation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['refund', 'refund-query', 'close'])
    parser.add_argument('order')
    parser.add_argument('--confirm-order', help='Repeat the exact approved order ID for mutations')
    args = parser.parse_args()
    try:
        checkout = build_checkout(None)
        if not checkout:
            raise ValueError('Web checkout not configured')
        result = asyncio.run(WebOperations(checkout).operate(args.action, args.order, args.confirm_order == args.order))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # Do not print SDK payloads, signed requests or configuration.
        print(json.dumps({'error': type(exc).__name__, 'message': 'Operation not confirmed; reconcile the same order before retrying'}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
