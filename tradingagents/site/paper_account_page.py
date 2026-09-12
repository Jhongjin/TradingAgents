"""`/paper`: the harness paper account — holdings, closed trades, totals.

Every pick the daily harness executes buys into one simulated account with a
target and a stop, and the next run sells it when a rule fires. This page is
the running record of that account. It is a simulation: no brokerage, no real
money, no order ever leaves the process.

Prices are not fetched while rendering (the page is public and cached); the
browser fills current prices from the public price API after load.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from tradingagents.storage import StorageRepository

from .design_system import TOKEN_STORAGE_KEY, badge, h, icon_tile, rating_label, render_shell, stat_tile
from .plain_korean import exit_reason_label, market_label
from .seo import ad_unit, canonical_url

PAPER_CSS = """
.paper-head { padding: 26px 0 18px; }
.paper-head h1 { font-size: 26px; margin-top: 8px; }
.paper-head p { color: var(--ink2); font-size: 13px; margin-top: 6px; max-width: 70ch; }
.paper-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.paper-table th { text-align: left; font-size: 11px; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--line); }
.paper-table td { padding: 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
.paper-table tr:last-child td { border-bottom: 0; }
.paper-table .num { font-variant-numeric: tabular-nums; }
.paper-table small { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }
.paper-up { color: var(--gain); font-weight: 700; }
.paper-down { color: var(--loss); font-weight: 700; }
.paper-flat { color: var(--ink2); font-weight: 600; }
.paper-empty { padding: 28px 12px; text-align: center; color: var(--muted); font-size: 13px; }
.paper-scroll { overflow-x: auto; }
.paper-curve { display: grid; gap: 12px; }
.paper-curve svg { width: 100%; height: auto; display: block; }
.paper-curve-legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--ink2); }
.paper-curve-legend span { display: inline-flex; align-items: center; gap: 6px; }
.paper-curve-legend i { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
.paper-curve-stats { display: flex; flex-wrap: wrap; gap: 18px; font-size: 13px; }
.paper-curve-stats b { font-variant-numeric: tabular-nums; }
.paper-rules { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px 18px; }
.paper-rules .kv { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; font-size: 13px; padding: 6px 0; border-bottom: 1px dashed var(--line); }
.paper-rule-history { grid-column: 1 / -1; margin-top: 4px; }
.paper-rule-history ul { margin: 6px 0 0; padding-left: 18px; display: grid; gap: 4px; font-size: 12px; color: var(--ink2); }
.paper-books { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
.paper-book { padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--bg); }
.paper-book .v { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin: 2px 0 4px; }
.paper-why-cell { max-width: 280px; }
.paper-why { display: block; margin-top: 4px; font-size: 12px; color: var(--ink2); line-height: 1.5; }
.paper-hash { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--ink2); }
.paper-backtest { border-style: dashed; }
.paper-backtest-notes { margin: 12px 0 0; padding-left: 18px; display: grid; gap: 4px; font-size: 12px; color: var(--muted); line-height: 1.6; }
@media (max-width: 900px) { .paper-table { min-width: 820px; } }
"""

PAPER_LOCK_CSS = """
.paper-locked td { color: var(--muted); }
.paper-locked .paper-lock-copy { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.paper-locked a { font-weight: 600; }
"""

PAPER_JS = """
(function(){
  // Paid members replace the free view with today's rows, using their session.
  var token = '';
  try { token = localStorage.getItem('__TOKEN_KEY__') || sessionStorage.getItem('__TOKEN_KEY__') || ''; } catch (e) {}
  if (token && document.querySelector('[data-paper-locked]')) {
    fetch('/api/paper-account', { headers: { 'Authorization': 'Bearer ' + token } })
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(payload){
        if (!payload || !payload.plan_gate || payload.plan_gate.locked !== false) return;
        window.location.reload();
      })
      .catch(function(){});
  }

  // Copying writes the same rows a member could type into their journal by
  // hand; the server decides which holdings that member is allowed to see.
  var copyButton = document.getElementById('paperCopyButton');
  var copyMessage = document.getElementById('paperCopyMessage');
  if (copyButton && token) {
    copyButton.hidden = false;
    copyButton.addEventListener('click', function(){
      copyButton.disabled = true;
      var previous = copyMessage ? copyMessage.textContent : '';
      if (copyMessage) copyMessage.textContent = '내 일지에 담는 중입니다.';
      fetch('/api/member/paper-account/copy', { method: 'POST', headers: { 'Authorization': 'Bearer ' + token } })
        .then(function(r){ return r.json().then(function(body){ return { ok: r.ok, body: body }; }); })
        .then(function(result){
          if (!copyMessage) return;
          if (!result.ok) {
            copyMessage.textContent = (result.body && (result.body.detail || result.body.error)) || '담지 못했습니다. 로그인 상태를 확인해 주세요.';
            return;
          }
          var copied = result.body.copied || 0;
          var skipped = result.body.skipped || 0;
          copyMessage.textContent = copied
            ? copied + '종목을 \'' + result.body.portfolio_name + '\' 일지에 담았습니다' + (skipped ? ' (이미 있던 ' + skipped + '종목 제외)' : '') + '.'
            : '새로 담을 종목이 없습니다. 이미 일지에 있습니다.';
        })
        .catch(function(){ if (copyMessage) copyMessage.textContent = previous; })
        .finally(function(){ copyButton.disabled = false; });
    });
  }

  var codes = __CODES__;
  if (!codes.length) return;
  fetch('/api/prices/latest?tickers=' + encodeURIComponent(codes.join(',')))
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(payload){
      if (!payload || !payload.prices) return;
      Object.keys(payload.prices).forEach(function(code){
        var close = Number(payload.prices[code].close);
        if (!close) return;
        var row = document.querySelector('[data-holding="' + code + '"]');
        if (!row) return;
        var average = Number(row.getAttribute('data-average'));
        var quantity = Number(row.getAttribute('data-quantity'));
        var priceNode = row.querySelector('[data-current]');
        if (priceNode) priceNode.textContent = close.toLocaleString('ko-KR') + '원';
        if (!average) return;
        var move = (close / average) - 1;
        var pnl = (close - average) * quantity;
        var node = row.querySelector('[data-pnl]');
        if (!node) return;
        node.className = move > 0 ? 'paper-up num' : (move < 0 ? 'paper-down num' : 'paper-flat num');
        node.innerHTML = (move >= 0 ? '+' : '') + (move * 100).toFixed(2) + '%<small>' +
          (pnl >= 0 ? '+' : '') + Math.round(pnl).toLocaleString('ko-KR') + '원</small>';
      });
    })
    .catch(function(){});
})();
"""


def _num(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value) * 100:+.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _sign_class(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "paper-flat"
    return "paper-up" if number > 0 else ("paper-down" if number < 0 else "paper-flat")


def _curve_svg(points: list[Mapping[str, Any]], *, width: int = 720, height: int = 180) -> str:
    """Two lines from the daily rows: the account and the benchmark, in percent."""

    account = [(index, item.get("total_return")) for index, item in enumerate(points)]
    benchmark = [(index, item.get("benchmark_return")) for index, item in enumerate(points)]
    values = [float(value) for _, value in account + benchmark if value is not None]
    if len(values) < 2:
        return ""
    low, high = min(values + [0.0]), max(values + [0.0])
    span = (high - low) or 0.02
    pad = span * 0.12
    low, high = low - pad, high + pad
    steps = max(len(points) - 1, 1)

    def path(series: list[tuple[int, Any]]) -> str:
        coordinates = []
        for index, value in series:
            if value is None:
                continue
            x = 8 + (index / steps) * (width - 16)
            y = height - 8 - ((float(value) - low) / (high - low)) * (height - 16)
            coordinates.append(f"{x:.1f},{y:.1f}")
        return " ".join(coordinates)

    zero_y = height - 8 - ((0.0 - low) / (high - low)) * (height - 16)
    account_path = path(account)
    benchmark_path = path(benchmark)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="모의 계좌 수익률 추이" preserveAspectRatio="none">'
        f'<line x1="8" y1="{zero_y:.1f}" x2="{width - 8}" y2="{zero_y:.1f}" stroke="var(--line-strong)" stroke-width="1" stroke-dasharray="3 4"/>'
        + (f'<polyline fill="none" stroke="var(--muted)" stroke-width="2" stroke-linejoin="round" points="{benchmark_path}"/>' if benchmark_path else "")
        + (f'<polyline fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" points="{account_path}"/>' if account_path else "")
        + "</svg>"
    )


def _curve_card(curve: Mapping[str, Any]) -> str:
    points = list(curve.get("points") or [])
    summary = curve.get("summary") or {}
    benchmark_name = summary.get("benchmark_name") or "KOSPI"
    if len(points) < 2:
        return f"""<div class="card" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("trend", "b-blue", small=True)}수익률 추이</h2><span class="badge b-grey">기록 {len(points)}일</span></div>
    <div class="card-b"><p class="small ink2">장 마감 뒤 하루 한 번 계좌를 기록합니다. 이틀치가 쌓이면 {h(benchmark_name)} 지수와 비교한 곡선이 여기에 그려집니다.</p></div>
  </div>"""

    risk = summary.get("risk") or {}
    stats = [
        f'<span>계좌 <b class="{_sign_class(summary.get("account_return"))}">{h(_pct(summary.get("account_return")))}</b></span>',
        f'<span>{h(benchmark_name)} <b>{h(_pct(summary.get("benchmark_return")))}</b></span>',
        f'<span>지수 대비 <b class="{_sign_class(summary.get("excess_return"))}">{h(_pct(summary.get("excess_return")))}</b></span>',
        f'<span>최대 낙폭 <b>{h(_pct(summary.get("max_drawdown")))}</b></span>',
    ]
    if risk.get("sharpe_ratio") is not None:
        stats.append(f'<span>샤프 <b>{h(risk.get("sharpe_ratio"))}</b></span>')
    if risk.get("annualized_volatility") is not None:
        stats.append(f'<span>변동성 <b>{h(_pct(risk.get("annualized_volatility")))}</b></span>')
    return f"""<div class="card" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("trend", "b-blue", small=True)}수익률 추이</h2><span class="badge b-grey">{h(summary.get("day_count"))}일 기록</span></div>
    <div class="card-b paper-curve">
      <div class="paper-curve-stats">{"".join(stats)}</div>
      {_curve_svg(points)}
      <div class="paper-curve-legend"><span><i style="background: var(--accent);"></i>모의 계좌</span><span><i style="background: var(--muted);"></i>{h(benchmark_name)} 지수</span></div>
    </div>
    <div class="card-f"><span>{h(summary.get("first_date"))}부터 기록</span><span>지수 대비는 기록을 시작한 날을 0%로 두고 비교합니다.</span></div>
  </div>"""


def _why_cell(item: Mapping[str, Any]) -> str:
    """The AI's verdict and its reason, the part that makes a record readable."""

    rating = item.get("decision_rating")
    confidence = item.get("decision_confidence")
    reason = str(item.get("entry_reason") or "").strip()
    if not rating and not reason:
        return '<span class="muted">-</span>'
    parts = []
    if rating:
        confidence_text = f' <span class="muted num">{float(confidence):.2f}</span>' if confidence is not None else ""
        parts.append(f'{badge(rating_label(rating), "b-violet", xs=True)}{confidence_text}')
    if reason:
        parts.append(f'<span class="paper-why">{h(reason)}</span>')
    return "".join(parts)


