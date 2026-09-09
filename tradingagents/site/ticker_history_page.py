"""`/stocks/{ticker}/history` — one question, one page: "이 종목은 AI 선별에서 어떻게 판정됐나?"

Direct answer first, then the decision history table, verification results,
AI reports for the ticker, and a FAQ (mirrored in FAQPage JSON-LD).
"""

from __future__ import annotations

from typing import Any

from tradingagents.storage import StorageRepository

from .design_system import badge, h, icon, icon_tile, render_shell, stat_tile
from .harness_api import build_harness_outcomes_payload, build_harness_ticker_history_payload
from .seo import canonical_url

STAGE_TONE = {
    "ordered": ("b-teal", "check"),
    "exit": ("b-orange", "logout"),
    "sized": ("b-blue", "target"),
    "gate_rejected": ("b-amber", "shield"),
    "forecast_rejected": ("b-grey", "trend"),
    "confirmation_rejected": ("b-grey", "brain"),
    "screened": ("b-grey", "filter"),
}

HISTORY_CSS = """
.hist-head { padding: 26px 0 18px; }
.hist-head h1 { font-size: 26px; margin-top: 8px; }
.hist-table { min-width: 860px; font-size: 13px; }
.hist-table td small { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
.faq dt { font-weight: 700; } .faq dd { margin: 4px 0 12px; color: var(--ink2); font-size: 13px; }
"""


def _pct(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value) * 100:+.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def build_ticker_history_model(repo: StorageRepository | None, *, ticker: str, site_base_url: str | None = None) -> dict[str, Any]:
    history = build_harness_ticker_history_payload(repo, ticker_code=ticker, limit=60)
    outcomes = build_harness_outcomes_payload(repo, ticker_code=ticker, limit=60) if repo is not None else {"items": [], "summary": {}}
    items = list(history.get("items") or [])
    by_decision: dict[str, list[dict[str, Any]]] = {}
    for outcome in outcomes.get("items") or []:
        by_decision.setdefault(str(outcome.get("harness_decision_id")), []).append(outcome)
    for item in items:
        item["outcomes"] = sorted(by_decision.get(str(item.get("id")), []), key=lambda o: int(o.get("horizon_days") or 0))
    name = next((str(item.get("ticker_name")) for item in items if item.get("ticker_name")), ticker)
    market = next((str(item.get("market")) for item in items if item.get("market")), "KR")
    passed = [item for item in items if item.get("stage") in {"ordered", "exit"}]
    latest = items[0] if items else None
    summary = outcomes.get("summary") or {}
    five, twenty = summary.get("5") or {}, summary.get("20") or {}
    if latest:
        verdict = latest.get("confirmation_rating") or latest.get("stage_label") or "-"
        answer = f"{name}({ticker})는 최근 {len(items)}회 선별에서 {len(passed)}회 통과했습니다. 마지막 판정은 {latest.get('as_of_date')} {verdict}입니다."
    else:
        answer = f"{name}({ticker})는 아직 종목 선별에 오른 기록이 없습니다. 선별 대상에 들어오면 이 페이지에 판정이 쌓입니다."
    return {
        "ticker": ticker,
        "name": name,
        "market": market,
        "items": items,
        "passed": passed,
        "latest": latest,
        "answer": answer,
        "five": five,
        "twenty": twenty,
        "outcome_items": list(outcomes.get("items") or []),
        "status": history.get("status"),
        "canonical": canonical_url(f"/stocks/{ticker}/history", site_base_url=site_base_url),
    }


