# 사이트 디자인 시스템 (v3 · 슬레이트)

2026-09-09 적용. 홈 → 로그인/내 공간 → 하네스 → 요금제 → 구독 관리 → 회원 관리가
한 시스템(`tradingagents/site/design_system.py`) 위에서 렌더링됩니다. 시안은
Claude Design 캔버스 "TradingAgents Korea 통일 시안 v2"의 v3 페이지입니다.

## 토큰과 테마

- 글꼴: Pretendard 한 가지(cdnjs 동적 서브셋). 제목 700, 본문 400, 숫자는 `.num`
  (`font-variant-numeric: tabular-nums`). CSP `style-src`/`font-src`에 cdnjs 허용.
- 색: 밝은 슬레이트 바탕(#f3f5f9), 흰 카드, 강조색 청록(#0f766e) 하나. 역할별 보조색은
  예측 파랑, AI 토론 보라, 데일리 패스 호박, 코스피 남색, 코스닥 주황, 상승 빨강·하락 파랑.
- 테마: `light`(기본), `dark`, `paper`, `nord`, `solar`. 헤더의 팔레트 버튼으로 고르며
  `localStorage['ta-theme']`에 저장. 저장값이 없으면 OS `prefers-color-scheme`를 따릅니다.
  토큰은 `:root`(light), `@media dark` + `:root:not([data-theme])`, `:root[data-theme=…]`
  순으로 선언되어 어느 상태에서도 색이 비어 있지 않습니다.

## 셸과 컴포넌트

- `render_shell(title, body, active, canonical_path, …)`: 헤더(브랜드, 5개 메뉴, 종목 검색,
  테마 메뉴, 로그인/무료로 시작 또는 플랜 배지+아바타), 푸터(신뢰 문구 3개, 링크).
  헤더는 `/api/billing/me`로 플랜과 관리자 여부를 읽어 `[data-admin-only]`를 켭니다.
- 클래스: `.card` `.card-h` `.card-b` `.card-f`, `.tile`, `.badge .b-teal|b-blue|b-violet|
  b-amber|b-orange|b-navy|b-grey|b-gain|b-loss`, `.btn .primary|.ghost|.sm`, `.tabs`, `.bar`,
  `.switch`, `.kv`, `.grid-2/3/4`, `.grid-main`, `.hero`, `.grad`, `.soft`, `.ico`.
- 차트: `sparkline_svg(values)`(서버) 또는 홈 JS의 `spark()`(클라이언트). 60일 종가는
  `GET /api/prices/sparkline?tickers=…&days=60`(프로세스 내 10분 캐시, 병렬 조회, 종목별 오류 분리).

## 페이지별 위치

| 경로 | 모듈 |
|---|---|
| `/` | `home_page.py` (`build_home_view_model` 그대로, `_render`만 교체) |
| `/member`, `/mypage` | `member_page.py` (마크업·CSS) + `web_pages.MEMBER_PAGE_JS` (동작은 그대로) |
| `/harness`, `/harness/{id}` | `harness_pages.py` |
| `/pricing` | `pricing_page.py` |
| `/billing` | `billing_page.py` |
| `/admin/members` | `admin_members_page.py` |
| `/analyses`, `/analyses/{id}`, `/outcomes` | `analysis_pages.py` (데이터 헬퍼는 `web_pages`에서 재사용) |
| `/stocks/{code}` | `stock_page.py` (차트 엔진 `PAGE_JS`는 그대로, CSS만 토큰으로 이식) |
| `/features`, `/features/{slug}`, `/privacy`, `/terms`, `/disclaimer` | `info_pages.py` |
| `/admin` | `admin_console_page.py` (`ADMIN_PAGE_JS` 그대로) |
| `/stocks/{code}/history` | `ticker_history_page.py` (종목별 AI 판정 이력, 질문 하나 = 페이지 하나) |
| 아이콘·OG | `brand.py`(로고·파비콘·매니페스트), `og_image.py`(1200×630 PNG, Pretendard OTF) |

`web_pages.py`의 같은 이름 함수는 위 모듈로 위임만 합니다. 옛 시스템(`PAGE_CSS`)은 `/?legacy=1`과
`PAGE_JS`(종목 차트·검색 자동완성)에만 남아 있습니다.

## 한글 표기 규칙 (2026-09-09, epoko77-ai/im-not-ai 규칙 참고)

화면 용어는 아래로 통일합니다. URL·API 필드명(`/harness`, `harness_runs`)은 그대로입니다.

| 쓰지 않는 말 | 쓰는 말 |
|---|---|
| 하네스, 일일 하네스 | 종목 선별, 선별 기록 |
| 유니버스 | 대상 종목 |
| 깔때기 | 선별 과정 |
| 요인 점수 / 요인 상위 | 규칙 점수 / 후보 |
| 예측·토론 통과 | AI 토론 통과 |
| 가상 주문·가상 매수·가상계좌 | 모의 주문·모의 매수·모의투자 계좌 (회원 기능명 "AI 가상매매"는 유지) |
| 채점 | 성과 검증 (검증 대기·검증 완료) |
| 감사 원장, 실행 상세 | 실행 기록 |
| 강세/약세 연구원, 판정관, 리스크 패널 | 강세 의견/약세 의견, 판정, 리스크 점검 |
| 내 공간 | 마이페이지 |
| 검증 성과, 사후 결과 | 성과 검증, 검증 결과 |
| 알파 | 초과수익 |
| 원문 데이터, 종목 분석실 | JSON 데이터, 종목 분석 |
| 60일 흐름, 20일 예측 / 확률 | 60일 주가, 20일 예상 / 상승 확률 |

문장 규칙: 합니다체, 한 문장 20자 안팎, "~를 통해/~에 대해/~에 있어서" 금지, 영어 buzzword·이모지 금지,
수치에는 단위와 기준일을 붙입니다("+3.2% (2026-09-08 기준)").
