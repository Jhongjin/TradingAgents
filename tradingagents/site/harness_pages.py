"""Server-rendered public pages for harness runs (`/harness`, `/harness/{id}`)."""

from __future__ import annotations

from typing import Any

from tradingagents.storage import StorageRepository

from .harness_api import HARNESS_NOTICES, build_harness_run_payload, build_harness_runs_payload
from .seo import canonical_url


def render_harness_page(
    *,
    repo: StorageRepository | None = None,
    harness_run_id: str | None = None,
    site_base_url: str | None = None,
    limit: int = 20,
) -> str:
    from .web_pages import PAGE_CSS, PAGE_JS, _h, _script_json, _top_nav

    runs_payload = build_harness_runs_payload(repo, limit=limit)
    run_payload = build_harness_run_payload(repo, harness_run_id=harness_run_id)
    if harness_run_id and run_payload is None:
        raise ValueError("Harness run not found")
    run_payload = run_payload or {"status": "empty", "run": None, "decisions": [], "summary": {}}
    run = run_payload.get("run") or {}
    decisions = run_payload.get("decisions") or []
    summary = run_payload.get("summary") or {}
    path = f"/harness/{harness_run_id}" if harness_run_id else "/harness"
    title = "AI 하네스 파이프라인 기록" if not run else f"하네스 {run.get('as_of_date')} 기록"
    description = "스크리너, 통계 예측, AI 토론, 리스크 게이트를 거친 일일 종목 선별 기록입니다. 모든 웹 실행은 dry-run이며 실제 주문과 연결되지 않습니다."

    status_text = {
        "available": "기록 있음",
        "empty": "기록 없음",
        "not_configured": "저장소 미연결",
        "not_migrated": "마이그레이션 필요",
        "unavailable": "저장소 오류",
    }.get(str(run_payload.get("status") or runs_payload.get("status")), "기록 없음")
    storage_error = run_payload.get("error") or runs_payload.get("error")

    def fmt_pct(value: Any) -> str:
        try:
            return f"{float(value) * 100:+.1f}%"
        except (TypeError, ValueError):
            return "-"

    def fmt_num(value: Any, digits: int = 0) -> str:
        try:
            return f"{float(value):,.{digits}f}"
        except (TypeError, ValueError):
            return "-"

    def outcome_cell(outcomes: list[dict[str, Any]]) -> str:
        if not outcomes:
            return "-"
        parts = []
        for outcome in outcomes:
            horizon = outcome.get("horizon_days")
            if outcome.get("status") == "completed":
                parts.append(f"{_h(horizon)}D {_h(fmt_pct(outcome.get('raw_return')))} <small>α {_h(fmt_pct(outcome.get('alpha_return')))}</small>")
            elif outcome.get("status") == "pending":
                parts.append(f"{_h(horizon)}D <small>대기</small>")
            else:
                parts.append(f"{_h(horizon)}D <small>데이터 없음</small>")
        return "<br>".join(parts)

    decision_rows = "\n".join(
        f"""<tr>
          <td>{_h(item.get('screener_rank') or '-')}</td>
          <td><a href="{_h(item.get('stock_path'))}">{_h(item.get('ticker_name') or item.get('ticker_code'))}</a><br><small>{_h(item.get('ticker_code'))} · {_h(item.get('market'))}</small></td>
          <td><span class="status-pill">{_h(item.get('stage_label'))}</span></td>
          <td>{_h(fmt_num(item.get('composite_score'), 3))}</td>
          <td>{_h(fmt_pct(item.get('forecast_expected_return')))}<br><small>상승 {_h(fmt_pct(item.get('forecast_probability_up')) if item.get('forecast_probability_up') is not None else '-')}</small></td>
          <td>{_h(item.get('confirmation_rating') or '-')}<br><small>{_h(fmt_num(item.get('confirmation_confidence'), 2))} · {_h(item.get('confirmation_source') or '-')}</small></td>
          <td>{_h(item.get('quantity') or '-')}<br><small>{_h(fmt_num(item.get('entry_price')))} / 손절 {_h(fmt_num(item.get('stop_price')))}</small></td>
          <td>{_h(item.get('order_status') or '-')}</td>
          <td>{outcome_cell(item.get('outcomes') or [])}</td>
          <td class="harness-reasons">{_h('; '.join(str(r) for r in (item.get('reasons') or [])[:3]))}</td>
        </tr>"""
        for item in decisions
    )
    if not decision_rows:
        if storage_error:
            decision_rows = f'<tr><td colspan="10">{_h(storage_error)}</td></tr>'
        else:
            decision_rows = '<tr><td colspan="10">아직 저장된 하네스 결정이 없습니다. 운영자가 <code>tradingagents pipeline --persist</code> 또는 크론을 실행하면 여기에 기록됩니다.</td></tr>'

    outcome_summary = run_payload.get("outcome_summary") or {}
    outcome_summary_html = " · ".join(
        f"{horizon}D: 승률 {_h(fmt_pct(stats.get('hit_rate')) if stats.get('hit_rate') is not None else '-')}, "
        f"평균 알파 {_h(fmt_pct(stats.get('average_alpha')))} ({_h(stats.get('completed'))}건 확정, {_h(stats.get('pending'))}건 대기)"
        for horizon, stats in outcome_summary.items()
    ) or "사후 결과는 5거래일/20거래일이 지난 뒤 자동 계산됩니다."

    run_rows = "\n".join(
        f"""<li><a href="{_h(item.get('detail_path'))}">{_h(item.get('as_of_date'))}</a> · {_h(item.get('confirmer'))} · 후보 {_h(item.get('candidate_count'))} · 가상주문 {_h(item.get('order_count'))} · {'dry-run' if item.get('dry_run') else _h(item.get('broker'))}</li>"""
        for item in runs_payload.get("items") or []
    ) or "<li>저장된 실행 기록이 없습니다.</li>"

    notices = "\n".join(f"<li>{_h(notice)}</li>" for notice in HARNESS_NOTICES)
    payload_json = _script_json({"runs": runs_payload, "run": run_payload})
    canonical = canonical_url(path, site_base_url=site_base_url) if site_base_url else path

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_h(title)} | TradingAgents Korea</title>
  <meta name="description" content="{_h(description)}">
  <link rel="canonical" href="{_h(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="ko_KR">
  <meta property="og:site_name" content="TradingAgents Korea">
  <meta property="og:title" content="{_h(title)}">
  <meta property="og:description" content="{_h(description)}">
  <style>{PAGE_CSS}
  .harness-table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
  .harness-table th, .harness-table td {{ padding: 0.55rem 0.5rem; border-bottom: 1px solid rgba(120,120,120,0.25); vertical-align: top; text-align: left; }}
  .harness-table small {{ opacity: 0.75; }}
  .harness-reasons {{ max-width: 22rem; }}
  .harness-scroll {{ overflow-x: auto; }}
  .harness-runs {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 0.35rem; }}
  </style>
