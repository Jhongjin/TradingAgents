"""Public pricing page on the shared design system."""

from __future__ import annotations

from .billing import PAID_PLANS, PLANS, RESEARCH_TOOL_NOTICES, TRIAL_DAYS
from .design_system import badge, h, icon, icon_tile, render_shell

PRICING_CSS = """
.pricing-hero { padding: 36px 0 26px; text-align: center; }
.pricing-hero h1 { font-size: 30px; margin-top: 10px; }
.pricing-hero p.deck { margin: 10px auto 0; max-width: 620px; color: var(--ink2); font-size: 15px; }
.plans { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; align-items: stretch; }
.plan { display: flex; flex-direction: column; gap: 12px; padding: 22px; position: relative; }
.plan.featured { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft), var(--shadow); }
.plan .ribbon { position: absolute; top: -12px; left: 22px; }
.plan .name { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; display: flex; align-items: center; gap: 8px; }
.plan .price { font-size: 32px; font-weight: 700; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
.plan .price small { font-size: 13px; font-weight: 500; color: var(--muted); margin-left: 4px; letter-spacing: 0; }
.plan .tag { font-size: 13px; color: var(--ink2); }
.plan ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; font-size: 13px; color: var(--ink2); flex: 1; }
.plan li { display: flex; gap: 8px; align-items: flex-start; }
.plan li svg { width: 15px; height: 15px; color: var(--accent); flex: none; margin-top: 2px; }
.plan .cta { margin-top: auto; }
.notes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.notes > div { display: flex; gap: 10px; align-items: flex-start; font-size: 13px; color: var(--ink2); padding: 12px 14px; }
.faq { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.faq .card { padding: 16px 18px; }
.faq dt { font-weight: 700; } .faq dd { margin: 6px 0 0; color: var(--ink2); font-size: 13px; }
@media (max-width: 960px) { .plans, .notes, .faq { grid-template-columns: 1fr; } }
"""


def render_pricing_page(*, site_base_url: str | None = None) -> str:
    cards = []
    tones = {"free": "b-grey", "daily": "b-amber", "pro": "b-violet"}
    icons = {"free": "layers", "daily": "zap", "pro": "brain"}
    for plan_id in ("free", "daily", "pro"):
        plan = PLANS[plan_id]
        featured = " featured" if plan_id == "daily" else ""
        if plan_id == "free":
            cta = '<a class="btn" href="/member?mode=signup">무료로 시작</a>'
        elif plan_id == "daily":
            cta = f'<a class="btn primary" href="/member?mode=signup&amp;plan={plan_id}">{h(str(TRIAL_DAYS))}일 무료 체험 후 구독</a>'
        else:
            cta = f'<a class="btn" href="/member?mode=signup&amp;plan={plan_id}">프로로 시작</a>'
        features = "".join(f"<li>{icon('check')}<span>{h(item)}</span></li>" for item in plan.features)
        price = "0" if plan.price_krw == 0 else f"{plan.price_krw:,}"
        ribbon = f'<span class="ribbon">{badge("가장 많이 선택", "b-amber", icon_name="star")}</span>' if plan_id == "daily" else ""
        cards.append(
            f"""<div class="card plan{featured}">
          {ribbon}
          <div class="name">{icon_tile(icons[plan_id], tones[plan_id], small=True)}{h(plan.name)}</div>
          <div class="price">{price}<small>원 / 월</small></div>
          <div class="tag">{h(plan.tagline)}</div>
          <ul>{features}</ul>
          <div class="cta">{cta}</div>
        </div>"""
        )
    notices = "".join(f'<div class="soft">{icon_tile("shield", "b-teal", small=True)}<span>{h(item)}</span></div>' for item in RESEARCH_TOOL_NOTICES)
    faqs = [
        ("무료와 유료의 차이는 무엇인가요?", "같은 데이터를 보되 시점과 깊이가 다릅니다. 무료는 다음 거래일부터 원장을 볼 수 있고, 유료는 07:50·10:05 실행 직후 토론 전문까지 봅니다."),
        ("결제는 어떻게 되나요?", "포트원을 통한 카드·카카오페이·네이버페이 정기결제입니다. 카드 정보는 결제사에만 저장되며 서비스는 결제 참조키만 보관합니다."),
        ("해지와 환불은요?", "구독 관리에서 언제든 해지할 수 있고 남은 기간은 그대로 이용합니다. 결제 후 7일 이내 전액 환불, 이후는 남은 기간 일할 환불입니다."),
        ("실계좌 자동매매도 되나요?", "아니요. 모의투자 자동화는 운영 검증용이며, 어떤 플랜에도 실계좌 주문이나 투자일임은 포함되지 않습니다."),
    ]
    faq_html = "".join(f'<div class="card"><dt>{h(q)}</dt><dd>{h(a)}</dd></div>' for q, a in faqs)
    body = f"""
<section class="hero pricing-hero">
  <div class="shell">
    {badge("요금제 · 리서치 도구 이용 범위", "b-teal")}
    <h1>오늘의 하네스를 언제, 얼마나 깊이 볼지 고르세요</h1>
    <p class="deck">무료는 전일 실행까지, 데일리 패스는 당일 실행 즉시와 AI 토론 전문까지 열립니다. 어느 플랜도 종목을 권유하거나 주문을 대신 내지 않습니다.</p>
  </div>
</section>
<section class="block"><div class="shell" style="padding-top: 14px;"><div class="plans">{''.join(cards)}</div></div></section>
<section class="block"><div class="shell">
  <div class="row between" style="margin-bottom: 10px;"><h2>이용 원칙과 환불</h2><a class="link tiny" href="/terms">이용약관 →</a></div>
  <div class="notes">{notices}</div>
</div></section>
<section class="block" style="padding-bottom: 28px;"><div class="shell">
  <h2 style="margin-bottom: 10px;">자주 묻는 질문</h2>
  <dl class="faq" style="margin: 0;">{faq_html}</dl>
</div></section>
"""
    return render_shell(
        title="요금제 | TradingAgents Korea",
        description="무료, 데일리 패스(월 10,000원), 프로(월 30,000원). 당일 하네스 열람, AI 토론 전문, 분석 요청 횟수를 넓히는 리서치 도구 요금제입니다.",
        body=body,
        active="/pricing",
        canonical_path="/pricing",
        site_base_url=site_base_url,
        extra_css=PRICING_CSS,
    )


__all__ = ["render_pricing_page", "PAID_PLANS"]
