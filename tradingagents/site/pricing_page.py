"""Public pricing page — same tokens and type as the home page."""

from __future__ import annotations

import html
from typing import Any

from .billing import PAID_PLANS, PLANS, RESEARCH_TOOL_NOTICES, TRIAL_DAYS
from .home_page import HOME_CSS, HOME_JS, THEMES, THEME_LABELS
from .seo import canonical_url


def _h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


PRICING_CSS = """
.plans{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;align-items:stretch}
.plan{border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:22px 22px 20px;display:flex;flex-direction:column;gap:12px}
.plan.featured{border-color:var(--accent);box-shadow:var(--shadow)}
.plan .name{font-family:"Noto Serif KR",serif;font-size:20px;font-weight:700}
.plan .price{font-family:"IBM Plex Mono",monospace;font-size:30px;font-variant-numeric:tabular-nums}
.plan .price small{font-size:13px;font-family:"IBM Plex Sans KR",sans-serif;color:var(--muted);margin-left:4px}
.plan .tag{font-size:14px;color:var(--ink2)}
.plan ul{margin:0;padding-left:18px;font-size:14px;color:var(--ink2);display:flex;flex-direction:column;gap:6px;flex:1}
.plan .cta{margin-top:auto}
.notes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 24px;font-size:14px;color:var(--ink2)}
.faq dt{font-weight:600;margin-top:14px}.faq dd{margin:4px 0 0;color:var(--ink2);font-size:14px}
@media (max-width:900px){.plans,.notes{grid-template-columns:1fr}}
"""


def render_pricing_page(*, site_base_url: str | None = None) -> str:
    theme_buttons = "".join(
        f'<button type="button" class="{name}" data-theme="{name}" aria-pressed="false" aria-label="{_h(THEME_LABELS[name])} 테마" title="{_h(THEME_LABELS[name])}"></button>'
        for name in THEMES
    )
    cards = []
    for plan_id in ("free", "daily", "pro"):
        plan = PLANS[plan_id]
        featured = " featured" if plan_id == "daily" else ""
        if plan_id == "free":
            cta = '<a class="btn" href="/member?mode=signup">무료로 시작</a>'
        else:
            cta = f'<a class="btn primary" href="/member?mode=signup&amp;plan={plan_id}">{_h(str(TRIAL_DAYS))}일 무료 체험 후 구독</a>' if plan_id == "daily" else f'<a class="btn" href="/member?mode=signup&amp;plan={plan_id}">프로로 시작</a>'
        features = "".join(f"<li>{_h(item)}</li>" for item in plan.features)
        price = "0" if plan.price_krw == 0 else f"{plan.price_krw:,}"
        cards.append(
            f"""<div class="plan{featured}">
          <div class="name">{_h(plan.name)}</div>
          <div class="price">{price}<small>원 / 월</small></div>
          <div class="tag">{_h(plan.tagline)}</div>
          <ul>{features}</ul>
          <div class="cta">{cta}</div>
        </div>"""
        )
    notices = "".join(f"<div>{_h(item)}</div>" for item in RESEARCH_TOOL_NOTICES)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>요금제 | TradingAgents Korea</title>
<meta name="description" content="무료, 데일리 패스(월 10,000원), 프로(월 30,000원). 당일 하네스 열람, AI 토론 전문, 분석 요청 횟수를 넓히는 리서치 도구 요금제입니다.">
<link rel="canonical" href="{_h(canonical_url('/pricing', site_base_url=site_base_url))}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700&family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<script>(function(){{try{{var t=localStorage.getItem('ta-theme');if(t==='paper'||t==='dark'||t==='sepia'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
<style>{HOME_CSS}{PRICING_CSS}</style>
</head>
<body>
<header class="masthead">
  <div class="shell">
    <a class="brand" href="/"><span class="brand-name">TradingAgents Korea</span><span class="brand-sub">한국 주식 AI 리서치 데일리</span></a>
    <nav class="nav" aria-label="주요 메뉴">
      <a href="/">오늘</a><a href="/harness">일일 하네스</a><a href="/outcomes">검증 성과</a><a href="/pricing" aria-current="page">요금제</a><a href="/features/methodology">분석 기준</a>
    </nav>
    <div class="mast-right">
      <div class="theme-switch" role="group" aria-label="페이지 테마">{theme_buttons}</div>
      <a class="btn" href="/member">로그인</a>
    </div>
  </div>
</header>
<main id="main-content">
<section class="hero">
  <div class="shell" style="grid-template-columns:1fr">
    <div>
      <div class="issue">요금제 · 리서치 도구 이용 범위</div>
      <h1>오늘의 하네스를 언제, 얼마나 깊이 볼지 고르세요</h1>
      <p class="deck">무료는 전일 실행까지, 데일리 패스는 당일 실행 즉시와 AI 토론 전문까지 열립니다. 어느 플랜도 종목을 권유하거나 주문을 대신 내지 않습니다.</p>
    </div>
  </div>
</section>
<section class="block">
  <div class="shell">
    <div class="plans">{''.join(cards)}</div>
  </div>
</section>
<section class="block">
  <div class="shell">
    <div class="block-head"><h2>이용 원칙과 환불</h2></div>
    <div class="notes">{notices}</div>
    <dl class="faq">
      <dt>무료와 유료의 차이는 무엇인가요?</dt><dd>같은 데이터를 보되 시점과 깊이가 다릅니다. 무료는 다음 거래일부터 원장을 볼 수 있고, 유료는 07:50·10:05 실행 직후 토론 전문까지 봅니다.</dd>
      <dt>결제는 어떻게 되나요?</dt><dd>포트원을 통한 카드·카카오페이·네이버페이 정기결제입니다. 카드 정보는 결제사에만 저장되며 서비스는 결제 참조키만 보관합니다.</dd>
      <dt>해지와 환불은요?</dt><dd>마이페이지에서 언제든 해지할 수 있고 남은 기간은 그대로 이용합니다. 결제 후 7일 이내 전액 환불, 이후는 남은 기간 일할 환불입니다.</dd>
      <dt>실계좌 자동매매도 되나요?</dt><dd>아니요. 모의투자 자동화는 운영 검증용이며, 어떤 플랜에도 실계좌 주문이나 투자일임은 포함되지 않습니다.</dd>
    </dl>
  </div>
</section>
</main>
<footer>
  <div class="shell">
    <span>© 2026 TradingAgents Korea</span><a href="/terms">약관</a><a href="/disclaimer">투자 유의사항</a><a href="/privacy">개인정보</a>
  </div>
</footer>
<script>{HOME_JS}</script>
</body>
</html>"""
