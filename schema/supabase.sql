-- TED Procurement Intelligence MCP v0.2.0
-- Run once in the Supabase SQL editor for the production warehouse.

create table if not exists public.notices (
  publication_number text primary key,
  publication_date date,
  title text,
  buyer_names jsonb not null default '[]'::jsonb,
  buyer_countries jsonb not null default '[]'::jsonb,
  cpv_codes jsonb not null default '[]'::jsonb,
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

create index if not exists notices_publication_date_idx
  on public.notices (publication_date desc);

create table if not exists public.supplier_profiles (
  profile_id text primary key,
  profile jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists public.sync_state (
  sync_key text primary key,
  iteration_next_token text,
  updated_at timestamptz not null default now()
);

create table if not exists public.api_keys (
  key_hash text primary key,
  name text not null,
  daily_quota integer not null default 1000 check (daily_quota >= 0),
  enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.api_usage (
  key_hash text not null references public.api_keys(key_hash) on delete cascade,
  usage_date date not null,
  request_count integer not null default 0 check (request_count >= 0),
  primary key (key_hash, usage_date)
);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists notices_touch_updated_at on public.notices;
create trigger notices_touch_updated_at
before update on public.notices
for each row execute function public.touch_updated_at();

drop trigger if exists supplier_profiles_touch_updated_at on public.supplier_profiles;
create trigger supplier_profiles_touch_updated_at
before update on public.supplier_profiles
for each row execute function public.touch_updated_at();

drop trigger if exists sync_state_touch_updated_at on public.sync_state;
create trigger sync_state_touch_updated_at
before update on public.sync_state
for each row execute function public.touch_updated_at();

create or replace function public.increment_api_usage(
  p_key_hash text,
  p_usage_date date
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  new_count integer;
begin
  insert into public.api_usage(key_hash, usage_date, request_count)
  values (p_key_hash, p_usage_date, 1)
  on conflict (key_hash, usage_date)
  do update set request_count = public.api_usage.request_count + 1
  returning request_count into new_count;

  return new_count;
end;
$$;

create or replace view public.warehouse_stats as
select
  (select count(*)::bigint from public.notices) as notice_count,
  (select count(*)::bigint from public.supplier_profiles) as supplier_profile_count,
  (select max(publication_date) from public.notices) as latest_publication_date;

-- The MCP server uses the service-role key. Keep direct client access closed.
alter table public.notices enable row level security;
alter table public.supplier_profiles enable row level security;
alter table public.sync_state enable row level security;
alter table public.api_keys enable row level security;
alter table public.api_usage enable row level security;

revoke all on public.notices from anon, authenticated;
revoke all on public.supplier_profiles from anon, authenticated;
revoke all on public.sync_state from anon, authenticated;
revoke all on public.api_keys from anon, authenticated;
revoke all on public.api_usage from anon, authenticated;
revoke all on public.warehouse_stats from anon, authenticated;
revoke all on function public.increment_api_usage(text, date) from public, anon, authenticated;
grant execute on function public.increment_api_usage(text, date) to service_role;
grant select, insert, update, delete on public.notices to service_role;
grant select, insert, update, delete on public.supplier_profiles to service_role;
grant select, insert, update, delete on public.sync_state to service_role;
grant select, insert, update, delete on public.api_keys to service_role;
grant select, insert, update, delete on public.api_usage to service_role;
grant select on public.warehouse_stats to service_role;
