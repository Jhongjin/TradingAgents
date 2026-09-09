"""Evidence-first public home page (design direction "A+D").

The page is a daily report front page: a numbered issue headline that states
today's harness conclusion, the decision ledger, the debate transcript
excerpts (bull / bear / judge / risk panel), the scored track record, and the
paper account. Everything is read from what the backend already stores; the
page never triggers analysis, orders, or vendor calls in the request path.
Prices for the stock rail are fetched by the browser from ``/api/prices/latest``
after load so the HTML itself renders in one database round trip.

Themes: ``paper`` (light), ``dark``, ``sepia``. The choice is stored in
``localStorage`` under ``ta-theme``; without a stored choice the page follows
``prefers-color-scheme``. Colors are CSS custom properties on ``:root`` so a
theme switch is one attribute change.
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from tradingagents.storage import StorageRepository

from .harness_api import build_harness_outcomes_payload, build_harness_run_payload, build_harness_runs_payload
from .seo import canonical_url

RAIL_TICKERS: tuple[tuple[str, str], ...] = (
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("373220", "LG에너지솔루션"),
    ("086520", "에코프로"),
    ("196170", "알테오젠"),
)

THEMES = ("paper", "dark", "sepia")
THEME_LABELS = {"paper": "종이", "dark": "다크", "sepia": "세피아"}

ROLE_LABELS = {
    "bull": ("강세 연구원", "accent"),
    "bear": ("약세 연구원", "loss"),
    "judge": ("판정관", "ink"),
    "risk_panel": ("리스크 패널", "brass"),
}

STAGE_STYLE = {
    "ordered": "ordered",
    "exit": "ordered",
    "gate_rejected": "gate",
    "sized": "gate",
    "forecast_rejected": "rejected",
    "confirmation_rejected": "rejected",
    "screened": "rejected",
}


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pct(value: Any, digits: int = 1, signed: bool = True) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number * 100:{'+' if signed else ''}.{digits}f}%"


def _num(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _sign_class(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number > 0:
        return "up"
    if number < 0:
        return "down"
    return ""


def _korean_date(value: Any) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return str(value)
    if not isinstance(value, date):
        return "-"
    weekdays = "월화수목금토일"
    return f"{value.year}년 {value.month}월 {value.day}일 ({weekdays[value.weekday()]})"


def build_home_view_model(repo: StorageRepository | None, *, site_base_url: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Assemble everything the template needs from stored harness data."""

    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    latest, runs, outcomes = _load_sources(repo)

    run = (latest or {}).get("run") if isinstance(latest, dict) else None
    decisions = list((latest or {}).get("decisions") or []) if isinstance(latest, dict) else []
    ordered = [item for item in decisions if item.get("stage") in {"ordered", "exit"}]
    featured = ordered[0] if ordered else (decisions[0] if decisions else None)
    debate = _debate_excerpts(featured)
    total_runs = int(runs.get("item_count") or len(runs.get("items") or []) or 0)

    summary = (outcomes or {}).get("summary") or {}
    five = summary.get("5") or {}
    twenty = summary.get("20") or {}
    alpha_bars = _alpha_bars((outcomes or {}).get("items") or [])

    account = _account_from_run(run)
    headline, deck = _headline(run, decisions, featured)
    teaser = _today_teaser(runs.get("items") or [], run, now)

    return {
        "site_base_url": site_base_url,
        "canonical": canonical_url("/", site_base_url=site_base_url),
        "now_text": now.strftime("%Y년 %m월 %d일 %H:%M KST"),
        "issue_number": total_runs,
        "run": run,
        "run_date_text": _korean_date(run.get("as_of_date")) if run else None,
        "headline": headline,
        "deck": deck,
        "decisions": decisions,
        "featured": featured,
        "debate": debate,
        "funnel": _funnel(run, decisions),
        "outcomes": {
            "five": five,
            "twenty": twenty,
            "alpha_bars": alpha_bars,
            "completed_total": int(five.get("completed") or 0) + int(twenty.get("completed") or 0),
        },
        "account": account,
        "previous_runs": [item for item in (runs.get("items") or []) if not run or item.get("id") != run.get("id")][:3],
        "teaser": teaser,
        "plan_gate": (latest or {}).get("plan_gate") if isinstance(latest, dict) else None,
        "rail": [{"code": code, "name": name, "path": f"/stocks/{code}"} for code, name in RAIL_TICKERS],
        "storage_status": (latest or {}).get("status") if isinstance(latest, dict) else ("not_configured" if repo is None else "empty"),
    }


SOURCE_CACHE_SECONDS = 60
_source_cache: dict[int, tuple[float, tuple[Any, Any, Any]]] = {}


