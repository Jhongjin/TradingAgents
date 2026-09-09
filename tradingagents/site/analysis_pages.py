"""Public analysis pages on the shared design system.

Renders ``/analyses`` (AI report list), ``/analyses/{id}`` (one report) and
``/outcomes`` (5/20 trading-day verification list). The data layer stays in
``web_pages`` (payload builders, view models, label helpers, JSON-LD builder);
only the HTML is rebuilt here from the ``design_system`` vocabulary.

Signatures match the legacy renderers in ``web_pages`` one to one so the API
app can swap them in without touching the routes.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from tradingagents.storage import StorageRepository

from .design_system import badge, h, icon, icon_tile, pct, render_shell, stat_tile

ANALYSIS_CSS = """
.an-head { padding: 26px 0 18px; }
.an-head h1 { font-size: 26px; margin-top: 8px; }
.an-head .lede { margin-top: 6px; max-width: 760px; }
.an-filter { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.an-filter .field { width: 240px; }
.an-filter select.field { width: 160px; }
.an-state { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 10px; font-size: 13px; }
.an-table { min-width: 960px; font-size: 13px; }
.an-table td small { color: var(--muted); display: block; margin-top: 2px; font-size: 12px; }
.an-links { display: flex; gap: 6px; flex-wrap: wrap; }
.an-empty { padding: 28px 18px; text-align: center; }
.an-empty h3 { font-size: 16px; }
.an-empty p { margin-top: 6px; color: var(--ink2); }
.an-empty .an-links { justify-content: center; margin-top: 14px; }
.an-report + .an-report { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--line); }
.an-report h3 { margin-top: 8px; }
.an-report .body p { margin-top: 8px; color: var(--ink2); font-size: 14px; }
.an-quality { margin-top: 8px; padding: 10px 12px; }
.an-quality ul { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: var(--ink2); display: grid; gap: 3px; }
.an-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.an-steps .soft { padding: 12px 14px; }
.an-steps .t { font-weight: 700; margin-top: 8px; }
.an-steps .d { font-size: 13px; color: var(--ink2); margin-top: 4px; }
.an-notices { margin: 0; padding-left: 18px; font-size: 12px; color: var(--ink2); display: grid; gap: 4px; }
.an-rationale { font-size: 15px; line-height: 1.7; color: var(--ink); }
@media (max-width: 960px) { .an-steps { grid-template-columns: 1fr; } .an-filter .field { width: 100%; } }
"""

ROLE_LABELS: dict[str, str] = {
    "market": "시장 분석",
    "news": "뉴스 분석",
    "fundamentals": "기업 분석",
    "social": "여론 분석",
    "bull": "강세 의견",
    "bear": "약세 의견",
    "research_manager": "연구 종합",
    "trader": "매매 계획",
    "judge": "판정",
    "risk": "리스크 점검",
    "risk_manager": "리스크 점검",
    "portfolio_manager": "최종 판정",
}

STATUS_LABELS: dict[str, str] = {"completed": "검증 완료", "pending": "검증 대기", "unavailable": "데이터 없음"}
STATUS_TONES: dict[str, str] = {"completed": "b-teal", "pending": "b-amber", "unavailable": "b-grey"}
REQUEST_HREF = "/member?mode=signup&tab=analysis#analysis-request-section"


# --- small formatting helpers ---------------------------------------------------------
def _pct_text(value: Any) -> str:
    """Plain signed percent text (``+3.00%``) or ``-`` for missing values."""

    from .web_pages import _percent

    return _percent(value, signed=True)


def _pct_html(value: Any) -> str:
    if value is None:
        return '<span class="muted">–</span>'
    try:
        return pct(float(value))
    except (TypeError, ValueError):
        return '<span class="muted">–</span>'


def _rating_tone(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if raw in {"strong buy", "buy", "accumulate", "outperform"}:
        return "b-teal"
    if raw in {"sell", "strong sell", "reduce", "underperform", "avoid"}:
        return "b-orange"
    if raw:
        return "b-blue"
    return "b-grey"


def _status_badge(status: Any) -> str:
    key = str(status or "pending")
    return badge(STATUS_LABELS.get(key, "확인"), STATUS_TONES.get(key, "b-grey"))


def _role_label(role: Any) -> str:
    key = str(role or "agent").strip().lower()
    return ROLE_LABELS.get(key, str(role or "agent"))


def _links(*pairs: tuple[str, str] | None, ghost_last: bool = False) -> str:
    items = [pair for pair in pairs if pair]
    out = []
    for index, (href, text) in enumerate(items):
        cls = "btn sm ghost" if ghost_last and index == len(items) - 1 else "btn sm"
        out.append(f'<a class="{cls}" href="{h(href)}">{h(text)}</a>')
    return f'<div class="an-links">{"".join(out)}</div>'


def _empty_card(title: str, text: str, *pairs: tuple[str, str] | None) -> str:
    return f'<div class="an-empty"><h3>{h(title)}</h3><p class="small">{h(text)}</p>{_links(*pairs)}</div>'


def _notices(*items: str) -> str:
    rows = "".join(f"<li>{h(item)}</li>" for item in items)
    return f'<div class="soft" style="padding: 14px 18px;"><p class="label">투자 유의사항</p><ul class="an-notices" style="margin-top: 6px;">{rows}</ul></div>'


def _hero(*, chips: str, title: str, lede: str, actions: str, state: str = "", tiles: str = "") -> str:
    tiles_html = f'<div class="grid-4" style="margin-top: 18px;">{tiles}</div>' if tiles else ""
    return f"""
