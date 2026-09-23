-- Apply separately in the NEW project's SQL editor. No credentials in this file.
begin;
create table if not exists public.ted_aipay_orders (
  out_trade_no text primary key,
  amount numeric(12,2) not null check (amount > 0),
  resource_id text not null,
  pay_before timestamptz not null,
  bill jsonb not null,
  state text not null default 'PENDING_PAYMENT'
    check (state in ('PENDING_PAYMENT','GENERATING','PENDING_CONFIRM','FULFILLED','CANCELLED')),
  trade_no text unique,
  lease_token text,
  lease_until timestamptz,
  result jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (state not in ('PENDING_CONFIRM','FULFILLED') or result is not null)
);
alter table public.ted_aipay_orders enable row level security;
revoke all on public.ted_aipay_orders from public, anon, authenticated;
grant select, insert, update on public.ted_aipay_orders to service_role;

create or replace function public.ted_aipay_order(p_action text, p_data jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.ted_aipay_orders%rowtype;
begin
  if p_action = 'create' then
    insert into public.ted_aipay_orders(out_trade_no, amount, resource_id, pay_before, bill)
    values(p_data->>'out_trade_no', (p_data->>'amount')::numeric,
      p_data->>'resource_id', (p_data->>'pay_before')::timestamptz, p_data->'bill')
    returning * into o;
    return to_jsonb(o);
  end if;
  select * into o from public.ted_aipay_orders
    where out_trade_no = p_data->>'out_trade_no' for update;
  if not found then return null; end if;
  if p_action = 'get' then return to_jsonb(o); end if;
  if p_action = 'claim' then
    if o.amount is distinct from (p_data->>'amount')::numeric
      or o.resource_id is distinct from p_data->>'resource_id'
      or nullif(p_data->>'trade_no','') is null
      or nullif(p_data->>'lease_token','') is null
      or (o.trade_no is not null and o.trade_no <> p_data->>'trade_no')
      or o.state = 'CANCELLED' then return null; end if;
    if o.state in ('PENDING_CONFIRM','FULFILLED') then return to_jsonb(o); end if;
    if o.pay_before <= clock_timestamp() then return null; end if;
    if o.state = 'GENERATING' and o.lease_until > clock_timestamp() then
      return jsonb_build_object('busy', true);
    end if;
    update public.ted_aipay_orders set state='GENERATING',
      trade_no=p_data->>'trade_no', lease_token=p_data->>'lease_token',
      lease_until=clock_timestamp()+interval '90 seconds', updated_at=clock_timestamp()
      where out_trade_no=o.out_trade_no returning * into o;
  elsif p_action = 'save' then
    if o.state <> 'GENERATING' or o.lease_token is distinct from p_data->>'lease_token'
      or o.trade_no is distinct from p_data->>'trade_no' or p_data->'result' is null
      or p_data->'result' = 'null'::jsonb then return null; end if;
    update public.ted_aipay_orders set state='PENDING_CONFIRM', result=p_data->'result',
      lease_token=null, lease_until=null, updated_at=clock_timestamp()
      where out_trade_no=o.out_trade_no returning * into o;
  elsif p_action = 'complete' then
    if o.trade_no is distinct from p_data->>'trade_no' or o.state not in ('PENDING_CONFIRM','FULFILLED')
      then return null; end if;
    update public.ted_aipay_orders set state='FULFILLED', updated_at=clock_timestamp()
      where out_trade_no=o.out_trade_no returning * into o;
  else
    raise exception 'Unsupported payment state action';
  end if;
  return to_jsonb(o);
exception when unique_violation then
  if p_action = 'claim' then return null; end if;
  raise;
end $$;
revoke all on function public.ted_aipay_order(text,jsonb) from public, anon, authenticated;
grant execute on function public.ted_aipay_order(text,jsonb) to service_role;
commit;
