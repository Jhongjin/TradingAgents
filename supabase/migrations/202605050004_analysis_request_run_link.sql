alter table public.analysis_refresh_requests
    add column if not exists analysis_run_id uuid references public.analysis_runs(id) on delete set null;

create index if not exists idx_analysis_refresh_requests_run
    on public.analysis_refresh_requests (analysis_run_id);
