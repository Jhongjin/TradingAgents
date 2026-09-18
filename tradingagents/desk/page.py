"""The desk's one page.

Self-contained rather than built on the site's design system: this is not the
product, it must not pick up the product's navigation, and it has to keep
working when nothing else does. One file, no build step, no network fonts.
"""

from __future__ import annotations

_CSS = """
:root {
  --bg: #0f1216; --panel: #161b22; --line: #232a33;
  --ink: #e8edf3; --ink2: #9aa7b4; --muted: #6b7785;
  --up: #ff5c60; --down: #4d9bff; --accent: #4ee6a8; --warn: #f0b429;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--ink); font-variant-numeric: tabular-nums;
  font-family: "Pretendard", -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  padding: 28px 24px 64px; line-height: 1.5;
}
.wrap { max-width: 1040px; margin: 0 auto; }
header { display: flex; align-items: baseline; gap: 14px; margin-bottom: 22px; }
h1 { font-size: 22px; letter-spacing: -0.02em; }
.badge {
  font-size: 12px; font-weight: 700; letter-spacing: 0.06em; padding: 3px 9px;
  border-radius: 999px; border: 1px solid currentColor;
  background: transparent; cursor: pointer; font-family: inherit;
}
.suggest { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 7px; }
.suggest button {
  background: transparent; border: 1px solid var(--line); color: var(--ink2);
  font-size: 13px; font-weight: 400; padding: 5px 11px; border-radius: 999px;
}
.suggest button:hover { color: var(--ink); border-color: var(--accent); }
.badge.paper { color: var(--accent); }
.badge.live { color: var(--warn); }
.local { margin-left: auto; font-size: 12px; color: var(--muted); }
.tab {
  font-size: 13px; color: var(--ink2); text-decoration: none; padding: 4px 11px;
  border: 1px solid var(--line); border-radius: 999px;
}
.tab:hover { color: var(--ink); border-color: var(--ink2); }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin-bottom: 18px; }
.panel h2 { font-size: 13px; font-weight: 600; color: var(--ink2); letter-spacing: 0.04em; margin-bottom: 14px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; }
.stat .k { font-size: 12px; color: var(--muted); }
.stat .v { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; margin-top: 3px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: right; font-weight: 500; color: var(--muted); font-size: 12px; padding: 0 0 9px; border-bottom: 1px solid var(--line); }
th:first-child, td:first-child { text-align: left; }
td { text-align: right; padding: 11px 0; border-bottom: 1px solid var(--line); }
tr:last-child td { border-bottom: 0; }
.name { font-weight: 600; }
.code { color: var(--muted); font-size: 12px; margin-left: 7px; }
.up { color: var(--up); } .down { color: var(--down); }
form { display: flex; gap: 9px; }
input {
  flex: 0 0 180px; background: #0d1117; border: 1px solid var(--line); color: var(--ink);
  border-radius: 8px; padding: 9px 12px; font: inherit;
}
input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
button {
  background: var(--accent); color: #07130d; border: 0; border-radius: 8px;
  padding: 9px 18px; font: inherit; font-weight: 700; cursor: pointer;
}
.msg { color: var(--warn); font-size: 13px; margin-top: 10px; word-break: break-all; }
.empty { color: var(--muted); font-size: 13px; padding: 10px 0; }
footer { color: var(--muted); font-size: 12px; margin-top: 26px; line-height: 1.7; }
.hint { color: var(--muted); font-size: 12px; font-weight: 400; }
.order { flex-wrap: wrap; align-items: flex-end; gap: 12px; }
.order label { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--muted); }
.order input { flex: 0 0 120px; width: 120px; }
.order select {
  background: #0d1117; border: 1px solid var(--line); color: var(--ink);
  border-radius: 8px; padding: 9px 12px; font: inherit; width: 96px;
}
.order button { background: var(--warn); color: #1a1205; }
.order button[disabled] { opacity: .4; cursor: not-allowed; }
.amount { font-size: 15px; font-weight: 700; margin-top: 12px; }
.cancel {
  background: transparent; border: 1px solid var(--line); color: var(--ink2);
  font-size: 12px; font-weight: 500; padding: 5px 12px; border-radius: 7px;
}
.cancel:hover { color: var(--up); border-color: var(--up); }
.cancel[disabled] { opacity: .3; cursor: not-allowed; }
"""