<section class="hero an-head">
  <div class="shell">
    <div class="row between wrap" style="align-items: flex-start;">
      <div>
        <div class="row wrap">{chips}</div>
        <h1>{h(title)}</h1>
        <p class="small ink2 lede">{h(lede)}</p>
        {state}
      </div>
      <div class="an-links">{actions}</div>
    </div>
    {tiles_html}
  </div>
</section>"""


# --- /analyses -------------------------------------------------------------------------
def _feed_rows(items: list[dict[str, Any]]) -> str:
    from .web_pages import _decision_pair_label

    rows = []
    for item in items:
        code = str(item.get("ticker_code") or "")
        name = str(item.get("ticker_name") or code or "공개 분석")
        market = str(item.get("market") or "KR")
        trade_date = str(item.get("trade_date") or "-")
        provider = str(item.get("model_provider") or "AI")
        run_id = str(item.get("id") or "")
        report_path = str(item.get("report_path") or (f"/analyses/{run_id}" if run_id else "/analyses"))
        api_path = str(item.get("api_path") or (f"/api/analyses/{run_id}" if run_id else "/api/analyses"))
        outcome_path = f"/outcomes?ticker={code}" if code else "/outcomes"
        stock_path = f"/stocks/{code}" if code else "/analyses"
        report_count = item.get("report_count")
        reports = f"{int(report_count)}개" if report_count is not None else "-"
        horizon = item.get("outcome_horizon_days")
        completed = int(item.get("completed_outcome_count") or 0)
        if horizon:
            outcome_cell = (
                f'{h(horizon)}거래일 초과수익 {_pct_html(item.get("alpha_return"))}'
                f'<small class="num">종목 {h(_pct_text(item.get("raw_return")))} · 시장 {h(_pct_text(item.get("benchmark_return")))} · 검증 완료 {completed}건</small>'
            )
        else:
            outcome_cell = f'{badge("검증 대기", "b-amber")}<small>5거래일·20거래일 뒤 계산합니다.</small>'
        rating = item.get("decision_rating")
        decision = _decision_pair_label(rating, item.get("decision_action"))
        rows.append(
            f"""<tr>
          <td><a href="{h(report_path)}"><b style="font-weight: 700;">{h(name)}</b></a><small class="num">{h(code)} · {h(market)}</small></td>
          <td class="num">{h(trade_date)}</td>
          <td>{badge(decision, _rating_tone(rating))}</td>
          <td>{h(provider)}<small class="num">분석 ID {h(run_id[:8] or "-")}</small></td>
          <td class="num">{h(reports)}</td>
          <td>{outcome_cell}</td>
          <td><div class="an-links"><a class="btn sm" href="{h(report_path)}">리포트 상세</a><a class="btn sm ghost" href="{h(stock_path)}">종목 분석</a><a class="btn sm ghost" href="{h(outcome_path)}">검증 결과</a><a class="btn sm ghost" href="{h(api_path)}">JSON 데이터</a></div></td>
        </tr>"""
        )
    return "\n".join(rows)


def _feed_empty(ticker: str | None) -> str:
    if ticker:
        return _empty_card(
            f"{ticker} 리포트가 아직 없습니다",
            "조건에 맞는 완료 리포트가 없습니다. 종목 분석 페이지를 먼저 보거나 마이페이지에서 분석을 요청합니다.",
            ("/analyses", "필터 초기화"),
            (f"/stocks/{ticker}", "종목 분석"),
            (f"/outcomes?ticker={ticker}", "검증 결과"),
            (REQUEST_HREF, "분석 요청"),
        )
    return _empty_card(
        "아직 공개된 AI 리포트가 없습니다",
        "리포트가 완료되면 이 목록에 실립니다. 먼저 삼성전자 종목 분석을 보거나 마이페이지에서 분석을 요청합니다.",
        ("/stocks/005930", "삼성전자 종목 분석"),
        ("/features/methodology", "분석 기준"),
        (REQUEST_HREF, "분석 요청"),
    )


def render_public_analysis_feed_page(
    *,
    repo: StorageRepository | None = None,
    ticker: str | None = None,
    limit: int = 20,
    max_limit: int = 50,
    site_base_url: str | None = None,
) -> str:
    """Render the public completed-analysis list (``/analyses``)."""

    from .web_pages import (
        _analysis_feed_payload,
        _analysis_feed_status_label,
        _analysis_feed_view_model,
        _decision_rating_label,
        _script_json,
        _top_count_label,
    )

    payload = _analysis_feed_payload(repo, ticker=ticker, limit=limit, max_limit=max_limit)
    model = _analysis_feed_view_model(payload, site_base_url=site_base_url)
    items: list[dict[str, Any]] = model["items"]
    summary: dict[str, Any] = model["summary"] or {}
    ticker_code = str(model.get("ticker_code") or "").strip()
    status_label = _analysis_feed_status_label(payload.get("status"))
    basis_label = str(model.get("basis_label") or "")
    count = len(items)

    page_title = f"{ticker_code} AI 리포트" if ticker_code else "AI 리포트"
    lede = (
        f"{ticker_code} 종목의 완료된 AI 분석 리포트 목록입니다. "
        if ticker_code
        else "TradingAgents Korea가 공개한 한국 주식 AI 분석 리포트 목록입니다. "
    ) + "완료된 리포트만 싣고, 리포트마다 5거래일과 20거래일 검증 결과를 함께 표시합니다."

    chips = badge("AI 리포트", "b-teal", icon_name="book") + badge(status_label, "b-grey")
    if ticker_code:
        chips += badge(f"{ticker_code} 필터", "b-blue", icon_name="filter")

    if ticker_code:
        state = (
            f'<div class="an-state">{badge(f"{ticker_code} 필터 적용", "b-blue")}{badge(f"결과 {count}건", "b-grey")}'
            f'<a class="link" href="/stocks/{h(ticker_code)}">종목 분석</a><a class="link" href="/outcomes?ticker={h(ticker_code)}">검증 결과</a></div>'
        )
    else:
        state = f'<div class="an-state">{badge("전체 종목", "b-grey")}<span class="muted">{h(basis_label)}</span><a class="link" href="/outcomes">성과 검증</a></div>'

    actions = (
        f'<a class="btn sm" href="/outcomes">{icon("target", 14)}성과 검증</a>'
        f'<a class="btn sm" href="/api/analyses">JSON 데이터</a>'
        f'<a class="btn sm ghost" href="/features/methodology">분석 기준 →</a>'
    )

    tiles = ""
    track_html = ""
    if items:
        latest = str(summary.get("latest_trade_date") or "-")
        completed_outcomes = int(summary.get("completed_outcome_count") or 0)
        markets = summary.get("market_counts") if isinstance(summary.get("market_counts"), dict) else {}
        ratings = summary.get("decision_rating_counts") if isinstance(summary.get("decision_rating_counts"), dict) else {}
        providers = summary.get("model_provider_counts") if isinstance(summary.get("model_provider_counts"), dict) else {}
        avg_alpha = summary.get("average_alpha_return")
        tiles = "".join(
            [
                stat_tile("book", "b-teal", "완료 리포트", f"{int(summary.get('completed_count') or 0)}건", basis_label),
                stat_tile("layers", "b-navy", "대상 종목", f"{int(summary.get('unique_ticker_count') or 0)}개", "중복 제외"),
                stat_tile("clock", "b-blue", "최신 기준일", h(latest), f"주요 시장 {_top_count_label(markets) or '-'}"),
                stat_tile("target", "b-violet", "평균 초과수익", _pct_html(avg_alpha) if avg_alpha is not None else "–", f"검증 완료 {completed_outcomes}건"),
            ]
        )
        positive_rate = summary.get("positive_alpha_rate")
        coverage = summary.get("outcome_coverage_rate")
        covered = int(summary.get("outcome_covered_count") or 0)
        positive_count = int(summary.get("positive_alpha_count") or 0)
        if completed_outcomes:
            track_cells = [
                ("검증 완료", f"{completed_outcomes}건", f"검증 결과가 붙은 리포트 {covered}개"),
                ("평균 초과수익", _pct_text(avg_alpha), "종목 수익률에서 시장 지수 수익률을 뺀 값"),
                ("초과수익 양수 비율", _pct_text(positive_rate).lstrip("+") if positive_rate is not None else "-", f"양수 {positive_count}건"),
                ("검증 연결 비율", _pct_text(coverage).lstrip("+") if coverage is not None else "-", basis_label),
            ]
        else:
            track_cells = [
                ("검증 대기", "0건", "5거래일·20거래일이 지나면 채워집니다."),
                ("평균 초과수익", "-", "검증 결과 대기"),
                ("초과수익 양수 비율", "-", "검증 결과 대기"),
                ("검증 연결 비율", "-", basis_label),
            ]
        track_grid = "".join(
            f'<div class="soft" style="padding: 12px 14px;"><p class="label">{h(label)}</p><p class="num" style="font-size: 20px; font-weight: 700;">{h(value)}</p><p class="tiny muted">{h(note)}</p></div>'
            for label, value, note in track_cells
        )
        mix = "".join(
            f'<div class="kv"><span class="muted">{h(label)}</span><span class="num">{h(value)}</span></div>'
            for label, value in (
                ("주요 시장", _top_count_label(markets) or "-"),
                ("주요 AI 의견", _top_count_label(ratings, formatter=_decision_rating_label) or "-"),
                ("주요 모델", _top_count_label(providers) or "-"),
            )
        )
        track_html = f"""
    <div class="grid-main">
      <div class="card">
        <div class="card-h"><h2>{icon_tile("target", "b-violet", small=True)}성과 검증 요약</h2><span class="tiny muted">5거래일 · 20거래일 · 시장 지수 대비</span></div>
        <div class="card-b"><div class="grid-4">{track_grid}</div></div>
        <div class="card-f"><span>초과수익 = 종목 수익률 − 같은 기간 시장 지수 수익률</span><a class="link" href="/outcomes">전체 검증 결과 →</a></div>
      </div>
      <div class="card">
        <div class="card-h"><h2>{icon_tile("layers", "b-navy", small=True)}목록 구성</h2><span class="tiny muted">{h(basis_label)}</span></div>
        <div class="card-b" style="padding-top: 4px;">{mix}</div>
      </div>
    </div>"""

    rows = _feed_rows(items)
    if rows:
        table_html = f"""
      <div class="table-wrap">
        <table class="an-table">
          <thead><tr><th>종목</th><th>기준일</th><th>AI 의견</th><th>모델</th><th>리포트</th><th>검증 결과</th><th>링크</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>"""
    else:
        table_html = _feed_empty(ticker_code or None)

    count_label = f"결과 {count}건" if ticker_code or count else "목록 대기"
    body = _hero(chips=chips, title=page_title, lede=lede, actions=actions, state=state, tiles=tiles) + f"""