def _load_sources(repo: StorageRepository | None) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Four database round trips, memoised per process for a minute.

    Serverless instances stay warm between requests and the CDN caches the
    rendered page, so a short in-process cache removes most origin latency
    (each Supabase query costs a cross-region round trip).
    """

    import time

    if repo is None:
        return None, {"items": [], "item_count": 0}, {"summary": {}, "items": []}
    key = id(repo)
    cached = _source_cache.get(key)
    if cached and time.monotonic() - cached[0] < SOURCE_CACHE_SECONDS:
        return cached[1]
    from .billing import gate_harness_payload, latest_visible_run_id, resolve_plan_access

    # The home page is public and CDN-cached, so it renders the free view:
    # newest run before today, no debate transcript. Today's run appears as a
    # teaser (counts only) until the next trading day.
    free_access = resolve_plan_access(None, None)
    runs = build_harness_runs_payload(repo, limit=50)
    visible_id = latest_visible_run_id(repo, free_access)
    latest = build_harness_run_payload(repo, harness_run_id=visible_id) if visible_id else build_harness_run_payload(repo)
    latest = gate_harness_payload(latest, free_access) if latest else latest
    outcomes = build_harness_outcomes_payload(repo, limit=120)
    _source_cache[key] = (time.monotonic(), (latest, runs, outcomes))
    return latest, runs, outcomes


def clear_home_cache() -> None:
    _source_cache.clear()


def _today_teaser(items: list[Mapping[str, Any]], visible_run: Mapping[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """Counts for a run newer than the visible one (today's, still locked for free)."""

    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    for item in items:
        as_of = item.get("as_of_date")
        as_of_date = as_of if isinstance(as_of, date) else _parse_date(as_of)
        if as_of_date is None or as_of_date < today:
            continue
        if visible_run and item.get("id") == visible_run.get("id"):
            return None
        return {
            "as_of_date": as_of_date.isoformat(),
            "candidate_count": int(item.get("candidate_count") or 0),
            "order_count": int(item.get("order_count") or 0),
            "confirmer": item.get("confirmer"),
        }
    return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and len(value) >= 10:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _debate_excerpts(decision: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if not decision:
        return []
    confirmation = ((decision.get("detail") or {}).get("confirmation") or {})
    raw = confirmation.get("raw") or {}
    turns = (raw.get("debate") or {}).get("turns") or {}
    public_excerpts = confirmation.get("excerpts") or {}
    excerpts: list[dict[str, str]] = []
    for key, (label, tone) in ROLE_LABELS.items():
        if turns:
            text = _turn_text(key, (turns.get(key) or {}).get("data") or {})
        else:
            text = str(public_excerpts.get(key) or "").strip()
        if text:
            excerpts.append({"role": key, "label": label, "tone": tone, "text": text})
    return excerpts


def _turn_text(role: str, data: Mapping[str, Any]) -> str:
    if role in {"bull", "bear"}:
        text = data.get("thesis") or data.get("summary") or ""
    elif role == "judge":
        text = data.get("rationale") or data.get("summary") or ""
    else:
        score = data.get("risk_score")
        stop = data.get("stop_loss_pct")
        take = data.get("take_profit_pct")
        parts = []
        if stop is not None:
            parts.append(f"손절 {_pct(-abs(_float(stop, 0.0)), 0)}")
        if take is not None:
            parts.append(f"익절 {_pct(abs(_float(take, 0.0)), 0)}")
        if score is not None:
            parts.append(f"위험 점수 {_float(score, 0.0):.2f}")
        view = data.get("neutral_view") or data.get("summary") or ""
        text = (" · ".join(parts) + ". " if parts else "") + str(view)
    text = str(text).strip()
    return text[:220] + ("…" if len(text) > 220 else "")


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _funnel(run: Mapping[str, Any] | None, decisions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not run:
        return []
    universe = int(run.get("universe_size") or 0)
    candidates = int(run.get("candidate_count") or 0)
    confirmed = sum(1 for item in decisions if item.get("stage") in {"sized", "gate_rejected", "ordered"})
    orders = int(run.get("order_count") or 0)
    return [
        {"label": "유니버스", "value": universe},
        {"label": "요인 상위", "value": candidates},
        {"label": "예측·토론 통과", "value": confirmed},
        {"label": "가상 주문", "value": orders},
    ]


def _account_from_run(run: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not run or run.get("dry_run"):
        return None
    before = _float(run.get("cash_before"), 0.0)
    after = _float(run.get("cash_after"), 0.0)
    if before <= 0:
        return None
    return {"broker": run.get("broker"), "cash_before": before, "cash_after": after, "change": (after / before) - 1 if before else None}


def _headline(run: Mapping[str, Any] | None, decisions: list[Mapping[str, Any]], featured: Mapping[str, Any] | None) -> tuple[str, str]:
    if not run:
        return (
            "첫 하네스 실행을 기다리고 있습니다",
            "평일 아침 07:50과 장중 10:05에 KOSPI·KOSDAQ 상위 종목을 거르고, AI 토론으로 확인한 결과가 여기에 실립니다.",
        )
    total = len(decisions)
    ordered = [item for item in decisions if item.get("stage") in {"ordered", "exit"}]
    if not ordered:
        return (
            f"{total}개 후보를 살폈지만 오늘은 한 종목도 통과하지 못했다",
            "예측 확률이 기준에 못 미쳤거나 토론에서 약세 논거가 이겼습니다. 사지 않은 이유도 아래 원장에 남깁니다.",
        )
    names = [str(item.get("ticker_name") or item.get("ticker_code")) for item in ordered]
    if len(ordered) == 1:
        head = f"{total}개 후보 중 {total - 1}개가 떨어졌다. {names[0]}만 남은 이유"
    else:
        head = f"{total}개 후보 중 {len(ordered)}개가 통과했다: {', '.join(names[:3])}"
    rationale = ""
    if featured:
        confirmation = ((featured.get("detail") or {}).get("confirmation") or {})
        rationale = str(confirmation.get("rationale") or "").strip()
    deck = rationale[:180] + ("…" if len(rationale) > 180 else "") if rationale else "강세·약세 연구원의 토론과 리스크 패널의 한도 검사를 거친 결과입니다."
    return head, deck


def _alpha_bars(items: list[Mapping[str, Any]], limit: int = 30) -> list[float]:
    values: list[float] = []
    for item in items:
        if item.get("status") != "completed" or item.get("horizon_days") != 20:
            continue
        alpha = item.get("alpha_return")
        if alpha is None:
            continue
        values.append(float(alpha))
    return values[:limit]


def render_home_page(*, repo: StorageRepository | None = None, site_base_url: str | None = None, now: datetime | None = None) -> str:
    model = build_home_view_model(repo, site_base_url=site_base_url, now=now)
    return _render(model)


# --------------------------------------------------------------------------
# template
# --------------------------------------------------------------------------

HOME_CSS = """
:root{--bg:#fbfaf4;--bg2:#f2f0e6;--panel:#ffffff;--ink:#17201f;--ink2:#4b5654;--muted:#7a847f;--line:#d9ddd3;--line-strong:#b9c0b6;--accent:#146b63;--accent-ink:#0f4e49;--accent-soft:#dcefe9;--brass:#a87d24;--brass-soft:#f4ead2;--gain:#b42318;--loss:#1d4ed8;--on-accent:#ffffff;--shadow:0 12px 32px -20px rgba(23,32,31,.35);color-scheme:light}
:root[data-theme="dark"]{--bg:#10130f;--bg2:#171a16;--panel:#171a16;--ink:#f6f3e8;--ink2:#c9cec3;--muted:#9aa39b;--line:#2a2e28;--line-strong:#3d423a;--accent:#8fd8bd;--accent-ink:#b9ead6;--accent-soft:#1b2a26;--brass:#d6b25d;--brass-soft:#2b2418;--gain:#ff6b57;--loss:#6bb7ff;--on-accent:#10130f;--shadow:0 12px 32px -20px rgba(0,0,0,.8);color-scheme:dark}
:root[data-theme="sepia"]{--bg:#f3ead9;--bg2:#eadfc9;--panel:#fbf6ec;--ink:#2b2418;--ink2:#5a4d38;--muted:#8a7a5e;--line:#d9cbb0;--line-strong:#c1ad89;--accent:#7a5a1e;--accent-ink:#5c4315;--accent-soft:#eedfbf;--brass:#8f6a1c;--brass-soft:#ecdcb4;--gain:#a8281c;--loss:#2b4f9e;--on-accent:#fbf6ec;color-scheme:light}
@media (prefers-color-scheme: dark){:root:not([data-theme]){--bg:#10130f;--bg2:#171a16;--panel:#171a16;--ink:#f6f3e8;--ink2:#c9cec3;--muted:#9aa39b;--line:#2a2e28;--line-strong:#3d423a;--accent:#8fd8bd;--accent-ink:#b9ead6;--accent-soft:#1b2a26;--brass:#d6b25d;--brass-soft:#2b2418;--gain:#ff6b57;--loss:#6bb7ff;--on-accent:#10130f;--shadow:0 12px 32px -20px rgba(0,0,0,.8);color-scheme:dark}}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;font-size:15px;line-height:1.55}
a{color:var(--accent-ink)}a:hover{color:var(--accent)}
h1,h2,h3{font-family:"Noto Serif KR","Apple SD Gothic Neo",serif;margin:0;font-weight:700;line-height:1.25;text-wrap:balance}
.serif{font-family:"Noto Serif KR","Apple SD Gothic Neo",serif}
.mono{font-family:"IBM Plex Mono",Consolas,monospace;font-variant-numeric:tabular-nums}
.up{color:var(--gain)}.down{color:var(--loss)}.muted{color:var(--muted)}
.shell{max-width:1180px;margin:0 auto;padding:0 24px}
.skip-link{position:absolute;left:-9999px}.skip-link:focus{left:16px;top:8px;background:var(--panel);padding:8px 12px;z-index:10}
.masthead{border-bottom:2px solid var(--ink)}
.masthead .shell{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:16px 24px;flex-wrap:wrap}
.brand{display:flex;align-items:baseline;gap:10px;text-decoration:none;color:var(--ink)}
.brand-name{font-family:"Noto Serif KR",serif;font-size:22px;font-weight:700}
.brand-sub{font-size:12px;color:var(--muted)}
.nav{display:flex;gap:20px;font-size:14px;font-weight:500}
.nav a{text-decoration:none;color:var(--ink2);padding:4px 0;border-bottom:2px solid transparent}
.nav a[aria-current="page"]{color:var(--ink);border-bottom-color:var(--accent)}
.mast-right{display:flex;gap:10px;align-items:center}
.btn{display:inline-flex;align-items:center;gap:8px;padding:9px 14px;border-radius:6px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-weight:500;text-decoration:none;cursor:pointer}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.btn:focus-visible,.theme-switch button:focus-visible,.search input:focus-visible,.nav a:focus-visible,.stock:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.theme-switch{display:inline-flex;gap:4px;padding:4px;border:1px solid var(--line-strong);border-radius:999px;background:var(--panel)}
.theme-switch button{width:22px;height:22px;border-radius:50%;border:1px solid var(--line-strong);cursor:pointer;padding:0}
.theme-switch button[aria-pressed="true"]{box-shadow:0 0 0 2px var(--accent)}
.theme-switch .paper{background:#fbfaf4}.theme-switch .dark{background:#10130f}.theme-switch .sepia{background:#f3ead9}
.tape{background:var(--bg2);border-bottom:1px solid var(--line);font-size:13px}
.tape .shell{display:flex;flex-wrap:wrap;gap:6px 28px;padding:8px 24px}
.tape .date{font-weight:600;color:var(--ink2)}
.hero{padding:44px 0 28px;border-bottom:1px solid var(--line)}
.hero .shell{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(300px,.85fr);gap:40px;align-items:end}
.issue{font-family:"IBM Plex Mono",monospace;font-size:12px;letter-spacing:.1em;color:var(--muted)}
.hero h1{font-size:clamp(28px,3.6vw,40px);letter-spacing:-.015em;margin:12px 0 14px}
.hero .deck{max-width:34em;color:var(--ink2);font-size:16px;margin:0 0 22px}
.teaser{margin:0 0 18px;padding:10px 14px;border:1px solid var(--brass);border-radius:8px;background:var(--brass-soft);color:var(--ink);font-size:14px;max-width:34em}
.teaser a{font-weight:600}
.search{display:flex;border:1px solid var(--line-strong);border-radius:8px;background:var(--panel);overflow:hidden;max-width:560px}
.search input{flex:1;border:0;padding:14px 16px;font:inherit;font-size:16px;background:transparent;color:var(--ink);min-width:0}
.search input::placeholder{color:var(--muted)}
.search button{border:0;background:var(--accent);color:var(--on-accent);font:inherit;font-weight:600;padding:0 20px;cursor:pointer}
.proof{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);border-radius:10px;background:var(--panel);box-shadow:var(--shadow);overflow:hidden}
.proof>div{padding:16px 18px;border-left:1px solid var(--line)}.proof>div:first-child{border-left:0}
.proof .label{font-size:12px;color:var(--muted);font-weight:600}
.proof .value{font-family:"IBM Plex Mono",monospace;font-size:26px;line-height:1.15;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.proof .sub{font-size:12px;color:var(--ink2)}
section.block{padding:36px 0;border-bottom:1px solid var(--line)}
.block-head{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:18px;flex-wrap:wrap}
.block-head h2{font-size:24px}.block-head .meta{font-size:13px;color:var(--muted)}
.two-col{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,1fr);gap:28px;align-items:start}
.funnel{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--panel);margin-bottom:18px}
.funnel div{padding:10px 12px;border-left:1px solid var(--line)}.funnel div:first-child{border-left:0}
.funnel .k{font-size:11px;color:var(--muted);letter-spacing:.04em;text-transform:uppercase}
.funnel .v{font-family:"IBM Plex Mono",monospace;font-size:20px}
.ledger-wrap{overflow-x:auto}
.ledger{width:100%;border-collapse:collapse;font-size:14px;min-width:640px}
.ledger th{text-align:left;font-size:12px;letter-spacing:.04em;color:var(--muted);font-weight:600;padding:0 10px 10px;border-bottom:1px solid var(--line-strong)}
.ledger td{padding:12px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.ledger .r{text-align:right}.ledger .code{color:var(--muted);font-size:12px;margin-left:6px}.ledger .why{color:var(--ink2);font-size:13px;line-height:1.5}
.stage{display:inline-block;font-size:12px;font-weight:600;padding:3px 8px;border-radius:4px;white-space:nowrap}
.stage.ordered{background:var(--accent-soft);color:var(--accent-ink)}
.stage.rejected{background:var(--bg2);color:var(--ink2);border:1px solid var(--line)}
.stage.gate{background:var(--brass-soft);color:var(--brass)}
.debate{margin-top:18px;border:1px solid var(--line);border-radius:10px;background:var(--panel);padding:20px 22px;display:flex;flex-direction:column;gap:14px}
.debate h3{font-size:18px}
.debate-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 24px}
.quote{border-left:3px solid var(--line-strong);padding:2px 0 2px 16px}
.quote .who{font-size:12px;font-weight:700}
.quote p{margin:4px 0 0;font-family:"Noto Serif KR",serif;font-size:16px;line-height:1.6}
.quote.accent{border-left-color:var(--accent)}.quote.accent .who{color:var(--accent-ink)}
.quote.loss{border-left-color:var(--loss)}.quote.loss .who{color:var(--loss)}
.quote.ink{border-left-color:var(--ink)}.quote.ink .who{color:var(--ink)}
.quote.brass{border-left-color:var(--brass)}.quote.brass .who{color:var(--brass)}
.debate-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-top:12px;border-top:1px dashed var(--line-strong);font-size:13px;flex-wrap:wrap}
.record{border:1px solid var(--line);border-radius:10px;background:var(--panel);box-shadow:var(--shadow);padding:18px 20px;display:flex;flex-direction:column;gap:12px}
.record h3{font-size:17px}.record .sub{font-size:13px;color:var(--muted);margin:0}
.record dl{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px;margin:0}
.record dt{font-size:12px;color:var(--muted)}.record dd{margin:0;font-family:"IBM Plex Mono",monospace;font-size:20px;font-variant-numeric:tabular-nums}
.record dd small{font-size:12px;font-family:"IBM Plex Sans KR",sans-serif;color:var(--muted);margin-left:6px}
.record svg{display:block;width:100%;height:auto}
.record .rows{border-top:1px dashed var(--line-strong);padding-top:12px;display:flex;flex-direction:column;gap:6px;font-size:13px}
.record .row{display:flex;justify-content:space-between;gap:12px}
.prev{border-top:1px solid var(--line);padding-top:12px;display:flex;flex-direction:column;gap:8px;font-size:14px}
.prev a{text-decoration:none}
.process{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}
.step{padding:14px 16px;border-left:3px solid var(--line-strong)}.step:first-child{border-left-color:var(--accent)}
.step h3{font-family:"IBM Plex Sans KR",sans-serif;font-size:15px;font-weight:600;margin-bottom:4px}
.step p{margin:0;font-size:13px;color:var(--ink2)}
.rail{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}
.stock{display:block;text-decoration:none;color:var(--ink);padding:12px 14px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
.stock:hover{border-color:var(--accent)}
.stock .n{font-weight:600;font-size:14px}.stock .c{font-size:11px;color:var(--muted);margin-left:4px}
.stock .p{font-family:"IBM Plex Mono",monospace;font-size:15px;margin-top:6px;display:flex;justify-content:space-between;min-height:22px;font-variant-numeric:tabular-nums}
.trust{padding:22px 0 36px;font-size:13px;color:var(--ink2)}
.trust .shell{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.trust strong{display:block;color:var(--ink);margin-bottom:4px}
footer{border-top:1px solid var(--line);padding:18px 0 40px;font-size:12px;color:var(--muted)}
footer .shell{display:flex;flex-wrap:wrap;gap:8px 20px}
.empty{padding:18px;border:1px dashed var(--line-strong);border-radius:8px;color:var(--ink2);font-size:14px}
@media (max-width:960px){.hero .shell,.two-col{grid-template-columns:1fr}.nav{display:none}.process,.rail{grid-template-columns:repeat(2,1fr)}.trust .shell{grid-template-columns:1fr}.debate-grid{grid-template-columns:1fr}}
@media (max-width:560px){.proof{grid-template-columns:1fr}.proof>div{border-left:0;border-top:1px solid var(--line)}.proof>div:first-child{border-top:0}.process,.rail,.funnel{grid-template-columns:1fr 1fr}}
@media (prefers-reduced-motion:no-preference){.stock,.btn{transition:border-color .15s ease,background-color .15s ease}}
"""

HOME_JS = """
(function(){
  var KEY='ta-theme';
  var root=document.documentElement;
  function apply(name,persist){
    if(name==='system'){root.removeAttribute('data-theme');}else{root.setAttribute('data-theme',name);}
    var buttons=document.querySelectorAll('.theme-switch button');
    for(var i=0;i<buttons.length;i++){buttons[i].setAttribute('aria-pressed',buttons[i].getAttribute('data-theme')===name?'true':'false');}
    if(persist){try{localStorage.setItem(KEY,name);}catch(e){}}
  }
  var stored=null;try{stored=localStorage.getItem(KEY);}catch(e){}
  if(stored==='paper'||stored==='dark'||stored==='sepia'){apply(stored,false);}
  var switchEl=document.querySelector('.theme-switch');
  if(switchEl){switchEl.addEventListener('click',function(ev){var b=ev.target.closest('button');if(!b)return;apply(b.getAttribute('data-theme'),true);});}
  var rail=document.querySelector('[data-rail-tickers]');
  if(rail&&window.fetch){
    fetch('/api/prices/latest?tickers='+encodeURIComponent(rail.getAttribute('data-rail-tickers')),{credentials:'same-origin'})
      .then(function(r){return r.ok?r.json():null})
      .then(function(d){if(!d||!d.items)return;var items=d.items;Object.keys(items).forEach(function(code){var el=rail.querySelector('[data-code="'+code+'"] .p');if(!el)return;var q=items[code]||{};if(q.close==null)return;var chg=q.change_rate;var cls=chg>0?'up':(chg<0?'down':'');el.innerHTML='<span>'+Number(q.close).toLocaleString('ko-KR')+'</span><span class="'+cls+'">'+(chg==null?'':(chg>0?'+':'')+(chg*100).toFixed(2)+'%')+'</span>';});})
      .catch(function(){});
  }
})();
"""


def _render(model: dict[str, Any]) -> str:
    run = model["run"]
    outcomes = model["outcomes"]
    five, twenty = outcomes["five"], outcomes["twenty"]
    account = model["account"]

    def stage_class(stage: str) -> str:
        return STAGE_STYLE.get(stage, "rejected")

    ledger_rows = "\n".join(
        f"""<tr>
          <td class="mono">{_h(item.get('screener_rank') or index + 1)}</td>
          <td><a href="{_h(item.get('stock_path'))}"><strong>{_h(item.get('ticker_name') or item.get('ticker_code'))}</strong></a><span class="code">{_h(item.get('ticker_code'))} · {_h(item.get('market'))}</span></td>
          <td><span class="stage {stage_class(str(item.get('stage')))}">{_h(item.get('stage_label'))}{' ' + _h(item.get('quantity')) + '주' if item.get('stage') == 'ordered' and item.get('quantity') else ''}</span></td>
          <td class="r mono">{_h(_num(item.get('composite_score'), 2) if item.get('composite_score') is not None else '-')}</td>
          <td class="r mono {_sign_class(item.get('forecast_expected_return'))}">{_h(_pct(item.get('forecast_expected_return')))} <span class="muted">/ {_h(_pct(item.get('forecast_probability_up'), 0, signed=False))}</span></td>
          <td>{_h(item.get('confirmation_rating') or '-')}{' <span class="mono">' + _h(_num(item.get('confirmation_confidence'), 2)) + '</span>' if item.get('confirmation_confidence') is not None else ''}</td>
          <td class="why">{_h('; '.join(str(reason) for reason in (item.get('reasons') or [])[:2]))}</td>
        </tr>"""
        for index, item in enumerate(model["decisions"][:8])
    )
    if not ledger_rows:
        ledger_rows = '<tr><td colspan="7" class="empty">아직 저장된 하네스 결정이 없습니다. 첫 실행 후 이곳에 후보별 단계와 근거가 실립니다.</td></tr>'

    funnel_html = "".join(f'<div><div class="k">{_h(step["label"])}</div><div class="v">{_h(_num(step["value"]))}</div></div>' for step in model["funnel"])

    debate_html = ""
    if model["debate"]:
        featured = model["featured"] or {}
        quotes = "".join(
            f'<div class="quote {_h(item["tone"])}"><div class="who">{_h(item["label"])}</div><p>“{_h(item["text"])}”</p></div>' for item in model["debate"]
        )
        confirmation = ((featured.get("detail") or {}).get("confirmation") or {})
        weight = confirmation.get("position_weight")
        debate_html = f"""
        <div class="debate">
          <div class="block-head" style="margin:0">
            <h3>토론 기록 — {_h(featured.get('ticker_name') or featured.get('ticker_code'))}는 이렇게 결정됐다</h3>
            <span class="meta mono">bull → bear → judge → risk → PM</span>
          </div>
          <div class="debate-grid">{quotes}</div>
          <div class="debate-foot">
            <span>포트폴리오 매니저: <strong>{_h(featured.get('confirmation_rating') or '-')} · 확신 {_h(_num(featured.get('confirmation_confidence'), 2))}{' · 비중 ' + _h(_pct(weight, 0, signed=False)) if weight is not None else ''}</strong></span>
            <a href="{_h((run or {}).get('detail_path') or '/harness')}">토론 전문과 근거 데이터 →</a>
          </div>
        </div>"""

    bars = outcomes["alpha_bars"]
    chart_html = ""
    if bars:
        max_abs = max(abs(value) for value in bars) or 0.01
        rects = []
        for index, value in enumerate(bars):
            height = min(48.0, abs(value) / max_abs * 48.0)
            x = 8 + index * 10
            if value >= 0:
                rects.append(f'<rect x="{x}" y="{64 - height:.1f}" width="7" height="{height:.1f}" fill="var(--gain)"></rect>')
            else:
                rects.append(f'<rect x="{x}" y="64" width="7" height="{height:.1f}" fill="var(--loss)"></rect>')
        chart_html = f"""<svg viewBox="0 0 320 110" role="img" aria-label="최근 {len(bars)}건의 20일 알파">
          <line x1="8" y1="64" x2="312" y2="64" stroke="var(--line-strong)" stroke-width="1"></line>
          <text x="8" y="12" font-size="10" fill="var(--muted)" font-family="IBM Plex Mono, monospace">20일 알파 · 최근 {len(bars)}건</text>
          {''.join(rects)}
        </svg>"""
    else:
        chart_html = '<p class="sub">20일 성과가 확정되면 초과수익 막대가 여기에 쌓입니다.</p>'

    def hit(bucket: Mapping[str, Any]) -> str:
        completed = int(bucket.get("completed") or 0)
        rate = bucket.get("hit_rate")
        if not completed or rate is None:
            pending = int(bucket.get("pending") or 0)
            return f'<span class="muted">대기 {pending}건</span>' if pending else "-"
        wins = round(float(rate) * completed)
        return f"{_h(_pct(rate, 0, signed=False))}<small>{wins}/{completed}</small>"

    def alpha(bucket: Mapping[str, Any]) -> str:
        value = bucket.get("average_alpha")
        return f'<span class="{_sign_class(value)}">{_h(_pct(value))}</span>' if value is not None else "-"

    account_html = ""
    if account:
        change = account.get("change")
        account_html = f"""<div class="rows">
          <div class="row"><span>모의투자 계좌 ({_h(str(account.get('broker') or '').upper())})</span><span class="mono">{_h(_num(account['cash_after']))}원</span></div>
          <div class="row"><span>이번 실행 현금 변화</span><span class="mono {_sign_class(change)}">{_h(_pct(change, 2))}</span></div>
          <div class="row"><span>실계좌 주문</span><span>없음 · 사이트에서 불가</span></div>
        </div>"""

    prev_html = "".join(
        f'<div><a href="{_h(item.get("detail_path"))}"><span class="serif" style="font-weight:700">{_h(_korean_date(item.get("as_of_date")))}</span></a> — 후보 {_h(item.get("candidate_count"))} · 가상주문 {_h(item.get("order_count"))} <span class="mono muted">{"dry-run" if item.get("dry_run") else _h(item.get("broker"))}</span></div>'
        for item in model["previous_runs"]
    )
    prev_block = f'<div class="prev"><div class="issue">지난 호</div>{prev_html}</div>' if prev_html else ""

    rail_codes = ",".join(item["code"] for item in model["rail"])
    rail_html = "".join(
        f'<a class="stock" href="{_h(item["path"])}" data-code="{_h(item["code"])}"><span class="n">{_h(item["name"])}</span><span class="c">{_h(item["code"])}</span><div class="p"><span class="muted">가격 불러오는 중</span></div></a>'
        for item in model["rail"]
    )

    theme_buttons = "".join(
        f'<button type="button" class="{name}" data-theme="{name}" aria-pressed="false" aria-label="{_h(THEME_LABELS[name])} 테마" title="{_h(THEME_LABELS[name])}"></button>'
        for name in THEMES
    )

    run_meta = ""
    if run:
        run_meta = f"{'토론 확인기' if run.get('confirmer') == 'debate' else _h(run.get('confirmer'))} · {'KIS 모의투자' if run.get('broker') == 'kis' else '로컬 가상계좌'}{' · dry-run' if run.get('dry_run') else ''} · <a href=\"{_h(run.get('detail_path'))}\">실행 상세와 감사 원장</a>"

    title_date = model["run_date_text"] or "오늘"
    proof_completed = outcomes["completed_total"]
    teaser = model.get("teaser")
    teaser_html = ""
    if teaser:
        teaser_html = (
            f'<p class="teaser"><strong>오늘 {_h(_korean_date(teaser["as_of_date"]))} 실행 완료</strong> — 후보 {_h(teaser["candidate_count"])}개 중 {_h(teaser["order_count"])}개 통과. '
            f'종목과 토론 전문은 <a href="/pricing">데일리 패스</a>에서 즉시, 무료 플랜은 다음 거래일에 열립니다.</p>'
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TradingAgents Korea — 오늘 고른 종목과 지난 선택의 성적표</title>
<meta name="description" content="KOSPI·KOSDAQ 상위 종목을 규칙으로 거르고 AI 토론으로 확인한 뒤 모의투자로 검증합니다. 모든 선택은 5·20거래일 뒤 지수 대비 수익률로 채점됩니다.">
<link rel="canonical" href="{_h(model['canonical'])}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700&family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<script>(function(){{try{{var t=localStorage.getItem('ta-theme');if(t==='paper'||t==='dark'||t==='sepia'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
<style>{HOME_CSS}</style>
</head>
<body class="public-home">
<a class="skip-link" href="#main-content">본문 바로가기</a>
<header class="masthead">
  <div class="shell">
    <a class="brand" href="/"><span class="brand-name">TradingAgents Korea</span><span class="brand-sub">한국 주식 AI 리서치 데일리</span></a>
    <nav class="nav" aria-label="주요 메뉴">
      <a href="/" aria-current="page">오늘</a>
      <a href="/harness">일일 하네스</a>
      <a href="/outcomes">검증 성과</a>
      <a href="/analyses">AI 리포트</a>
      <a href="/features/methodology">분석 기준</a>
    </nav>
    <div class="mast-right">
      <div class="theme-switch" role="group" aria-label="페이지 테마">{theme_buttons}</div>
      <a class="btn" href="/member">로그인</a>
      <a class="btn primary" href="/member?mode=signup">내 공간 만들기</a>
    </div>
  </div>
</header>
<div class="tape" aria-label="실행 요약">
  <div class="shell">
    <span class="date">{_h(model['now_text'])}</span>
    {f'<span>최근 실행 <span class="mono">{_h(title_date)}</span></span>' if run else ''}
    {f'<span>스크리닝 <span class="mono">{_h(_num(run.get("universe_size")))} → 후보 {_h(_num(run.get("candidate_count")))}</span></span>' if run else ''}
    <span>다음 실행 07:50 · 10:05 · 16:40 KST</span>
  </div>
</div>
<main id="main-content">
<section class="hero">
  <div class="shell">
    <div>
      <div class="issue">제 {_h(model['issue_number'])}호 · 매일 아침, 규칙과 AI 토론으로 고른 종목과 그 결과까지</div>
      <h1>{_h(model['headline'])}</h1>
      <p class="deck">{_h(model['deck'])}</p>
      {teaser_html}
      <form class="search" action="/stocks" method="get" role="search">
        <label class="skip-link" for="home-ticker">종목코드 또는 종목명</label>
        <input id="home-ticker" name="ticker" placeholder="종목명 또는 6자리 코드 — 예: 삼성전자, 005930" autocomplete="off" required>
        <button type="submit">분석실 열기</button>
      </form>
    </div>
    <div class="proof" aria-label="누적 성과 요약">
      <div><div class="label">5일 승률</div><div class="value">{hit(five)}</div><div class="sub">지수 대비 초과수익 기준</div></div>
      <div><div class="label">20일 평균 알파</div><div class="value">{alpha(twenty)}</div><div class="sub">확정 {_h(twenty.get('completed') or 0)}건</div></div>
      <div><div class="label">채점 완료</div><div class="value mono">{_h(proof_completed)}</div><div class="sub">5일·20일 결과 합계</div></div>
    </div>
  </div>
</section>

<section class="block" aria-labelledby="today-title">
  <div class="shell">
    <div class="block-head">
      <h2 id="today-title">{'오늘의 하네스 — ' + _h(title_date) + ' 실행' if run else '오늘의 하네스'}</h2>
      <p class="meta">{run_meta}</p>
    </div>
    <div class="two-col">
      <div>
        {f'<div class="funnel" aria-label="선정 깔때기">{funnel_html}</div>' if funnel_html else ''}
        <div class="ledger-wrap">
          <table class="ledger">
            <thead><tr><th>#</th><th>종목</th><th>단계</th><th class="r">요인</th><th class="r">20일 예측 / 상승확률</th><th>AI 토론</th><th>근거</th></tr></thead>
            <tbody>{ledger_rows}</tbody>
          </table>
        </div>
        {debate_html}
      </div>
      <aside class="record" aria-label="검증 성과">
        <h3>선택은 채점됩니다</h3>
        <p class="sub">모든 가상 주문은 5·20거래일 뒤 지수 대비 초과수익으로 확정됩니다.</p>
        <dl>
          <dt>5일 승률</dt><dd>{hit(five)}</dd>
          <dt>20일 승률</dt><dd>{hit(twenty)}</dd>
          <dt>5일 평균 알파</dt><dd>{alpha(five)}</dd>
          <dt>20일 평균 알파</dt><dd>{alpha(twenty)}</dd>
        </dl>
        {chart_html}
        {account_html}
        {prev_block}
      </aside>
    </div>
  </div>
</section>

<section class="block" aria-labelledby="how-title">
  <div class="shell">
    <div class="block-head"><h2 id="how-title">한 종목이 여기까지 오는 다섯 단계</h2><p class="meta">각 단계는 감사 원장에 해시로 묶여 기록됩니다 · <a href="/features/methodology">분석 기준 전문</a></p></div>
    <div class="process">
      <div class="step"><h3>스크리닝</h3><p>시가총액 상위 300종목을 모멘텀·추세·RSI·거래량·변동성 점수로 정렬합니다.</p></div>
      <div class="step"><h3>확률 예측</h3><p>20거래일 가격 밴드와 상승 확률을 계산해 기대수익 2%·확률 55% 미만이면 멈춥니다.</p></div>
      <div class="step"><h3>AI 토론</h3><p>강세·약세 연구원이 근거로 다투고, 판정관과 리스크 패널이 등급과 손절·익절을 정합니다.</p></div>
      <div class="step"><h3>수량과 한도</h3><p>거래당 계좌의 1%만 잃도록 수량을 계산하고, 종목 20%·총노출·일손실 한도를 검사합니다.</p></div>
      <div class="step"><h3>가상 주문과 채점</h3><p>KIS 모의투자에 지정가로 넣고, 5·20거래일 뒤 지수 대비 성과를 공개합니다.</p></div>
    </div>
  </div>
</section>

<section class="block" aria-labelledby="rail-title">
  <div class="shell">
    <div class="block-head"><h2 id="rail-title">종목 분석실</h2><p class="meta">차트·공시·뉴스·AI 토론·가상매매 기록을 한 화면에서 봅니다.</p></div>
    <div class="rail" data-rail-tickers="{_h(rail_codes)}">{rail_html}</div>
  </div>
</section>

<section class="trust" aria-label="운영 원칙">
  <div class="shell">
    <div><strong>실계좌 주문은 이 사이트에서 일어나지 않습니다.</strong>공개 페이지와 API는 조회 전용이며, 모의투자 주문은 운영자 파이프라인에서만 실행됩니다.</div>
    <div><strong>모든 숫자는 출처와 시각을 답니다.</strong>pykrx·Naver·DART·KIS 중 어느 데이터인지, 언제 값인지, 대체 데이터를 썼는지 표시합니다.</div>
    <div><strong>AI 의견은 연구 자료입니다.</strong>투자 판단과 책임은 이용자에게 있으며, 수익을 보장하지 않습니다.</div>
  </div>
</section>
</main>
<footer>
  <div class="shell">
    <span>© 2026 TradingAgents Korea</span>
    <a href="/features/methodology">분석 기준</a><a href="/disclaimer">면책</a><a href="/privacy">개인정보</a><a href="/terms">약관</a>
    <span>데이터: pykrx · Naver 금융 · DART · KIS Open API</span>
  </div>
</footer>
<script>{HOME_JS}</script>
</body>
</html>"""
