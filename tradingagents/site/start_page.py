"""`/start`: what this site is, in one screen, for someone who just arrived.

A first-time reader lands on a headline like "3개 후보 중 3개가 통과했다" and
has no way to know what was screened, by whom, or whether anyone bought it.
This page answers that in the order the question is actually asked: what
happens here, what it costs, and what changes if you sign in.

It is deliberately one screen of reading. The feature hub at `/features` goes
deeper; this is the thing a visitor can finish before deciding to stay.
"""

from __future__ import annotations

from .design_system import badge, h, icon, icon_tile, render_shell
from .seo import canonical_url

START_CSS = """
.start-hero { padding: 40px 0 30px; }
.start-hero h1 { font-size: 32px; margin-top: 10px; max-width: 24ch; }
.start-hero .lead { margin-top: 12px; max-width: 60ch; word-break: keep-all; color: var(--ink2); font-size: 15px; line-height: 1.7; }
.start-hero .cta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 20px; }
.start-block { padding: 26px 0; border-top: 1px solid var(--line); }
.start-block h2 { font-size: 19px; letter-spacing: -0.02em; }
.start-block .sub { color: var(--ink2); font-size: 13.5px; margin-top: 6px; max-width: 62ch; }
.flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; counter-reset: flow; }
.flow > div { position: relative; padding: 16px 16px 14px; }
.flow .when { font-size: 12px; font-weight: 700; color: var(--accent-ink); font-variant-numeric: tabular-nums; }
.flow h3 { margin-top: 6px; font-size: 15px; }
.flow p { margin-top: 6px; font-size: 13px; color: var(--ink2); line-height: 1.6; }
.opens { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }
.opens a { display: flex; gap: 12px; align-items: flex-start; padding: 14px 16px; text-decoration: none; }
.opens a:hover { border-color: var(--line-strong); text-decoration: none; }
.opens b { display: block; font-size: 14px; }
.opens span { font-size: 13px; color: var(--ink2); line-height: 1.6; }
.perks { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.perks > div { padding: 16px; }
.perks h3 { margin-top: 10px; font-size: 14.5px; }
.perks p { margin-top: 6px; font-size: 13px; color: var(--ink2); line-height: 1.6; }
.start-end { display: flex; gap: 14px; align-items: center; justify-content: space-between; flex-wrap: wrap; padding: 20px 22px; margin: 26px 0 34px; }
.start-end p { font-size: 15px; font-weight: 700; }
.start-end .tiny { font-weight: 400; margin-top: 4px; }
@media (max-width: 900px) {
  .flow, .perks { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .opens { grid-template-columns: 1fr; }
  .start-hero h1 { font-size: 25px; }
}
@media (max-width: 560px) { .flow, .perks { grid-template-columns: 1fr; } }
"""

FLOW = (
    ("아침 07:50", "규칙이 먼저 거릅니다", "코스피200·코스닥150에서 추세·모멘텀·거래대금 점수로 후보를 추립니다. 사람이 고르지 않습니다."),
    ("그 직후", "AI가 토론해 확인합니다", "강세·약세 의견이 맞붙고 판정과 리스크 점검을 거쳐 비중을 정합니다. 토론 전문을 그대로 공개합니다."),
    ("장중", "모의 계좌가 실제로 담습니다", "통과한 종목을 세 계좌가 매수하고, 그 자리에서 목표가와 손절가를 정합니다. 실계좌 주문은 없습니다."),
    ("5·20거래일 뒤", "맞았는지 공개합니다", "수익률과 지수 대비 성적을 기록에 남깁니다. 틀린 날도 지우지 않습니다."),
)

OPENS = (
    ("layers", "b-navy", "오늘의 선별 결과", "종목, 규칙 점수, AI 등급, 목표가와 손절가까지 그날 아침 그대로.", "/harness"),
    ("wallet", "b-teal", "세 모의 계좌", "AI 계좌, 규칙만 쓰는 계좌, KIS 모의투자 계좌의 편입·청산과 손익.", "/paper"),
    ("target", "b-violet", "성과 검증", "지난 선별이 5일·20일 뒤 어떻게 됐는지, 코스피 대비 성적까지.", "/outcomes"),
    ("brain", "b-amber", "AI 토론 전문", "왜 담았고 왜 걸렀는지, 강세·약세·판정·리스크 의견 전문.", "/analyses"),
)

PERKS = (
    ("send", "b-blue", "아침 알림", "선별이 끝나면 텔레그램으로 종목·등급·목표가가 바로 옵니다. 사이트를 열지 않아도 됩니다."),
    ("target", "b-amber", "목표가 도달 알림", "내가 적어둔 목표가·손절가에 닿으면 알려주고, 지금 정리할 때인지 AI가 근거를 비중으로 정리해 줍니다."),
    ("layers", "b-teal", "내 조건만 보기", "관심 없는 업종과 ETF, 가격대를 빼고 내 기준에 맞는 종목만 추려 받습니다."),
    ("wallet", "b-navy", "매매 일지", "내 매매를 기록하면 같은 종목의 AI 판정과 나란히 놓고 볼 수 있습니다."),
    ("shield", "b-violet", "공시 알림", "담고 있거나 지켜보는 종목에 중요한 공시가 뜨면 바로 알려드립니다."),
    ("clock", "b-grey", "주간 리포트", "금요일마다 내 종목과 세 계좌의 한 주 성적을 정리해 보냅니다."),
)