def _source_badge(item: Mapping[str, Any]) -> str:
    label = str(item.get("account_label") or "")
    if not label:
        return ""
    return badge(label, "b-teal" if item.get("account") == "kis" else "b-grey", xs=True)


def _books_card(books: list[Mapping[str, Any]]) -> str:
    """Each book's own totals, because each has its own capital and cash."""

    rows = []
    for book in books:
        summary = book.get("summary") or {}
        if not summary:
            continue
        rows.append(
            f'<div class="paper-book"><p class="label">{h(book.get("label"))}</p>'
            f'<p class="v num {_sign_class(summary.get("return"))}">{h(_pct(summary.get("return")))}</p>'
            f'<p class="tiny muted">평가 {h(_num(summary.get("equity")))}원 · 현금 {h(_num(summary.get("cash")))}원 · '
            f'시작 {h(_num(summary.get("initial_cash")))}원 · 보유 {h(summary.get("open_count") or 0)}종목</p></div>'
        )
    if not rows:
        return ""
    return f"""<div class="card" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("wallet", "b-teal", small=True)}계좌별 성적</h2><span class="badge b-grey">{len(rows)}개 계좌</span></div>
    <div class="card-b paper-books">{"".join(rows)}</div>
    <div class="card-f"><span>같은 선별 결과를 세 계좌가 각자 삽니다. AI 확인은 토론을 거치고, 규칙 전용은 점수만 보고, KIS는 실제 주문을 넣습니다.</span><span>AI 확인과 규칙 전용의 차이가 AI가 보탠 몫이고, KIS와의 차이가 주문 마찰입니다.</span></div>
  </div>"""


