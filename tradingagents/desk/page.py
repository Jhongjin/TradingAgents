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
select {
  background: #0d1117; border: 1px solid var(--line); color: var(--ink);
  border-radius: 8px; padding: 9px 12px; font: inherit;
}
.order select { width: 96px; }
.order button { background: var(--warn); color: #1a1205; }
/* borrowed money gets its own colour, so the two orders never look alike */
.order button.credit { background: var(--up); color: #1a0506; }
.order button[disabled] { opacity: .4; cursor: not-allowed; }
.amount { font-size: 15px; font-weight: 700; margin-top: 12px; }
.book { margin-top: 16px; font-size: 13px; }
.book .row { display: grid; grid-template-columns: 1fr 110px 1fr; align-items: center; gap: 10px; padding: 2px 0; }
.book .px { text-align: center; font-weight: 700; }
.book .bar { height: 15px; border-radius: 3px; }
.book .ask .bar { background: rgba(77,155,255,.28); justify-self: end; }
.book .bid .bar { background: rgba(255,92,96,.28); }
.book .qty { color: var(--muted); font-size: 12px; }
.book .ask .px { color: var(--down); } .book .bid .px { color: var(--up); }
.book .spread { border-top: 1px solid var(--line); margin: 6px 0; }
#chart { width: 100%; height: 180px; margin-top: 18px; display: block; }
#chart rect.up { fill: var(--up); } #chart rect.down { fill: var(--down); }
#chart line.up { stroke: var(--up); } #chart line.down { stroke: var(--down); }
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
const qty = (v) => v == null ? '–' : Math.round(v).toLocaleString('ko-KR');
// 20260918 -> 09.18, because a column of eight digits is a column nobody reads
const day = (v) => (v || '').length === 8 ? v.slice(4, 6) + '.' + v.slice(6) : (v || '');

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
      <td class="${h.on_margin ? 'down' : ''}">${h.kind || (h.on_margin ? '신용' : '현금')}</td>
      <td>${h.quantity == null ? '–' : h.quantity.toLocaleString('ko-KR')}</td>
      <td>${won(h.average_price)}</td>
      <td>${won(h.last_price)}</td>
      <td>${won(h.value)}</td>
      <td class="${cls(h.unrealised)}">${won(h.unrealised)}</td>
      <td class="${cls(h.return_pct)}">${pct(h.return_pct)}</td>
    </tr>`).join('') : '<tr><td colspan="8" class="empty">보유 종목이 없습니다.</td></tr>';

  drawMargin(data.margin);
}

function drawMargin(margin) {
  const panel = el('margin-panel');
  if (!margin) { panel.hidden = true; return; }
  panel.hidden = false;

  const room = margin.room_pct;
  el('margin-stats').innerHTML = [
    ['담보비율', margin.ratio == null ? '–' : margin.ratio.toFixed(1) + '%',
     margin.at_risk ? 'down' : ''],
    ['반대매매선', margin.maintenance_pct.toFixed(0) + '%', ''],
    ['하락 여유', room == null ? '–' : '약 ' + room.toFixed(1) + '%', room != null && room < 10 ? 'down' : ''],
    ['융자잔액', won(margin.loan_total), ''],
    ['가장 이른 만기', margin.next_due_days == null ? '–' : `D-${margin.next_due_days}`,
     margin.next_due_days != null && margin.next_due_days <= 14 ? 'down' : ''],
  ].map(([k, v, c]) => `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');

  el('margin-rows').innerHTML = (margin.loans || []).map((l) => `
    <tr>
      <td><span class="name">${l.name || l.code}</span><span class="code">${l.code}</span></td>
      <td>${won(l.loan_amount)}</td>
      <td>${won(l.value)}</td>
      <td>${l.deposit_rate || '–'}</td>
      <td>${(l.opened_on || '').slice(5)}</td>
      <td class="${l.due_soon ? 'down' : ''}">${(l.expires_on || '').slice(5)}${l.days_left == null ? '' : ` (D-${l.days_left})`}</td>
    </tr>`).join('');

  // the estimate and the setting are both said out loud: one is arithmetic on a
  // formula NH does not publish, the other is a contract term, and neither is
  // something the API handed over
  el('margin-note').textContent =
    `하락 여유는 담보비율이 ${margin.maintenance_pct.toFixed(0)}%에 닿기까지 보유 평가금액이 더 빠질 수 있는 폭의 개략치입니다. `
    + `NH가 담보비율 계산식을 공개하지 않아 교과서 공식으로 계산했고, 반대매매선 `
    + `${margin.maintenance_pct.toFixed(0)}%도 설정값입니다. 실제 기준은 약정서를 확인하세요.`;
}

function drawBook(book) {
  const box = el('book');
  if (!book || (!book.asks.length && !book.bids.length)) { box.innerHTML = ''; return; }
  const biggest = Math.max(1, ...[...book.asks, ...book.bids].map((l) => l.size || 0));
  const side = (level, klass) => {
    const width = Math.round(((level.size || 0) / biggest) * 100);
    const bar = `<div class="bar" style="width:${width}%"></div>`;
    const qty = `<span class="qty">${(level.size || 0).toLocaleString('ko-KR')}</span>`;
    return klass === 'ask'
      ? `<div class="row ask">${bar}<span class="px">${won(level.price)}</span>${qty}</div>`
      : `<div class="row bid">${qty}<span class="px">${won(level.price)}</span>${bar}</div>`;
  };
  box.innerHTML = book.asks.map((l) => side(l, 'ask')).join('')
    + '<div class="spread"></div>'
    + book.bids.map((l) => side(l, 'bid')).join('');

  // clicking a price puts it in the order box, which is the whole point of
  // looking at the ladder before placing a limit
  for (const [index, node] of [...box.querySelectorAll('.px')].entries()) {
    node.style.cursor = 'pointer';
    node.onclick = () => {
      const all = [...book.asks, ...book.bids];
      el('o-price').value = Math.round(all[index].price);
      el('o-code').value = el('code').value.trim();
      askCapacitySoon();
      refreshOrderUi();
    };
  }
}

async function drawChart(code) {
  const svg = el('chart');
  const data = await ask('/api/candles?count=60&code=' + encodeURIComponent(code));
  if (data.error || !(data.candles || []).length) { svg.hidden = true; el('chart-note').textContent = ''; return; }

  const bars = data.candles;
  const highs = bars.map((b) => b.high), lows = bars.map((b) => b.low);
  const top = Math.max(...highs), bottom = Math.min(...lows);
  const span = (top - bottom) || 1;
  const step = 880 / bars.length;
  const y = (v) => 174 - ((v - bottom) / span) * 168;

  svg.innerHTML = bars.map((b, i) => {
    const x = i * step + step / 2;
    const rising = b.close >= b.open;
    const klass = rising ? 'up' : 'down';
    const width = Math.max(step * 0.62, 1.5);
    const bodyTop = y(Math.max(b.open, b.close));
    const height = Math.max(Math.abs(y(b.open) - y(b.close)), 1);
    return `<line class="${klass}" x1="${x}" x2="${x}" y1="${y(b.high)}" y2="${y(b.low)}" stroke-width="1" />`
      + `<rect class="${klass}" x="${x - width / 2}" y="${bodyTop}" width="${width}" height="${height}" />`;
  }).join('');
  svg.hidden = false;
  el('chart-note').textContent =
    `최근 ${bars.length}거래일 · ${bars[0].date} ~ ${bars[bars.length - 1].date} · 고 ${won(top)} / 저 ${won(bottom)}`;
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
    el('chart').hidden = true;
    el('flow-table').hidden = true;
    el('book').innerHTML = '';
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
  drawBook(data.book);
  drawChart(q.code || code);
  loadFlow(q.code || code);
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

async function loadFlow(code) {
  const table = el('flow-table');
  const data = await ask('/api/investors?days=10&code=' + encodeURIComponent(code));
  const rows = data.rows || [];
  if (data.error || !rows.length) { table.hidden = true; return; }
  el('flow').innerHTML = rows.map((r) => `
    <tr>
      <td>${day(r.date)}</td>
      <td>${won(r.price)}</td>
      <td class="${cls(r.change_pct)}">${pct(r.change_pct)}</td>
      <td class="${cls(r.foreign)}">${qty(r.foreign)}</td>
      <td class="${cls(r.institution)}">${qty(r.institution)}</td>
      <td class="${cls(r.individual)}">${qty(r.individual)}</td>
      <td>${r.foreign_pct == null ? '–' : r.foreign_pct.toFixed(2) + '%'}</td>
    </tr>`).join('');
  table.hidden = false;
}

async function loadPnl(event) {
  if (event) event.preventDefault();
  const data = await ask('/api/pnl?days=' + el('pnl-days').value);
  if (data.error) {
    el('pnl-msg').textContent = data.error;
    el('pnl-stats').innerHTML = ''; el('pnl-stocks').innerHTML = ''; el('pnl-note').textContent = '';
    return;
  }
  el('pnl-msg').textContent = '';
  const t = data.totals || {}, s = data.standing;
  const cards = [
    ['실현손익', won(t.profit), cls(t.profit)],
    ['매수', won(t.bought), ''],
    ['매도', won(t.sold), ''],
    ['수수료·세금', won(t.costs), ''],
  ];
  // the standing line is a separate live-only call; when it is missing the
  // period figures above are still true, so the panel just gets shorter
  if (s) cards.push(['평가손익 (보유분)', won(s.open_profit), cls(s.open_profit)]);
  el('pnl-stats').innerHTML = cards
    .map(([k, v, c]) => `<div class="stat"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`).join('');

  const rows = data.stocks || [];
  el('pnl-stocks').innerHTML = rows.length ? rows.map((r) => `
    <tr>
      <td><span class="name">${r.name || r.code}</span><span class="code">${r.code}</span></td>
      <td>${won(r.bought)}</td>
      <td>${won(r.sold)}</td>
      <td class="${cls(r.profit)}">${won(r.profit)}</td>
      <td class="${cls(r.return_pct)}">${pct(r.return_pct)}</td>
    </tr>`).join('') : '<tr><td colspan="5" class="empty">이 기간에 매매가 없습니다.</td></tr>';

  const days = (data.days || []).filter((d) => d.profit);
  el('pnl-note').textContent = days.length
    ? `매매한 날 ${days.length}일 · ${day(days[days.length - 1].date)} ~ ${day(days[0].date)}`
    : `${data.from} ~ ${data.to}`;
}

async function loadReconcile() {
  const data = await ask('/api/reconcile?days=90');
  if (data.error) {
    el('rec-msg').textContent = data.error;
    el('rec-verdict').textContent = '';
    el('rec-rows').innerHTML = '';
    return;
  }
  el('rec-msg').textContent = '';

  const gaps = [
    ...data.broker_only.map((r) => ({ ...r, verdict: '우리 기록에 없음' })),
    ...data.ours_only.map((r) => ({ ...r, verdict: '증권사에 없음' })),
    ...data.quantity_differs.map((r) => ({ ...r, verdict: '수량 불일치' })),
  ];
  el('rec-verdict').innerHTML = data.clean
    ? `<span class="up">일치</span> · 증권사 ${data.broker_trades}건 / 우리 기록 ${data.our_trades}건`
    : `<span class="down">차이 ${gaps.length}건</span> · 증권사 ${data.broker_trades}건 / 우리 기록 ${data.our_trades}건`;

  // the gaps are the reason this panel exists, so they go on top
  const rows = [...gaps, ...data.agreed.map((r) => ({ ...r, verdict: '일치' }))];
  el('rec-rows').innerHTML = rows.length ? rows.map((r) => `
    <tr>
      <td>${day(r.day)}</td>
      <td><span class="name">${r.name || r.code}</span><span class="code">${r.code}</span></td>
      <td>${r.side === 'sell' ? '매도' : '매수'}</td>
      <td>${qty(r.broker_quantity)}</td>
      <td>${qty(r.our_quantity)}</td>
      <td class="${r.verdict === '일치' ? '' : 'down'}">${r.verdict}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">이 기간에 거래가 없습니다.</td></tr>';

  const cash = data.cash || [];
  el('rec-cash').textContent = cash.length
    ? '입출금 ' + cash.map((c) => `${day(c.day)} ${c.kind} ${won(c.amount)}`).join(' · ')
    : '';
}

async function loadReserved() {
  const data = await ask('/api/reserved');
  const rows = data.reserved || [];
  if (data.error) {
    el('reserved-msg').textContent = data.error;
    el('reserved').innerHTML = '<tr><td colspan="7" class="empty">예약주문을 불러오지 못했습니다.</td></tr>';
    return;
  }
  el('reserved-msg').textContent = data.unsupported || '';
  if (data.unsupported) {
    el('r-send').disabled = true;
    el('reserve-form').querySelectorAll('input, select').forEach((f) => { f.disabled = true; });
  }
  el('reserved').innerHTML = rows.length ? rows.map((r) => `
    <tr>
      <td><span class="name">${r.name || r.code}</span><span class="code">${r.code}</span></td>
      <td>${r.side || ''}</td>
      <td>${qty(r.quantity)}</td>
      <td>${won(r.price)}</td>
      <td>${qty(r.filled)}</td>
      <td>${day(r.from)} ~ ${day(r.to)}</td>
      <td><button class="cancel" data-no="${r.reserved_no}" data-code="${r.code}"
            data-side="${(r.side || '').includes('매도') ? 'sell' : 'buy'}">취소</button></td>
    </tr>`).join('') : '<tr><td colspan="7" class="empty">예약된 주문이 없습니다.</td></tr>';

  for (const button of el('reserved').querySelectorAll('.cancel')) {
    button.onclick = () => cancelReserved(button.dataset);
  }
}

async function cancelReserved(row) {
  if (!confirm(`예약주문 ${row.no} · ${row.code} 를 취소합니다.`)) return;
  const data = await ask('/api/reserved/cancel', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reserved_no: Number(row.no), code: row.code, order_side: row.side }),
  });
  el('reserved-msg').textContent = data.error || (data.message || '취소 요청을 보냈습니다.');
  loadReserved();
}

function reserveAmount() {
  const q = parseInt(el('r-qty').value, 10), p = parseInt(el('r-price').value, 10);
  return (q > 0 && p > 0) ? q * p : 0;
}

function refreshReserveUi() {
  const amount = reserveAmount();
  el('r-amount').textContent = amount ? `예약 금액 ${won(amount)}` : '';
  el('r-send').disabled = !(amount > 0 && el('r-confirm').value.trim() === el('r-qty').value.trim());
}

async function sendReserve(event) {
  event.preventDefault();
  const side = el('r-side').value;
  const label = side === 'buy' ? '매수' : '매도';
  if (!confirm(`${el('r-code').value} ${el('r-qty').value}주 ${label} 예약
지정가 ${won(parseInt(el('r-price').value, 10))}
예약 금액 ${won(reserveAmount())}

다음 장에 자동으로 나갑니다. 예약하시겠습니까?`)) return;

  el('r-send').disabled = true;
  const data = await ask('/api/reserved/order', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      side, code: el('r-code').value.trim(),
      quantity: parseInt(el('r-qty').value, 10),
      price: parseInt(el('r-price').value, 10),
      confirmation: el('r-confirm').value.trim(),
    }),
  });
  if (data.error) { el('reserved-msg').textContent = data.error; }
  else {
    el('reserved-msg').textContent = `예약했습니다. 번호 ${data.reserved_no ?? '-'} · ${data.message ?? ''}`;
    el('r-qty').value = el('r-confirm').value = '';
    loadReserved();
  }
  loadLimits();
  refreshReserveUi();
}

function orderAmount() {
  const q = parseInt(el('o-qty').value, 10), p = parseInt(el('o-price').value, 10);
  return (q > 0 && p > 0) ? q * p : 0;
}

function onCredit() { return el('funding').value === 'credit'; }

function refreshOrderUi() {
  const amount = orderAmount();
  const ready = amount > 0 && el('o-confirm').value.trim() === el('o-qty').value.trim();
  const credit = onCredit();
  el('o-amount').innerHTML = amount
    ? (credit ? `<span class="down">신용</span> 주문 금액 ${won(amount)} · 빌린 돈입니다`
              : `주문 금액 ${won(amount)}`)
    : '';
  // the button changes colour with the money, so the two orders never look alike
  el('o-send').textContent = credit ? '신용 주문' : '주문';
  el('o-send').classList.toggle('credit', credit);
  el('o-send').disabled = !ready;
}

let capacityTimer = null;

async function showCapacity() {
  const code = el('o-code').value.trim();
  const side = el('side').value;
  const price = parseInt(el('o-price').value, 10);
  if (!code || (side === 'buy' && !(price > 0))) { el('capacity').textContent = ''; return; }

  const url = `/api/capacity?code=${encodeURIComponent(code)}&side=${side}&price=${price || 0}`;
  const d = await ask(url);
  if (d.error) { el('capacity').textContent = d.error; return; }
  el('capacity').textContent = side === 'buy'
    ? `이 가격에 최대 ${(d.quantity || 0).toLocaleString('ko-KR')}주 (${won(d.amount)})`
    : `매도 가능 ${(d.quantity || 0).toLocaleString('ko-KR')}주 · 보유 ${(d.held || 0).toLocaleString('ko-KR')}주`;
}

function askCapacitySoon() {
  // one call after typing stops, not one per keystroke: NH allows five a second
  clearTimeout(capacityTimer);
  capacityTimer = setTimeout(showCapacity, 450);
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
  const credit = onCredit();
  const label = (credit ? '신용 ' : '') + (side === 'buy' ? '매수' : '매도');
  const amount = orderAmount();
  // the borrowed-money warning goes in the dialog too: the colour on the button
  // is easy to stop seeing after the tenth order
  const warning = credit
    ? (side === 'buy'
        ? '\n\n빌린 돈으로 삽니다. 손실이 넣은 돈보다 커질 수 있고, 이자와 반대매매가 따릅니다.'
        : '\n\n신용으로 보유한 수량을 갚습니다.')
    : '';
  if (!confirm(`${el('o-code').value} ${el('o-qty').value}주 ${label}
지정가 ${won(parseInt(el('o-price').value, 10))}
주문 금액 ${won(amount)}${warning}

보내시겠습니까?`)) return;

  el('o-send').disabled = true;
  const data = await ask('/api/order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      side, credit, code: el('o-code').value.trim(),
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
for (const id of ['o-code', 'o-price']) {
  el(id).addEventListener('input', askCapacitySoon);
}
el('side').addEventListener('change', showCapacity);
el('funding').addEventListener('change', refreshOrderUi);
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

for (const id of ['r-qty', 'r-price', 'r-confirm']) {
  el(id).addEventListener('input', refreshReserveUi);
}
document.getElementById('reserve-form').addEventListener('submit', sendReserve);
document.getElementById('pnl-form').addEventListener('submit', loadPnl);
el('pnl-days').addEventListener('change', loadPnl);

el('mode-btn').addEventListener('click', switchMode);
loadLimits();
refreshOrderUi();
refreshReserveUi();
document.getElementById('quote-form').addEventListener('submit', lookUp);
loadAccount();
loadOrders();

// The panels below the fold cost eight NH calls between them, and NH allows
// five a second. Loading them when they are first scrolled to means opening
// the desk asks for the account and today's orders and nothing else; the rest
// arrives as it is looked at, which is also when it is wanted.
const WHEN_SEEN = [
  ['pnl-panel', loadPnl],
  ['reconcile-panel', loadReconcile],
  ['reserved-panel', loadReserved],
];

function loadWhenSeen() {
  const pending = new Map(WHEN_SEEN);
  // no observer (an old browser, a odd webview): load everything and move on
  if (!('IntersectionObserver' in window)) {
    for (const load of pending.values()) load();
    return;
  }
  const watcher = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const load = pending.get(entry.target.id);
      if (load) { pending.delete(entry.target.id); load(); }
      watcher.unobserve(entry.target);
    }
  }, { rootMargin: '200px' });   // start just before it comes into view

  for (const [id] of WHEN_SEEN) {
    const node = el(id);
    if (node) watcher.observe(node);
  }
}

loadWhenSeen();
// A desk left open in a background tab was refreshing twice a minute forever,
// spending the same rate limit the foreground needs. It catches up on return.
let stale = false;
setInterval(() => {
  if (document.hidden) { stale = true; return; }
  loadAccount();
  loadOrders();
}, 60000);

document.addEventListener('visibilitychange', () => {
  if (document.hidden || !stale) return;
  stale = false;
  loadAccount();
  loadOrders();
});
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
  <a class="tab" href="/krxgold">금현물 (원/g)</a>
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
      <th>종목</th><th>자금</th><th>수량</th><th>평단</th><th>현재가</th><th>평가금액</th><th>평가손익</th><th>수익률</th>
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
  <div class="book" id="book"></div>
  <svg id="chart" viewBox="0 0 880 180" preserveAspectRatio="none" hidden></svg>
  <p class="hint" id="chart-note"></p>
  <table id="flow-table" hidden>
    <thead><tr>
      <th>수급</th><th>종가</th><th>등락</th><th>외국인</th><th>기관</th><th>개인</th><th>외인비중</th>
    </tr></thead>
    <tbody id="flow"></tbody>
  </table>
  <p class="msg" id="quote-msg"></p>
</section>

<section class="panel" id="pnl-panel">
  <h2>실현손익 <span class="hint">기간 내 매수·매도로 확정된 손익</span></h2>
  <form id="pnl-form">
    <select id="pnl-days">
      <option value="30">최근 30일</option>
      <option value="90" selected>최근 90일</option>
      <option value="365">최근 1년</option>
    </select>
    <button type="submit">조회</button>
  </form>
  <div class="stats" id="pnl-stats" style="margin-top:16px"></div>
  <table style="margin-top:16px">
    <thead><tr>
      <th>종목</th><th>매수</th><th>매도</th><th>실현손익</th><th>수익률</th>
    </tr></thead>
    <tbody id="pnl-stocks"><tr><td colspan="5" class="empty">…</td></tr></tbody>
  </table>
  <p class="hint" id="pnl-note"></p>
  <p class="msg" id="pnl-msg"></p>
</section>

<section class="panel" id="margin-panel" hidden>
  <h2>신용 <span class="hint">빌린 돈 · 만기와 반대매매선</span></h2>
  <div class="stats" id="margin-stats"></div>
  <table style="margin-top:16px">
    <thead><tr>
      <th>종목</th><th>융자잔액</th><th>평가금액</th><th>증거금률</th><th>대출일</th><th>만기</th>
    </tr></thead>
    <tbody id="margin-rows"></tbody>
  </table>
  <p class="hint" id="margin-note"></p>
</section>

<section class="panel" id="reconcile-panel">
  <h2>거래내역 대조 <span class="hint">우리 원장 vs 증권사 장부</span></h2>
  <p class="amount" id="rec-verdict"></p>
  <table style="margin-top:12px">
    <thead><tr>
      <th>날짜</th><th>종목</th><th>구분</th><th>증권사</th><th>우리 기록</th><th>판정</th>
    </tr></thead>
    <tbody id="rec-rows"><tr><td colspan="6" class="empty">…</td></tr></tbody>
  </table>
  <p class="hint" id="rec-cash"></p>
  <p class="msg" id="rec-msg"></p>
</section>

<section class="panel" id="reserved-panel">
  <h2>예약 주문 <span class="hint">장 시작 전에 걸어두는 주문 · 실계좌 전용</span></h2>
  <table>
    <thead><tr>
      <th>종목</th><th>구분</th><th>수량</th><th>지정가</th><th>체결</th><th>유효기간</th><th></th>
    </tr></thead>
    <tbody id="reserved"><tr><td colspan="7" class="empty">…</td></tr></tbody>
  </table>
  <form id="reserve-form" class="order" style="margin-top:16px">
    <label>구분<select id="r-side"><option value="buy">매수</option><option value="sell">매도</option></select></label>
    <label>종목<input id="r-code" placeholder="종목명 또는 코드" autocomplete="off" /></label>
    <label>수량<input id="r-qty" inputmode="numeric" autocomplete="off" /></label>
    <label>지정가<input id="r-price" inputmode="numeric" autocomplete="off" /></label>
    <label>수량 다시 입력<input id="r-confirm" inputmode="numeric" autocomplete="off" placeholder="확인" /></label>
    <button type="submit" id="r-send">예약</button>
  </form>
  <p class="amount" id="r-amount"></p>
  <p class="msg" id="reserved-msg"></p>
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
  <h2>주문 <span class="hint">지정가만</span></h2>
  <form id="order-form" class="order">
    <label>구분<select id="side"><option value="buy">매수</option><option value="sell">매도</option></select></label>
    <label>자금<select id="funding"><option value="cash">현금</option><option value="credit">신용</option></select></label>
    <label>종목<input id="o-code" placeholder="종목명 또는 코드" autocomplete="off" /></label>
    <label>수량<input id="o-qty" inputmode="numeric" autocomplete="off" /></label>
    <label>지정가<input id="o-price" inputmode="numeric" autocomplete="off" /></label>
    <label>수량 다시 입력<input id="o-confirm" inputmode="numeric" autocomplete="off" placeholder="확인" /></label>
    <button type="submit" id="o-send">주문</button>
  </form>
  <p class="amount" id="o-amount"></p>
  <p class="hint" id="capacity"></p>
  <p class="msg" id="order-msg"></p>
  <p class="hint" id="limits"></p>
</section>

<footer>
  주문은 지정가만 보냅니다. 시장가는 코드값 뜻이 문서에 없어 넣지 않았습니다.<br />
  신용 주문은 .env 에 TRADINGAGENTS_ENABLE_MARGIN_TRADING=true 가 있어야 나갑니다.
  빌린 돈이라 손실이 넣은 돈보다 커질 수 있습니다.<br />
  숫자는 NH 나무증권 API가 돌려준 값을 그대로 보여줍니다. 매매 권유가 아닙니다.
</footer>

</div><script>{_JS}</script></body></html>"""
