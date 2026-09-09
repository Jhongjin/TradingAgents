"""Operator console `/admin` on the shared design system.

The page never embeds worker secrets: the token lives in the browser session and
is sent only as a request header by ``web_pages.ADMIN_PAGE_JS``. Every id, class and
data-attribute that script binds is kept here.
"""

from __future__ import annotations

from .design_system import badge, h, icon, icon_tile, render_shell

ADMIN_CSS = """
.admin-head { padding: 26px 0 18px; }
.admin-head h1 { font-size: 24px; margin-top: 8px; }
.admin-head p.lead { margin-top: 6px; max-width: 640px; color: var(--ink2); font-size: 14px; }
.admin-hero-grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 20px; align-items: start; }
.token-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.principles > div { padding: 12px 14px; }
.principles b { display: block; font-size: 14px; margin-top: 4px; }
.principles small { color: var(--muted); font-size: 12px; display: block; margin-top: 2px; }
.admin-cells { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.admin-cells > div { border: 1px solid var(--line); border-left: 3px solid var(--line-strong); border-radius: 10px; padding: 10px 12px; background: var(--bg); display: grid; gap: 2px; }
.admin-cells > div > span { font-size: 12px; color: var(--muted); }
.admin-cells > div > strong { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; }
.admin-cells > div > small { font-size: 12px; color: var(--ink2); }
.admin-cells .is-ok { border-left-color: var(--accent); }
.admin-cells .is-warn { border-left-color: var(--amber); }
.admin-cells .is-error { border-left-color: var(--gain); }
.admin-cells .is-waiting { border-left-color: var(--line-strong); }
.admin-recent { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.admin-recent:empty { display: none; }
.admin-recent-list { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; background: var(--bg); }
.admin-recent-list span { font-size: 11px; color: var(--muted); }
.admin-recent-list strong { display: block; font-size: 13px; margin-top: 2px; }
.admin-recent-list ul { margin: 6px 0 0; padding-left: 16px; font-size: 12px; color: var(--ink2); display: grid; gap: 3px; }
.admin-recent-list a { color: var(--accent-ink); }
.admin-out { margin: 12px 0 0; max-height: 280px; overflow: auto; font-size: 12px; line-height: 1.5; padding: 10px 12px; border-radius: 10px; background: var(--bg2); color: var(--ink2); white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.admin-controls { display: grid; grid-template-columns: minmax(96px, 0.5fr) repeat(2, minmax(0, 1fr)); gap: 8px; align-items: end; }
.admin-controls label { display: grid; gap: 4px; }
.admin-controls .field { height: 38px; }
.admin-limit-hint { display: block; margin-top: 6px; }
.admin-help { display: block; margin-top: 8px; font-size: 12px; color: var(--muted); }
.admin-card-panel { margin-top: 12px; }
.admin-card-panel .admin-cells { grid-template-columns: 1fr; }
.check-row { display: flex; gap: 12px; flex-wrap: wrap; font-size: 13px; color: var(--ink2); }
.check-row label { display: inline-flex; gap: 6px; align-items: center; }
.admin-token-ready #adminTokenForm { border-color: var(--accent); }
@media (max-width: 960px) {
  .admin-hero-grid, .admin-cells, .admin-recent { grid-template-columns: 1fr; }
  .admin-controls { grid-template-columns: 1fr; }
}
"""


def _cell(kind: str, label: str, value: str, note: str) -> str:
    return f'<div class="{kind} is-waiting"><span>{h(label)}</span><strong>{h(value)}</strong><small>{h(note)}</small></div>'


def _action_card(
    *,
    icon_name: str,
    tone: str,
    eyebrow: str,
    heading: str,
    pill: str,
    limit_id: str,
    limit_max: int,
    limit_value: int,
    hint_id: str,
    dry_action: str,
    run_action: str,
    run_label: str,
    help_text: str,
    panel_id: str,
    panel_label: str,
    panel_note: str,
    output_id: str,
) -> str:
    return f"""<div class="card">
  <div class="card-h"><h2>{icon_tile(icon_name, tone, small=True)}{h(heading)}</h2>{badge(pill, "b-grey", xs=True)}</div>
  <div class="card-b">
    <p class="label" style="margin-bottom: 8px;">{h(eyebrow)}</p>
    <div class="admin-controls">
      <label for="{limit_id}"><span class="label">이번 실행 건수</span><input class="field" id="{limit_id}" type="number" min="1" max="{limit_max}" value="{limit_value}"></label>
      <button class="btn sm" type="button" data-admin-action="{dry_action}">대상 미리보기</button>
      <button class="btn sm primary" type="button" data-admin-action="{run_action}">{h(run_label)}</button>
    </div>
    <small class="admin-limit-hint tiny muted" id="{hint_id}">현재 최대 {limit_max}건</small>
    <small class="admin-help">{h(help_text)}</small>
    <div class="admin-card-panel"><div class="admin-cells" id="{panel_id}" aria-live="polite">{_cell("action-cell", panel_label, "대기", panel_note)}</div></div>
    <pre class="admin-out" id="{output_id}">대기 중</pre>
  </div>
</div>"""


