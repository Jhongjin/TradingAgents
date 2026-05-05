from pathlib import Path


def test_supabase_migration_avoids_dashboard_fragile_dollar_quotes():
    migration = Path("supabase/migrations/202605050001_tradingagents_public_site.sql").read_text(
        encoding="utf-8"
    )

    assert "$$" not in migration
    assert "create table if not exists public.analysis_runs" in migration
    assert "enable row level security" in migration