def _holding_row(item: Mapping[str, Any]) -> str:
    code = str(item.get("ticker_code") or "")
    market = market_label(item.get("market"), code)
    return f"""<tr data-holding="{h(code)}" data-average="{h(item.get('average_price') or 0)}" data-quantity="{h(item.get('quantity') or 0)}">
      <td><a href="/stocks/{h(code)}"><b style="font-weight: 700;">{h(item.get('ticker_name') or code)}</b></a> {_source_badge(item)}<small>{h(code)}{' · ' + h(market) if market else ''} · 진입 {h(item.get('entry_date') or '-')}</small></td>
      <td class="num">{h(item.get('quantity'))}주<small>평단 {h(_num(item.get('average_price')))}원</small></td>
      <td class="num" data-current>{h(_num(item.get('current_price'))) + '원' if item.get('current_price') else '불러오는 중'}</td>
      <td class="num">{h(_num(item.get('target_price')))}원<small>손절 {h(_num(item.get('stop_price')))}원</small></td>
      <td class="{_sign_class(item.get('unrealized_return'))} num" data-pnl>{h(_pct(item.get('unrealized_return')))}<small>{h(_num(item.get('unrealized_pnl')))}원</small></td>
      <td class="paper-why-cell">{_why_cell(item)}</td>
    </tr>"""


