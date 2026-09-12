"""Evidence-first public home page (design direction "A+D").

The page is a daily report front page: a numbered issue headline that states
today's harness conclusion, the decision ledger, the debate transcript
excerpts (bull / bear / judge / risk panel), the scored track record, and the
paper account. Everything is read from what the backend already stores; the
page never triggers analysis, orders, or vendor calls in the request path.
Prices for the stock rail are fetched by the browser from ``/api/prices/latest``
after load so the HTML itself renders in one database round trip.

Layout and themes come from ``design_system`` (slate light default, IDE-style
selectable themes stored under ``ta-theme``). Sparklines are fetched by the
browser from ``/api/prices/sparkline`` after load.
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


ROLE_LABELS = {
    "bull": ("강세 의견", "accent"),
    "bear": ("약세 의견", "loss"),
    "judge": ("판정", "ink"),
    "risk_panel": ("리스크 점검", "brass"),
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
_source_cache: dict[int, tuple[float, tuple[Any, Any, Any], Any]] = {}


def _load_sources(repo: StorageRepository | None) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """Four database round trips, memoised per process for a minute.

    Serverless instances stay warm between requests and the CDN caches the
    rendered page, so a short in-process cache removes most origin latency
    (each Supabase query costs a cross-region round trip).
    """

    import time

    if repo is None:
        return None, {"items": [], "item_count": 0}, {"summary": {}, "items": []}
    import weakref

    key = id(repo)
    cached = _source_cache.get(key)
    # id() can be recycled after a repo is garbage collected; the weakref guards against a stale hit
    if cached and time.monotonic() - cached[0] < SOURCE_CACHE_SECONDS and cached[2]() is repo:
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
    _source_cache[key] = (time.monotonic(), (latest, runs, outcomes), weakref.ref(repo))
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
        {"label": "대상 종목", "value": universe},
        {"label": "후보", "value": candidates},
        {"label": "AI 토론 통과", "value": confirmed},
        {"label": "모의 주문", "value": orders},
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
            "첫 종목 선별을 기다리고 있습니다",
            "평일 아침 07:50에 코스피200·코스닥150 종목을 거르고 10:05에 AI 토론으로 확인한 결과가 여기에 실립니다.",
        )
    total = len(decisions)
    ordered = [item for item in decisions if item.get("stage") in {"ordered", "exit"}]
    if not ordered:
        return (
            f"{total}개 후보를 살폈지만 오늘은 한 종목도 통과하지 못했다",
            "예상 수익률이 기준에 못 미쳤거나 토론에서 약세 의견이 이겼습니다. 사지 않은 이유도 아래 표에 남깁니다.",
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
    deck = rationale[:180] + ("…" if len(rationale) > 180 else "") if rationale else "강세·약세 의견이 맞선 토론과 리스크 점검을 거친 결과입니다."
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
# template (v3 slate system; see design_system.py)
# --------------------------------------------------------------------------

from .design_system import THEMES as DS_THEMES  # noqa: E402
from .design_system import THEME_LABELS as DS_THEME_LABELS  # noqa: E402
from .design_system import badge, icon, icon_tile, rating_label, render_shell, sparkline_svg, stat_tile  # noqa: E402
from .plain_korean import market_label, reason_text  # noqa: E402

THEMES = DS_THEMES
THEME_LABELS = DS_THEME_LABELS

STAGE_TONE = {
    "ordered": ("b-teal", "check"),
    "exit": ("b-orange", "logout"),
    "sized": ("b-blue", "target"),
    "gate_rejected": ("b-amber", "shield"),
    "forecast_rejected": ("b-grey", "trend"),
    "confirmation_rejected": ("b-grey", "brain"),
    "screened": ("b-grey", "filter"),
}

ROLE_TONE = {"bull": ("b-gain", "강"), "bear": ("b-loss", "약"), "judge": ("b-violet", "판"), "risk_panel": ("b-amber", "리")}

HOME_CSS = """
.home-hero { padding: 28px 0 22px; }
.home-hero .shell { display: grid; grid-template-columns: minmax(0, 1fr) 520px; gap: 28px; align-items: center; }
.home-hero h1 { font-size: 32px; margin-top: 12px; }
.home-hero h1 em { font-style: normal; color: var(--accent); }
.home-hero .deck { margin-top: 10px; max-width: 560px; font-size: 15px; color: var(--ink2); }
.home-hero .actions { display: flex; gap: 10px; margin-top: 18px; flex-wrap: wrap; }
.funnel-bar { display: flex; gap: 3px; }
.funnel-bar > div { height: 10px; }
.funnel-labels { display: flex; margin-top: 10px; }
.funnel-labels p.v { font-weight: 700; font-size: 18px; letter-spacing: -0.02em; }
.picks td.spark { width: 120px; }
.picks .why { font-size: 12px; color: var(--ink2); margin-top: 3px; max-width: 260px; }
.picks .empty { padding: 28px 18px; color: var(--muted); text-align: center; }
.quotes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.quotes .card { padding: 14px 16px; }
.quotes p.text { margin-top: 8px; font-size: 13px; color: var(--ink2); }
.steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.steps .soft { padding: 14px; }
.steps p.t { font-weight: 700; margin-top: 10px; }
.steps p.d { font-size: 13px; color: var(--ink2); margin-top: 3px; }
.alpha-bars { display: flex; gap: 4px; align-items: flex-end; height: 44px; margin-top: 14px; }
.alpha-bars > div { flex: 1; border-radius: 3px 3px 0 0; min-height: 3px; }
.market .kv .spark-wrap { display: inline-flex; align-items: center; gap: 10px; }
.teaser-card { margin-top: 0; }
@media (max-width: 960px) {
  .home-hero .shell { grid-template-columns: 1fr; }
  .steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .quotes { grid-template-columns: 1fr; }
  .home-hero h1 { font-size: 26px; }
}
"""

# Supabase auth links (magic link, signup confirmation, recovery) may land on the site root; the member page owns session handling.
AUTH_FORWARD_SCRIPT = "<script>(function(){var h=location.hash||'';if(h.indexOf('access_token=')>=0||h.indexOf('type=recovery')>=0||h.indexOf('error_description=')>=0){location.replace('/member'+h);}})();</script>"

HOME_JS = r"""
(function(){
  function fmtNum(v){ return Number(v).toLocaleString('ko-KR'); }
  function spark(closes, w, h, color, area){
    if(!closes || closes.length < 2) return '';
    var lo = Math.min.apply(null, closes), hi = Math.max.apply(null, closes), span = (hi - lo) || 1, n = closes.length;
    var pts = closes.map(function(y, i){ return [ (i/(n-1))*(w-2)+1, h-2-((y-lo)/span)*(h-4) ]; });
    var line = pts.map(function(p){ return p[0].toFixed(1)+','+p[1].toFixed(1); }).join(' ');
    var fill = area ? '<path d="M'+pts[0][0].toFixed(1)+','+h+' L'+pts.map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' L')+' L'+pts[n-1][0].toFixed(1)+','+h+' Z" fill="'+color+'" opacity="0.12"/>' : '';
    var last = pts[n-1];
    return '<svg width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'" aria-hidden="true">'+fill+'<polyline points="'+line+'" fill="none" stroke="'+color+'" stroke-width="1.6" stroke-linejoin="round"/><circle cx="'+last[0].toFixed(1)+'" cy="'+last[1].toFixed(1)+'" r="2.2" fill="'+color+'"/></svg>';
  }
  function colorFor(closes){ return closes[closes.length-1] >= closes[0] ? 'var(--gain)' : 'var(--loss)'; }

  // 60-day sparklines for the picks table and the market widget
  var targets = Array.prototype.slice.call(document.querySelectorAll('[data-spark]'));
  var codes = targets.map(function(n){ return n.getAttribute('data-spark'); }).filter(function(c, i, a){ return c && a.indexOf(c) === i; });
  if (codes.length) {
    fetch('/api/prices/sparkline?tickers=' + encodeURIComponent(codes.join(',')) + '&days=60').then(function(r){ return r.ok ? r.json() : null; }).then(function(d){
      if(!d || !d.series) return;
      targets.forEach(function(node){
        var s = d.series[node.getAttribute('data-spark')];
        if(!s || !s.closes || s.closes.length < 2) { node.innerHTML = '<span class="tiny muted">차트 없음</span>'; return; }
        var w = parseInt(node.getAttribute('data-w') || '104', 10), h = parseInt(node.getAttribute('data-h') || '32', 10);
        node.innerHTML = spark(s.closes, w, h, colorFor(s.closes), node.getAttribute('data-area') !== 'no');
        var chg = node.parentElement && node.parentElement.querySelector('[data-spark-change]');
        if (chg) { var c = s.closes, p = (c[c.length-1]/c[0]-1)*100; chg.textContent = (p>=0?'+':'') + p.toFixed(1) + '%'; chg.className = 'num ' + (p>=0?'up':'down'); }
      });
    }).catch(function(){});
  }

  // latest prices for the market widget
  var rail = document.querySelector('[data-rail-tickers]');
  if (rail) {
    fetch('/api/prices/latest?tickers=' + encodeURIComponent(rail.getAttribute('data-rail-tickers'))).then(function(r){ return r.ok ? r.json() : null; }).then(function(d){
      if(!d || !d.prices) return;
      rail.querySelectorAll('[data-code]').forEach(function(node){
        var p = d.prices[node.getAttribute('data-code')];
        var price = node.querySelector('[data-price]');
        if (p && price) { price.textContent = fmtNum(p.close); price.title = (p.date || '') + ' ' + (p.vendor || ''); }
      });
    }).catch(function(){});
  }
})();
"""


def _stage_badge(item: Mapping[str, Any]) -> str:
    stage = str(item.get("stage") or "")
    tone, ic = STAGE_TONE.get(stage, ("b-grey", "filter"))
    label = str(item.get("stage_label") or stage or "-")
    if stage == "ordered" and item.get("quantity"):
        label = f"{label} {item.get('quantity')}주"
    return badge(label, tone, icon_name=ic)


def _pick_row(index: int, item: Mapping[str, Any]) -> str:
    code = str(item.get("ticker_code") or "")
    name = str(item.get("ticker_name") or code)
    market = market_label(item.get("market"), code)
    market_tone = "b-orange" if market.upper() == "KOSDAQ" else "b-navy"
    score = item.get("composite_score")
    score_width = 0
    try:
        score_width = max(0, min(100, int(float(score) / 2.5 * 100))) if score is not None else 0
    except (TypeError, ValueError):
        score_width = 0
    prob = item.get("forecast_probability_up")
    prob_pct = 0
    try:
        prob_pct = max(0, min(100, int(float(prob) * 100))) if prob is not None else 0
    except (TypeError, ValueError):
        prob_pct = 0
    reasons = reason_text(item.get("reasons"), limit=2)
    rating = item.get("confirmation_rating")
    confidence = item.get("confirmation_confidence")
    price = item.get("entry_price")
    return f"""<tr>
      <td class="muted num tiny">{_h(item.get('screener_rank') or index + 1)}</td>
      <td><div class="row" style="gap: 10px; align-items: flex-start;"><span class="avatar {market_tone}">{_h(name[:2])}</span><div><a href="{_h(item.get('stock_path') or '#')}"><b style="font-weight: 700;">{_h(name)}</b></a> <span class="muted tiny num">{_h(code)}</span> {badge(market, market_tone, xs=True) if market else ''}<div class="why">{_h(reasons)}</div></div></div></td>
      <td class="spark"><span data-spark="{_h(code)}" data-w="104" data-h="32"><span class="tiny muted">불러오는 중</span></span></td>
      <td><div class="num" style="font-weight: 600;">{_h(_num(score, 2)) if score is not None else '-'}</div><div class="bar" style="width: 60px; margin-top: 5px;"><i style="width: {score_width}%; background: var(--blue);"></i></div></td>
      <td><div class="num"><span class="{_sign_class(item.get('forecast_expected_return'))}" style="font-weight: 700;">{_h(_pct(item.get('forecast_expected_return')))}</span> <span class="muted tiny">/ {_h(_pct(prob, 0, signed=False))}</span></div><div class="bar" style="width: 60px; margin-top: 5px;"><i style="width: {prob_pct}%; background: var(--violet);"></i></div></td>
      <td>{badge(rating_label(rating), 'b-violet') if rating else '<span class="muted">-</span>'}<div class="tiny muted num" style="margin-top: 4px;">{'신뢰도 ' + _h(_num(confidence, 2)) if confidence is not None else ''}</div></td>
      <td>{_stage_badge(item)}<div class="tiny muted num" style="margin-top: 4px;">{'기준가 ' + _h(_num(price)) + '원' if price else ''}</div></td>
    </tr>"""


def _funnel_html(steps: list[Mapping[str, Any]]) -> str:
    if not steps:
        return ""
    colors = ["var(--line-strong)", "var(--blue)", "var(--violet)", "var(--amber)", "var(--accent)"]
    widths = [40, 24, 18, 18] if len(steps) == 4 else [40, 20, 14, 13, 13]
    bars, labels = [], []
    for index, step in enumerate(steps):
        color = colors[index % len(colors)]
        width = widths[index] if index < len(widths) else 10
        radius = "999px 0 0 999px" if index == 0 else ("0 999px 999px 0" if index == len(steps) - 1 else "0")
        bars.append(f'<div style="width: {width}%; background: {color}; border-radius: {radius};"></div>')
        labels.append(f'<div style="width: {width}%;"><p class="v num" style="color: {color};">{_h(_num(step["value"]))}</p><p class="tiny muted">{_h(step["label"])}</p></div>')
    return f'<div class="funnel-bar">{"".join(bars)}</div><div class="funnel-labels">{"".join(labels)}</div>'


def _render(model: dict[str, Any]) -> str:
    run = model["run"]
    outcomes = model["outcomes"]
    five, twenty = outcomes["five"], outcomes["twenty"]
    account = model["account"]
    decisions = model["decisions"]
    ordered = [item for item in decisions if item.get("stage") in {"ordered", "exit"}]
    title_date = model["run_date_text"] or "오늘"
    teaser = model.get("teaser")

    def hit(bucket: Mapping[str, Any]) -> tuple[str, str]:
        completed = int(bucket.get("completed") or 0)
        rate = bucket.get("hit_rate")
        if not completed or rate is None:
            pending = int(bucket.get("pending") or 0)
            return "–", (f"대기 {pending}건" if pending else "확정 후 표시")
        wins = round(float(rate) * completed)
        return _pct(rate, 0, signed=False), f"{wins}/{completed} 적중"

    def alpha(bucket: Mapping[str, Any]) -> tuple[str, str]:
        value = bucket.get("average_alpha")
        completed = int(bucket.get("completed") or 0)
        if value is None:
            return "–", f"확정 {completed}건"
        return f'<span class="{_sign_class(value)}">{_h(_pct(value))}</span>', f"확정 {completed}건"

    five_hit, five_sub = hit(five)
    twenty_alpha, twenty_sub = alpha(twenty)
    pending_total = int(five.get("pending") or 0) + int(twenty.get("pending") or 0)

    # hero -------------------------------------------------------------------
    if run:
        chips = badge(f"{title_date} 선별", "b-teal") + " " + badge("다음 07:50 · 10:05 · 16:40", "b-grey", icon_name="clock")
        headline = _h(model["headline"])
        if ordered:
            headline = headline.replace(f"{len(ordered)}개가 통과", f"<em>{len(ordered)}개</em>가 통과", 1)
    else:
        chips = badge("첫 실행 대기", "b-grey", icon_name="clock")
        headline = _h(model["headline"])
    hero_actions = (
        f'<a class="btn primary" href="{_h((run or {}).get("detail_path") or "/harness")}">{icon("layers", 16)}선별 기록 보기</a>'
        f'<a class="btn" href="/outcomes">{icon("target", 16)}성과 검증</a>'
        f'<a class="btn ghost" href="/features/methodology">분석 기준 →</a>'
    )
    tiles = "".join(
        [
            stat_tile("layers", "b-navy", "대상 종목", _num((run or {}).get("universe_size")) if run else "–", "코스피200 · 코스닥150"),
            stat_tile("check", "b-teal", "통과 · 모의 주문", str(len(ordered)) if run else "–", f"{len(decisions)}개 후보 중" if run else "선별 전"),
            stat_tile("clock", "b-amber", "검증 대기", f"{pending_total}건" if pending_total else "–", "5·20거래일 뒤 확정"),
            stat_tile("target", "b-violet", "5일 승률", five_hit, five_sub),
        ]
    )

    # teaser (today's locked run) --------------------------------------------
    teaser_html = ""
    if teaser:
        teaser_html = f"""<div class="card grad" style="padding: 18px 20px;">
      <div class="row between"><span class="badge" style="background: rgba(255,255,255,.16); color: #fff;">{icon("lock", 12)}오늘 {_h(_korean_date(teaser["as_of_date"]))}</span><span class="tiny muted">실행 완료</span></div>
      <p style="font-size: 17px; font-weight: 700; margin-top: 10px; letter-spacing: -0.01em;">후보 {_h(teaser["candidate_count"])}개 중 {_h(teaser["order_count"])}개 통과</p>
      <p class="small muted" style="margin-top: 4px;">종목과 토론 전문은 데일리 패스에서 바로 볼 수 있습니다. 무료 플랜은 다음 거래일 아침에 공개됩니다.</p>
      <div class="row" style="gap: 8px; margin-top: 14px;"><a class="btn sm" style="background: #fff; color: #115e59; border-color: #fff;" href="/pricing">월 10,000원</a><a class="btn sm" style="background: transparent; color: #fff; border-color: rgba(255,255,255,.4); box-shadow: none;" href="/member?mode=signup&amp;plan=daily">14일 무료 체험</a></div>
    </div>"""

    # picks table ---------------------------------------------------------------
    rows = "\n".join(_pick_row(index, item) for index, item in enumerate(decisions[:8]))
    if not rows:
        rows = '<tr><td colspan="7" class="empty">아직 저장된 선별 결과가 없습니다. 첫 실행 후 이곳에 후보별 단계와 근거가 실립니다.</td></tr>'
    run_meta = ""
    if run:
        run_meta = f"{'토론 확인기' if run.get('confirmer') == 'debate' else _h(run.get('confirmer'))} · {'KIS 모의투자' if run.get('broker') == 'kis' else '로컬 모의투자 계좌'}{' · 기록만 (체결 없음)' if run.get('dry_run') else ''}"

    # debate excerpts ----------------------------------------------------------
    debate_html = ""
    if model["debate"]:
        featured = model["featured"] or {}
        confirmation = ((featured.get("detail") or {}).get("confirmation") or {})
        weight = confirmation.get("position_weight")
        quotes = "".join(
            f'<div class="card"><div class="row" style="gap: 10px;"><span class="avatar {ROLE_TONE.get(item["role"], ("b-grey", "·"))[0]}">{ROLE_TONE.get(item["role"], ("b-grey", "·"))[1]}</span><p style="font-weight: 700; font-size: 13px;">{_h(item["label"])}</p></div><p class="text">“{_h(item["text"])}”</p></div>'
            for item in model["debate"]
        )
        gate = model.get("plan_gate") or {}
        lock = badge("전문은 데일리 패스", "b-amber", icon_name="lock") if gate.get("debate_transcript") is False else ""
        debate_html = f"""<div class="card">
      <div class="card-h"><h2>{icon_tile("brain", "b-violet", small=True)}{_h(featured.get('ticker_name') or featured.get('ticker_code'))}, 이렇게 결정됐습니다</h2>{lock}</div>
      <div class="card-b"><div class="quotes">{quotes}</div></div>
      <div class="card-f"><span>포트폴리오 매니저: <b style="color: var(--ink);">{_h(rating_label(featured.get('confirmation_rating')) or '-')} · 확신 {_h(_num(featured.get('confirmation_confidence'), 2))}{' · 비중 ' + _h(_pct(weight, 0, signed=False)) if weight is not None else ''}</b></span><a class="link" href="{_h((run or {}).get('detail_path') or '/harness')}">토론 전문 보기 →</a></div>
    </div>"""

    # sidebar: account ----------------------------------------------------------
    account_html = ""
    if account:
        change = account.get("change")
        account_html = f"""<div class="card">
      <div class="card-h"><h2>{icon_tile("wallet", "b-teal", small=True)}모의투자 계좌</h2>{badge("KIS 모의투자" if account.get("broker") == "kis" else str(account.get("broker") or "가상"), "b-grey")}</div>
      <div class="card-b">
        <div class="row between" style="align-items: flex-end;"><div><p class="label">현금</p><p class="num" style="font-size: 24px; font-weight: 700; letter-spacing: -0.02em;">{_h(_num(account['cash_after']))}<span class="muted" style="font-size: 13px; font-weight: 500;">원</span></p></div>{badge(_pct(change, 2), 'b-gain' if (change or 0) >= 0 else 'b-loss')}</div>
        <p class="tiny muted" style="margin-top: 8px;">선별 전 {_h(_num(account['cash_before']))}원 · 실계좌 주문 없음</p>
      </div>
    </div>"""

    # sidebar: outcomes ---------------------------------------------------------
    bars = outcomes["alpha_bars"]
    if bars:
        max_abs = max(abs(value) for value in bars) or 0.01
        bar_html = "".join(f'<div style="height: {max(6, abs(v) / max_abs * 100):.0f}%; background: var(--{"gain" if v >= 0 else "loss"});" title="{_h(_pct(v))}"></div>' for v in bars[:24])
        chart_html = f'<div class="alpha-bars" role="img" aria-label="최근 {len(bars)}건의 20일 초과수익">{bar_html}</div><p class="tiny muted" style="margin-top: 6px;">20일 초과수익 · 최근 {len(bars)}건</p>'
    else:
        chart_html = f'<div class="alpha-bars" aria-hidden="true">{"".join(f"<div style=\"height: {h}%; background: var(--line);\"></div>" for h in (30, 45, 25, 60, 40, 55, 35, 50))}</div><p class="tiny muted" style="margin-top: 6px;">20일 성과가 확정되면 초과수익 막대가 여기에 쌓입니다.</p>'
    outcomes_html = f"""<div class="card">
      <div class="card-h"><h2>{icon_tile("target", "b-violet", small=True)}성과 검증</h2><span class="tiny muted">지수 대비 초과수익</span></div>
      <div class="card-b">
        <div class="grid-2">
          <div class="soft" style="padding: 12px 14px;"><p class="label">5일 승률</p><p class="num" style="font-size: 22px; font-weight: 700;">{five_hit}</p><p class="tiny muted">{_h(five_sub)}</p></div>
          <div class="soft" style="padding: 12px 14px;"><p class="label">20일 평균 초과수익</p><p class="num" style="font-size: 22px; font-weight: 700;">{twenty_alpha}</p><p class="tiny muted">{_h(twenty_sub)}</p></div>
        </div>
        {chart_html}
      </div>
      <div class="card-f"><span>모든 모의 주문은 5거래일과 20거래일 뒤 성과를 확인합니다.</span><a class="link" href="/outcomes">전체 성과 →</a></div>
    </div>"""

    # sidebar: market widget ------------------------------------------------------
    rail_codes = ",".join(item["code"] for item in model["rail"])
    rail_rows = "".join(
        f'<div class="kv" data-code="{_h(item["code"])}"><span><a href="{_h(item["path"])}"><b style="font-weight: 700;">{_h(item["name"])}</b></a> <span class="tiny muted num" data-price>—</span></span><span class="spark-wrap"><span data-spark="{_h(item["code"])}" data-w="70" data-h="22" data-area="no"></span><span class="num muted" data-spark-change>·</span></span></div>'
        for item in model["rail"]
    )
    market_html = f"""<div class="card market">
      <div class="card-h"><h2>{icon_tile("trend", "b-blue", small=True)}종목 분석</h2><span class="tiny muted">{_h(model['now_text'])}</span></div>
      <div class="card-b" style="padding-top: 6px;" data-rail-tickers="{_h(rail_codes)}">{rail_rows}</div>
      <div class="card-f"><span>60일 주가 · 종가 기준</span><form action="/stocks" method="get" role="search" class="row"><input class="field" name="ticker" placeholder="종목명 또는 코드" aria-label="종목 검색" style="height: 30px; width: 150px; font-size: 12px;"><button class="btn sm primary" type="submit">분석실 열기</button></form></div>
    </div>"""

    # previous runs ------------------------------------------------------------
    prev_html = "".join(
        f'<div class="kv"><span><a href="{_h(item.get("detail_path"))}"><b style="font-weight: 600;">{_h(_korean_date(item.get("as_of_date")))}</b></a></span><span class="tiny muted num">후보 {_h(item.get("candidate_count"))} · 모의 주문 {_h(item.get("order_count"))} · {"기록만" if item.get("dry_run") else _h(item.get("broker"))}</span></div>'
        for item in model["previous_runs"]
    )
    prev_block = f'<div class="card"><div class="card-h"><h2>{icon_tile("clock", "b-grey", small=True)}지난 선별</h2><a class="link tiny" href="/harness">전체 →</a></div><div class="card-b" style="padding-top: 4px;">{prev_html}</div></div>' if prev_html else ""

    body = f"""