def render_start_page(*, site_base_url: str | None = None) -> str:
    flow = "".join(
        f'<div class="card"><p class="when">{h(when)}</p><h3>{h(title)}</h3><p>{h(text)}</p></div>'
        for when, title, text in FLOW
    )
    opens = "".join(
        f'<a class="card" href="{h(href)}">{icon_tile(name, tone, small=True)}<span><b>{h(title)}</b><span>{h(text)}</span></span></a>'
        for name, tone, title, text, href in OPENS
    )
    perks = "".join(
        f'<div class="card">{icon_tile(name, tone, small=True)}<h3>{h(title)}</h3><p>{h(text)}</p></div>'
        for name, tone, title, text in PERKS
    )
    faqs = [
        ("무엇을 파는 사이트인가요?", "아무것도 팔지 않습니다. AI가 고른 종목과 그 결과를 공개하는 기록입니다. 모든 기능이 무료이고 광고로 운영합니다."),
        ("종목을 추천해 주나요?", "아니요. AI의 판단과 모의 계좌의 기록을 공개할 뿐, 특정 종목의 매매를 권유하지 않습니다. 투자 판단의 책임은 본인에게 있습니다."),
        ("실제로 주문이 나가나요?", "나가지 않습니다. 증권사 실계좌 주문 권한이 없고, 공개된 매매는 전부 모의 계좌 기록입니다."),
        ("가입하지 않아도 볼 수 있나요?", "네, 선별 결과와 토론 전문, 모의 계좌 기록까지 전부 그대로 보입니다. 가입은 알림과 내 기록을 위한 것입니다."),
    ]
    faq_html = "".join(
        f'<div class="card" style="padding: 16px 18px;"><dt style="font-weight: 700;">{h(q)}</dt>'
        f'<dd style="margin: 6px 0 0; color: var(--ink2); font-size: 13px;">{h(a)}</dd></div>'
        for q, a in faqs
    )
    structured = [
        {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]},
    ]

    body = f"""
<section class="hero start-hero">
  <div class="shell">
    {badge("30초 안내", "b-teal", icon_name="zap")}
    <h1>AI가 매일 아침 종목을 고르고, 맞았는지까지 공개합니다</h1>
    <p class="lead">코스피200·코스닥150을 규칙으로 거르고, AI 토론으로 확인하고, 모의 계좌가 실제로 담습니다.
    예측을 결과가 나오기 전에 먼저 공개하고 5·20거래일 뒤 성적을 그대로 남깁니다. 전부 무료입니다.</p>
    <div class="cta">
      <a class="btn primary" href="/harness">{icon("layers", 16)}오늘의 선별 보기</a>
      <a class="btn" href="/member?mode=signup">{icon("send", 16)}가입하고 아침 알림 받기</a>
      <a class="btn ghost" href="/outcomes">지난 성적부터 보기 →</a>
    </div>
  </div>
</section>

<section class="start-block"><div class="shell">
  <h2>하루가 이렇게 돕니다</h2>
  <p class="sub">사람이 종목을 고르는 단계는 없습니다. 규칙과 AI가 정하고, 결과는 날짜와 함께 남습니다.</p>
  <div class="flow">{flow}</div>
</div></section>

<section class="start-block"><div class="shell">
  <h2>지금 열려 있는 것</h2>
  <p class="sub">가입하지 않아도, 로그인하지 않아도 아래는 전부 그대로 보입니다.</p>
  <div class="opens">{opens}</div>
</div></section>

<section class="start-block"><div class="shell">
  <h2>가입하면 여기에 더해집니다</h2>
  <p class="sub">공개 기록은 그대로 두고, 나에게 맞춘 알림과 내 기록이 열립니다. 결제는 없습니다.</p>
  <div class="perks">{perks}</div>
</div></section>

<section class="start-block"><div class="shell">
  <h2>자주 묻는 것</h2>
  <dl class="opens" style="margin-top: 14px;">{faq_html}</dl>
  <div class="card start-end">
    <div>
      <p>먼저 오늘 무엇을 골랐는지부터 보세요</p>
      <p class="tiny muted">가입은 그다음에 결정해도 늦지 않습니다. AI 실험 기록이며 매매 권유가 아닙니다.</p>
    </div>
    <div class="row wrap" style="gap: 8px;">
      <a class="btn primary" href="/harness">오늘의 선별 보기</a>
      <a class="btn" href="/member?mode=signup">무료로 가입</a>
    </div>
  </div>
</div></section>
"""
    return render_shell(
        title="30초 안내 | TradingAgents Korea",
        description="AI가 매일 아침 코스피200·코스닥150에서 종목을 고르고, 모의 계좌가 담고, 5·20거래일 뒤 결과를 공개합니다. 전부 무료이며 실계좌 주문은 없습니다.",
        body=body,
        active=None,
        canonical_path="/start",
        site_base_url=site_base_url,
        extra_css=START_CSS,
        structured_data=structured,
        og_image=canonical_url("/og/default.png", site_base_url=site_base_url),
    )


__all__ = ["render_start_page"]
