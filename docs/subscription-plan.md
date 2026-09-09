# 구독 상품 기획 (리서치 도구 포지셔닝)

승인일: 2026-09-09. 결정: `docs/product-monetization-proposal.md`의 B안(리서치 도구)으로
시작한다. 실계좌 자동매매·투자일임은 상품에 포함하지 않는다.

## 1. 포지셔닝과 카피 규칙

- 서비스는 "AI 리서치 도구"다. 사용자가 스스로 판단하기 위한 분석 자료를 제공하며 특정
  종목의 매매를 권유하지 않는다. 유료 플랜은 도구의 **이용 범위**(열람 시점, 토론 전문,
  요청 횟수)를 넓힌다.
- 금지 어휘(공개 페이지·알림·광고): "추천 종목", "매수 추천", "적중률", "수익 보장",
  "따라 사면". 허용 어휘: "하네스 결과", "AI 토론", "분석 자료", "가상 매수(모의투자)",
  "성적표(지수 대비)".
- 성적표는 나쁜 결과를 포함해 그대로 공개한다. 분모를 항상 함께 쓴다.
- 이 문서는 법률 자문이 아니다. 유료 출시 전 유사투자자문업 신고 필요 여부를 전문가와
  확인한다. 신고를 택하면 표시의무(신고번호·"투자판단 책임"), 환불 규정, 광고 심의를 반영한다.

## 2. 플랜

| 플랜 | 가격 | 하네스 열람 | 토론 전문 | 분석 요청 | 기타 |
|---|---|---|---|---|---|
| 무료 | 0 | 전일 실행까지 | 없음 | 하루 3회, 동시 2건 | 공개 성적표, 종목 페이지 |
| 데일리 패스 | 10,000원/월 | 당일 실행 즉시 | 있음 | 하루 20회, 동시 5건 | 알림(2단계), 가상계좌 추적, 테마, 광고 없음 |
| 프로 | 30,000원/월 | 당일 실행 즉시 | 있음 | 하루 60회, 동시 10건 | 사용자 지정 하네스, 본인 KIS 모의투자 키, 주간 PDF, JSON API |

14일 무료 체험은 데일리 패스 기준이며 회원당 1회. 체험 종료 후 자동으로 무료 플랜으로
내려가고 결제는 발생하지 않는다.

## 3. 게이트 규칙 (구현: `tradingagents/site/billing.py`)

- `/api/harness/runs/latest`: 무료·비로그인은 KST 기준 **오늘 이전** 날짜의 최신 실행,
  유료는 최신 실행.
- `/api/harness/runs/{id}`: 무료 사용자가 당일 실행을 열면 `plan_gate.locked=true`와
  함께 종목코드·이름·수량·가격·근거를 비운 채 단계와 요인 점수만 준다.
- 모든 무료 응답에서 `detail.confirmation.raw`(토론 전문)를 제거한다.
- 회원 자격 헤더나 Authorization이 붙은 응답과 `/api/billing/*`는 `private, no-store`.
- 유료 판정: `status=active`는 기간 종료 후 2일 유예, `trialing`은 `trial_ends_at`까지.

## 4. 결제 흐름 (포트원 V2)

1. 마이페이지에서 플랜 선택 → `POST /api/billing/checkout` → 브라우저가 포트원 SDK
   `requestIssueBillingKey`로 카드/카카오페이/네이버페이 빌링키 발급.
2. 포트원 웹훅 `BillingKey.Issued` → 서버가 빌링키 저장 후 첫 달 결제 요청.
3. 웹훅 `Transaction.Paid` → 서버가 포트원 API로 결제를 다시 조회해 금액·상태를 확인한
   뒤 30일 활성화. 같은 결제 ID는 한 번만 처리한다.
4. 매일 09:10 KST 크론 `/api/cron/process-subscription-renewals`가 만료 예정 구독을 재결제.
   실패 3회면 `past_due`로 내려가고 무료 플랜이 적용된다.
5. 해지: `POST /api/billing/cancel` → 기간 종료 시 해지. 환불은 운영자가 포트원 콘솔에서
   처리하고 `billing_events`에 기록한다(자동 환불 API는 2단계).

필요한 환경변수: `PORTONE_API_SECRET`, `PORTONE_STORE_ID`, `PORTONE_CHANNEL_KEY`,
`PORTONE_WEBHOOK_SECRET`. 웹훅 URL: `https://<도메인>/api/billing/portone/webhook`.

텔레그램: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`를
Vercel에 넣은 뒤 운영자 토큰으로 `POST /api/admin/notifications/telegram/setup`을 한 번
호출하면 웹훅(`/api/notifications/telegram/webhook`)이 등록된다. 로컬 망은 텔레그램이
차단되어 있으므로 검증은 배포 후 `/billing`에서 연결 코드를 받아 봇에 `/start`로 진행한다.

## 5. 데이터

`subscriptions`(회원당 1행: 플랜, 상태, 빌링키 참조, 기간, 실패 횟수)와
`billing_events`(결제·체험·해지 이력). 마이그레이션 `202609090001_subscriptions.sql`,
RLS는 본인 행 읽기만 허용, 쓰기는 서버(DATABASE_URL)만.

## 6. 구현 현황

완료(2026-09-09):
- `/billing` 구독 관리 페이지: 플랜 상태, 체험 시작, 데일리/프로 결제(포트원 SDK
  `requestIssueBillingKey`), 기간 종료 해지, 텔레그램 연결 코드, 결제 이력.
- 분석 요청 쿼터를 플랜별로 적용(운영자 env 상한과 비교해 작은 값).
- 홈·`/harness` HTML은 항상 무료 뷰(전일 실행, 토론 발췌 1줄씩)를 렌더링하고, 당일
  실행은 "후보 N개 중 M개 통과" 티저로만 노출. 유료 회원은 API로 당일 전문을 받음.
- 텔레그램: 봇 웹훅(`/start 코드` 연결, `/stop` 해제), 발행 푸시
  (`/api/cron/notify-harness-issue` 07:56·10:25 KST, 유료는 종목·등급, 무료는 발행 안내).

남은 것:
- 환불 자동화(포트원 취소 API)와 영수증 메일.
- 손절·익절 발동, 5D/20D 확정 알림(현재는 발행 알림만).
- 마이페이지(`/mypage`) 안에 `/billing` 진입 링크와 플랜 배지.

## 7. 출시 체크리스트

- [ ] 유사투자자문업 신고 여부 결정(전문가 확인)
- [ ] 약관·환불 규정 게시(이용약관 "유료 플랜과 환불" 절 반영됨)
- [ ] 포트원 가맹 심사, 웹훅 시크릿 등록, Vercel 환경변수 4개
- [ ] Supabase 마이그레이션 적용
- [ ] 마이페이지 결제 UI, 잠금 UI
- [ ] 베타 100명 체험 초대 → 전환율·재방문·알림 클릭률 측정