def _closed_row(item: Mapping[str, Any]) -> str:
    code = str(item.get("ticker_code") or "")
    return f"""<tr>
      <td><a href="/stocks/{h(code)}"><b style="font-weight: 700;">{h(item.get('ticker_name') or code)}</b></a> {_source_badge(item)}<small>{h(code)} · {h(item.get('entry_date') or '-')} → {h(item.get('exit_date') or '-')}</small></td>
      <td class="num">{h(item.get('quantity'))}주<small>{h(_num(item.get('entry_price')))}원 → {h(_num(item.get('exit_price')))}원</small></td>
      <td>{badge(exit_reason_label(item.get('exit_reason')), 'b-grey')}</td>
      <td class="{_sign_class(item.get('realized_return'))} num">{h(_pct(item.get('realized_return')))}<small>{h(_num(item.get('realized_pnl')))}원</small></td>
      <td class="paper-why-cell">{_why_cell(item)}</td>
    </tr>"""


def _paid_plans_enabled() -> bool:
    from .billing import paid_plans_enabled

    return paid_plans_enabled()


def _locked_positions_row(count: int) -> str:
    return f"""<tr class="paper-locked" data-paper-locked>
      <td colspan="6"><div class="paper-lock-copy">{badge("오늘 편입 " + str(count) + "종목", "b-amber")}<span>당일 편입 종목과 목표가·손절가는 데일리 패스에서 열립니다.</span><a class="link" href="/pricing">요금제 보기</a></div></td>
    </tr>"""


def _locked_closed_row(count: int) -> str:
    return f"""<tr class="paper-locked" data-paper-locked>
      <td colspan="5"><div class="paper-lock-copy">{badge("오늘 청산 " + str(count) + "건", "b-amber")}<span>당일 청산 내역은 데일리 패스에서 열립니다.</span><a class="link" href="/pricing">요금제 보기</a></div></td>
    </tr>"""


