"""Public pricing page on the shared design system."""

from __future__ import annotations

from .billing import PAID_PLANS, PLANS, RESEARCH_TOOL_NOTICES, TRIAL_DAYS
from .design_system import badge, h, icon, icon_tile, render_shell
from .seo import canonical_url

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


FREE_CSS = """
.free-hero { padding: 36px 0 26px; text-align: center; }
.free-hero h1 { font-size: 30px; margin-top: 10px; }
.free-hero p.deck { margin: 10px auto 0; max-width: 640px; color: var(--ink2); font-size: 15px; }
.free-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.free-grid .card { padding: 22px; display: flex; flex-direction: column; gap: 12px; }
.free-grid .name { font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.free-grid ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; font-size: 13px; color: var(--ink2); }
.free-grid li { display: flex; gap: 8px; align-items: flex-start; }
.free-grid li svg { width: 15px; height: 15px; color: var(--accent); flex: none; margin-top: 2px; }
.free-grid .cta { margin-top: auto; display: flex; gap: 8px; flex-wrap: wrap; }
.faq { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.faq .card { padding: 16px 18px; }
.faq dt { font-weight: 700; } .faq dd { margin: 6px 0 0; color: var(--ink2); font-size: 13px; }
@media (max-width: 960px) { .free-grid, .faq { grid-template-columns: 1fr; } }
"""


