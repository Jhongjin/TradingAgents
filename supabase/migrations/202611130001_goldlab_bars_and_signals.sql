-- Gold pattern lab: a bar store that outlives the vendor's window, and the
-- signal ledger graded against it.
--
-- Yahoo serves only about 60 days of 5-minute bars, so the lab keeps every bar
-- it has fetched here and merges new ones in. The ledger records each pattern
-- signal once, as it was visible at its own bar, and fills in how it turned out
-- as later bars arrive. Research only: nothing here trades.
--
-- Unlike cached_payloads and backtest_runs these tables are NOT publicly
-- readable. RLS is on with no select policy, so only the service role (the
-- scheduled job and the server) can see them.

create table if not exists public.goldlab_bars (
    symbol varchar(32) not null,
    interval varchar(8) not null,
    ts timestamptz not null,
    open double precision not null,
    high double precision not null,
    low double precision not null,
    close double precision not null,
    volume double precision not null default 0,
    -- 'yahoo' or a vendor tag (e.g. 'databento'); a vendor bar is never overwritten by a Yahoo one
    source varchar(24) not null default 'yahoo',
    updated_at timestamptz not null default now(),
    primary key (symbol, interval, ts)
);

create table if not exists public.goldlab_signals (
    signal_id varchar(160) primary key,
    symbol varchar(32) not null,
    interval varchar(8) not null,
    pattern varchar(48) not null,
    ts timestamptz not null,
    direction varchar(8) not null,
    complete boolean not null default false,
    payload_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_goldlab_signals_series_ts
    on public.goldlab_signals (symbol, interval, ts);
create index if not exists idx_goldlab_signals_pending
    on public.goldlab_signals (symbol, interval) where not complete;

alter table public.goldlab_bars enable row level security;
alter table public.goldlab_signals enable row level security;
