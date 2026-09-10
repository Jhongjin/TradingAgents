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

from .design_system import TOKEN_STORAGE_KEY, badge, h, icon_tile, render_shell, stat_tile
from .plain_korean import exit_reason_label, market_label
from .seo import canonical_url

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
@media (max-width: 720px) { .paper-table { min-width: 640px; } }
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


def _holding_row(item: Mapping[str, Any]) -> str:
    code = str(item.get("ticker_code") or "")
    market = market_label(item.get("market"), code)
    return f"""<tr data-holding="{h(code)}" data-average="{h(item.get('average_price') or 0)}" data-quantity="{h(item.get('quantity') or 0)}">
      <td><a href="/stocks/{h(code)}"><b style="font-weight: 700;">{h(item.get('ticker_name') or code)}</b></a><small>{h(code)}{' · ' + h(market) if market else ''} · 진입 {h(item.get('entry_date') or '-')}</small></td>
      <td class="num">{h(item.get('quantity'))}주<small>평단 {h(_num(item.get('average_price')))}원</small></td>
      <td class="num" data-current>{h(_num(item.get('current_price'))) + '원' if item.get('current_price') else '불러오는 중'}</td>
      <td class="num">{h(_num(item.get('target_price')))}원<small>손절 {h(_num(item.get('stop_price')))}원</small></td>
      <td class="{_sign_class(item.get('unrealized_return'))} num" data-pnl>{h(_pct(item.get('unrealized_return')))}<small>{h(_num(item.get('unrealized_pnl')))}원</small></td>
    </tr>"""


def _closed_row(item: Mapping[str, Any]) -> str:
    code = str(item.get("ticker_code") or "")
    return f"""<tr>
      <td><a href="/stocks/{h(code)}"><b style="font-weight: 700;">{h(item.get('ticker_name') or code)}</b></a><small>{h(code)} · {h(item.get('entry_date') or '-')} → {h(item.get('exit_date') or '-')}</small></td>
      <td class="num">{h(item.get('quantity'))}주<small>{h(_num(item.get('entry_price')))}원 → {h(_num(item.get('exit_price')))}원</small></td>
      <td>{badge(exit_reason_label(item.get('exit_reason')), 'b-grey')}</td>
      <td class="{_sign_class(item.get('realized_return'))} num">{h(_pct(item.get('realized_return')))}<small>{h(_num(item.get('realized_pnl')))}원</small></td>
    </tr>"""


def _locked_positions_row(count: int) -> str:
    return f"""<tr class="paper-locked" data-paper-locked>
      <td colspan="5"><div class="paper-lock-copy">{badge("오늘 편입 " + str(count) + "종목", "b-amber")}<span>당일 편입 종목과 목표가·손절가는 데일리 패스에서 열립니다.</span><a class="link" href="/pricing">요금제 보기</a></div></td>
    </tr>"""


def _locked_closed_row(count: int) -> str:
    return f"""<tr class="paper-locked" data-paper-locked>
      <td colspan="4"><div class="paper-lock-copy">{badge("오늘 청산 " + str(count) + "건", "b-amber")}<span>당일 청산 내역은 데일리 패스에서 열립니다.</span><a class="link" href="/pricing">요금제 보기</a></div></td>
    </tr>"""


def render_paper_account_page(
    *,
    repo: StorageRepository | None = None,
    site_base_url: str | None = None,
    initial_cash: float = 10_000_000.0,
) -> str:
    from tradingagents.harness.paper_state import build_paper_account_payload

    from .billing import gate_paper_account_payload, resolve_plan_access

    # Server-rendered pages are public and cacheable, so they always show the
    # free view; a paid session swaps in today's rows from the API after load.
    payload = gate_paper_account_payload(
        build_paper_account_payload(repo, initial_cash=initial_cash),
        resolve_plan_access(None, None),
    ) or {}
    summary = payload.get("summary") or {}
    positions = payload.get("positions") or []
    closed = payload.get("closed") or []
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
    holdings_html = "\n".join(holdings_rows) or '<tr><td colspan="5" class="paper-empty">보유 중인 모의 종목이 없습니다. 다음 선별에서 조건을 통과하면 여기에 담깁니다.</td></tr>'

    closed_rows = [_closed_row(item) for item in closed[:50]]
    if locked_closed:
        closed_rows.insert(0, _locked_closed_row(locked_closed))
    closed_html = "\n".join(closed_rows) or '<tr><td colspan="4" class="paper-empty">아직 종료된 모의 매매가 없습니다. 목표가나 손절선에 닿으면 자동으로 정리되고 여기에 남습니다.</td></tr>'
    codes = [str(item.get("ticker_code")) for item in positions if item.get("ticker_code")]

    body = f"""
<div class="hero paper-head">
  <div class="shell">
    <p class="eyebrow">AI 모의 계좌</p>
    <h1>선별한 종목을 실제로 담고, 규칙대로 정리한 기록</h1>
    <p>매일 아침 선별을 통과한 종목을 시작 자금 {_num(initial_cash)}원의 모의 계좌로 매수합니다. 매수와 동시에 목표가와 손절선을 정하고, 다음 실행에서 그 선에 닿으면 자동으로 정리합니다. 실제 증권 계좌와 연결되지 않은 모의 기록입니다. 지난 기록은 모두 공개하며, 당일 편입·청산은 데일리 패스에서 열립니다.</p>
  </div>
</div>
<div class="shell">
  <div class="grid-5" style="margin-bottom: 18px;">{tiles}</div>

  <div class="card" style="margin-bottom: 18px;">
    <div class="card-h"><h2>{icon_tile("target", "b-teal", small=True)}보유 종목</h2><span class="badge b-grey">{len(positions) + locked_positions}종목</span></div>
    <div class="card-b paper-scroll">
      <table class="paper-table">
        <thead><tr><th>종목</th><th>수량 · 평단</th><th>현재가</th><th>목표가 · 손절가</th><th>평가손익</th></tr></thead>
        <tbody>{holdings_html}</tbody>
      </table>
    </div>
    <div class="card-f"><span>목표가와 손절가는 매수 시점에 규칙으로 정해집니다.</span><span>현재가는 최근 종가 기준입니다.</span></div>
  </div>

  <div class="card">
    <div class="card-h"><h2>{icon_tile("check", "b-blue", small=True)}종료된 매매</h2><span class="badge b-grey">{len(closed) + locked_closed}건</span></div>
    <div class="card-b paper-scroll">
      <table class="paper-table">
        <thead><tr><th>종목</th><th>수량 · 체결가</th><th>정리 사유</th><th>실현 손익</th></tr></thead>
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
