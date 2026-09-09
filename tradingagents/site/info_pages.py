"""Public information pages on the shared design system.

`/features`, `/features/{slug}` and the policy pages (`/privacy`, `/terms`,
`/disclaimer`). Copy and legal text still live in ``web_pages`` (``FEATURE_DETAIL_PAGES``,
``POLICY_PAGES``); this module only renders them with :func:`render_shell`.
"""

from __future__ import annotations

from typing import Any, Sequence

from .design_system import badge, h, icon, icon_tile, render_shell
from .seo import canonical_url

# Plain-language replacements for product jargon in feature copy. Policy pages are
# legal text and are rendered verbatim; only their wrapper changes.
_PLAIN_TERMS: tuple[tuple[str, str], ...] = (
    ("내 공간", "마이페이지"),
    ("사후 결과", "검증 결과"),
    ("종목 분석실", "종목 분석"),
    ("하네스", "종목 선별"),
    ("유니버스", "대상 종목"),
    ("깔때기", "선별 과정"),
    ("가상 주문", "모의 주문"),
    ("가상 매수", "모의 매수"),
    ("감사 원장", "실행 기록"),
    ("판정관", "판정"),
    ("리스크 패널", "리스크 점검"),
    ("알파", "초과수익"),
)

FEATURE_ICONS: dict[str, tuple[str, str]] = {
    "research": ("search", "b-teal"),
    "member-workspace": ("users", "b-blue"),
    "outcomes": ("target", "b-violet"),
    "methodology": ("book", "b-amber"),
}

INFO_CSS = """
.info-hero { padding: 34px 0 26px; }
.info-hero h1 { font-size: 30px; margin-top: 10px; max-width: 760px; }
.info-hero p.lead { margin-top: 10px; max-width: 680px; color: var(--ink2); font-size: 15px; line-height: 1.65; }
.info-hero .cta-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 18px; }
.proof { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 18px; max-width: 760px; }
.proof > div { padding: 10px 14px; }
.proof b { display: block; font-size: 14px; color: var(--ink); margin-top: 2px; }
.feature-card { display: flex; flex-direction: column; gap: 10px; padding: 18px; color: inherit; }
.feature-card:hover { text-decoration: none; border-color: var(--accent); }
.feature-card h2 { font-size: 16px; }
.feature-card p { color: var(--ink2); font-size: 13px; flex: 1; }
.feature-card .go { color: var(--accent-ink); font-size: 13px; font-weight: 600; display: inline-flex; align-items: center; gap: 4px; }
.feature-card .go svg { width: 14px; height: 14px; }
.steps { display: grid; gap: 12px; }
.steps > div { display: flex; gap: 12px; align-items: flex-start; }
.steps .n { width: 28px; height: 28px; border-radius: 8px; background: var(--accent-soft); color: var(--accent-ink); font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; flex: none; font-variant-numeric: tabular-nums; }
.steps b { display: block; font-size: 14px; }
.steps p { color: var(--ink2); font-size: 13px; margin-top: 2px; }
.flow { display: grid; gap: 8px; }
.flow .item { display: flex; gap: 10px; align-items: center; padding: 10px 12px; font-size: 13px; font-weight: 600; }
.flow .n { width: 22px; height: 22px; border-radius: 6px; background: var(--panel); color: var(--accent-ink); font-size: 11px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.bullets { margin: 0; padding-left: 18px; color: var(--ink2); font-size: 13px; display: grid; gap: 6px; }
.grid-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.grid-cards.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.feature-hero-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 24px; align-items: start; }
.next-card { display: flex; gap: 12px; align-items: flex-start; padding: 16px 18px; color: inherit; }
.next-card:hover { text-decoration: none; border-color: var(--accent); }
.next-card b { display: block; font-size: 14px; }
.next-card p { color: var(--ink2); font-size: 13px; margin-top: 2px; }
@media (max-width: 960px) {
  .proof, .grid-cards, .grid-cards.two, .feature-hero-grid { grid-template-columns: 1fr; }
  .info-hero h1 { font-size: 24px; }
}
"""

POLICY_CSS = """
.policy-doc { max-width: 760px; font-size: 15px; line-height: 1.7; color: var(--ink); }
.policy-doc h2 { font-size: 18px; margin-top: 32px; display: flex; align-items: center; gap: 10px; }
.policy-doc h2:first-child { margin-top: 0; }
.policy-doc h2 .n { font-size: 12px; font-weight: 700; color: var(--accent-ink); background: var(--accent-soft); border-radius: 6px; padding: 2px 7px; font-variant-numeric: tabular-nums; }
.policy-doc ul { margin: 12px 0 0; padding-left: 22px; display: grid; gap: 8px; }
.policy-doc li { color: var(--ink2); }
.callouts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.callouts > div { padding: 14px 16px; }
.callouts b { display: block; font-size: 14px; margin-top: 6px; }
.callouts p { color: var(--ink2); font-size: 13px; margin-top: 4px; }
@media (max-width: 960px) { .callouts { grid-template-columns: 1fr; } }
"""