def _audit_payload(repo: Any) -> dict[str, Any]:
    from .audit_trail import build_audit_payload

    if repo is None:
        return {"status": "not_configured", "entries": [], "summary": {}}
    try:
        return build_audit_payload(repo.list_harness_runs(limit=40))
    except Exception:
        return {"status": "unavailable", "entries": [], "summary": {}}


def _audit_card(audit: Mapping[str, Any]) -> str:
    """Publish the chain so the record can be checked, not just believed."""

    entries = list(audit.get("entries") or [])
    if not entries:
        return ""
    summary = audit.get("summary") or {}
    rows = "".join(
        f'<tr><td>{h(item["as_of_date"])}<small>{h(item.get("broker") or "")}</small></td>'
        f'<td class="num">{h(item.get("step_count") or "-")}단계<small>{h(item.get("sequence_start"))}–{h(item.get("sequence_end"))}</small></td>'
        f'<td class="paper-hash num">{h(item.get("head_short") or "-")}</td>'
        f'<td>{"<a class=\'link\' href=\'" + h(item["detail_path"]) + "\'>실행 보기</a>" if item.get("detail_path") else ""}</td></tr>'
        for item in entries
    )
    return f"""<div class="card" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("shield", "b-violet", small=True)}기록 검증</h2><span class="badge b-grey">{h(summary.get("hashed_count") or 0)}회 실행 봉인</span></div>
    <div class="card-b paper-scroll">
      <p class="small ink2" style="margin-bottom: 10px;">실행의 모든 단계는 순서대로 해시로 이어 붙입니다. 지난 기록을 나중에 고치면 그 뒤의 해시가 전부 어긋나므로, 아래 값이 그대로라는 것은 기록이 그날 이후 손대지지 않았다는 뜻입니다.</p>
      <table class="paper-table">
        <thead><tr><th>실행일</th><th>단계</th><th>연결 해시</th><th></th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class="card-f"><span>해시는 실행이 끝난 시각에 확정되며 이후 바뀌지 않습니다.</span><span>선별과 주문 기록은 같은 사슬에 함께 묶입니다.</span></div>
  </div>"""


def _rules_payload(repo: Any) -> dict[str, Any]:
    from .paper_rules import build_rules_payload

    if repo is None:
        return {"status": "not_configured", "current": [], "changes": []}
    try:
        runs = [run for run in repo.list_harness_runs(limit=60) if str(run.get("broker") or "") == "paper"]
        return build_rules_payload(runs)
    except Exception:
        return {"status": "unavailable", "current": [], "changes": []}


def _rules_card(rules: Mapping[str, Any]) -> str:
    current = list(rules.get("current") or [])
    if not current:
        return ""
    cells = "".join(
        f'<div class="kv"><span>{h(item["label"])}<small class="muted"> {h(item["unit"])}</small></span><b class="num">{h(item["value"])}</b></div>'
        for item in current
    )
    changes = list(rules.get("changes") or [])
    if changes:
        rows = "".join(
            f'<li><b>{h(item["date"])}</b> {h(item["label"])} {h(item["before"])} → {h(item["after"])}</li>'
            for item in changes[:6]
        )
        history = f'<div class="paper-rule-history"><p class="label">규칙이 바뀐 날</p><ul>{rows}</ul></div>'
    else:
        history = f'<p class="small ink2">{h(rules.get("since") or "")}부터 같은 규칙으로 운영하고 있습니다.</p>'
    return f"""<div class="card" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("shield", "b-navy", small=True)}운영 규칙</h2><span class="badge b-grey">{h(rules.get("as_of") or "")} 기준</span></div>
    <div class="card-b paper-rules">{cells}{history}</div>
    <div class="card-f"><span>매수와 동시에 이 규칙으로 목표가와 손절가가 정해집니다.</span><span>규칙이 바뀌면 이전 성과와 단순 비교할 수 없습니다.</span></div>
  </div>"""


def _backtest_payload(repo: Any) -> dict[str, Any]:
    if repo is None:
        return {"status": "not_configured"}
    try:
        row = repo.latest_backtest_run()
    except Exception:
        return {"status": "unavailable"}
    if not row:
        return {"status": "empty"}
    return {
        "status": "available",
        "start_date": str(row.get("start_date") or ""),
        "end_date": str(row.get("end_date") or ""),
        "universe_size": row.get("universe_size"),
        "metrics": row.get("metrics_json") or {},
        "config": row.get("config_json") or {},
        "notes": list(row.get("notes") or []),
    }


