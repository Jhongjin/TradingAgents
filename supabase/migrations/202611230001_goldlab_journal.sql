-- Gold lab: the operator's own trade calls ("내 판단 기록"), graded later by the lab.
--
-- Private like the other goldlab tables: RLS is on with no select policy, so
-- only the service role (the server, behind the operator token) can read or
-- write it. Nothing here places an order.

create table if not exists public.goldlab_journal (
    entry_id varchar(32) primary key,
    symbol varchar(32) not null,
    ts timestamptz not null,
    payload_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_goldlab_journal_symbol_ts
    on public.goldlab_journal (symbol, ts desc);

alter table public.goldlab_journal enable row level security;
