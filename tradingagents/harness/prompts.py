"""The ten-step analysis playbook.

Each prompt keeps the operator's original wording as ``template`` and adds a
``schema`` describing the JSON the LLM must return so results can be stored,
compared over time, and fed into the deterministic risk/sizing steps. The
placeholders ``[업종 또는 주식]`` etc. are filled from ``render_prompt``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class PlaybookPrompt:
    id: str
    order: int
    title: str
    template: str
    placeholders: tuple[str, ...]
    schema: dict[str, Any]
    role: str = "analyst"
    context_keys: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "order": self.order,
            "title": self.title,
            "template": self.template,
            "placeholders": list(self.placeholders),
            "schema": self.schema,
            "role": self.role,
            "context_keys": list(self.context_keys),
        }


_COMMON_SCHEMA_FIELDS = {
    "summary": "핵심 결론 3문장 이내 (한국어)",
    "evidence": "근거 목록. 각 항목은 {claim, source, as_of} 형태이며 제공된 데이터/도구 결과에서만 인용",
    "confidence": "0.0~1.0 사이의 자기 보고 신뢰도",
    "caveats": "데이터 부족, 가정, 반대 시나리오 목록",
}


def _schema(**fields: str) -> dict[str, Any]:
    return {**fields, **_COMMON_SCHEMA_FIELDS}


PLAYBOOK: tuple[PlaybookPrompt, ...] = (
    PlaybookPrompt(
        id="market_analysis",
        order=1,
        title="시장 분석",
        template=(
            "주식 시장의 현재 추세를 분석하고, [업종 또는 주식]에 중점을 두세요. "
            "신흥 패턴을 식별하고 잠재적인 투자 기회를 제안하세요. "
            "분석에서는 최신 재무 보고서와 업계 뉴스를 고려하세요."
        ),
        placeholders=("업종 또는 주식",),
        schema=_schema(
            market_regime="상승/횡보/하락 중 하나와 근거",
            emerging_patterns="관찰된 패턴 목록",
            opportunities="종목코드, 근거, 촉매, 시계를 포함한 기회 목록",
            stance="Buy/Overweight/Hold/Underweight/Sell",
        ),
        context_keys=("screener", "chart", "news", "fundamentals"),
    ),
    PlaybookPrompt(
        id="diversification",
        order=2,
        title="투자 포트폴리오 다각화",
        template=(
            "주어진 포트폴리오가 [현재 산업 또는 주식]을 포함하고 있을 때, "
            "위험을 줄이기 위한 추가 다각화 전략을 제안합니다. "
            "탐색할 잠재적 산업과 구체적인 주식을 포함"
        ),
        placeholders=("현재 산업 또는 주식",),
        schema=_schema(
            concentration_risks="현재 집중 위험 목록",
            candidate_sectors="추가 탐색 업종과 이유",
            candidate_tickers="종목코드, 업종, 편입 근거, 제안 비중 목록",
            target_weights="종목코드→비중 매핑 (합계 1 이하)",
        ),
        role="portfolio_manager",
        context_keys=("portfolio", "diversification", "screener"),
    ),
    PlaybookPrompt(
        id="risk_management",
        order=3,
        title="리스크 관리",
        template=(
            "주식 거래자의 효과적인 리스크 관리 기술을 분석하라. "
            "거래 전략에서 손절매 주문, 다각화, 포지션 규모를 실행하는 방법에 대한 상세한 예시를 제공하라. "
            "[현재 거래 전략 또는 주식]을 참조로 삼아"
        ),
        placeholders=("현재 거래 전략 또는 주식",),
        schema=_schema(
            stop_loss_pct="권장 손절 비율 (0~1)",
            take_profit_pct="권장 익절 비율 (0~1)",
            risk_percent_per_trade="거래당 계좌 위험 비율 (0~0.05)",
            max_position_weight="종목 최대 비중 (0~1)",
            max_holding_days="최대 보유 거래일",
            risk_score="0(안전)~1(위험) 종합 위험 점수",
        ),
        role="risk_manager",
        context_keys=("chart", "risk_metrics", "forecast"),
    ),
    PlaybookPrompt(
        id="technical_analysis",
        order=4,
        title="기술 분석",
        template=(
            "기술 분석을 사용하여 [주식]을 평가하세요. "
            "최근 가격 추세, 거래량, 그리고 이동 평균선과 RSI와 같은 주요 지표를 분석하세요. "
            "매수, 매도 또는 보유를 제안하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            trend="추세 판단과 이동평균 배열",
            momentum="RSI/MACD 등 모멘텀 판단",
            volume="거래량 해석",
            key_levels="{support, resistance, pivot} 가격 수준",
            action="Buy/Hold/Sell",
            technical_score="0~1 기술적 매력도",
        ),
        context_keys=("chart", "factors", "forecast"),
    ),
    PlaybookPrompt(
        id="economic_indicators",
        order=5,
        title="경제 지표",
        template=(
            "GDP, 실업률, 인플레이션 등 경제 지표가 주식 시장 성과에 어떻게 영향을 미치는지 설명하세요. "
            "투자자들이 이러한 지표를 사용하여 [업종 또는 주식]에 대한 현명한 의사결정을 내리는 방법에 대한 예를 제공하세요."
        ),
        placeholders=("업종 또는 주식",),
        schema=_schema(
            macro_backdrop="현재 거시 환경 요약",
            indicator_impacts="지표별 영향 목록 {indicator, direction, impact_on_target}",
            positioning="거시 관점에서의 비중 조절 제안",
        ),
        context_keys=("news", "macro"),
    ),
    PlaybookPrompt(
        id="value_investing",
        order=6,
        title="가치 투자",
        template=(
            "가치 투자 원칙을 설명하고, 저평가된 주식을 식별하는 방법을 설명하십시오. "
            "실제 사례를 사용하되, [주식 또는 회사]를 포함하여, "
            "투자자들이 현재 시장에서 이 전략을 어떻게 적용할 수 있는지 설명하십시오."
        ),
        placeholders=("주식 또는 회사",),
        schema=_schema(
            valuation_metrics="PER/PBR/배당수익률/EV 등 관측값",
            intrinsic_value_estimate="추정 내재가치와 방법",
            margin_of_safety="안전마진 비율",
            verdict="저평가/적정/고평가",
        ),
        context_keys=("fundamentals", "snapshot"),
    ),
    PlaybookPrompt(
        id="market_sentiment",
        order=7,
        title="시장 심리",
        template=(
            "시장 심리가 주가에 미치는 영향을 분석하라. "
            "투자자들이 감정을 평가하고 이를 거래 전략에 통합하는 데 사용할 수 있는 도구와 기술을 논의하라. "
            "[주식 또는 산업]에 중점을 두라."
        ),
        placeholders=("주식 또는 산업",),
        schema=_schema(
            sentiment_score="-1(공포)~1(탐욕)",
            drivers="심리를 움직이는 요인 목록",
            contrarian_signals="역발상 신호 여부",
            integration="전략 통합 방법",
        ),
        context_keys=("news", "chart"),
    ),
    PlaybookPrompt(
        id="financial_statements",
        order=8,
        title="재무제표 해석",
        template=(
            "회사의 재무제표를 어떻게 해석하는지 설명하세요. "
            "투자자들이 주목해야 할 핵심 지표를 강조하고, 이러한 지표가 주가에 어떻게 영향을 미치는지 다루세요. "
            "[회사 최신 재무제표]를 예로 들어 설명하세요."
        ),
        placeholders=("회사 최신 재무제표",),
        schema=_schema(
            profitability="매출/영업이익/순이익 추세",
            balance_sheet="부채비율, 유동성, 현금",
            cash_flow="영업/투자/재무 현금흐름 해석",
            red_flags="주의 항목 목록",
            quality_score="0~1 재무 건전성",
        ),
        context_keys=("fundamentals",),
    ),
    PlaybookPrompt(
        id="growth_vs_dividend",
        order=9,
        title="성장주/배당주",
        template=(
            "성장주와 배당주를 비교하고 대조하라. "
            "각 투자 유형의 장점과 위험을 분석하고, "
            "어떤 상황에서 한 유형이 다른 유형보다 더 적합할 수 있는지 제안하라."
        ),
        placeholders=(),
        schema=_schema(
            classification="대상 종목이 성장주/배당주/혼합 중 무엇인지",
            fit_for_current_regime="현재 시장 국면에 더 적합한 유형과 이유",
            allocation_hint="성장/배당 비중 제안",
        ),
        context_keys=("fundamentals", "snapshot", "macro"),
    ),
    PlaybookPrompt(
        id="global_events",
        order=10,
        title="글로벌 이벤트",
        template=(
            "주요 글로벌 이벤트(예: 지정학적 긴장, 팬데믹)가 주식 시장에 미치는 영향을 분석하세요. "
            "이러한 이벤트에서 투자자들이 포트폴리오를 보호할 수 있는 전략을 제공하세요. "
            "[업종 또는 주식]에 대한 영향을 고려하세요."
        ),
        placeholders=("업종 또는 주식",),
        schema=_schema(
            active_events="현재 진행 중인 글로벌 이벤트 목록",
            exposure="대상에 대한 노출도와 경로",
            hedging_strategies="보호 전략 목록",
        ),
        context_keys=("news", "macro"),
    ),
    # ------------------------------------------------------------------
    # Additional harness steps recommended for the Korean-market loop.
    # They cover gaps the ten operator prompts leave open: KRX-specific
    # flow data, disclosure/event risk, explicit scenarios, a devil's
    # advocate pass, a concrete execution plan, post-trade review, and a
    # market-regime gate.
    # ------------------------------------------------------------------
    PlaybookPrompt(
        id="investor_flows",
        order=11,
        title="수급 분석",
        template=(
            "[주식]의 최근 외국인·기관·개인 순매수 흐름, 공매도 잔고, 신용잔고 추이를 분석하세요. "
            "수급이 주가 방향과 일치하는지, 수급 반전 신호가 있는지 판단하고 매수/보유/매도 관점에서 함의를 제시하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            foreign_flow="외국인 순매수 추세와 해석",
            institution_flow="기관 순매수 추세와 해석",
            short_interest="공매도/신용 관련 위험",
            flow_alignment="수급과 가격 방향 일치 여부 (aligned/diverging/unknown)",
            flow_score="-1(매도 우위)~1(매수 우위)",
        ),
        context_keys=("flows", "chart"),
    ),
    PlaybookPrompt(
        id="disclosure_events",
        order=12,
        title="공시·이벤트 캘린더",
        template=(
            "[주식]의 최근 DART 공시(유상증자, 전환사채, 자사주, 대주주 변동, 실적 발표)와 향후 예정 이벤트(실적 발표일, 배당락, 락업 해제)를 정리하세요. "
            "각 이벤트가 주가에 미칠 영향과 진입 시점에 대한 시사점을 제시하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            recent_disclosures="최근 공시 목록 {date, type, impact}",
            upcoming_events="예정 이벤트 목록 {date, type, expected_impact}",
            dilution_risk="희석/오버행 위험 (low/medium/high)",
            timing_note="진입 시점 관련 주의사항",
        ),
        context_keys=("disclosures", "news"),
    ),
    PlaybookPrompt(
        id="scenario_catalysts",
        order=13,
        title="시나리오·촉매",
        template=(
            "[주식]에 대해 강세/기본/약세 세 가지 시나리오를 정의하고 각 시나리오의 확률, 목표가, 촉매(트리거)를 제시하세요. "
            "확률 가중 기대수익률을 계산하고, 어떤 시나리오가 현실화되고 있는지 판단할 관측 지표를 명시하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            bull_case="{probability, target_price, catalysts}",
            base_case="{probability, target_price, catalysts}",
            bear_case="{probability, target_price, catalysts}",
            expected_return="확률 가중 기대수익률 (소수)",
            monitoring_indicators="시나리오 확인용 관측 지표 목록",
        ),
        context_keys=("chart", "forecast", "fundamentals", "news"),
    ),
    PlaybookPrompt(
        id="devils_advocate",
        order=14,
        title="반대 논거 (프리모템)",
        template=(
            "[주식] 매수 결정이 6개월 뒤 실패로 판명되었다고 가정하고, 그 이유를 가장 설득력 있게 설명하세요. "
            "현재 분석에서 과소평가된 위험, 확증편향 가능성, 데이터 품질 문제를 지적하고 매수 논리가 무효화되는 조건을 명시하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            failure_narrative="실패 시나리오 서술",
            underweighted_risks="과소평가된 위험 목록",
            invalidation_conditions="매수 논리를 무효화하는 구체적 조건 목록",
            bias_check="확증편향/데이터 품질 우려",
            conviction_adjustment="-1~0 사이, 확신을 얼마나 낮춰야 하는지",
        ),
        role="bear_researcher",
        context_keys=("previous_conclusions", "risk_metrics", "forecast"),
    ),
    PlaybookPrompt(
        id="execution_plan",
        order=15,
        title="실행 계획",
        template=(
            "[주식]에 대한 구체적 실행 계획을 작성하세요: 진입 가격대와 분할 매수 계획, 손절가, 1차/2차 익절가, 최대 보유 기간, 계좌 대비 포지션 비중, "
            "재진입 및 물타기 금지 규칙을 포함하세요. 한국 시장 규칙(±30% 가격제한, 09:00-15:30 정규장, 매도 거래세)을 반영하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            entry_zone="{low, high} 진입 가격대",
            tranches="분할 매수 계획 목록 {weight, condition}",
            stop_loss_price="손절 가격",
            take_profit_prices="익절 가격 목록",
            max_holding_days="최대 보유 거래일",
            position_weight="계좌 대비 비중 (0~1)",
            rules="재진입/물타기/시간손절 규칙 목록",
        ),
        role="trader",
        context_keys=("chart", "risk_metrics", "forecast", "previous_conclusions"),
    ),
    PlaybookPrompt(
        id="post_trade_review",
        order=16,
        title="사후 복기",
        template=(
            "[주식]에 대한 과거 가상매매/분석 결과를 복기하세요. 진입 근거가 실제로 맞았는지, 손절/익절 규칙이 적절했는지, "
            "패턴별 승률과 평균 수익률에서 얻은 교훈을 정리하고 다음 분석에 반영할 규칙 변경을 제안하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            hit_rate="승률 (0~1) 또는 null",
            average_return="평균 수익률 또는 null",
            what_worked="효과가 있었던 근거/규칙 목록",
            what_failed="실패한 근거/규칙 목록",
            rule_changes="다음 분석에 적용할 규칙 변경 제안 목록",
        ),
        context_keys=("paper_outcomes", "previous_conclusions"),
    ),
    PlaybookPrompt(
        id="market_regime",
        order=17,
        title="시장 국면·상대강도",
        template=(
            "KOSPI/KOSDAQ 지수의 추세, 시장 폭(상승 종목 비율), 변동성 수준을 바탕으로 현재 시장 국면(위험선호/중립/위험회피)을 판정하고, "
            "[주식]의 벤치마크 대비 상대강도를 평가하세요. 국면상 신규 매수를 줄여야 하는지 판단하세요."
        ),
        placeholders=("주식",),
        schema=_schema(
            regime="risk_on/neutral/risk_off",
            index_trend="지수 추세 요약",
            relative_strength="벤치마크 대비 상대강도 (-1~1)",
            new_entry_allowed="신규 매수 허용 여부 (true/false)",
            exposure_cap="권장 총 노출 상한 (0~1)",
        ),
        role="risk_manager",
        context_keys=("index", "chart", "screener"),
    ),
)

_BY_ID = {prompt.id: prompt for prompt in PLAYBOOK}

_PLACEHOLDER_ALIASES = {
    "업종 또는 주식": ("target", "sector_or_ticker", "ticker", "sector"),
    "현재 산업 또는 주식": ("portfolio_holdings", "target", "ticker"),
    "현재 거래 전략 또는 주식": ("strategy", "target", "ticker"),
    "주식": ("target", "ticker"),
    "주식 또는 회사": ("target", "ticker", "company"),
    "주식 또는 산업": ("target", "ticker", "sector"),
    "회사 최신 재무제표": ("financial_statements", "target", "ticker"),
}


CORE_PROMPT_COUNT = 10


def list_prompts(*, extended: bool = True) -> list[PlaybookPrompt]:
    """Return prompts in order. ``extended=False`` keeps only the operator's ten."""

    prompts = sorted(PLAYBOOK, key=lambda prompt: prompt.order)
    if not extended:
        return [prompt for prompt in prompts if prompt.order <= CORE_PROMPT_COUNT]
    return prompts


def get_prompt(prompt_id: str) -> PlaybookPrompt:
    try:
        return _BY_ID[prompt_id]
    except KeyError as exc:
        raise KeyError(f"Unknown playbook prompt {prompt_id!r}. Choose from {sorted(_BY_ID)}") from exc


def render_prompt(prompt: PlaybookPrompt | str, values: Mapping[str, Any]) -> str:
    """Fill the bracket placeholders using ``values`` (or their aliases)."""

    selected = get_prompt(prompt) if isinstance(prompt, str) else prompt
    text = selected.template
    for placeholder in selected.placeholders:
        replacement = None
        for key in (placeholder, *_PLACEHOLDER_ALIASES.get(placeholder, ())):
            if key in values and values[key] not in (None, ""):
                replacement = str(values[key])
                break
        if replacement is None:
            raise ValueError(f"missing value for placeholder [{placeholder}] in prompt {selected.id}")
        text = text.replace(f"[{placeholder}]", replacement)
    return text