def _plain(value: Any) -> str:
    text = "" if value is None else str(value)
    for jargon, plain in _PLAIN_TERMS:
        text = text.replace(jargon, plain)
    return text


def _og_head(title: str, description: str, canonical: str) -> str:
    return (
        '<meta property="og:type" content="website">'
        '<meta property="og:locale" content="ko_KR">'
        '<meta name="twitter:card" content="summary">'
        '<meta property="og:site_name" content="TradingAgents Korea">'
        f'<meta property="og:title" content="{h(title)}">'
        f'<meta property="og:description" content="{h(description)}">'
        f'<meta property="og:url" content="{h(canonical)}">'
    )


def _proof_row(items: Sequence[tuple[str, str]], *, label: str, plain: bool = True) -> str:
    cells = "".join(
        f'<div class="soft"><span class="label">{h(_plain(key) if plain else key)}</span><b>{h(_plain(value) if plain else value)}</b></div>'
        for key, value in items
    )
    return f'<div class="proof" role="list" aria-label="{h(label)}">{cells}</div>'


def _steps(rows: Sequence[tuple[str, str, str]]) -> str:
    return "".join(
        f'<div><span class="n">{h(number)}</span><div><b>{h(_plain(title))}</b><p>{h(_plain(copy))}</p></div></div>'
        for number, title, copy in rows
    )


# --- /features ---------------------------------------------------------------------------
def render_feature_index_page(*, site_base_url: str | None = None) -> str:
    """Render the public feature hub for first-time visitors."""

    from .web_pages import FEATURE_DETAIL_PAGES

    title = "처음 시작하기 | TradingAgents Korea"
    description = "TradingAgents Korea의 종목 검색, AI 리포트, 마이페이지, 검증 결과, 분석 기준을 한 번에 확인합니다."
    canonical = canonical_url("/features", site_base_url=site_base_url)

    cards = []
    for index, (slug, page) in enumerate(FEATURE_DETAIL_PAGES.items(), start=1):
        icon_name, tone = FEATURE_ICONS.get(slug, ("layers", "b-grey"))
        cards.append(
            f'<a class="card feature-card" href="{h(str(page["path"]))}">'
            f'<div class="row between">{icon_tile(icon_name, tone)}<span class="tiny muted num">{index:02d}</span></div>'
            f'<h2>{h(_plain(page["heading"]))}</h2>'
            f'<p>{h(_plain(page["description"]))}</p>'
            f'<span class="go">자세히 보기{icon("chevron")}</span>'
            "</a>"
        )

    journey = _steps(
        (
            ("01", "종목 검색", "6자리 코드나 종목명으로 공개 가격, 뉴스, 공시, 리포트를 확인합니다."),
            ("02", "근거 확인", "기준일과 출처, AI 의견, 리포트 본문, 검증 결과를 차례로 읽습니다."),
            ("03", "회원 저장", "가입 후 매매 일지, 관심그룹, 분석 요청을 마이페이지에 남깁니다."),
            ("04", "주문 없음", "서비스는 증권사 주문 권한을 갖지 않고 기록과 조회만 제공합니다."),
        )
    )
    flow = "".join(
        f'<div class="item soft"><span class="n">{i}</span>{h(step)}</div>'
        for i, step in enumerate(("종목 검색", "AI 리포트", "회원 기록", "요청 대기열", "주문 차단"), start=1)
    )

    body = f"""
<section class="hero info-hero">
  <div class="shell feature-hero-grid">
    <div>
      {badge("처음 방문자 흐름", "b-teal", icon_name="zap")}
      <h1>종목을 읽고, 필요한 기록만 마이페이지에 남깁니다</h1>
      <p class="lead">먼저 종목을 검색하고 AI 리포트를 읽어보세요. 가입 후에는 관심그룹, 분석 요청, 매매 일지를 마이페이지에 저장합니다. 주문은 실행하지 않습니다.</p>
      {_proof_row((("공개 리서치", "검색 / 분석 / 검증 결과"), ("회원 공간", "관심그룹 / 매매 일지 / 요청"), ("투자 실행", "실거래 주문 차단")), label="서비스 범위")}
      <div class="cta-row">
        <a class="btn primary" href="/stocks/005930">샘플 종목 보기</a>
        <a class="btn" href="/member?mode=signup">마이페이지 만들기</a>
        <a class="btn ghost" href="/analyses">공개 분석 보기</a>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h2>{icon_tile("layers", "b-blue", small=True)}서비스 이용 흐름</h2>{badge("조회 전용", "b-grey", xs=True)}</div>
      <div class="card-b flow">{flow}</div>
      <div class="card-f"><span>검색은 공개, 기록은 회원 공간</span><span>공개 데이터와 개인 기록을 분리합니다.</span></div>
    </div>
  </div>
</section>
<section class="block"><div class="shell">
  <h2 style="margin-bottom: 10px;">사용 흐름 목록</h2>
  <div class="grid-cards two">{''.join(cards)}</div>
</div></section>
<section class="block" style="padding-bottom: 28px;"><div class="shell">
  <div class="card">
    <div class="card-h"><h2>{icon_tile("check", "b-teal", small=True)}처음 방문자가 바로 이어갈 수 있는 순서</h2><span class="tiny muted">공개 리서치로 먼저 확인하고, 다시 볼 종목만 회원 공간에 보관합니다.</span></div>
    <div class="card-b grid-4 steps" style="gap: 16px;">{journey}</div>
  </div>
</div></section>
"""
    return render_shell(
        title=title,
        description=description,
        body=body,
        active=None,
        canonical_path="/features",
        site_base_url=site_base_url,
        extra_head=_og_head(title, description, canonical),
        extra_css=INFO_CSS,
    )


