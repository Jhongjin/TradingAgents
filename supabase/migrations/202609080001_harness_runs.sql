-- Harness pipeline persistence: screener -> forecast -> confirm -> size -> gate -> order.
-- Rows describe research decisions and dry-run/paper intents. Public runs are
-- readable by anyone; writes come only from the service role (worker/cron).

create table if not exists public.harness_runs (
    id uuid primary key default gen_random_uuid(),
    as_of_date date not null,
    mode varchar(16) not null default 'paper',
    broker varchar(32) not null default 'paper',
    dry_run integer not null default 1,
    confirmer varchar(32) not null default 'none',
    visibility varchar(16) not null default 'public',
    status varchar(32) not null default 'completed',
    markets varchar(64) not null default 'KOSPI,KOSDAQ',
    universe_size integer not null default 0,
    candidate_count integer not null default 0,
    order_count integer not null default 0,
    cash_before numeric(18, 4),
    cash_after numeric(18, 4),
    audit_sequence_start integer,
    audit_sequence_end integer,
    notes_json jsonb not null default '[]'::jsonb,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.harness_decisions (
    id uuid primary key default gen_random_uuid(),
    harness_run_id uuid not null references public.harness_runs(id) on delete cascade,
    as_of_date date not null,
    ticker_code varchar(12) not null,
    ticker_name varchar(120),
    market varchar(32) not null default 'KR',
    stage varchar(32) not null,
    screener_rank integer,
    composite_score double precision,
    forecast_expected_return double precision,
    forecast_probability_up double precision,
    confirmation_rating varchar(32),
    confirmation_confidence double precision,
    confirmation_source varchar(32),
    quantity integer,
    entry_price numeric(18, 4),
    stop_price numeric(18, 4),
    take_profit_price numeric(18, 4),
    order_status varchar(32),
    reasons_json jsonb not null default '[]'::jsonb,
    detail_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_harness_runs_date
    on public.harness_runs (as_of_date desc, created_at desc);

create index if not exists idx_harness_decisions_run
    on public.harness_decisions (harness_run_id);

create index if not exists idx_harness_decisions_ticker_date
    on public.harness_decisions (ticker_code, as_of_date desc);

create index if not exists idx_harness_decisions_date
    on public.harness_decisions (as_of_date desc, created_at desc);

alter table public.harness_runs enable row level security;
alter table public.harness_decisions enable row level security;

drop policy if exists "public harness runs are readable" on public.harness_runs;
create policy "public harness runs are readable"
on public.harness_runs
for select
using (visibility = 'public');

drop policy if exists "public harness decisions are readable" on public.harness_decisions;
create policy "public harness decisions are readable"
on public.harness_decisions
for select
using (
    exists (
        select 1 from public.harness_runs r
        where r.id = harness_run_id and r.visibility = 'public'
    )
);
