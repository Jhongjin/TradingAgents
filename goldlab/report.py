"""A page to look at, written to a local file.

A terminal table cannot hold eleven columns of numbers and stay readable, and
this is meant to be glanced at while a chart is open. The page is written to
disk and opened in a browser. It is not published anywhere: no server, no
upload, one file on the operator's own machine.

Everything on it is a count of what happened before. The page says so, in the
same size type as the numbers.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .live import LiveScan, load_study
from .patterns import PATTERN_REGISTRY

CSS = """
:root {
  color-scheme: light dark;
  --bg: #0f1115; --panel: #171a21; --line: #262b36; --ink: #e7eaf0; --ink2: #9aa4b8;
  --up: #ff5d5d; --down: #4c8dff; --flat: #9aa4b8; --accent: #d8a544;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.55 -apple-system, "Segoe UI", "Malgun Gothic", system-ui, sans-serif; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 28px 20px 60px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: var(--ink2); font-size: 13px; margin-bottom: 22px; }
.bias { display: inline-flex; align-items: center; gap: 10px; padding: 10px 16px; border-radius: 10px;
  background: var(--panel); border: 1px solid var(--line); margin-bottom: 22px; font-size: 15px; }
.bias b { font-size: 17px; }
.up { color: var(--up); } .down { color: var(--down); } .flat { color: var(--flat); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 24px; }
.tile { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.tile .k { color: var(--ink2); font-size: 12px; }
.tile .v { font-size: 19px; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 2px; }
.tile .n { color: var(--ink2); font-size: 11px; margin-top: 2px; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; margin-bottom: 20px; }
section h2 { font-size: 15px; margin: 0; padding: 14px 16px; border-bottom: 1px solid var(--line); }
.scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--ink2); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 11px 12px; border-bottom: 1px solid var(--line); vertical-align: top; white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
.num { font-variant-numeric: tabular-nums; }
.name { font-weight: 600; }
.name small { display: block; color: var(--ink2); font-weight: 400; font-size: 11px; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.tag.s { background: rgba(255,93,93,.16); color: var(--up); }
.tag.m { background: rgba(216,165,68,.16); color: var(--accent); }
.tag.w { background: rgba(154,164,184,.16); color: var(--ink2); }
.empty { padding: 26px 16px; color: var(--ink2); }
.notes { color: var(--ink2); font-size: 12px; margin: 0; padding: 14px 16px 16px 34px; }
.notes li { margin-bottom: 4px; }
@media (max-width: 700px) { table { min-width: 760px; } }
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _pct(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _signed(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value) * 100:+.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.1f}"
    except (TypeError, ValueError):
        return "-"


def _tone(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "flat"
    return "up" if number > 0 else ("down" if number < 0 else "flat")


def _confidence_tag(text: str) -> str:
    css = {"강함": "s", "보통": "m"}.get(text, "w")
    return f'<span class="tag {css}">{_e(text)}</span>'


def _signal_rows(scan: LiveScan) -> str:
    if not scan.signals:
        return '<tr><td colspan="10" class="empty">최근 봉에서 완성된 패턴이 없습니다.</td></tr>'
    rows = []
    for signal in scan.signals:
        arrow = "▲" if signal.direction == "bullish" else "▼"
        tone = "up" if signal.direction == "bullish" else "down"
        rows.append(
            f"<tr>"
            f'<td class="num">{_e(signal.interval)}</td>'
            f'<td class="name"><span class="{tone}">{arrow}</span> {_e(signal.label)}'
            f'<small>{_e(signal.timestamp[5:16].replace("T", " "))} · {signal.bars_ago}봉 전</small></td>'
            f'<td class="num">{_pct(signal.win_rate)}<small style="color:var(--ink2)">기준 {_pct(signal.base_win_rate)}</small></td>'
            f'<td class="num {_tone(signal.edge_win_rate)}">{_signed(signal.edge_win_rate)}</td>'
            f'<td class="num">{_e(signal.samples or "-")}</td>'
            f'<td class="num">{_e(signal.t_stat if signal.t_stat is not None else "-")}</td>'
            f'<td class="num">{_e(signal.horizon or "-")}봉</td>'
            f'<td class="num up">{_money(signal.upside_price)}</td>'
            f'<td class="num down">{_money(signal.downside_price)}</td>'
            f"<td>{_confidence_tag(signal.confidence)}</td>"
            f"</tr>"
        )
    return "".join(rows)


def _interval_tiles(scan: LiveScan) -> str:
    tiles = []
    for row in scan.intervals:
        if row.get("status") != "available":
            tiles.append(
                f'<div class="tile"><p class="k">{_e(row["interval"])}</p>'
                f'<p class="v flat">-</p><p class="n">{_e(row.get("status"))}</p></div>'
            )
            continue
        tiles.append(
            f'<div class="tile"><p class="k">{_e(row["interval"])}</p>'
            f'<p class="v">{_money(row.get("last_price"))}</p>'
            f'<p class="n">{_e(str(row.get("last_timestamp"))[5:16].replace("T", " "))} · {_e(row.get("bars"))}봉</p></div>'
        )
    return "".join(tiles)


def _record_table(symbol: str, interval: str, *, min_samples: int = 30) -> str:
    """Every measured pattern for one timeframe, strongest first."""

    study = load_study(symbol, interval)
    if not study:
        return f'<section><h2>{_e(interval)} 과거 측정</h2><p class="empty">아직 측정하지 않았습니다. study 명령을 먼저 실행하세요.</p></section>'
    horizons = [str(value) for value in (study.get("horizons") or [])]
    if not horizons:
        return ""
    primary = horizons[min(1, len(horizons) - 1)]
    base = ((study.get("base_rate") or {}).get(primary) or {}).get("long") or {}

    rows = []
    for row in study.get("patterns") or []:
        stats = (row.get("horizons") or {}).get(primary) or {}
        if int(stats.get("count") or 0) < min_samples:
            continue
        rows.append(
            f"<tr>"
            f'<td class="name">{_e(row.get("label"))}<small>{_e("상승" if row.get("direction") == "bullish" else "하락")}</small></td>'
            f'<td class="num">{_e(stats.get("count"))}</td>'
            f'<td class="num">{_pct(stats.get("win_rate"))}</td>'
            f'<td class="num {_tone(stats.get("edge_win_rate"))}">{_signed(stats.get("edge_win_rate"))}</td>'
            f'<td class="num {_tone(stats.get("edge_return"))}">{_signed(stats.get("edge_return"), 3)}</td>'
            f'<td class="num">{_e(stats.get("t_stat"))}</td>'
            f'<td class="num up">{_signed(stats.get("average_mfe"), 2)}</td>'
            f'<td class="num down">{_signed(stats.get("average_mae"), 2)}</td>'
            f'<td class="num">{_e(f"{float(stats.get('money_per_trade') or 0):,.0f}")}</td>'
            f"</tr>"
        )
    body = "".join(rows) or f'<tr><td colspan="9" class="empty">표본 {min_samples}회를 넘긴 패턴이 없습니다.</td></tr>'
    return f"""<section>
  <h2>{_e(interval)} 과거 측정 · {_e(primary)}봉 뒤 · 기준 승률 {_pct(base.get('win_rate'))} ({_e(study.get('bars'))}봉)</h2>
  <div class="scroll"><table>
    <thead><tr><th>패턴</th><th>표본</th><th>승률</th><th>기준대비</th><th>기준대비 수익</th><th>t</th><th>평균 유리폭</th><th>평균 불리폭</th><th>1계약</th></tr></thead>
    <tbody>{body}</tbody>
  </table></div>
</section>"""


def render_report(scan: LiveScan, *, intervals: Sequence[str] | None = None) -> str:
    """One self-contained page: what is live now, then the record behind it."""

    bias = scan.bias()
    tone = {"상승 우세": "up", "하락 우세": "down"}.get(bias["direction"], "flat")
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    shown = list(intervals or [row["interval"] for row in scan.intervals])
    records = "".join(_record_table(scan.symbol, interval) for interval in shown)
    notes = "".join(f"<li>{_e(note)}</li>" for note in scan.notes)

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(scan.symbol)} 패턴 현황</title>
<style>{CSS}</style></head>
<body><div class="wrap">
  <h1>{_e(scan.symbol)} 차트 패턴 현황</h1>
  <p class="sub">{_e(generated)} 기준 · 표시된 승률은 모두 같은 종목의 과거 같은 패턴에서 센 값입니다. 예측이 아니라 기록입니다.</p>

  <div class="bias">종합 판단 <b class="{tone}">{_e(bias['direction'])}</b>
    <span style="color:var(--ink2)">판정에 쓰인 신호 {_e(bias.get('counted'))}개</span></div>

  <div class="grid">{_interval_tiles(scan)}</div>

  <section>
    <h2>지금 완성된 패턴 {len(scan.signals)}건</h2>
    <div class="scroll"><table>
      <thead><tr><th>주기</th><th>패턴</th><th>승률</th><th>기준대비</th><th>표본</th><th>t</th><th>기준 구간</th><th>예상 상단</th><th>예상 하단</th><th>신뢰도</th></tr></thead>
      <tbody>{_signal_rows(scan)}</tbody>
    </table></div>
    <ul class="notes">{notes}</ul>
  </section>

  {records}
</div></body></html>"""