# --- /features/{slug} ---------------------------------------------------------------------
def render_feature_detail_page(slug: str, *, site_base_url: str | None = None) -> str:
    """Render a public feature detail page on the shared shell."""

    from .web_pages import FEATURE_DETAIL_PAGES

    page = FEATURE_DETAIL_PAGES.get(slug)
    if page is None:
        raise ValueError("Unknown feature page")

    icon_name, tone = FEATURE_ICONS.get(slug, ("layers", "b-grey"))
    title = _plain(page["title"])
    description = str(page["description"])
    path = str(page["path"])
    canonical = canonical_url(path, site_base_url=site_base_url)

    cards = "".join(
        f'<div class="card feature-card"><div class="row between"><span class="tiny muted num">{index:02d}</span></div>'
        f'<h2>{h(_plain(card_title))}</h2><p>{h(_plain(copy))}</p></div>'
        for index, (card_title, copy) in enumerate(page["cards"], start=1)
    )
    flow = "".join(
        f'<div class="item soft"><span class="n">{i}</span>{h(_plain(step))}</div>'
        for i, step in enumerate(page["steps"], start=1)
    )
    journey_rows = page.get("journey", ())
    journey = _steps(journey_rows) if journey_rows else ""
    secondary_href = str(page.get("secondary_cta_href", "/features/member-workspace"))
    secondary_label = _plain(page.get("secondary_cta_label", "회원 기능 보기"))
    grid_class = "grid-cards" if len(page["cards"]) % 3 == 0 else "grid-cards two"

    body = f"""
<section class="hero info-hero">
  <div class="shell feature-hero-grid">
    <div>
      {badge(_plain(page["eyebrow"]), tone, icon_name=icon_name)}
      <h1>{h(_plain(page["heading"]))}</h1>
      <p class="lead">{h(_plain(page["lead"]))}</p>
      {_proof_row(page["proof"], label="기능 기준")}
      <div class="cta-row">
        <a class="btn primary" href="{h(str(page["cta_href"]))}">{h(_plain(page["cta_label"]))}</a>
        <a class="btn" href="{h(secondary_href)}">{h(secondary_label)}</a>
      </div>
    </div>
    <div class="card">
      <div class="card-h"><h2>{icon_tile(icon_name, tone, small=True)}{h(_plain(page.get("diagram_label") or page["eyebrow"]))}</h2>{badge("주문 없음", "b-grey", xs=True)}</div>
      <div class="card-b flow">{flow}</div>
      <div class="card-f"><span>TA-KR</span><span>{h(description)}</span></div>
    </div>
  </div>
</section>
<section class="block"><div class="shell">
  <h2 style="margin-bottom: 10px;">기능 세부 구성</h2>
  <div class="{grid_class}">{cards}</div>
</div></section>
<section class="block"><div class="shell">
  <div class="card">
    <div class="card-h"><h2>{icon_tile("check", "b-teal", small=True)}{h(_plain(page.get("journey_heading", "처음 방문자도 바로 이어갈 수 있습니다")))}</h2><span class="tiny muted">{h(_plain(page.get("journey_intro", "공개 리서치를 먼저 확인하고 필요한 기록만 마이페이지에 저장합니다.")))}</span></div>
    <div class="card-b grid-4 steps" style="gap: 16px;">{journey}</div>
  </div>
</div></section>
<section class="block" style="padding-bottom: 28px;"><div class="shell">
  <div class="card">
    <div class="card-h"><h2>{icon_tile("shield", "b-teal", small=True)}데이터 경계</h2><span class="tiny muted">필요한 데이터만 불러옵니다</span></div>
    <div class="card-b"><ul class="bullets">
      <li>공개 상세 페이지는 안내 내용과 로그인 상태 표시만 사용합니다.</li>
      <li>회원 데이터는 로그인 상태를 확인한 뒤 마이페이지에서만 불러옵니다.</li>
    </ul></div>
  </div>
</div></section>
"""
    return render_shell(
        title=title,
        description=description,
        body=body,
        active=None,
        canonical_path=path,
        site_base_url=site_base_url,
        extra_head=_og_head(title, description, canonical),
        extra_css=INFO_CSS,
    )


