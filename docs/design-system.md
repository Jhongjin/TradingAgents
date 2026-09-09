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

아직 옛 시스템(`web_pages.PAGE_CSS`)에 남은 페이지: `/analyses`, `/outcomes`, `/stocks/{code}`,
`/features`, 정책 페이지, `/admin` 운영 콘솔, `/?legacy=1`. 2단계에서 같은 셸로 옮깁니다.