<section class="block" style="padding-bottom: 28px;">
  <div class="shell stack" style="gap: 20px;">
    <div class="card" style="padding: 16px 18px;">
      <form class="an-filter" action="/analyses" method="get" role="search" aria-label="AI 리포트 검색">
        <label for="analysisTicker" class="label">종목명 또는 코드</label>
        <input id="analysisTicker" class="field" name="ticker" maxlength="80" value="{h(ticker_code)}" placeholder="005930 또는 삼성전자" autocomplete="off">
        <button class="btn primary" type="submit">리포트 찾기</button>
        <a class="btn ghost" href="/analyses">전체 보기</a>
        <span class="tiny muted">종목명이나 6자리 코드로 완료 리포트만 찾습니다.</span>
      </form>
    </div>
    {track_html}
    <div class="card" style="overflow: hidden;">
      <div class="card-h"><h2>{icon_tile("book", "b-teal", small=True)}최근 AI 리포트 {badge(count_label, "b-grey")}</h2><span class="tiny muted">정렬: 최신 기준일순 · {h(model.get("filter_label") or "전체 종목")}</span></div>
      {table_html}
      <div class="card-f"><span>리포트 상세에서 출처, 본문, 검증 결과를 확인합니다.</span><span>{icon("shield", 12)} 실계좌 주문 없음</span></div>
    </div>
    {_notices("AI 리포트는 정보 제공용입니다. 투자 조언이 아닙니다.", "이 사이트는 실계좌 주문을 하지 않습니다.")}
  </div>