</head>
<body class="public-home market-page harness-page">
  <a class="skip-link" href="#main-content">본문 바로가기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TradingAgents Korea home">
      <span class="brand-mark">TA</span>
      <span>TradingAgents Korea</span>
    </a>
    {_top_nav(label="공개 리서치", current="/harness")}
  </header>

  <main id="main-content" class="shell market-shell">
    <section class="summary-band" aria-labelledby="harness-title">
      <div>
        <p class="eyebrow">일일 하네스</p>
        <h1 id="harness-title">{_h(title)}</h1>
        <p class="asof">{_h(description)}</p>
        <div class="analysis-detail-actions">
          <a href="/harness">최근 실행</a>
          <a href="/api/harness/runs">원문 데이터</a>
          <a href="/features/methodology">분석 기준</a>
        </div>
      </div>
      <div class="decision-box">
        <span class="decision-label">상태</span>
        <strong>{_h(status_text)}</strong>
        <span>후보 {_h(summary.get('decision_count', 0))} · 가상주문 {_h(summary.get('ordered_count', 0))} · 탈락 {_h(summary.get('rejected_count', 0))}</span>
      </div>
    </section>

    <section class="report-section" aria-labelledby="harness-run-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">실행 요약</p>
          <h2 id="harness-run-title">{_h(run.get('as_of_date') or '최근 실행')} · {_h(run.get('confirmer') or '-')} · {_h(run.get('markets') or '-')}</h2>
        </div>
        <span class="status-pill">{'dry-run' if run.get('dry_run', True) else _h(run.get('broker'))}</span>
      </div>
      <p>유니버스 {_h(run.get('universe_size', '-'))} · 후보 {_h(run.get('candidate_count', '-'))} · 현금 {_h(fmt_num(run.get('cash_before')))} → {_h(fmt_num(run.get('cash_after')))} KRW</p>
      <p class="asof">사후 결과 · {outcome_summary_html} · <a href="/api/harness/outcomes">전체 기록</a></p>
      <div class="harness-scroll">
        <table class="harness-table">
          <thead>
            <tr><th>#</th><th>종목</th><th>단계</th><th>요인점수</th><th>예측(20일)</th><th>AI 확인</th><th>수량/가격</th><th>주문</th><th>사후 결과</th><th>사유</th></tr>
          </thead>
          <tbody>
            {decision_rows}
          </tbody>
        </table>
      </div>
    </section>

    <section class="report-section" aria-labelledby="harness-history-title">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">실행 이력</p>
          <h2 id="harness-history-title">최근 하네스 실행</h2>
        </div>
      </div>
      <ul class="harness-runs">
        {run_rows}
      </ul>
    </section>

    <section class="notice-strip" aria-label="투자 유의사항">
      <ul>
        {notices}
      </ul>
    </section>
  </main>

  <script id="harness-payload" type="application/json">{payload_json}</script>
  <script>{PAGE_JS}</script>
</body>
</html>"""