_JS = """
const won = (v) => v == null ? '–' : Math.round(v).toLocaleString('ko-KR') + '원';
const pct = (v) => v == null ? '–' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
const cls = (v) => v == null || v === 0 ? '' : (v > 0 ? 'up' : 'down');
const el = (id) => document.getElementById(id);

async function ask(path, options) {
  const response = await fetch(path, Object.assign({ credentials: 'same-origin' }, options || {}));
  const body = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok && !body.error) body.error = 'HTTP ' + response.status;
  return body;
}

async function loadAccount() {
  const data = await ask('/api/account');
  if (data.error) { el('account-msg').textContent = data.error; return; }
  el('account-msg').textContent = '';
  const s = data.summary || {};
  el('stats').innerHTML = [
    ['총자산', won(s.total_assets), ''],
    ['예수금', won(s.cash), ''],
    ['출금가능', won(s.withdrawable), ''],
    ['평가손익', won(s.unrealised), cls(s.unrealised)],
    ['수익률', pct(s.return_pct), cls(s.return_pct)],
  ].map(([k, v, c]) => `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');

  const rows = data.holdings || [];
  el('holdings').innerHTML = rows.length ? rows.map((h) => `
    <tr>
      <td><span class="name">${h.name || h.code}</span><span class="code">${h.code}</span></td>
      <td>${h.quantity == null ? '–' : h.quantity.toLocaleString('ko-KR')}</td>
      <td>${won(h.average_price)}</td>
      <td>${won(h.last_price)}</td>
      <td>${won(h.value)}</td>
      <td class="${cls(h.unrealised)}">${won(h.unrealised)}</td>
      <td class="${cls(h.return_pct)}">${pct(h.return_pct)}</td>
    </tr>`).join('') : '<tr><td colspan="7" class="empty">보유 종목이 없습니다.</td></tr>';
}

async function lookUp(event) {
  if (event) event.preventDefault();
  const code = el('code').value.trim();
  if (!code) return;
  const data = await ask('/api/quote?code=' + encodeURIComponent(code));
  el('suggest').innerHTML = '';
  if (data.error) {
    el('quote-msg').textContent = data.error;
    el('quote').innerHTML = '';
    // several names matched: offer them rather than making them guess again
    for (const s of (data.suggestions || [])) {
      const b = document.createElement('button');
      b.textContent = `${s.name} ${s.code}`;
      b.onclick = () => { el('code').value = s.code; lookUp(); };
      el('suggest').appendChild(b);
    }
    return;
  }
  el('quote-msg').textContent = '';
  const q = data.quote || {};
  el('quote').innerHTML = `
    <div class="stat"><div class="k">${q.name || ''} ${q.code || ''}</div>
      <div class="v ${cls(q.change)}">${won(q.price)}</div></div>
    <div class="stat"><div class="k">전일 대비</div>
      <div class="v ${cls(q.change)}">${won(q.change)} (${pct(q.change_pct)})</div></div>
    <div class="stat"><div class="k">고가 / 저가</div>
      <div class="v">${won(q.high)} / ${won(q.low)}</div></div>
    <div class="stat"><div class="k">거래량</div>
      <div class="v">${q.volume == null ? '–' : q.volume.toLocaleString('ko-KR')}</div></div>`;
}

function orderAmount() {
  const q = parseInt(el('o-qty').value, 10), p = parseInt(el('o-price').value, 10);
  return (q > 0 && p > 0) ? q * p : 0;
}

function refreshOrderUi() {
  const amount = orderAmount();
  const ready = amount > 0 && el('o-confirm').value.trim() === el('o-qty').value.trim();
  el('o-amount').textContent = amount ? `주문 금액 ${won(amount)}` : '';
  el('o-send').disabled = !ready;
}

async function loadOrders() {
  const data = await ask('/api/orders');
  if (data.error) { el('orders-msg').textContent = data.error; return; }
  el('orders-msg').textContent = '';
  const rows = data.orders || [];
  el('orders').innerHTML = rows.length ? rows.map((o) => `
    <tr>
      <td><span class="name">${o.name || o.code}</span><span class="code">${o.code}</span></td>
      <td>${o.side || ''}</td>
      <td>${(o.quantity || 0).toLocaleString('ko-KR')}</td>
      <td>${won(o.price)}</td>
      <td>${(o.filled || 0).toLocaleString('ko-KR')}</td>
      <td>${won(o.filled_price)}</td>
      <td>${o.status || ''}</td>
      <td><button class="cancel" data-order="${o.order_no}" data-code="${o.code}"
            data-qty="${o.cancellable}" ${o.cancellable > 0 ? '' : 'disabled'}>취소</button></td>
    </tr>`).join('') : '<tr><td colspan="8" class="empty">오늘 주문이 없습니다.</td></tr>';

  for (const button of el('orders').querySelectorAll('.cancel:not([disabled])')) {
    button.onclick = () => cancelOrder(button.dataset);
  }
}

async function cancelOrder(row) {
  if (!confirm(`주문번호 ${row.order} · ${row.code}
취소 가능 수량 ${row.qty}주를 취소합니다.`)) return;
  const data = await ask('/api/cancel', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ order_no: Number(row.order), code: row.code }),
  });
  el('orders-msg').textContent = data.error || (data.message || '취소 요청을 보냈습니다.');
  loadOrders();
  loadAccount();
}

async function loadLimits() {
  const d = await ask('/api/limits');
  if (d.error) return;
  el('limits').textContent =
    `1회 ${won(d.max_order_krw)} · 오늘 ${won(d.spent_today)} / ${won(d.max_daily_krw)}` +
    ` · ${d.orders_today}/${d.max_daily_orders}건`;
}

async function sendOrder(event) {
  event.preventDefault();
  const side = el('side').value;
  const label = side === 'buy' ? '매수' : '매도';
  const amount = orderAmount();
  if (!confirm(`${el('o-code').value} ${el('o-qty').value}주 ${label}
지정가 ${won(parseInt(el('o-price').value, 10))}
주문 금액 ${won(amount)}

보내시겠습니까?`)) return;

  el('o-send').disabled = true;
  const data = await ask('/api/order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      side, code: el('o-code').value.trim(),
      quantity: parseInt(el('o-qty').value, 10),
      price: parseInt(el('o-price').value, 10),
      confirmation: el('o-confirm').value.trim(),
    }),
  });
  if (data.error) { el('order-msg').textContent = data.error; }
  else {
    el('order-msg').textContent = `보냈습니다. 주문번호 ${data.order_no ?? '-'} · ${data.message ?? ''}`;
    el('o-qty').value = el('o-confirm').value = '';
    loadAccount();
    loadOrders();
  }
  loadLimits();
  refreshOrderUi();
}

for (const id of ['o-qty', 'o-price', 'o-confirm']) {
  el(id).addEventListener('input', refreshOrderUi);
}
document.getElementById('order-form').addEventListener('submit', sendOrder);
async function switchMode() {
  const now = el('mode-btn').textContent.trim();
  const want = now === '모의투자' ? 'live' : 'paper';
  if (want === 'live' && !confirm('실계좌로 전환합니다.

조회는 실제 계좌를 봅니다. 주문은 별도 설정이 없으면 여전히 막혀 있습니다.')) return;
  const data = await ask('/api/mode', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: want }),
  });
  if (data.error) { el('account-msg').textContent = data.error; return; }
  location.reload();
}

el('mode-btn').addEventListener('click', switchMode);
loadLimits();
refreshOrderUi();
document.getElementById('quote-form').addEventListener('submit', lookUp);
loadAccount();
loadOrders();
setInterval(() => { loadAccount(); loadOrders(); }, 60000);
"""