</section>
<script id="analysis-feed-payload" type="application/json">{_script_json(payload)}</script>
"""
    return render_shell(
        title=model["title"],
        description=model["description"],
        body=body,
        active="/analyses",
        canonical_path="/analyses",
        site_base_url=site_base_url,
        extra_css=ANALYSIS_CSS,
    )


# --- /outcomes -------------------------------------------------------------------------
def _outcome_rows(items: list[dict[str, Any]]) -> str:
    from .web_pages import _decision_pair_label

    rows = []
    for item in items:
        code = str(item.get("ticker_code") or "")
        name = str(item.get("ticker_name") or code or "공개 분석")
        market = str(item.get("market") or "KR")
        status = str(item.get("status") or "pending")
        run_id = str(item.get("analysis_run_id") or "")
        horizon = item.get("horizon_days") or "-"
        trade_date = str(item.get("trade_date") or "-")
        evaluated_at = str(item.get("evaluated_at") or "-")
        actual_days = item.get("actual_holding_days")
        report_path = f"/analyses/{run_id}" if run_id else "/analyses"
        stock_path = f"/stocks/{code}" if code else "/analyses"
        rating = item.get("decision_rating")
        decision = _decision_pair_label(rating, item.get("decision_action"))
        if status == "completed":
            sentence = f"{horizon}거래일 수익률 {_pct_text(item.get('raw_return'))}, 초과수익 {_pct_text(item.get('alpha_return'))} ({evaluated_at} 기준)"
        elif status == "pending":
            sentence = f"{actual_days or 0}거래일만 지나 {horizon}거래일 검증을 기다립니다."
        else:
            sentence = "가격 데이터를 아직 받지 못했습니다."
        rows.append(
            f"""<tr>
          <td><a href="{h(report_path)}"><b style="font-weight: 700;">{h(name)}</b></a><small class="num">{h(code)} · {h(market)} · {h(sentence)}</small></td>
          <td class="num">{h(trade_date)}</td>
          <td class="num">{h(horizon)}거래일<small>관측 {h(actual_days) if actual_days is not None else "-"}일</small></td>
          <td>{_pct_html(item.get("raw_return"))}</td>
          <td>{_pct_html(item.get("benchmark_return"))}</td>
          <td><b>{_pct_html(item.get("alpha_return"))}</b></td>
          <td>{_status_badge(status)}<small class="num">평가일 {h(evaluated_at)}</small></td>
          <td>{badge(decision, _rating_tone(rating))}</td>
          <td><div class="an-links"><a class="btn sm" href="{h(report_path)}">리포트 상세</a><a class="btn sm ghost" href="{h(stock_path)}">종목 분석</a><a class="btn sm ghost" href="{h(f'/analyses?ticker={code}' if code else '/analyses')}">같은 종목 리포트</a></div></td>
        </tr>"""
        )
    return "\n".join(rows)


def _outcome_empty(ticker: str, status: str) -> str:
    if ticker or status:
        bits = [bit for bit in (ticker, STATUS_LABELS.get(status, "") if status else "") if bit]
        return _empty_card(
            f"{' '.join(bits)} 검증 결과가 없습니다" if bits else "조건에 맞는 검증 결과가 없습니다",
            "조건에 맞는 결과가 아직 없습니다. 기준일에서 거래일이 덜 지났거나 가격 데이터가 비어 있을 수 있습니다.",
            ("/outcomes", "필터 초기화"),
            (f"/analyses?ticker={ticker}" if ticker else "/analyses", "AI 리포트"),
            (f"/stocks/{ticker}", "종목 분석") if ticker else None,
            (REQUEST_HREF, "분석 요청"),
        )
    return _empty_card(
        "아직 검증 결과가 없습니다",
        "리포트 기준일에서 5거래일과 20거래일이 지나면 평일 종가로 자동 계산합니다. 삼성전자 종목 분석에서 검증 흐름을 먼저 볼 수 있습니다.",
        ("/stocks/005930#analysis-outcomes", "삼성전자 검증 결과"),
        ("/analyses", "AI 리포트"),
        ("/features/outcomes", "계산 기준"),
        (REQUEST_HREF, "분석 요청"),
    )


def render_public_outcomes_page(
    *,
    repo: StorageRepository | None = None,
    ticker: str | None = None,
    status: str | None = None,
    limit: int = 20,
    max_limit: int = 50,
    site_base_url: str | None = None,
) -> str:
    """Render the public verification list (``/outcomes``)."""

    from .web_pages import _analysis_outcomes_payload, _analysis_outcomes_view_model, _script_json

    payload = _analysis_outcomes_payload(repo, ticker=ticker, status=status, limit=limit, max_limit=max_limit)
    model = _analysis_outcomes_view_model(payload, site_base_url=site_base_url)
    items: list[dict[str, Any]] = model["items"]
    summary: dict[str, Any] = model["summary"] or {}
    ticker_code = str(model.get("ticker_code") or "").strip()
    filter_status = str(model.get("filter_status") or "").strip()
    filter_label = str(model.get("filter_label") or "전체")
    count = len(items)
    query: dict[str, str] = {"limit": "20"}
    if ticker_code:
        query["ticker"] = ticker_code
    if filter_status:
        query["status"] = filter_status
    api_path = f"/api/analysis-outcomes?{urlencode(query)}"

    lede = "AI 리포트가 나온 뒤 5거래일과 20거래일 수익률을 같은 기간 시장 지수와 비교한 검증 결과 목록입니다. 초과수익은 종목 수익률에서 시장 지수 수익률을 뺀 값입니다."
    status_label = {"available": "검증 결과 있음", "not_configured": "저장소 미연결", "unavailable": "저장소 확인 필요"}.get(str(payload.get("status")), "상태 확인")
    chips = badge("성과 검증", "b-violet", icon_name="target") + badge(status_label, "b-grey")
    if ticker_code or filter_status:
        chips += badge(f"{filter_label} 필터", "b-blue", icon_name="filter")
    if ticker_code or filter_status:
        state_links = (f'<a class="link" href="/stocks/{h(ticker_code)}">종목 분석</a>' if ticker_code else "") + f'<a class="link" href="{h(f"/analyses?ticker={ticker_code}" if ticker_code else "/analyses")}">AI 리포트</a>'
        state = f'<div class="an-state">{badge(f"{filter_label} 적용", "b-blue")}{badge(f"결과 {count}건", "b-grey")}{state_links}</div>'
    else:
        state = f'<div class="an-state">{badge("전체 종목", "b-grey")}<span class="muted">5거래일 · 20거래일</span><a class="link" href="/analyses">AI 리포트</a></div>'
    actions = (
        f'<a class="btn sm" href="/analyses">{icon("book", 14)}AI 리포트</a>'
        f'<a class="btn sm" href="{h(api_path)}">JSON 데이터</a>'
        f'<a class="btn sm ghost" href="/features/outcomes">계산 기준 →</a>'
    )

    tiles = ""
    if items:
        completed = int(summary.get("completed_count") or 0)
        pending = int(summary.get("pending_count") or 0)
        unavailable = int(summary.get("unavailable_count") or 0)
        positive = int(summary.get("positive_alpha_count") or 0)
        avg_alpha = summary.get("average_alpha_return")
        positive_rate = summary.get("positive_alpha_rate")
        tiles = "".join(
            [
                stat_tile("check", "b-teal", "검증 완료", f"{completed}건", f"{model.get('filter_label') or '전체'} 기준"),
                stat_tile("target", "b-violet", "평균 초과수익", _pct_html(avg_alpha) if avg_alpha is not None else "–", f"종목 평균 수익률 {_pct_text(summary.get('average_raw_return'))}"),
                stat_tile("trend", "b-blue", "초과수익 양수 비율", h(_pct_text(positive_rate).lstrip("+")) if positive_rate is not None else "–", f"양수 {positive}건"),
                stat_tile("clock", "b-amber", "검증 대기 / 데이터 없음", f"{pending} / {unavailable}", "거래일이 더 지나야 확정"),
            ]
        )

    status_options = "".join(
        f'<option value="{h(value)}"{" selected" if value == filter_status else ""}>{h(label)}</option>'
        for value, label in (("", "전체"), ("completed", "검증 완료"), ("pending", "검증 대기"), ("unavailable", "데이터 없음"))
    )

    rows = _outcome_rows(items)
    if rows:
        table_html = f"""
      <div class="table-wrap">
        <table class="an-table">
          <thead><tr><th>종목</th><th>기준일</th><th>기간</th><th>종목 수익률</th><th>시장 수익률</th><th>초과수익</th><th>상태</th><th>AI 의견</th><th>링크</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>"""
    else:
        table_html = _outcome_empty(ticker_code, filter_status)

    count_label = f"결과 {count}건" if ticker_code or filter_status or count else "검증 대기"
    steps = f"""
    <div class="card">
      <div class="card-h"><h2>{icon_tile("layers", "b-navy", small=True)}검증은 이렇게 계산합니다</h2><a class="link tiny" href="/features/outcomes">계산 기준 전문 →</a></div>
      <div class="card-b an-steps">
        <div class="soft">{icon_tile("clock", "b-blue", small=True)}<p class="t">1 · 기준일</p><p class="d">리포트의 거래일 종가를 시작점으로 잡습니다.</p></div>
        <div class="soft">{icon_tile("trend", "b-violet", small=True)}<p class="t">2 · 기간</p><p class="d">5거래일과 20거래일이 지난 종가로 종목 수익률을 구합니다.</p></div>
        <div class="soft">{icon_tile("target", "b-teal", small=True)}<p class="t">3 · 초과수익</p><p class="d">같은 기간 시장 지수(KOSPI 또는 KOSDAQ) 수익률을 빼서 초과수익을 냅니다.</p></div>
      </div>
    </div>"""

    body = _hero(chips=chips, title="리포트 성과 검증", lede=lede, actions=actions, state=state, tiles=tiles) + f"""
