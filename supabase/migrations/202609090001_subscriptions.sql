-- Subscriptions for the research-tool plans (free / daily / pro).
--
-- Rows are written only by the server (payment webhooks and the renewal
-- worker, via DATABASE_URL). Members can read their own row through RLS so the
-- browser client can show plan state without a service key. Billing keys are
-- provider references, never card data.

create table if not exists public.subscriptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    plan varchar(16) not null default 'free',
    status varchar(24) not null default 'inactive',
    provider varchar(24) not null default 'portone',
    customer_key varchar(120),
    billing_key varchar(200),
    trial_ends_at timestamptz,
    current_period_start timestamptz,
    current_period_end timestamptz,
    cancel_at_period_end boolean not null default false,
    last_payment_id varchar(120),
    last_payment_at timestamptz,
    failure_count integer not null default 0,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id)
);

create table if not exists public.billing_events (
    id uuid primary key default gen_random_uuid(),
    subscription_id uuid references public.subscriptions (id) on delete set null,
    user_id uuid references auth.users (id) on delete set null,
    provider varchar(24) not null default 'portone',
    event_type varchar(64) not null,
    payment_id varchar(120),
    amount numeric(18, 2),
    currency varchar(8) not null default 'KRW',
    status varchar(24),
    message text,
    payload_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_subscriptions_status_period
    on public.subscriptions (status, current_period_end);

create index if not exists idx_billing_events_user_created
    on public.billing_events (user_id, created_at desc);

create index if not exists idx_billing_events_payment
    on public.billing_events (payment_id);

alter table public.subscriptions enable row level security;
alter table public.billing_events enable row level security;

drop policy if exists "members read own subscription" on public.subscriptions;
create policy "members read own subscription"
on public.subscriptions
for select
using (auth.uid() = user_id);

drop policy if exists "members read own billing events" on public.billing_events;
create policy "members read own billing events"
on public.billing_events
for select
using (auth.uid() = user_id);
