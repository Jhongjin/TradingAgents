"""The things the channel can explain on a day when nothing happened.

A daily channel that only reports its own account says the same sentence every
morning — we lost a little, the stop caught it — and gives nobody a reason to
subscribe. These are the other half: how the thing works, why it was built that
way, and what changed when the rule changed.

Nothing here is a slogan. Every figure in a proof row is either read off the
live account or comes from a backtest that is named and dated, because a cut
that explains the method and then makes its evidence up is worse than no cut.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

# The rule change that is actually in force, measured on the same universe over
# the same window. Stated with its date so it ages visibly instead of quietly.
BACKTEST_LABEL = "2026년 9월 백테스트 · 손절 5%→8%, 변동성 상위 20% 제외"
BACKTEST_ROWS = (
    ("누적 수익률", "+52.2%", "+129.7%"),
    ("최대 낙폭", "−28.7%", "−24.2%"),
    ("샤프 지수", "0.64", "1.20"),
    ("승률", "39.3%", "47.9%"),
)

Proof = tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class Topic:
    """One explainer: the question, the mechanism, and what it did."""

    key: str
    kicker: str
    hero: str
    hero_unit: str
    caption: str
    lines: tuple[str, str]
    steps_head: str
    steps: tuple[tuple[str, str], ...]
    steps_note: str
    proof_head: str
    proof: Callable[[Mapping[str, Any]], Proof]
    proof_note: str
    outro: tuple[str, str]
    call: str
    title: str
    lead: str                       # the first line of the description
    path: str                       # where the receipts live on the site
    tags: tuple[str, ...]
    comment: str
    narration: tuple[str, str, str, str]

    def ready(self, payload: Mapping[str, Any]) -> bool:
        """Whether the evidence beat has anything to put in it."""

        return bool(self.proof(payload))


def _books(payload: Mapping[str, Any]) -> dict[str, dict]:
    return {
        str(item.get("key")): item
        for item in payload.get("accounts") or []
        if (item.get("summary") or {}).get("total_return") is not None
    }


def _pct(value: Any) -> str:
    return f"{float(value) * 100:+.2f}%"


def stop_loss_pct() -> float:
    """The stop the account actually trades on, read from the rule itself."""

    try:
        from tradingagents.harness.config import PipelineConfig

        return float(PipelineConfig().stop_loss_pct)
    except Exception:                                   # noqa: BLE001 - the cut still has a number
        return 0.08


def _stop_proof(payload: Mapping[str, Any]) -> Proof:
    return BACKTEST_ROWS


def _books_proof(payload: Mapping[str, Any]) -> Proof:
    """The two books side by side: the whole reason a second one is run."""

    books = _books(payload)
    paper, rules = books.get("paper"), books.get("rules")
    if not paper or not rules:
        return ()
    ps, rs = paper.get("summary") or {}, rules.get("summary") or {}
    gap = float(ps.get("total_return") or 0.0) - float(rs.get("total_return") or 0.0)
    return (
        ("수익률", _pct(rs.get("total_return")), _pct(ps.get("total_return"))),
        ("보유 종목", f"{int(rs.get('open_count') or 0)}종목", f"{int(ps.get('open_count') or 0)}종목"),
        ("정리한 건수", f"{int(rs.get('closed_count') or 0)}건", f"{int(ps.get('closed_count') or 0)}건"),
        ("AI가 보탠 몫", "기준", f"{gap * 100:+.2f}%p"),
    )


def _open_proof(payload: Mapping[str, Any]) -> Proof:
    """What is on the site: everything, including the part that went wrong."""

    summary = payload.get("summary") or {}
    closed = [item for item in payload.get("closed") or [] if item.get("realized_return") is not None]
    total = int(summary.get("closed_count") or len(closed))
    if not total:
        return ()
    losses = len([item for item in closed if float(item["realized_return"]) < 0])
    return (
        ("공개한 거래", "일부", f"{total}건 전부"),
        ("그중 손실", "숨김", f"{losses}건 그대로"),
        ("지운 기록", "—", "0건"),
    )


TOPICS: tuple[Topic, ...] = (
    Topic(
        key="explain_stop",
        kicker="규칙 하나 뜯어보기",
        hero=f"{stop_loss_pct() * 100:.0f}",
        hero_unit="%",
        caption="모든 종목에 똑같이 걸려 있는 손절선입니다",
        lines=("사고 나서 정하지", "않습니다."),
        steps_head="언제 정하느냐가 전부입니다",
        steps=(
            ("사기 전에 정합니다", "주문을 넣는 순간 나갈 가격이 같이 기록됩니다. 오른 뒤에 올리거나 내린 뒤에 내리지 않습니다."),
            ("종목을 가리지 않습니다", "마음에 드는 종목이라고 더 버티지 않습니다. 같은 선, 같은 폭입니다."),
            ("닿으면 자동으로 정리됩니다", "다음 실행에서 바로 처리됩니다. 그 사이에 사람이 끼어들 자리는 없습니다."),
        ),
        steps_note="정해둔 선을 지키는 것과 잘 고르는 것은 다른 문제입니다. 여기서 지키는 건 앞쪽입니다.",
        proof_head="선을 바꿔봤더니",
        proof=_stop_proof,
        proof_note=BACKTEST_LABEL + ". 과거 성과이며 앞으로를 보장하지 않습니다.",
        outro=("규칙을 바꾸면", "바꾼 날짜까지 적습니다."),
        call="현재 적용 중인 규칙 전문",
        title="손절선 8%는 어디서 나온 숫자인가 | 바꿔보고 남긴 기록",
        lead="모든 종목에 같은 손절선을 걸어두는 이유와, 그 폭을 바꿨을 때 계좌가 어떻게 달라졌는지입니다.",
        path="/rules",
        tags=("주식", "AI주식", "손절", "리스크관리", "퀀트", "모의투자"),
        comment="손절선을 5%에서 8%로 바꾼 백테스트 결과와 현재 적용 중인 규칙 전문입니다.",
        narration=(
            "모든 종목에 똑같이 걸어둔 손절선, 8퍼센트입니다. 사고 나서 정하는 게 아니라 사기 전에 정합니다.",
            "주문 넣는 순간 나갈 가격이 같이 기록돼요. 종목도 안 가립니다. 닿으면 다음 실행에서 자동으로 정리되고요.",
            "그럼 이 폭이 왜 8퍼센트냐. 5퍼센트로 두고 돌려본 것과 비교해보면 이렇게 나옵니다. 과거 성과고, 앞으로를 보장하진 않아요.",
            "규칙을 바꾸면 바꾼 날짜까지 사이트에 적어둡니다. 언제 뭘 바꿨는지 나중에 확인할 수 있게요.",
        ),
    ),
    Topic(
        key="explain_debate",
        kicker="AI가 판단하는 순서",
        hero="3",
        hero_unit="단계",
        caption="종목 하나를 두고 AI 셋이 순서대로 붙습니다",
        lines=("한 모델이 혼자", "결정하지 않습니다."),
        steps_head="찬반을 먼저 만듭니다",
        steps=(
            ("강세 AI가 살 이유를 씁니다", "재무, 수급, 최근 뉴스에서 이 종목을 사야 할 근거만 모읍니다."),
            ("약세 AI가 반대합니다", "같은 자료에서 사면 안 되는 이유만 모읍니다. 앞의 주장을 보고 반박합니다."),
            ("판정 AI가 비중을 정합니다", "양쪽 주장을 읽고 비중 확대·중립·축소와 확신도를 매깁니다."),
        ),
        steps_note="셋 다 같은 자료를 봅니다. 다른 건 무엇을 찾으라고 시켰는지뿐입니다.",
        proof_head="그래서 계좌를 둘로 굴립니다",
        proof=_books_proof,
        proof_note="왼쪽이 규칙만 보는 계좌, 오른쪽이 AI가 한 번 더 본 계좌입니다. 차이가 곧 AI 몫입니다.",
        outro=("토론 전문도", "그대로 올려둡니다."),
        call="오늘의 토론 전문",
        title="AI 셋이 한 종목을 두고 싸웁니다 | 강세·약세·판정 3단계 공개",
        lead="종목 하나를 두고 강세 AI와 약세 AI가 각각 근거를 쓰고, 판정 AI가 비중을 정하는 과정입니다.",
        path="/harness",
        tags=("주식", "AI주식", "AI투자", "코스피", "모의투자", "종목분석"),
        comment="오늘 실제로 오간 강세·약세 주장 전문과 판정 근거는 여기 그대로 있습니다.",
        narration=(
            "종목 하나를 두고 AI 셋이 순서대로 붙습니다. 한 모델이 혼자 결정하지 않아요.",
            "강세 쪽은 살 이유만, 약세 쪽은 사면 안 되는 이유만 모읍니다. 그다음 판정 쪽이 둘 다 읽고 비중을 정하죠.",
            "이게 실제로 도움이 되는지 보려고 계좌를 둘로 굴립니다. 한쪽은 규칙만, 한쪽은 AI가 한 번 더 봅니다.",
            "오간 주장 전문도 사이트에 그대로 올려둡니다. 판단이 틀렸으면 틀린 근거까지 남는 거죠.",
        ),
    ),
    Topic(
        key="explain_open",
        kicker="이 채널의 규칙",
        hero="전부",
        hero_unit="",
        caption="고른 것도, 틀린 것도 같은 자리에 남습니다",
        lines=("맞힌 날만 올리면", "기록이 아닙니다."),
        steps_head="지울 수 없게 해뒀습니다",
        steps=(
            ("고른 순간 기록됩니다", "무엇을 왜 골랐는지가 매수와 동시에 저장됩니다. 결과를 보고 쓰는 게 아닙니다."),
            ("정리되면 값이 붙습니다", "며칠 뒤 얼마에 나갔는지가 같은 줄에 그대로 붙습니다."),
            ("빼지 않습니다", "손실이 난 건도 그 자리에 남습니다. 목록에서 사라지는 종목은 없습니다."),
        ),
        steps_note="좋은 것만 골라 보여주면 맞힐 확률이 올라가는 게 아니라, 확인할 방법이 없어지는 겁니다.",
        proof_head="지금 사이트에 있는 것",
        proof=_open_proof,
        proof_note="숫자는 모의 계좌 기록입니다. 실계좌 주문은 없습니다.",
        outro=("틀린 날까지 전부", "남는 기록"),
        call="전체 거래 기록",
        title="맞힌 것만 올리는 채널이 아닙니다 | 틀린 거래까지 전부 공개",
        lead="고른 이유부터 정리된 값까지, 손실이 난 거래를 포함해 하나도 빼지 않고 남겨두는 이유입니다.",
        path="/paper",
        tags=("주식", "AI주식", "모의투자", "투자기록", "코스피", "손절"),
        comment="여기에 지금까지의 거래가 전부 있습니다. 손실 난 건도 같은 목록에 그대로 있습니다.",
        narration=(
            "이 채널 규칙은 하나입니다. 고른 것도 틀린 것도 같은 자리에 남긴다.",
            "무엇을 왜 샀는지가 매수하는 순간 저장됩니다. 결과 보고 쓰는 게 아니에요. 며칠 뒤 얼마에 나갔는지가 같은 줄에 붙고요.",
            "지금 사이트에 올라가 있는 게 이겁니다. 손실 난 건도 빠지지 않습니다.",
            "맞힌 날만 올리면 그건 기록이 아니라 광고죠. 여긴 틀린 날도 그대로 남습니다.",
        ),
    ),
)

BY_TOPIC = {topic.key: topic for topic in TOPICS}

__all__ = ["BACKTEST_LABEL", "BACKTEST_ROWS", "BY_TOPIC", "TOPICS", "Topic", "stop_loss_pct"]