<section class="block" style="padding-bottom: 28px;">
  <div class="shell stack" style="gap: 20px;">
    <div class="card" style="padding: 16px 18px;">
      <form class="an-filter" action="/outcomes" method="get" role="search" aria-label="검증 결과 검색">
        <label for="outcomeTicker" class="label">종목명 또는 코드</label>
        <input id="outcomeTicker" class="field" name="ticker" maxlength="80" value="{h(ticker_code)}" placeholder="005930 또는 삼성전자" autocomplete="off">
        <label for="outcomeStatus" class="label">상태</label>
        <select id="outcomeStatus" class="field" name="status">{status_options}</select>
        <button class="btn primary" type="submit">검증 결과 찾기</button>
        <a class="btn ghost" href="/outcomes">전체 보기</a>
      </form>
    </div>
    <div class="card" style="overflow: hidden;">
      <div class="card-h"><h2>{icon_tile("target", "b-violet", small=True)}최근 검증 결과 {badge(count_label, "b-grey")}</h2><span class="tiny muted">정렬: 최신 기준일순 · {h(filter_label)}</span></div>
      {table_html}
      <div class="card-f"><span>초과수익 = 종목 수익률 − 같은 기간 시장 지수 수익률</span><a class="link" href="{h(api_path)}">JSON 데이터 →</a></div>
    </div>
    {steps}
    {_notices("검증 결과는 지난 리포트를 점검한 기록입니다. 미래 수익을 보장하지 않습니다.", "이 사이트는 실계좌 주문을 하지 않습니다.")}
  </div>
