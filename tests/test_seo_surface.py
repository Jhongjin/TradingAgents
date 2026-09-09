import json
from datetime import date

from fastapi.testclient import TestClient

from tradingagents.site import create_app
from tradingagents.site.seo import build_llms_txt, build_robots_txt, build_sitemap_xml
from tradingagents.storage import HarnessRunInput, StorageRepository, create_storage_engine


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine("sqlite+pysqlite:///:memory:"))
    repo.create_schema()
    return repo


def test_robots_allows_ai_search_and_fetch_agents_but_hides_member_paths():
    text = build_robots_txt(site_base_url="https://example.com")
    for agent in ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Yeti"):
        assert f"User-agent: {agent}\nAllow: /" in text
    assert text.count("Disallow: /billing") >= 2 and "Disallow: /api/" in text
    assert text.rstrip().endswith("Sitemap: https://example.com/sitemap.xml")


def test_llms_txt_names_primary_pages_and_data_policy():
    text = build_llms_txt(site_base_url="https://example.com", latest_run_date="2026-09-09")
    assert text.startswith("# TradingAgents Korea")
    assert "https://example.com/harness" in text and "https://example.com/outcomes" in text
    assert "2026-09-09" in text and "pykrx" in text and "인용 시 표기" in text


def test_sitemap_lists_harness_pricing_and_run_paths():
    xml = build_sitemap_xml(site_base_url="https://example.com", harness_paths=["/harness/abc", "/analyses/x", "/harness/abc"], generated_date="2026-09-09")
    assert "https://example.com/harness</loc>" in xml and "https://example.com/pricing</loc>" in xml
    assert xml.count("https://example.com/harness/abc</loc>") == 1 and "/analyses/x" not in xml


def test_shell_pages_carry_social_meta_and_site_graph():
    repo = _repo()
    repo.create_harness_run(HarnessRunInput(as_of_date=date(2026, 9, 8), confirmer="debate", candidate_count=3, order_count=1))
    client = TestClient(create_app(repo=repo, load_repo_from_env=False))
    home = client.get("/").text
    assert '<meta property="og:title"' in home and '<meta name="twitter:card" content="summary_large_image">' in home and '/og/home.png' in home
    graph = json.loads(home.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0])
    types = [node["@type"] for node in graph["@graph"]]
    assert types[:2] == ["Organization", "WebSite"] and "WebPage" in types
    assert graph["@graph"][1]["potentialAction"]["@type"] == "SearchAction"

    pricing = client.get("/pricing").text
    pricing_graph = json.loads(pricing.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0])
    ptypes = [node["@type"] for node in pricing_graph["@graph"]]
    assert "FAQPage" in ptypes and "Product" in ptypes
    faq = next(node for node in pricing_graph["@graph"] if node["@type"] == "FAQPage")
    assert faq["mainEntity"][0]["name"] in pricing  # JSON-LD mirrors the visible FAQ

    harness = client.get("/harness").text
    assert '<meta property="og:type" content="article">' in harness and '"BreadcrumbList"' in harness

    billing = client.get("/billing").text
    assert 'name="robots" content="noindex, nofollow"' in billing and "application/ld+json" not in billing

    llms = client.get("/llms.txt")
    assert llms.status_code == 200 and "text/markdown" in llms.headers["content-type"] and "2026-09-08" in llms.text
    assert llms.headers["cache-control"].startswith("public")


def test_verification_meta_from_env(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_NAVER_SITE_VERIFICATION", "naver-token")
    monkeypatch.setenv("TRADINGAGENTS_GOOGLE_SITE_VERIFICATION", "google-token")
    client = TestClient(create_app(repo=None, load_repo_from_env=False))
    html = client.get("/pricing").text
    assert '<meta name="naver-site-verification" content="naver-token">' in html
    assert '<meta name="google-site-verification" content="google-token">' in html