def render_admin_console_page(*, site_base_url: str | None = None) -> str:
    """Render a noindex operator console that never embeds worker secrets."""

    from .web_pages import ADMIN_PAGE_JS, _positive_env_int

    analysis_worker_max = _positive_env_int("TRADINGAGENTS_WORKER_MAX_REQUESTS", 1)
    outcome_worker_max = _positive_env_int("TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS", 20)
    paper_worker_max = _positive_env_int("TRADINGAGENTS_PAPER_SIMULATION_WORKER_MAX_RUNS", 20)
    outcome_default = min(10, outcome_worker_max)
    paper_default = min(10, paper_worker_max)

    principles = "".join(
        f'<div class="soft"><span class="label">{h(label)}</span><b>{h(value)}</b><small>{h(note)}</small></div>'
        for label, value, note in (
            ("상태 점검", "수동 확인", "배포 정보, 저장소, KRX 응답을 같은 패널에서 확인합니다."),
            ("작업자", "운영 토큰 입력", "HTML에는 비밀값을 싣지 않고 세션 스토리지에만 둡니다."),
            ("대기열", "대상 미리보기", "저장 전에 어떤 항목이 처리될지 먼저 확인합니다."),
            ("경계", "주문 없음", "운영 콘솔에도 실거래 주문 경로는 없습니다."),
        )
    )
    workflow = "".join(
        f'<div class="soft"><span class="tiny muted num">{number}</span><b>{h(title)}</b><small>{h(note)}</small></div>'
        for number, title, note in (
            ("01", "상태 점검", "페이지 진입 시 자동 조회합니다. 필요하면 KRX와 외부 데이터 응답 점검을 더합니다."),
            ("02", "대상 미리보기", "저장 없이 이번 실행 후보와 제한값을 확인합니다."),
            ("03", "처리 시작", "미리 본 대상 중 제한된 건수만 실제로 저장합니다."),
            ("04", "실행 기록 확인", "결과 데이터와 상태 패널을 함께 보고 다음 대기열을 정합니다."),
        )
    )

    requests_card = _action_card(
        icon_name="brain",
        tone="b-violet",
        eyebrow="분석 요청 대기열",
        heading="AI 리포트 생성",
        pill="운영 권한",
        limit_id="adminRequestLimit",
        limit_max=analysis_worker_max,
        limit_value=analysis_worker_max,
        hint_id="adminRequestLimitHint",
        dry_action="requests-dry-run",
        run_action="requests-process",
        run_label="대기열 처리 시작",
        help_text="대상 미리보기는 저장 없이 이번 후보만 보여줍니다. 대기열 처리 시작은 요청 상태를 처리 중으로 바꾸고 AI 리포트를 저장합니다.",
        panel_id="adminRequestsPanel",
        panel_label="분석 리포트",
        panel_note="회원이 요청한 종목을 AI 리포트로 생성합니다.",
        output_id="adminRequestsOutput",
    )
    outcomes_card = _action_card(
        icon_name="target",
        tone="b-blue",
        eyebrow="검증 결과 작업",
        heading="5일/20일 검증 결과",
        pill="5일 / 20일",
        limit_id="adminOutcomeLimit",
        limit_max=outcome_worker_max,
        limit_value=outcome_default,
        hint_id="adminOutcomeLimitHint",
        dry_action="outcomes-dry-run",
        run_action="outcomes-process",
        run_label="성과 검증 저장",
        help_text="대상 미리보기는 저장 없이 후보 리포트만 보여줍니다. 성과 검증 저장은 5일/20일 수익률과 시장 대비 차이를 저장합니다.",
        panel_id="adminOutcomesPanel",
        panel_label="검증 결과",
        panel_note="완료 리포트의 5일/20일 이후 성과를 저장합니다.",
        output_id="adminOutcomesOutput",
    )
    paper_card = _action_card(
        icon_name="wallet",
        tone="b-amber",
        eyebrow="AI 모의 매매",
        heading="모의 매매 기록 저장",
        pill="주문 없음",
        limit_id="adminPaperSimulationLimit",
        limit_max=paper_worker_max,
        limit_value=paper_default,
        hint_id="adminPaperSimulationLimitHint",
        dry_action="paper-dry-run",
        run_action="paper-process",
        run_label="모의 매매 기록 저장",
        help_text="대상 미리보기는 저장 없이 후보 리포트와 보유 중인 모의 포지션만 보여줍니다. 기록 저장은 실제 주문 없이 모의 매수·매도와 복기 사유만 저장합니다.",
        panel_id="adminPaperSimulationPanel",
        panel_label="AI 모의 매매",
        panel_note="완료 리포트 기준의 모의 매수·매도 근거를 저장합니다. 실제 주문은 없습니다.",
        output_id="adminPaperSimulationOutput",
    )

    body = f"""
<section class="hero admin-head">
  <div class="shell admin-hero-grid">
    <div>
      {badge("운영자 전용 · 비밀값 저장 없음", "b-navy", icon_name="shield")}
      <h1>운영 콘솔</h1>
      <p class="lead">운영 토큰은 브라우저 세션에만 보관되고 운영 API 호출 헤더로만 전송됩니다. 관리자 계정으로 로그인한 경우 토큰 없이도 실행할 수 있습니다.</p>
      <div class="row wrap" style="margin-top: 14px;">
        <a class="btn sm" href="/admin/members">{icon("users", 14)}회원 관리</a>
        <a class="btn sm ghost" href="/harness">{icon("filter", 14)}선별 기록</a>
        <a class="btn sm ghost" href="/outcomes">{icon("target", 14)}성과 검증</a>
      </div>
    </div>
    <form class="card" id="adminTokenForm">
      <div class="card-h"><h2>{icon_tile("lock", "b-navy", small=True)}운영 토큰</h2>{badge("세션 저장", "b-grey", xs=True)}</div>
      <div class="card-b">
        <label for="adminWorkerToken" class="label" style="display: block; margin-bottom: 6px;">토큰 값</label>
        <input class="field" id="adminWorkerToken" name="worker_token" type="password" autocomplete="off" placeholder="Vercel 운영 토큰 값">
        <div class="token-actions">
          <button class="btn sm primary" type="submit">세션에 저장</button>
          <button class="btn sm" type="button" data-admin-token-clear>토큰 지우기</button>
        </div>
      </div>
      <div class="card-f"><small id="adminTokenState">Vercel 환경변수 TRADINGAGENTS_WORKER_TOKEN, DASHBOARD_ADMIN_TOKEN, OPERATOR_ACCESS_CODE 중 설정된 값을 입력하세요. 운영 버튼은 토큰 입력 후 활성화됩니다.</small></div>
    </form>
  </div>
</section>
<section class="block"><div class="shell stack">
  <div class="grid-4 principles" aria-label="운영 기준 요약">{principles}</div>
  <div class="card">
    <div class="card-h"><h2>{icon_tile("layers", "b-blue", small=True)}권장 운영 순서</h2></div>
    <div class="card-b grid-4 principles">{workflow}</div>
  </div>
</div></section>
<section class="block"><div class="shell">
  <div class="card">
    <div class="card-h"><h2>{icon_tile("zap", "b-teal", small=True)}대기열 현황과 최근 결과</h2><div class="row"><span class="tiny muted">분석 요청, 검증 결과, 모의 매매 처리 상태를 요약합니다.</span><button class="btn sm primary" type="button" data-admin-ops-summary>운영 요약 조회</button></div></div>
    <div class="card-b">
      <div class="admin-cells" id="adminOpsSummary" aria-live="polite">{_cell("ops-cell", "대기열", "대기", "운영 토큰 저장 후 운영 요약을 조회하세요.")}</div>
      <div class="admin-recent" id="adminRecentPanel" aria-label="최근 운영 항목"></div>
      <pre class="admin-out" id="adminOpsOutput">대기 중</pre>
    </div>
  </div>
</div></section>
<section class="block"><div class="shell">
  <div class="card">
    <div class="card-h"><h2>{icon_tile("shield", "b-teal", small=True)}서비스 상태</h2>
      <div class="row wrap"><div class="check-row"><label><input id="adminProbeKrx" type="checkbox"> KRX 응답 점검</label><label><input id="adminProbeVendors" type="checkbox"> 외부 데이터 응답 점검</label></div><button class="btn sm" type="button" data-admin-readiness>상태 확인</button></div>
    </div>
    <div class="card-b">
      <div class="admin-cells" id="adminReadinessPanel" aria-live="polite">{_cell("readiness-cell", "상태", "대기", "상태 점검을 실행하면 배포와 외부 데이터 상태를 요약합니다.")}</div>
      <pre class="admin-out" id="adminReadinessOutput">대기 중</pre>
    </div>
  </div>
</div></section>
<section class="block" style="padding-bottom: 28px;"><div class="shell">
  <div class="grid-3" aria-label="운영 작업" style="align-items: start;">
    {requests_card}
    {outcomes_card}
    {paper_card}
  </div>
</div></section>
"""
    return render_shell(
        title="운영 콘솔 | TradingAgents Korea",
        description="TradingAgents Korea 운영 대기열과 상태를 점검하는 운영 콘솔입니다.",
        body=body,
        active=None,
        canonical_path="/admin",
        site_base_url=site_base_url,
        extra_css=ADMIN_CSS,
        extra_js=ADMIN_PAGE_JS,
        noindex=True,
        search=False,
    )


__all__ = ["render_admin_console_page"]