</section>
<script id="outcomes-payload" type="application/json">{_script_json(payload)}</script>
"""
    return render_shell(
        title="리포트 성과 검증 | TradingAgents Korea",
        description="TradingAgents Korea AI 리포트의 5거래일·20거래일 수익률과 시장 지수 대비 초과수익 검증 결과입니다.",
        body=body,
        active="/outcomes",
        canonical_path="/outcomes",
        site_base_url=site_base_url,
        extra_css=ANALYSIS_CSS,
    )


# --- /analyses/{id} --------------------------------------------------------------------
def _quality_html(quality: dict[str, Any] | None) -> str:
    if not quality:
        return ""
    risk = str(quality.get("risk_level") or "medium")
    risk_label = {"low": "낮음", "medium": "검토", "high": "높음"}.get(risk, "검토")
    risk_tone = {"low": "b-teal", "medium": "b-amber", "high": "b-orange"}.get(risk, "b-amber")
    passed = int(quality.get("passed_count") or 0)
    total = int(quality.get("total_count") or 0)
    warnings = int(quality.get("warning_count") or 0) + int(quality.get("failed_count") or 0)
    checks = quality.get("checks") or []
    flagged = [check for check in checks if isinstance(check, dict) and check.get("status") != "pass"][:4]
    if flagged:
        items = "".join(
            f"<li><b>{h(check.get('label') or check.get('id') or 'check')}</b> · {h(check.get('status') or '-')} · {h(check.get('detail') or '')}</li>"
            for check in flagged
        )
        list_html = f'<ul aria-label="근거 점검 상세">{items}</ul>'
    else:
        list_html = '<p class="tiny muted" style="margin-top: 4px;">핵심 기준을 모두 통과했습니다.</p>'
    return (
        f'<div class="soft an-quality"><div class="row wrap">{badge(f"근거 점검 {risk_label}", risk_tone, icon_name="shield")}'
        f'<span class="tiny muted">{passed}/{total}개 기준 통과 · 확인 필요 {warnings}건</span></div>{list_html}</div>'
    )


def _report_blocks(reports: list[dict[str, Any]], *, run_id: str, ticker_code: str) -> str:
    from .web_pages import _excerpt, _report_quality

    if not reports:
        return _empty_card(
            "아직 저장된 리포트가 없습니다",
            "저장된 AI 리포트 본문이 없습니다. JSON 데이터나 종목 분석 페이지에서 저장 상태를 확인합니다.",
            (f"/api/analyses/{run_id}", "JSON 데이터"),
            (f"/stocks/{ticker_code}", "종목 분석"),
            ("/analyses", "AI 리포트"),
            (REQUEST_HREF, "새 분석 요청"),
        )
    blocks = []
    for report in reports:
        role = str(report.get("role") or "agent")
        title = str(report.get("title") or role)
        raw_content = str(report.get("content") or "").replace("\r\n", "\n")
        paragraphs = [_excerpt(part.strip(), limit=400) for part in raw_content.split("\n") if part.strip()][:6] or ["리포트 본문이 비어 있습니다."]
        body = "".join(f"<p>{h(paragraph)}</p>" for paragraph in paragraphs)
        blocks.append(
            f'<article class="an-report"><div class="row wrap">{badge(_role_label(role), "b-violet")}<span class="tiny muted">{h(role)} · 본문 발췌</span></div>'
            f"<h3>{h(title)}</h3>{_quality_html(_report_quality(report))}<div class=\"body\">{body}</div></article>"
        )
    return "".join(blocks)


def _decision_block(decision: dict[str, Any], *, run_id: str, ticker_code: str) -> str:
    from .web_pages import _decision_action_label, _decision_rating_label, _excerpt, _percent

    if not decision:
        return _empty_card(
            "아직 저장된 AI 의견이 없습니다",
            "JSON 데이터와 종목 분석 페이지에서 저장 상태를 확인합니다.",
            (f"/api/analyses/{run_id}", "JSON 데이터"),
            (f"/stocks/{ticker_code}", "종목 분석"),
            (REQUEST_HREF, "새 분석 요청"),
        )
    rating_raw = decision.get("rating")
    rating = _decision_rating_label(rating_raw)
    action = _decision_action_label(decision.get("action"))
    target_weight = decision.get("target_weight")
    rationale = decision.get("rationale") or decision.get("raw_decision") or "AI 의견 근거가 저장되지 않았습니다."
    return (
        f'<div class="card-b"><div class="row wrap">{badge(f"AI 의견 {rating}", _rating_tone(rating_raw))}{badge("주문 없음", "b-grey", icon_name="shield")}</div>'
        f'<p class="an-rationale" style="margin-top: 12px;">{h(_excerpt(str(rationale), limit=900))}</p>'
        f'<div style="margin-top: 12px;"><div class="kv"><span class="muted">해석</span><span>{h(action)}</span></div>'
        f'<div class="kv"><span class="muted">목표 비중</span><span class="num">{h(_percent(target_weight) if target_weight is not None else "-")}</span></div></div></div>'
    )


def _outcome_block(outcomes: list[dict[str, Any]]) -> str:
    if not outcomes:
        return _empty_card(
            "검증 대기",
            "리포트 기준일에서 5거래일과 20거래일이 지나면 종목 수익률과 초과수익을 계산해 여기에 싣습니다.",
            ("/outcomes", "전체 검증 결과"),
            ("/features/outcomes", "계산 기준"),
        )
    rows = []
    for outcome in outcomes[:6]:
        status = str(outcome.get("status") or "pending")
        horizon = outcome.get("horizon_days") or "-"
        actual_days = outcome.get("actual_holding_days")
        evaluated_at = str(outcome.get("evaluated_at") or "-")
        if status == "completed":
            sentence = f"{horizon}거래일 수익률 {_pct_text(outcome.get('raw_return'))}, 초과수익 {_pct_text(outcome.get('alpha_return'))} ({evaluated_at} 기준)"
        elif status == "pending":
            sentence = f"{actual_days or 0}거래일만 지나 검증을 기다립니다."
        else:
            sentence = "가격 데이터를 아직 받지 못했습니다."
        rows.append(
            f"<tr><td class=\"num\">{h(horizon)}거래일<small>{h(sentence)}</small></td><td>{_status_badge(status)}</td>"
            f"<td>{_pct_html(outcome.get('raw_return'))}</td><td>{_pct_html(outcome.get('benchmark_return'))}</td><td><b>{_pct_html(outcome.get('alpha_return'))}</b></td>"
            f"<td class=\"num\">{h(outcome.get('trade_date') or '-')}</td><td class=\"num\">{h(evaluated_at)}</td></tr>"
        )
    return f"""<div class="table-wrap"><table class="an-table" style="min-width: 720px;">
      <thead><tr><th>기간</th><th>상태</th><th>종목 수익률</th><th>시장 수익률</th><th>초과수익</th><th>기준일</th><th>평가일</th></tr></thead>
      <tbody>{"".join(rows)}</tbody></table></div>"""


def render_public_analysis_detail_page(
    analysis_run_id: str,
    *,
    repo: StorageRepository | None = None,
    site_base_url: str | None = None,
) -> str:
    """Render one addressable public analysis report (``/analyses/{id}``)."""

    from .analysis_api import build_public_analysis_bundle_payload
    from .web_pages import _analysis_detail_structured_data, _analysis_detail_view_model, _script_json

    payload = build_public_analysis_bundle_payload(repo, analysis_run_id=analysis_run_id) if repo is not None else None
    if payload is None:
        raise ValueError("Public analysis not found")
    model = _analysis_detail_view_model(payload, analysis_run_id=analysis_run_id, site_base_url=site_base_url)
    run_id = str(model["run_id"])
    ticker_code = str(model["ticker_code"])
    ticker_name = str(model["ticker_name"])
    trade_date = str(model["trade_date"])
    summary: dict[str, Any] = model.get("summary") or {}
    reports: list[dict[str, Any]] = model.get("reports") or []
    outcomes: list[dict[str, Any]] = model.get("outcomes") or []
    completed_outcomes = int(summary.get("completed_outcome_count") or 0)
    avg_alpha = summary.get("average_alpha_return")
    rating_raw = summary.get("decision_rating") or (model.get("decision") or {}).get("rating")
    decision_label = str(model["decision_label"])

    lede = (
        f"{trade_date} 기준 {ticker_name}({ticker_code}) AI 분석 리포트입니다. "
        f"AI 의견은 {decision_label}이고, 리포트 {len(reports)}개와 검증 결과 {completed_outcomes}건을 담았습니다. 투자 조언이 아니며 주문은 일어나지 않습니다."
    )
    description = f"{trade_date} 기준 {ticker_name}({ticker_code}) AI 분석 리포트입니다. AI 의견 {decision_label}, 리포트 {len(reports)}개, 검증 결과 {completed_outcomes}건."

    chips = (
        badge("AI 리포트", "b-teal", icon_name="book")
        + badge(str(model["market"]), "b-grey")
        + badge(ticker_code, "b-grey")
        + badge(f"기준일 {trade_date}", "b-blue", icon_name="clock")
        + badge(decision_label, _rating_tone(rating_raw))
    )
    actions = (
        f'<a class="btn sm primary" href="/stocks/{h(ticker_code)}">{icon("trend", 14)}종목 분석</a>'
        f'<a class="btn sm" href="/analyses">리포트 목록</a>'
        f'<a class="btn sm" href="{h(f"/outcomes?ticker={ticker_code}" if ticker_code else "/outcomes")}">성과 검증</a>'
        f'<a class="btn sm ghost" href="/api/analyses/{h(run_id)}">JSON 데이터</a>'
    )
    tiles = "".join(
        [
            stat_tile("brain", "b-violet", "AI 의견", h(decision_label), "투자 조언 아님"),
            stat_tile("book", "b-teal", "리포트", f"{len(reports)}개", str(model.get("analyst_label") or "-")),
            stat_tile("check", "b-blue", "검증 완료", f"{completed_outcomes}건", f"전체 {len(outcomes)}건 중"),
            stat_tile("target", "b-navy", "평균 초과수익", _pct_html(avg_alpha) if avg_alpha is not None else "–", "5거래일 · 20거래일"),
        ]
    )
    tabs = (
        '<nav class="tabs" aria-label="리포트 섹션 바로가기" style="margin-top: 14px; width: fit-content;">'
        '<a href="#analysis-decision">AI 의견</a><a href="#analysis-reports">리포트 본문</a><a href="#analysis-outcomes">검증 결과</a><a href="#analysis-provenance">출처와 한계</a></nav>'
    )

    provenance = "".join(
        f'<div class="kv" style="align-items: flex-start;"><span class="muted" style="flex: none; width: 96px;">{h(label)}</span><span style="text-align: right;"><b style="font-weight: 600;">{h(value)}</b><br><span class="tiny muted">{h(note)}</span></span></div>'
        for label, value, note in (
            ("데이터 기준일", trade_date, str(model["timestamp_label"])),
            ("데이터 출처", "KRX · DART · Naver", "시세, 공시, 뉴스를 연결한 기준입니다."),
            ("분석 역할", str(model["analyst_label"]), "저장된 분석 설정 기준"),
            ("모델", str(model["model_label"]), str(model["metadata_note"])),
            ("검증 결과", f"{completed_outcomes}건 완료", f"평균 초과수익 {model['average_alpha_label']}"),
            ("분석 ID", run_id, "화면과 JSON 데이터가 같은 ID를 씁니다."),
            ("한계", "주문 없는 연구 자료", "휴장, 제공처 장애, 누락 데이터, 모델 오류 가능성이 있습니다."),
        )
    )
    next_links = "".join(
        f'<div class="kv"><span><b style="font-weight: 600;">{h(label)}</b><br><span class="tiny muted">{h(note)}</span></span><a class="btn sm ghost" href="{h(href)}">이동 →</a></div>'
        for label, note, href in (
            ("종목 분석", "가격 흐름과 공시를 봅니다.", f"/stocks/{ticker_code}" if ticker_code else "/analyses"),
            ("검증 결과", "5거래일·20거래일 초과수익", f"/outcomes?ticker={ticker_code}" if ticker_code else "/outcomes"),
            ("새 분석 요청", "로그인 후 마이페이지에서 요청", REQUEST_HREF),
            ("JSON 데이터", "저장된 리포트 원본", f"/api/analyses/{run_id}"),
        )
    )

    body = _hero(chips=chips, title=str(model["heading"]), lede=lede, actions=actions, state=tabs, tiles=tiles) + f"""
