from pathlib import Path


def test_supabase_migration_avoids_dashboard_fragile_dollar_quotes():
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
    )

    assert "$$" not in migrations
    assert "create table if not exists public.analysis_runs" in migrations
    assert "create table if not exists public.analysis_outcomes" in migrations
    assert "create table if not exists public.analysis_refresh_requests" in migrations
    assert "create table if not exists public.manual_watchlists" in migrations
    assert "create table if not exists public.harness_runs" in migrations
    assert "create table if not exists public.harness_decisions" in migrations
    assert "create table if not exists public.harness_outcomes" in migrations
    assert "create table if not exists public.subscriptions" in migrations
    assert "create table if not exists public.billing_events" in migrations
    assert "create table if not exists public.notification_channels" in migrations
    assert "enable row level security" in migrations