<section class="hero home-hero">
  <div class="shell">
    <div>
      <div class="row wrap">{chips}</div>
      <h1>{headline}</h1>
      <p class="deck">{_h(model['deck'])}</p>
      <div class="actions">{hero_actions}</div>
    </div>
    <div class="grid-2">{tiles}</div>
  </div>
</section>

<section class="block">
  <div class="shell">
    <div class="card" style="padding: 16px 18px;">
      <div class="row between wrap" style="margin-bottom: 10px;"><h2>{icon_tile("filter", "b-blue", small=True)}오늘의 선별 과정 · {_h(title_date)}</h2><span class="tiny muted">07:50 선별 → 10:05 모의 주문 · {run_meta}</span></div>
      {_funnel_html(model["funnel"]) or '<p class="muted small">첫 선별이 끝나면 대상 종목 → 후보 → 통과 → 모의 주문 수가 여기에 표시됩니다.</p>'}
    </div>
  </div>
</section>

<section class="block">
  <div class="shell grid-main">
    <div class="stack" style="gap: 20px;">
      <div class="card" style="overflow: hidden;">
        <div class="card-h"><h2>{icon_tile("trend", "b-teal", small=True)}선정 종목 {badge(str(len(decisions)), "b-grey")}</h2><div class="row"><a class="btn ghost sm" href="{_h((run or {}).get('detail_path') or '/harness')}">실행 기록 →</a></div></div>
        <div class="table-wrap">
          <table class="picks">
            <thead><tr><th>#</th><th>종목 · 근거</th><th>60일 주가</th><th>규칙 점수</th><th>20일 예상 / 상승 확률</th><th>AI 토론</th><th>결과</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        <div class="card-f"><span>차트: 60일 종가 · 규칙 점수: 추세·모멘텀·거래대금 합산 · 예상 수익률: TimesFM 20일 예측</span><span>가격 출처 pykrx · Naver</span></div>
      </div>
      {debate_html}
      <div class="card">
        <div class="card-h"><h2>{icon_tile("zap", "b-amber", small=True)}매일 아침 이렇게 고릅니다</h2><a class="link tiny" href="/features/methodology">분석 기준 전문 →</a></div>
        <div class="card-b steps">
          <div class="soft">{icon_tile("filter", "b-blue", small=True)}<p class="t">1 · 1차 선별</p><p class="d">코스피200과 코스닥150 종목을 추세·모멘텀·거래대금 규칙으로 거릅니다. ETF와 스팩은 제외합니다.</p></div>
          <div class="soft">{icon_tile("trend", "b-violet", small=True)}<p class="t">2 · 확률 예측</p><p class="d">20거래일 뒤 가격 범위와 상승 확률을 계산합니다. 예상 수익률 2%, 확률 55%에 못 미치면 멈춥니다.</p></div>
          <div class="soft">{icon_tile("brain", "b-amber", small=True)}<p class="t">3 · AI 토론</p><p class="d">강세와 약세 의견이 근거를 놓고 맞서고, 판정이 등급을, 리스크 점검이 손절·익절선을 정합니다.</p></div>
          <div class="soft">{icon_tile("check", "b-teal", small=True)}<p class="t">4 · 수량 · 모의 주문 · 성과 검증</p><p class="d">한 번의 거래에서 계좌의 1%만 잃도록 수량을 정하고, 모의투자 주문 뒤 5거래일·20거래일 성과를 공개합니다.</p></div>
        </div>
      </div>
    </div>
    <div class="stack">
      {teaser_html}
      {account_html}
      {outcomes_html}
      {market_html}
      {prev_block}
    </div>
  </div>