def render_desk(*, mode: str) -> str:
    """The desk page. `mode` is paper or live and is said out loud, in colour."""

    label = "모의투자" if mode == "paper" else "실계좌"
    return f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex, nofollow" />
<title>데스크 · {label}</title>
<style>{_CSS}</style>
</head><body><div class="wrap">

<header>
  <h1>데스크</h1>
  <button type="button" class="badge {mode}" id="mode-btn" title="클릭해서 전환">{label}</button>
  <a class="tab" href="/gold">골드 차트</a>
  <span class="local">이 페이지는 이 컴퓨터에서만 열립니다 · 127.0.0.1</span>
</header>

<section class="panel">
  <h2>계좌</h2>
  <div class="stats" id="stats"></div>
  <p class="msg" id="account-msg"></p>
</section>

<section class="panel">
  <h2>보유 종목</h2>
  <table>
    <thead><tr>
      <th>종목</th><th>수량</th><th>평단</th><th>현재가</th><th>평가금액</th><th>평가손익</th><th>수익률</th>
    </tr></thead>
    <tbody id="holdings"></tbody>
  </table>
</section>

<section class="panel">
  <h2>현재가 조회</h2>
  <form id="quote-form">
    <input id="code" placeholder="종목명 또는 코드 · 삼성전자 / 005930" autocomplete="off" />
    <button type="submit">조회</button>
  </form>
  <div class="suggest" id="suggest"></div>
  <div class="stats" id="quote" style="margin-top:16px"></div>
  <p class="msg" id="quote-msg"></p>
</section>

<section class="panel">
  <h2>오늘 주문 <span class="hint">체결·미체결·취소 가능 수량</span></h2>
  <table>
    <thead><tr>
      <th>종목</th><th>구분</th><th>수량</th><th>지정가</th><th>체결</th><th>체결가</th><th>상태</th><th></th>
    </tr></thead>
    <tbody id="orders"></tbody>
  </table>
  <p class="msg" id="orders-msg"></p>
</section>

<section class="panel">
  <h2>주문 <span class="hint">지정가만 · 모의투자 계좌</span></h2>
  <form id="order-form" class="order">
    <label>구분<select id="side"><option value="buy">매수</option><option value="sell">매도</option></select></label>
    <label>종목<input id="o-code" placeholder="종목명 또는 코드" autocomplete="off" /></label>
    <label>수량<input id="o-qty" inputmode="numeric" autocomplete="off" /></label>
    <label>지정가<input id="o-price" inputmode="numeric" autocomplete="off" /></label>
    <label>수량 다시 입력<input id="o-confirm" inputmode="numeric" autocomplete="off" placeholder="확인" /></label>
    <button type="submit" id="o-send">주문</button>
  </form>
  <p class="amount" id="o-amount"></p>
  <p class="msg" id="order-msg"></p>
  <p class="hint" id="limits"></p>
</section>

<footer>
  주문은 지정가만 보냅니다. 시장가는 코드값 뜻이 문서에 없어 넣지 않았습니다.<br />
  숫자는 NH 나무증권 API가 돌려준 값을 그대로 보여줍니다. 매매 권유가 아닙니다.
</footer>

</div><script>{_JS}</script></body></html>"""