def _backtest_card(backtest: Mapping[str, Any]) -> str:
    """The rules replayed over history, kept visibly apart from the record.

    A simulation and an executed record must not read as the same thing, so the
    card names itself a simulation, states its biases, and never appears inside
    the account's own numbers.
    """

    if backtest.get("status") != "available":
        return ""
    metrics = backtest.get("metrics") or {}
    config = backtest.get("config") or {}
    tiles = "".join(
        [
            stat_tile("trend", "b-grey", "기간 수익률", _pct(metrics.get("total_return")), f"{h(backtest.get('start_date'))} ~ {h(backtest.get('end_date'))}", value_class=_sign_class(metrics.get("total_return"))),
            stat_tile("shield", "b-grey", "최대 낙폭", _pct(metrics.get("max_drawdown")), "고점 대비 최대 하락"),
            stat_tile("check", "b-grey", "승률", _pct(metrics.get("hit_rate"), 1) if metrics.get("hit_rate") is not None else "-", f"거래 {metrics.get('trade_count') or 0}건"),
            stat_tile("target", "b-grey", "샤프 지수", h(metrics.get("sharpe_ratio") if metrics.get("sharpe_ratio") is not None else "-"), f"평균 보유 {metrics.get('average_holding_days') or '-'}일"),
        ]
    )
    excess = ""
    if metrics.get("benchmark_return") is not None:
        excess = f'<p class="small ink2">같은 기간 KOSPI {h(_pct(metrics.get("benchmark_return")))} · 지수 대비 <b class="{_sign_class(metrics.get("excess_return"))}">{h(_pct(metrics.get("excess_return")))}</b></p>'
    notes = "".join(f"<li>{h(note)}</li>" for note in (backtest.get("notes") or []))
    return f"""<div class="card paper-backtest" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("filter", "b-grey", small=True)}과거 시뮬레이션</h2><span class="badge b-amber">실행 기록 아님</span></div>
    <div class="card-b">
      <p class="small ink2" style="margin-bottom: 12px;">위 계좌 기록과는 별개입니다. 같은 선별 규칙을 과거 가격에 그대로 돌려 본 결과이며, 대상 종목 {h(backtest.get("universe_size"))}개를 하루 최대 {h(config.get("top_n") or "-")}종목까지 담는 조건으로 계산했습니다.</p>
      <div class="grid-4">{tiles}</div>
      {excess}
      <ul class="paper-backtest-notes">{notes}</ul>
    </div>
    <div class="card-f"><span>수수료와 증권거래세는 계좌와 같은 기준으로 반영했습니다.</span><span>과거 성과가 미래를 보장하지 않습니다.</span></div>
  </div>"""


def _factor_payload(repo: Any) -> dict[str, Any]:
    if repo is None:
        return {"status": "not_configured"}
    try:
        row = repo.latest_backtest_run(label="factors")
    except Exception:
        return {"status": "unavailable"}
    if not row:
        return {"status": "empty"}
    metrics = row.get("metrics_json") or {}
    return {
        "status": "available",
        "start_date": str(row.get("start_date") or ""),
        "end_date": str(row.get("end_date") or ""),
        "universe_size": row.get("universe_size"),
        "horizon_days": metrics.get("horizon_days"),
        "sample_dates": metrics.get("sample_dates"),
        "factors": metrics.get("factors") or [],
    }