# --- /privacy, /terms, /disclaimer -------------------------------------------------------
def render_policy_page(slug: str, *, site_base_url: str | None = None) -> str:
    """Render a public policy page. Legal text is passed through verbatim."""

    from .web_pages import POLICY_PAGES

    page = POLICY_PAGES.get(slug)
    if page is None:
        raise ValueError("Unknown policy page")

    title = str(page["title"])
    description = str(page["description"])
    path = str(page["path"])
    canonical = canonical_url(path, site_base_url=site_base_url)
    short_title = title.split("|")[0].strip()

    callouts = "".join(
        f'<div class="soft"><span class="tiny muted num">{index:02d}</span><b>{h(callout_title)}</b><p>{h(copy)}</p></div>'
        for index, (callout_title, copy) in enumerate(page["callouts"], start=1)
    )
    sections = "".join(
        f'<h2 id="policy-section-{index}"><span class="n">{index:02d}</span>{h(section_title)}</h2>'
        f'<ul>{"".join(f"<li>{h(item)}</li>" for item in items)}</ul>'
        for index, (section_title, items) in enumerate(page["sections"], start=1)
    )
    next_actions = "".join(
        f'<a class="card next-card" href="{h(href)}"><span class="badge b-grey xs num">{index:02d}</span><div><b>{h(label)}</b><p>{h(copy)}</p></div></a>'
        for index, (label, href, copy) in enumerate(page.get("next_actions", ()), start=1)
    )

    body = f"""
<section class="hero info-hero">
  <div class="shell">
    {badge(str(page["eyebrow"]), "b-navy", icon_name="shield")}
    <h1>{h(page["heading"])}</h1>
    <p class="lead">{h(page["lead"])}</p>
    {_proof_row(page["summary"], label="정책 요약", plain=False)}
  </div>
</section>
<section class="block"><div class="shell">
  <div class="row between wrap" style="margin-bottom: 10px;"><h2>{h(short_title)} 핵심 원칙</h2>{badge("공개 정책 · 주문 없음", "b-grey", xs=True)}</div>
  <div class="callouts">{callouts}</div>
</div></section>
<section class="block"><div class="shell">
  <div class="card">
    <div class="card-h"><h2>{icon_tile("book", "b-navy", small=True)}{h(short_title)}</h2><span class="tiny muted">{h(description)}</span></div>
    <div class="card-b"><article class="policy-doc" aria-label="정책 세부 내용">{sections}</article></div>
  </div>
</div></section>
<section class="block"><div class="shell">
  <div class="row between wrap" style="margin-bottom: 10px;"><h2>다음으로 확인할 화면</h2><span class="tiny muted">정책을 읽은 뒤 실제 서비스 흐름으로 이어갑니다.</span></div>
  <div class="grid-cards">{next_actions}</div>
</div></section>
<section class="block" style="padding-bottom: 28px;"><div class="shell">
  <div class="card">
    <div class="card-h"><h2>{icon_tile("shield", "b-teal", small=True)}AI 리포트와 회원 기록의 경계를 분리합니다</h2>{badge("주문 없음", "b-teal", xs=True)}</div>
    <div class="card-b"><ul class="bullets">
      <li><a class="link" href="/features/methodology">분석 기준</a>에서 데이터 출처와 AI 분석 한계를 함께 확인할 수 있습니다.</li>
      <li><a class="link" href="/disclaimer">투자 유의사항</a>, <a class="link" href="/terms">이용약관</a>, <a class="link" href="/privacy">개인정보처리방침</a>은 공개 페이지로 제공합니다.</li>
      <li>TradingAgents Korea는 실거래 주문 기능을 제공하지 않는 주문 없는 AI 리서치 플랫폼입니다.</li>
    </ul></div>
  </div>
</div></section>
"""
    return render_shell(
        title=title,
        description=description,
        body=body,
        active=None,
        canonical_path=path,
        site_base_url=site_base_url,
        extra_head=_og_head(title, description, canonical),
        extra_css=INFO_CSS + POLICY_CSS,
    )


__all__ = ["render_feature_index_page", "render_feature_detail_page", "render_policy_page"]