def render_ticker_history_page(ticker: str, *, repo: StorageRepository | None = None, site_base_url: str | None = None) -> str:
    model = build_ticker_history_model(repo, ticker=ticker, site_base_url=site_base_url)
    name, items, passed, latest = model["name"], model["items"], model["passed"], model["latest"]
    five, twenty = model["five"], model["twenty"]
    title = f"{name}({ticker}) AI 판정 이력"
    description = model["answer"]

    def hit(bucket: dict[str, Any]) -> str:
        completed = int(bucket.get("completed") or 0)
        rate = bucket.get("hit_rate")
        return "–" if not completed or rate is None else f"{float(rate) * 100:.0f}%"

    tiles = "".join(
        [
            stat_tile("filter", "b-blue", "선별 등장", f"{len(items)}회", "규칙 점수 상위 후보"),
            stat_tile("check", "b-teal", "AI 토론 통과", f"{len(passed)}회", "모의 주문까지"),
            stat_tile("target", "b-violet", "5일 적중률", hit(five), f"확정 {int(five.get('completed') or 0)}건"),
            stat_tile("trend", "b-amber", "20일 평균 초과수익", _pct(twenty.get("average_alpha")) if twenty.get("average_alpha") is not None else "–", f"확정 {int(twenty.get('completed') or 0)}건"),
        ]
    )
    rows = []
    for item in items:
        stage = str(item.get("stage") or "")
        tone, ic = STAGE_TONE.get(stage, ("b-grey", "filter"))
        outcome_bits = []
        for outcome in item.get("outcomes") or []:
            if outcome.get("status") == "completed":
                outcome_bits.append(f'{outcome.get("horizon_days")}일 {_pct(outcome.get("raw_return"))} <small>초과수익 {_pct(outcome.get("alpha_return"))}</small>')
            elif outcome.get("status") == "pending":
                outcome_bits.append(f'{outcome.get("horizon_days")}일 <small>검증 대기</small>')
        rows.append(
            f"""<tr>
          <td class="num"><a class="link" href="/harness/{h(item.get('harness_run_id'))}">{h(item.get('as_of_date'))}</a></td>
          <td>{badge(str(item.get('stage_label') or stage), tone, icon_name=ic)}</td>
          <td class="num">{h(f"{float(item['composite_score']):.2f}") if item.get('composite_score') is not None else '-'}</td>
          <td class="num">{h(_pct(item.get('forecast_expected_return')))}<small>상승 확률 {h(_pct(item.get('forecast_probability_up'), 0)) if item.get('forecast_probability_up') is not None else '-'}</small></td>
          <td>{badge(str(item.get('confirmation_rating')), 'b-violet') if item.get('confirmation_rating') else '<span class="muted">-</span>'}<small class="num">{('신뢰도 ' + f"{float(item['confirmation_confidence']):.2f}") if item.get('confirmation_confidence') is not None else ''}</small></td>
          <td>{'<br>'.join(outcome_bits) or '<span class="muted">-</span>'}</td>
          <td class="small ink2" style="max-width: 240px;">{h('; '.join(str(r) for r in (item.get('reasons') or [])[:2]))}</td>
        </tr>"""
        )
    table_rows = "\n".join(rows) or '<tr><td colspan="7" class="muted" style="text-align: center; padding: 24px;">아직 선별 기록이 없습니다.</td></tr>'

    faqs = [
        (f"{name}는 최근 AI 선별에서 통과했나요?", model["answer"]),
        ("판정은 어떻게 정해지나요?", "규칙 점수 상위 후보를 20거래일 예상 수익률과 상승 확률로 거른 뒤, 강세·약세 의견이 맞선 토론에서 판정이 등급을 정하고 리스크 점검이 손절·익절선을 정합니다."),
        ("실제로 매매하나요?", "아니요. 통과 종목은 한국투자증권 모의투자 계좌에만 주문하고, 5거래일과 20거래일 뒤 지수 대비 초과수익을 공개합니다. 투자 조언이 아닙니다."),
    ]
    faq_html = "".join(f"<dt>{h(q)}</dt><dd>{h(a)}</dd>" for q, a in faqs)
    structured = [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "오늘", "item": canonical_url("/", site_base_url=site_base_url)},
            {"@type": "ListItem", "position": 2, "name": f"{name} 종목 분석", "item": canonical_url(f"/stocks/{ticker}", site_base_url=site_base_url)},
            {"@type": "ListItem", "position": 3, "name": "AI 판정 이력", "item": model["canonical"]},
        ]},
        {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]},
        {"@type": "Article", "headline": title, "description": description, "inLanguage": "ko-KR", "mainEntityOfPage": model["canonical"],
         "datePublished": str(items[-1].get("as_of_date")) if items else None, "dateModified": str(latest.get("as_of_date")) if latest else None,
         "author": {"@id": f"{(site_base_url or '').rstrip('/')}/#organization"}},
    ]
    structured[2] = {k: v for k, v in structured[2].items() if v is not None}

    body = f"""
<section class="hero hist-head">
  <div class="shell">
    <div class="row wrap">{badge(str(model['market']), 'b-navy')}{badge('AI 판정 이력', 'b-teal', icon_name='brain')}{badge(f'{len(items)}회 등장', 'b-grey')}</div>
    <h1>{h(title)}</h1>
    <p class="ink2" style="margin-top: 8px; max-width: 760px; font-size: 15px;">{h(model['answer'])}</p>
    <div class="row wrap" style="margin-top: 14px;"><a class="btn sm primary" href="/stocks/{h(ticker)}">{icon('trend', 14)}종목 분석</a><a class="btn sm" href="/analyses?ticker={h(ticker)}">{icon('book', 14)}AI 리포트</a><a class="btn sm ghost" href="/harness">선별 기록 →</a></div>
    <div class="grid-4" style="margin-top: 18px;">{tiles}</div>
  </div>
</section>
<section class="block" style="padding-bottom: 28px;">
  <div class="shell stack" style="gap: 20px;">
    <div class="card" style="overflow: hidden;">
      <div class="card-h"><h2>{icon_tile('clock', 'b-grey', small=True)}선별 판정 이력</h2><span class="tiny muted">최근 60회 · 날짜를 누르면 그날 선별 기록으로 이동</span></div>
      <div class="table-wrap"><table class="hist-table">
        <thead><tr><th>날짜</th><th>결과</th><th>규칙 점수</th><th>20일 예상</th><th>AI 판정</th><th>검증 결과</th><th>근거</th></tr></thead>
        <tbody>{table_rows}</tbody>
      </table></div>
      <div class="card-f"><span>검증 결과는 5·20거래일 뒤 지수 대비 초과수익으로 확정됩니다.</span><a class="link" href="/api/harness/tickers/{h(ticker)}">JSON 데이터</a></div>
    </div>
    <div class="card"><div class="card-h"><h2>{icon_tile('brain', 'b-violet', small=True)}자주 묻는 질문</h2></div><div class="card-b"><dl class="faq" style="margin: 0;">{faq_html}</dl></div></div>
  </div>
</section>
"""
    return render_shell(
        title=f"{title} | TradingAgents Korea",
        description=description[:160],
        body=body,
        canonical_path=f"/stocks/{ticker}/history",
        site_base_url=site_base_url,
        extra_css=HISTORY_CSS,
        structured_data=structured,
        og_type="article",
        og_image=canonical_url(f"/og/stocks/{ticker}.png", site_base_url=site_base_url),
    )
