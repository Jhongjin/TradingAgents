create table if not exists public.analysis_refresh_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete set null,
    ticker_code text not null,
    ticker_name text,
    market text not null default 'KR',
    requested_trade_date date not null,
    status text not null default 'queued'
        check (status in ('queued', 'running', 'completed', 'failed', 'skipped')),
    reason text,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_analysis_refresh_requests_status_created
    on public.analysis_refresh_requests (status, created_at);
create index if not exists idx_analysis_refresh_requests_user
    on public.analysis_refresh_requests (user_id);
create index if not exists idx_analysis_refresh_requests_ticker_date
    on public.analysis_refresh_requests (ticker_code, requested_trade_date desc);

alter table public.analysis_refresh_requests enable row level security;

drop policy if exists "users manage own analysis refresh requests" on public.analysis_refresh_requests;
create policy "users manage own analysis refresh requests"
on public.analysis_refresh_requests
for all
using (auth.uid() = user_id)
with check (auth.uid() = user_id);