def _factor_card(study: Mapping[str, Any]) -> str:
    """What each part of the score was worth, measured rather than assumed."""

    factors = list(study.get("factors") or [])
    if study.get("status") != "available" or not factors:
        return ""
    rows = "".join(
        f'<tr><td>{h(item.get("label"))}<small>{h(item.get("key"))}</small></td>'
        f'<td class="{_sign_class(item.get("information_coefficient"))} num">{h(f"{float(item.get("information_coefficient") or 0):+.4f}")}</td>'
        f'<td class="num">{h(item.get("ic_t_stat") if item.get("ic_t_stat") is not None else "-")}</td>'
        f'<td class="num">{h(_pct(item.get("positive_rate"), 0)) if item.get("positive_rate") is not None else "-"}</td>'
        f'<td class="{_sign_class(item.get("top_minus_bottom"))} num">{h(_pct(item.get("top_minus_bottom"))) if item.get("top_minus_bottom") is not None else "-"}</td></tr>'
        for item in factors
    )
    return f"""<div class="card paper-backtest" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("brain", "b-grey", small=True)}점수 요소별 예측력</h2><span class="badge b-grey">{h(study.get("horizon_days"))}일 기준</span></div>
    <div class="card-b paper-scroll">
      <p class="small ink2" style="margin-bottom: 10px;">규칙 점수를 이루는 각 요소가 {h(study.get("horizon_days"))}거래일 뒤 수익률을 실제로 맞혔는지 {h(study.get("sample_dates"))}개 시점에서 측정했습니다. 상관값이 0에 가까우면 그 요소는 예측에 기여하지 않았다는 뜻이고, t값이 2보다 작으면 잡음과 구분되지 않습니다.</p>
      <table class="paper-table">
        <thead><tr><th>요소</th><th>상관</th><th>t값</th><th>맞힌 비율</th><th>상위-하위 수익률</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class="card-f"><span>{h(study.get("start_date"))} ~ {h(study.get("end_date"))} · 대상 {h(study.get("universe_size"))}종목</span><span>측정 결과이며 매매 권유가 아닙니다.</span></div>
  </div>"""


