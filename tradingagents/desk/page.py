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
}
.badge.paper { color: var(--accent); }
.badge.live { color: var(--warn); }
.local { margin-left: auto; font-size: 12px; color: var(--muted); }
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
"""

_JS = """
const won = (v) => v == null ? '–' : Math.round(v).toLocaleString('ko-KR') + '원';
const pct = (v) => v == null ? '–' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
const cls = (v) => v == null || v === 0 ? '' : (v > 0 ? 'up' : 'down');
const el = (id) => document.getElementById(id);

async function ask(path) {
  const response = await fetch(path, { credentials: 'same-origin' });
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
  event.preventDefault();
  const code = el('code').value.trim();
  if (!code) return;
  const data = await ask('/api/quote?code=' + encodeURIComponent(code));
  if (data.error) { el('quote-msg').textContent = data.error; el('quote').innerHTML = ''; return; }
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

document.getElementById('quote-form').addEventListener('submit', lookUp);
loadAccount();
setInterval(loadAccount, 60000);
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
  <span class="badge {mode}">{label}</span>
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
    <input id="code" placeholder="종목코드 예: 005930" autocomplete="off" />
    <button type="submit">조회</button>
  </form>
  <div class="stats" id="quote" style="margin-top:16px"></div>
  <p class="msg" id="quote-msg"></p>
</section>

<footer>
  읽기 전용입니다. 주문 기능은 아직 없습니다.<br />
  숫자는 NH 나무증권 API가 돌려준 값을 그대로 보여줍니다. 매매 권유가 아닙니다.
</footer>

</div><script>{_JS}</script></body></html>"""
