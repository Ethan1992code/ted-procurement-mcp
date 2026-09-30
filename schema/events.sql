-- Apply only to the SUPABASE_URL database used by the Vercel MCP deployment.
-- Server-only: callback signing secrets must never be available to browser roles.
CREATE TABLE IF NOT EXISTS public.event_subscriptions (
    id text PRIMARY KEY,
    payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS public.event_deliveries (
    subscription_id text NOT NULL REFERENCES public.event_subscriptions(id),
    event_id text NOT NULL,
    event jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('baseline','pending','delivered','failed')),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt double precision NOT NULL DEFAULT 0,
    PRIMARY KEY (subscription_id, event_id)
);
CREATE INDEX IF NOT EXISTS event_deliveries_pending ON public.event_deliveries(subscription_id,next_attempt) WHERE status='pending';
ALTER TABLE public.event_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.event_deliveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.event_subscriptions, public.event_deliveries FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.event_subscriptions, public.event_deliveries TO service_role;