</section>
"""
    page_description = (
        f"{model['run_date_text']} 선별: 후보 {len(decisions)}개 중 {len(ordered)}개 통과. " if run else ""
    ) + "코스피200·코스닥150을 매일 아침 규칙으로 거르고 AI 토론으로 확인한 뒤 모의투자로 검증합니다. 모든 선택은 5·20거래일 뒤 지수 대비 수익률로 확인합니다."
    home_url = canonical_url("/", site_base_url=model["site_base_url"])
    structured = [{k: v for k, v in {
        "@type": "WebPage",
        "@id": home_url + "#webpage",
        "name": "오늘의 선정 종목 | TradingAgents Korea",
        "description": page_description,
        "inLanguage": "ko-KR",
        "isPartOf": {"@id": home_url + "#website"},
        "dateModified": str((run or {}).get("created_at") or (run or {}).get("as_of_date") or "")[:19] or None,
    }.items() if v is not None}]
    return render_shell(
        title="오늘의 선정 종목 | TradingAgents Korea",
        description=page_description,
        body=body,
        active="/",
        canonical_path="/",
        site_base_url=model["site_base_url"],
        extra_head=AUTH_FORWARD_SCRIPT,
        extra_css=HOME_CSS,
        extra_js=HOME_JS,
        body_class="public-home",
        structured_data=structured,
        og_image=canonical_url("/og/home.png", site_base_url=model["site_base_url"]),
    )