<section class="block" style="padding-bottom: 28px;">
  <div class="shell grid-main">
    <div class="stack" style="gap: 20px;">
      <div class="card" id="analysis-decision">
        <div class="card-h"><h2>{icon_tile("brain", "b-violet", small=True)}AI 의견</h2><span class="tiny muted">{h(model["data_basis"])}</span></div>
        {_decision_block(model.get("decision") or {}, run_id=run_id, ticker_code=ticker_code)}
      </div>
      <div class="card" id="analysis-reports">
        <div class="card-h"><h2>{icon_tile("book", "b-teal", small=True)}리포트 본문 {badge(str(model["report_count_label"]), "b-grey")}</h2><span class="tiny muted">본문 일부만 먼저 보여줍니다.</span></div>
        <div class="card-b">{_report_blocks(reports, run_id=run_id, ticker_code=ticker_code)}</div>
        <div class="card-f"><span>전체 본문은 JSON 데이터에서 확인합니다.</span><a class="link" href="/api/analyses/{h(run_id)}">JSON 데이터 →</a></div>
      </div>
      <div class="card" id="analysis-outcomes" style="overflow: hidden;">
        <div class="card-h"><h2>{icon_tile("target", "b-navy", small=True)}검증 결과</h2><span class="tiny muted">리포트 기준일 뒤 5거래일·20거래일 수익률을 시장 지수와 비교합니다.</span></div>
        {_outcome_block(outcomes)}
        <div class="card-f"><span>초과수익 = 종목 수익률 − 같은 기간 시장 지수 수익률</span><a class="link" href="{h(f"/outcomes?ticker={ticker_code}" if ticker_code else "/outcomes")}">이 종목 검증 결과 →</a></div>
      </div>
    </div>
    <div class="stack">
      <div class="card" id="analysis-provenance">
        <div class="card-h"><h2>{icon_tile("shield", "b-blue", small=True)}출처와 한계</h2></div>
        <div class="card-b" style="padding-top: 4px;">{provenance}</div>
      </div>
      <div class="card">
        <div class="card-h"><h2>{icon_tile("chevron", "b-grey", small=True)}다음 이동</h2></div>
        <div class="card-b" style="padding-top: 4px;">{next_links}</div>
      </div>
      {_notices("이 AI 리포트는 정보 제공용입니다. 투자 조언이나 매수·매도 지시가 아닙니다.", "이 사이트는 실계좌 주문을 하지 않습니다.")}
    </div>
  </div>
</section>
<script id="analysis-detail-payload" type="application/json">{_script_json(payload)}</script>
"""
    structured_data = _script_json(_analysis_detail_structured_data(model, payload))
    return render_shell(
        title=model["title"],
        description=description,
        body=body,
        active="/analyses",
        canonical_path=f"/analyses/{run_id}",
        site_base_url=site_base_url,
        extra_css=ANALYSIS_CSS,
        extra_head=f'<script type="application/ld+json">{structured_data}</script>',
        og_type="article",
    )