def render_free_page(*, site_base_url: str | None = None) -> str:
    """The page at /pricing while nothing is for sale: what is open, and how it is paid for."""

    import os

    from .billing import OPEN_PLAN

    youtube = (os.getenv("TRADINGAGENTS_YOUTUBE_URL") or "").strip()
    telegram_channel = (os.getenv("TRADINGAGENTS_TELEGRAM_CHANNEL_URL") or "").strip()

    def items(rows):
        return "".join(f"<li>{icon('check')}<span>{h(item)}</span></li>" for item in rows)

    follow = [f'<a class="btn primary" href="/member?mode=signup">텔레그램 아침 알림 받기</a>']
    if telegram_channel:
        follow.append(f'<a class="btn" href="{h(telegram_channel)}" target="_blank" rel="noopener">공개 채널</a>')
    if youtube:
        follow.append(f'<a class="btn" href="{h(youtube)}" target="_blank" rel="noopener">유튜브</a>')
    cards = f"""<div class="card">
      <div class="name">{icon_tile("zap", "b-amber", small=True)}전부 열립니다</div>
      <ul>{items(OPEN_PLAN.features)}</ul>
      <div class="cta"><a class="btn" href="/harness">오늘의 선별 보기</a><a class="btn" href="/paper">모의 계좌</a></div>
    </div>
    <div class="card">
      <div class="name">{icon_tile("shield", "b-teal", small=True)}이렇게 운영합니다</div>
      <ul>{items((
          "광고로 운영합니다. 결제와 구독은 없습니다.",
          "매일 아침 예측을 먼저 공개하고, 5·20거래일 뒤 결과를 그대로 기록합니다. 틀린 날도 남깁니다.",
          "실계좌 주문, 자동매매, 투자일임은 하지 않습니다. 모의 계좌 기록입니다.",
          "특정 종목의 매매를 권유하지 않으며 투자 판단의 책임은 본인에게 있습니다.",
      ))}</ul>
      <div class="cta"><a class="btn" href="/outcomes">성과 검증</a><a class="btn" href="/features/methodology">분석 기준</a></div>
    </div>
    <div class="card">
      <div class="name">{icon_tile("send", "b-blue", small=True)}받아보는 방법</div>
      <ul>{items((
          "회원가입 뒤 텔레그램을 연결하면 평일 아침 종목·등급·목표가·손절가가 옵니다.",
          "목표가·손절가 도달과 모의 계좌 청산도 같은 채널로 알려드립니다.",
          "가입은 무료이고, 저널·관심그룹·선호 설정을 한 곳에서 관리합니다.",
      ))}</ul>
      <div class="cta">{''.join(follow)}</div>
    </div>"""
    faqs = [
        ("왜 무료인가요?", "기록이 쌓여야 판단할 수 있는 서비스라서, 먼저 전부 공개하고 광고로 운영합니다. 결제 장벽 없이 예측과 결과를 그대로 보여드리는 쪽을 택했습니다."),
        ("광고는 어디에 나오나요?", "공개 페이지의 표 아래와 본문 사이에 Google 광고가 나옵니다. 광고 개인 최적화는 Google 광고 설정에서 끌 수 있습니다."),
        ("나중에 유료로 바뀌나요?", "지금 열려 있는 기능은 그대로 둡니다. 개인화 기능이나 후원 옵션을 나중에 더할 수는 있지만, 그때도 예측과 결과 기록은 공개합니다."),
        ("실계좌 자동매매도 되나요?", "아니요. 모의 계좌 자동화는 검증용이며, 실계좌 주문이나 투자일임은 하지 않습니다."),
    ]
    faq_html = "".join(f'<div class="card"><dt>{h(q)}</dt><dd>{h(a)}</dd></div>' for q, a in faqs)
    structured = [{"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]}]
    body = f"""
<section class="hero free-hero">
  <div class="shell">
    {badge("전부 무료 · 광고로 운영", "b-teal")}
    <h1>오늘의 선별부터 모의 계좌까지, 전부 무료입니다</h1>
    <p class="deck">당일 선별 결과, AI 토론 전문, 세 모의 계좌의 편입·청산, 텔레그램 아침 알림. 결제 없이 전부 열립니다. 어느 기능도 종목을 권유하거나 주문을 대신 내지 않습니다.</p>
  </div>
</section>
<section class="block"><div class="shell" style="padding-top: 14px;"><div class="free-grid">{cards}</div></div></section>
<section class="block" style="padding-bottom: 28px;"><div class="shell">
  <h2 style="margin-bottom: 10px;">자주 묻는 질문</h2>
  <dl class="faq" style="margin: 0;">{faq_html}</dl>
</div></section>
"""
    return render_shell(
        title="무료 안내 | TradingAgents Korea",
        description="당일 종목 선별, AI 토론 전문, 모의 계좌 기록, 텔레그램 아침 알림까지 전부 무료입니다. 광고로 운영하며 실계좌 주문은 없습니다.",
        body=body,
        active="/pricing",
        canonical_path="/pricing",
        site_base_url=site_base_url,
        extra_css=FREE_CSS,
        structured_data=structured,
        og_image=canonical_url("/og/pricing.png", site_base_url=site_base_url),
    )


def render_pricing_page(*, site_base_url: str | None = None) -> str:
    from .billing import paid_plans_enabled

    if not paid_plans_enabled():
        return render_free_page(site_base_url=site_base_url)
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
        ("무료와 유료의 차이는 무엇인가요?", "같은 데이터를 보되 시점과 깊이가 다릅니다. 무료는 다음 거래일부터 결과를 볼 수 있고, 유료는 07:50·10:05 선별 직후 토론 전문까지 봅니다."),
        ("결제는 어떻게 되나요?", "포트원으로 결제하는 카드·카카오페이·네이버페이 정기결제입니다. 카드 정보는 결제사에만 저장되며 서비스는 결제 참조키만 보관합니다."),
        ("해지와 환불은요?", "구독 관리에서 언제든 해지할 수 있고 남은 기간은 그대로 이용합니다. 결제 후 7일 이내 전액 환불, 이후는 남은 기간 일할 환불입니다."),
        ("실계좌 자동매매도 되나요?", "아니요. 모의투자 자동화는 운영 검증용이며, 어떤 플랜에도 실계좌 주문이나 투자일임은 포함되지 않습니다."),
    ]
    faq_html = "".join(f'<div class="card"><dt>{h(q)}</dt><dd>{h(a)}</dd></div>' for q, a in faqs)
    structured = [
        {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]},
        {
            "@type": "Product",
            "name": "TradingAgents Korea 리서치 플랜",
            "description": "당일 종목 선별 열람, AI 토론 전문, 분석 요청 횟수를 넓히는 리서치 도구 구독",
            "offers": [
                {"@type": "Offer", "name": PLANS[pid].name, "price": str(PLANS[pid].price_krw), "priceCurrency": "KRW", "availability": "https://schema.org/InStock", "url": canonical_url("/pricing", site_base_url=site_base_url)}
                for pid in ("free", "daily", "pro")
            ],
        },
    ]
    body = f"""
<section class="hero pricing-hero">
  <div class="shell">
    {badge("요금제 · 리서치 도구 이용 범위", "b-teal")}
    <h1>오늘의 선별 결과를 언제, 얼마나 깊이 볼지 고르세요</h1>
    <p class="deck">무료는 전날 결과까지, 데일리 패스는 당일 결과와 AI 토론 전문까지 열립니다. 어느 플랜도 종목을 권유하거나 주문을 대신 내지 않습니다.</p>
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
        description="무료, 데일리 패스(월 10,000원), 프로(월 30,000원). 당일 종목 선별 열람, AI 토론 전문, 분석 요청 횟수를 넓히는 리서치 도구 요금제입니다.",
        body=body,
        active="/pricing",
        canonical_path="/pricing",
        site_base_url=site_base_url,
        extra_css=PRICING_CSS,
        structured_data=structured,
        og_image=canonical_url("/og/pricing.png", site_base_url=site_base_url),
    )


__all__ = ["render_pricing_page", "PAID_PLANS"]
