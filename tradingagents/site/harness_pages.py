"""Server-rendered public pages for harness runs (`/harness`, `/harness/{id}`)."""

from __future__ import annotations

from typing import Any

from tradingagents.storage import StorageRepository

from .design_system import badge, h, icon, icon_tile, render_shell, stat_tile
from .harness_api import HARNESS_NOTICES, build_harness_run_payload, build_harness_runs_payload
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

HARNESS_CSS = """
.harness-head { padding: 26px 0 18px; }
.harness-head h1 { font-size: 26px; margin-top: 8px; }
.harness-table { min-width: 1040px; font-size: 13px; }
.harness-table td small { color: var(--muted); display: block; margin-top: 2px; font-size: 12px; }
.harness-reasons { max-width: 240px; color: var(--ink2); font-size: 12px; }
.runs { display: grid; gap: 0; }
.runs .kv { font-size: 13px; }
.notices { margin: 0; padding-left: 18px; font-size: 12px; color: var(--ink2); display: grid; gap: 4px; }
"""


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "-"


def _fmt_num(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _outcome_cell(outcomes: list[dict[str, Any]]) -> str:
    if not outcomes:
        return '<span class="muted">-</span>'
    parts = []
    for outcome in outcomes:
        horizon = outcome.get("horizon_days")
        if outcome.get("status") == "completed":
            raw = outcome.get("raw_return") or 0
            parts.append(f'<span class="num {"up" if float(raw) >= 0 else "down"}">{h(horizon)}D {h(_fmt_pct(raw))}</span> <small>α {h(_fmt_pct(outcome.get("alpha_return")))}</small>')
        elif outcome.get("status") == "pending":
            parts.append(f'{h(horizon)}D <small>대기</small>')
        else:
            parts.append(f'{h(horizon)}D <small>데이터 없음</small>')
    return "<br>".join(parts)


def render_harness_page(
    *,
    repo: StorageRepository | None = None,
    harness_run_id: str | None = None,
    site_base_url: str | None = None,
    limit: int = 20,
) -> str:
    from .billing import gate_harness_payload, latest_visible_run_id, resolve_plan_access
    from .web_pages import _script_json

    # Server-rendered pages are public and cacheable, so they always show the
    # free view: the newest run dated before today, no debate transcript. Paid
    # members open the same-day run through the API with their session.
    free_access = resolve_plan_access(None, None)
    runs_payload = build_harness_runs_payload(repo, limit=limit)
    target_run_id = harness_run_id or latest_visible_run_id(repo, free_access)
    run_payload = build_harness_run_payload(repo, harness_run_id=target_run_id) if target_run_id else build_harness_run_payload(repo)
    if harness_run_id and run_payload is None:
        raise ValueError("Harness run not found")
    run_payload = gate_harness_payload(run_payload, free_access) if run_payload else None
    run_payload = run_payload or {"status": "empty", "run": None, "decisions": [], "summary": {}}
    plan_gate = run_payload.get("plan_gate") or {}
    gate_notice = ""
    if plan_gate.get("locked"):
        gate_notice = f'<div class="soft harness-gate" style="padding: 12px 14px; margin-top: 12px; display: flex; gap: 10px; align-items: center; font-size: 13px;">{icon_tile("lock", "b-amber", small=True)}<span>{h(plan_gate.get("reason"))} <a class="link" href="/pricing">요금제 보기</a></span></div>'
    elif run_payload.get("run"):
        gate_notice = f'<div class="soft harness-gate" style="padding: 12px 14px; margin-top: 12px; display: flex; gap: 10px; align-items: center; font-size: 13px;">{icon_tile("lock", "b-amber", small=True)}<span>강세·약세·판정·리스크 점검 토론 전문은 데일리 패스 회원에게 열립니다. <a class="link" href="/pricing">요금제 보기</a></span></div>'
    run = run_payload.get("run") or {}
    decisions = run_payload.get("decisions") or []
    summary = run_payload.get("summary") or {}
    path = f"/harness/{harness_run_id}" if harness_run_id else "/harness"
    title = "종목 선별 기록" if not run else f"종목 선별 {run.get('as_of_date')} 기록"
    description = "스크리너, 통계 예측, AI 토론, 리스크 게이트를 거친 일일 종목 선별 기록입니다. 모든 웹 실행은 dry-run이며 실제 주문과 연결되지 않습니다."

    status_text = {
        "available": "기록 있음",
        "empty": "기록 없음",
        "not_configured": "저장소 미연결",
        "not_migrated": "마이그레이션 필요",
        "unavailable": "저장소 오류",
    }.get(str(run_payload.get("status") or runs_payload.get("status")), "기록 없음")
    storage_error = run_payload.get("error") or runs_payload.get("error")

    rows = []
    for item in decisions:
        stage = str(item.get("stage") or "")
        tone, ic = STAGE_TONE.get(stage, ("b-grey", "filter"))
        market = str(item.get("market") or "")
        rows.append(
            f"""<tr>
          <td class="muted num">{h(item.get('screener_rank') or '-')}</td>
          <td><a href="{h(item.get('stock_path'))}"><b style="font-weight: 700;">{h(item.get('ticker_name') or item.get('ticker_code'))}</b></a><small class="num">{h(item.get('ticker_code'))} · {h(market)}</small></td>
          <td>{badge(str(item.get('stage_label') or stage), tone, icon_name=ic)}</td>
          <td class="num">{h(_fmt_num(item.get('composite_score'), 3))}</td>
          <td class="num">{h(_fmt_pct(item.get('forecast_expected_return')))}<small>상승 {h(_fmt_pct(item.get('forecast_probability_up')) if item.get('forecast_probability_up') is not None else '-')}</small></td>
          <td>{badge(str(item.get('confirmation_rating')), 'b-violet') if item.get('confirmation_rating') else '<span class="muted">-</span>'}<small class="num">{h(_fmt_num(item.get('confirmation_confidence'), 2))} · {h(item.get('confirmation_source') or '-')}</small></td>
          <td class="num">{h(item.get('quantity') or '-')}<small>{h(_fmt_num(item.get('entry_price')))} / 손절 {h(_fmt_num(item.get('stop_price')))}</small></td>
          <td>{h(item.get('order_status') or '-')}</td>
          <td>{_outcome_cell(item.get('outcomes') or [])}</td>
          <td class="harness-reasons">{h('; '.join(str(r) for r in (item.get('reasons') or [])[:3]))}</td>
        </tr>"""
        )
    decision_rows = "\n".join(rows)
    if not decision_rows:
        if storage_error:
            decision_rows = f'<tr><td colspan="10" class="muted" style="text-align: center; padding: 24px;">{h(storage_error)}</td></tr>'
        else:
            decision_rows = '<tr><td colspan="10" class="muted" style="text-align: center; padding: 24px;">아직 저장된 선별 결과가 없습니다. 운영자가 <code>tradingagents pipeline --persist</code> 또는 크론을 실행하면 여기에 기록됩니다.</td></tr>'

    outcome_summary = run_payload.get("outcome_summary") or {}
    outcome_summary_html = " · ".join(
        f"{horizon}D: 승률 {h(_fmt_pct(stats.get('hit_rate')) if stats.get('hit_rate') is not None else '-')}, "
        f"평균 초과수익 {h(_fmt_pct(stats.get('average_alpha')))} ({h(stats.get('completed'))}건 확정, {h(stats.get('pending'))}건 대기)"
        for horizon, stats in outcome_summary.items()
    ) or "검증 결과는 5거래일/20거래일이 지난 뒤 자동 계산됩니다."

    run_rows = "".join(
        f'<div class="kv"><span><a class="link" href="{h(item.get("detail_path"))}">{h(item.get("as_of_date"))}</a> <span class="muted">· {h(item.get("confirmer"))}</span></span><span class="num muted">후보 {h(item.get("candidate_count"))} · 모의 주문 {h(item.get("order_count"))} · {"dry-run" if item.get("dry_run") else h(item.get("broker"))}</span></div>'
        for item in runs_payload.get("items") or []
    ) or '<p class="muted small">저장된 실행 기록이 없습니다.</p>'

    notices = "".join(f"<li>{h(notice)}</li>" for notice in HARNESS_NOTICES)
    payload_json = _script_json({"runs": runs_payload, "run": run_payload})
    broker_badge = badge("dry-run" if run.get("dry_run", True) else str(run.get("broker") or "-"), "b-grey" if run.get("dry_run", True) else "b-teal")

    tiles = "".join(
        [
            stat_tile("layers", "b-navy", "대상 종목", _fmt_num(run.get("universe_size")) if run else "–", str(run.get("markets") or "KOSPI · KOSDAQ")),
            stat_tile("filter", "b-blue", "후보", str(summary.get("decision_count", 0)), "후보"),
            stat_tile("check", "b-teal", "모의 주문", str(summary.get("ordered_count", 0)), f"탈락 {summary.get('rejected_count', 0)}"),
            stat_tile("wallet", "b-amber", "현금", _fmt_num(run.get("cash_after")) if run.get("cash_after") is not None else "–", f"실행 전 {_fmt_num(run.get('cash_before'))}" if run.get("cash_before") is not None else "기록 없음"),
        ]
    )

    body = f"""
<section class="hero harness-head">
  <div class="shell">
    <div class="row between wrap">
      <div>
        <div class="row wrap">{badge("선별 기록", "b-teal", icon_name="layers")}{badge(status_text, "b-grey")}{broker_badge}</div>
        <h1>{h(title)}</h1>
        <p class="small ink2" style="margin-top: 6px; max-width: 720px;">{h(description)}</p>
        {gate_notice}
      </div>
      <div class="row wrap"><a class="btn sm" href="/harness">최근 실행</a><a class="btn sm" href="/api/harness/runs">JSON 데이터</a><a class="btn sm ghost" href="/features/methodology">분석 기준 →</a></div>
    </div>
    <div class="grid-4" style="margin-top: 18px;">{tiles}</div>
  </div>
</section>
<section class="block" style="padding-bottom: 28px;">
  <div class="shell stack" style="gap: 20px;">
    <div class="card" style="overflow: hidden;">
      <div class="card-h"><h2>{icon_tile("trend", "b-teal", small=True)}실행 요약 · {h(run.get('as_of_date') or '최근 실행')} <span class="muted" style="font-weight: 500;">· {h(run.get('confirmer') or '-')} · {h(run.get('markets') or '-')}</span></h2><span class="tiny muted">검증 결과 · {outcome_summary_html} · <a class="link" href="/api/harness/outcomes">전체 기록</a></span></div>
      <div class="table-wrap">
        <table class="harness-table">
          <thead><tr><th>#</th><th>종목</th><th>단계</th><th>요인점수</th><th>예측(20일)</th><th>AI 확인</th><th>수량/가격</th><th>주문</th><th>검증 결과</th><th>사유</th></tr></thead>
          <tbody>{decision_rows}</tbody>
        </table>
      </div>
      <div class="card-f"><span>각 단계는 실행 기록에 해시로 묶여 기록됩니다.</span><span>{icon("shield", 12)} 웹 실행은 항상 dry-run</span></div>
    </div>
    <div class="grid-main">
      <div class="card">
        <div class="card-h"><h2>{icon_tile("clock", "b-grey", small=True)}최근 종목 선별</h2><a class="link tiny" href="/api/harness/runs">JSON →</a></div>
        <div class="card-b runs" style="padding-top: 4px;">{run_rows}</div>
      </div>
      <div class="soft" style="padding: 16px 18px;">
        <p class="label">투자 유의사항</p>
        <ul class="notices" style="margin-top: 8px;">{notices}</ul>
      </div>
    </div>
  </div>
</section>
<script id="harness-payload" type="application/json">{payload_json}</script>
"""
    structured: list[dict[str, Any]] = [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "오늘", "item": canonical_url("/", site_base_url=site_base_url)},
            {"@type": "ListItem", "position": 2, "name": "선별 기록", "item": canonical_url("/harness", site_base_url=site_base_url)},
        ] + ([{"@type": "ListItem", "position": 3, "name": str(run.get("as_of_date")), "item": canonical_url(path, site_base_url=site_base_url)}] if harness_run_id and run else [])},
    ]
    if run:
        structured.append({
            "@type": "Article",
            "headline": title,
            "description": f"{run.get('as_of_date')} 종목 선별: 대상 {run.get('universe_size') or '-'}개, 후보 {summary.get('decision_count', 0)}개, 모의 주문 {summary.get('ordered_count', 0)}개.",
            "datePublished": str(run.get("as_of_date")),
            "dateModified": str(run.get("created_at") or run.get("as_of_date"))[:19],
            "inLanguage": "ko-KR",
            "author": {"@id": f"{(site_base_url or '').rstrip('/')}/#organization"},
            "publisher": {"@id": f"{(site_base_url or '').rstrip('/')}/#organization"},
            "mainEntityOfPage": canonical_url(path, site_base_url=site_base_url),
        })
    return render_shell(
        title=f"{title} | TradingAgents Korea",
        description=description,
        body=body,
        active="/harness",
        canonical_path=path,
        site_base_url=site_base_url,
        extra_css=HARNESS_CSS,
        structured_data=structured,
        og_type="article" if run else "website",
    )
