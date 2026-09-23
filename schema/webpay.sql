-- Additive migration: independent web checkout orders; does not change A2M orders.
create table if not exists public.ted_web_orders (
 id text primary key, session_hash text not null, request_id text not null,
 keywords text not null check(length(keywords) between 1 and 200),
 amount numeric(12,2) not null check(amount > 0),
 state text not null default 'PENDING', trade_no text unique,
 result jsonb, lease text, lease_until timestamptz,
 created_at timestamptz not null default now(),
 unique(session_hash,request_id)
);
alter table public.ted_web_orders add column if not exists refund_request_id text;
alter table public.ted_web_orders enable row level security;
revoke all on public.ted_web_orders from anon,authenticated;

create or replace function public.ted_web_order(p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare o public.ted_web_orders; begin
 if p_action='create' then
  insert into public.ted_web_orders(id,session_hash,request_id,keywords,amount)
  values(p_data->>'id',p_data->>'session_hash',p_data->>'request_id',p_data->>'keywords',(p_data->>'amount')::numeric)
  on conflict(session_hash,request_id) do nothing;
  select * into o from public.ted_web_orders where session_hash=p_data->>'session_hash' and request_id=p_data->>'request_id';
  if o.keywords is distinct from p_data->>'keywords' or o.amount is distinct from (p_data->>'amount')::numeric then return null; end if;
  return to_jsonb(o);
 end if;
 select * into o from public.ted_web_orders where id=p_data->>'id' for update;
 if not found then return null; end if;
 if p_action='get' then
  if o.session_hash is distinct from p_data->>'session_hash' then return null; end if;
 elsif p_action='internal_get' then null;
 elsif p_action='paid' then
  if o.amount is distinct from (p_data->>'amount')::numeric or coalesce(p_data->>'trade_no','')='' then return null; end if;
  if o.trade_no is not null and o.trade_no is distinct from p_data->>'trade_no' then return null; end if;
  if o.state in ('PENDING','CLOSING','CLOSED') then
   update public.ted_web_orders set state='PAID',trade_no=p_data->>'trade_no' where id=o.id returning * into o;
  end if;
 elsif p_action='closed' then
  if o.state in ('PENDING','CLOSING') then update public.ted_web_orders set state='CLOSED' where id=o.id returning * into o; end if;
 elsif p_action='close_prepare' then
  if o.state not in ('PENDING','CLOSING') then return null; end if;
  update public.ted_web_orders set state='CLOSING' where id=o.id returning * into o;
 elsif p_action='refund_prepare' then
  if o.state not in ('PAID','GENERATING','READY','REFUNDING','REFUNDED') or o.trade_no is null then return null; end if;
  if o.state not in ('REFUNDING','REFUNDED') then
   update public.ted_web_orders set state='REFUNDING',refund_request_id='RF'||o.id,lease=null,lease_until=null where id=o.id returning * into o;
  end if;
 elsif p_action='refunded' then
  if o.state not in ('REFUNDING','REFUNDED') or o.refund_request_id is null or o.refund_request_id is distinct from p_data->>'refund_request_id' then return null; end if;
  update public.ted_web_orders set state='REFUNDED',result=null where id=o.id returning * into o;
 elsif p_action='claim' then
  if o.state='READY' then return to_jsonb(o); end if;
  if o.state not in ('PAID','GENERATING') then return null; end if;
  if o.state='GENERATING' and o.lease_until>now() then return jsonb_build_object('busy',true); end if;
  if coalesce(p_data->>'lease','')='' then return null; end if;
  update public.ted_web_orders set state='GENERATING',lease=p_data->>'lease',lease_until=now()+interval '90 seconds' where id=o.id returning * into o;
 elsif p_action='save' then
  if o.state<>'GENERATING' or o.lease is distinct from p_data->>'lease' or jsonb_typeof(p_data->'result'->'notices') is distinct from 'array' then return null; end if;
  update public.ted_web_orders set state='READY',result=p_data->'result',lease=null,lease_until=null where id=o.id returning * into o;
 else raise exception 'Unknown web order operation'; end if;
 return to_jsonb(o);
end $$;
revoke all on function public.ted_web_order(text,jsonb) from public,anon,authenticated;
grant execute on function public.ted_web_order(text,jsonb) to service_role;