def render_paper_account_page(
    *,
    repo: StorageRepository | None = None,
    site_base_url: str | None = None,
    initial_cash: float | None = None,
) -> str:
    from tradingagents.harness.paper_state import ACCOUNTS, build_combined_account_payload, default_initial_cash

    from .billing import gate_paper_account_payload, resolve_plan_access

    initial_cash = default_initial_cash() if initial_cash is None else initial_cash

    # Server-rendered pages are public and cacheable, so they always show the
    # free view; a paid session swaps in today's rows from the API after load.
    payload = gate_paper_account_payload(build_combined_account_payload(repo), resolve_plan_access(None, None)) or {}
    summary = payload.get("summary") or {}
    positions = payload.get("positions") or []
    closed = payload.get("closed") or []
    from .paper_snapshot_worker import build_paper_curve_payload

    curves = {key: build_paper_curve_payload(repo, account_key=key) for key, _label in ACCOUNTS}
    curve = curves.get("paper") or {}
    rules = _rules_payload(repo)
    audit = _audit_payload(repo)
    backtest = _backtest_payload(repo)
    factors = _factor_payload(repo)
    books = list(payload.get("accounts") or [])
    gate = payload.get("plan_gate") or {}
    locked_positions = int(gate.get("locked_position_count") or 0)
    locked_closed = int(gate.get("locked_closed_count") or 0)

    tiles = "".join(
        [
            stat_tile("wallet", "b-teal", "평가금액", f"{_num(summary.get('equity'))}원", f"현금 {_num(summary.get('cash'))}원"),
            stat_tile("trend", "b-blue", "누적 수익률", _pct(summary.get("total_return")), f"시작 자금 {_num(summary.get('initial_cash'))}원", value_class=_sign_class(summary.get("total_return"))),
            stat_tile("check", "b-violet", "실현 손익", f"{_num(summary.get('realized_pnl'))}원", f"종료 매매 {summary.get('closed_count') or 0}건", value_class=_sign_class(summary.get("realized_pnl"))),
            stat_tile("target", "b-amber", "보유 종목", f"{summary.get('open_count') or 0}종목", f"평가액 {_num(summary.get('holdings_value'))}원"),
            stat_tile("shield", "b-navy", "승률", _pct(summary.get("hit_rate"), 1) if summary.get("hit_rate") is not None else "-", f"이익 {summary.get('win_count') or 0}건"),
        ]
    )

    holdings_rows = [_holding_row(item) for item in positions]
    if locked_positions:
        holdings_rows.append(_locked_positions_row(locked_positions))
    holdings_html = "\n".join(holdings_rows) or '<tr><td colspan="6" class="paper-empty">보유 중인 모의 종목이 없습니다. 다음 선별에서 조건을 통과하면 여기에 담깁니다.</td></tr>'

    closed_rows = [_closed_row(item) for item in closed[:50]]
    if locked_closed:
        closed_rows.insert(0, _locked_closed_row(locked_closed))
    closed_html = "\n".join(closed_rows) or '<tr><td colspan="5" class="paper-empty">아직 종료된 모의 매매가 없습니다. 목표가나 손절선에 닿으면 자동으로 정리되고 여기에 남습니다.</td></tr>'
    codes = [str(item.get("ticker_code")) for item in positions if item.get("ticker_code")]

    body = f"""
<div class="hero paper-head">
  <div class="shell">
    <p class="eyebrow">AI 모의 계좌</p>
    <h1>선별한 종목을 실제로 담고, 규칙대로 정리한 기록</h1>
    <p>매일 아침 선별한 종목을 세 계좌가 각자 매수합니다. AI 토론을 거친 계좌, 규칙 점수만 보는 계좌, 그리고 실제로 KIS 모의투자에 주문을 넣는 계좌입니다. 세 성적을 나란히 두면 AI가 실제로 보탠 몫이 드러납니다. 매수와 동시에 목표가와 손절선을 정하고, 다음 실행에서 그 선에 닿으면 자동으로 정리합니다. 실제 증권 계좌와 연결되지 않은 모의 기록입니다. {'지난 기록은 모두 공개하며, 당일 편입·청산은 데일리 패스에서 열립니다.' if _paid_plans_enabled() else '편입과 청산, 목표가와 손절가까지 모두 공개합니다.'}</p>
  </div>
</div>
<div class="shell">
  <div class="grid-5" style="margin-bottom: 18px;">{tiles}</div>
  {ad_unit()}

  {_curve_card(curve)}

  {_books_card(books)}

  {_rules_card(rules)}

  {_audit_card(audit)}

  {_backtest_card(backtest)}

  {_factor_card(factors)}

  <div class="card" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("target", "b-teal", small=True)}보유 종목</h2><div class="row" style="gap: 8px; align-items: center;"><button class="btn sm" type="button" id="paperCopyButton" hidden>내 일지에 담기</button><span class="badge b-grey">{len(positions) + locked_positions}종목</span></div></div>
    <div class="card-b paper-scroll">
      <table class="paper-table">
        <thead><tr><th>종목</th><th>수량 · 평단</th><th>현재가</th><th>목표가 · 손절가</th><th>평가손익</th><th>담은 이유</th></tr></thead>
        <tbody>{holdings_html}</tbody>
      </table>
    </div>
    <div class="card-f"><span id="paperCopyMessage">목표가와 손절가는 매수 시점에 규칙으로 정해집니다.</span><span>현재가는 최근 종가 기준입니다.</span></div>
  </div>

  <div class="card">
    <div class="card-h"><h2>{icon_tile("check", "b-blue", small=True)}종료된 매매</h2><span class="badge b-grey">{len(closed) + locked_closed}건</span></div>
    <div class="card-b paper-scroll">
      <table class="paper-table">
        <thead><tr><th>종목</th><th>수량 · 체결가</th><th>정리 사유</th><th>실현 손익</th><th>담은 이유</th></tr></thead>
        <tbody>{closed_html}</tbody>
      </table>
    </div>
    <div class="card-f"><span>실현 손익은 매도 시 증권거래세를 반영한 금액입니다.</span><span>실계좌 주문은 일어나지 않습니다.</span></div>
  </div>
</div>
"""

    return render_shell(
        title="AI 모의 계좌",
        body=body,
        description="매일 선별한 한국 주식을 모의 계좌로 매수하고 목표가·손절선 규칙에 따라 정리한 기록입니다. 보유 종목, 종료된 매매, 누적 수익률을 공개합니다.",
        active="/paper",
        canonical_path="/paper",
        site_base_url=site_base_url,
        extra_css=PAPER_CSS + PAPER_LOCK_CSS,
        extra_js=PAPER_JS.replace("__CODES__", json.dumps(codes)).replace("__TOKEN_KEY__", TOKEN_STORAGE_KEY),
        og_image="/og/default.png",
    )
