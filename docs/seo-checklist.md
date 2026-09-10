# SEO · AEO · GEO · NEO 점검표 (2026-09-09)

참고: leopard627/fire-your-seo-agency(5개 레인), AgriciDaniel/claude-seo(기술·구조화 데이터·GEO).
목표는 "정확한 데이터의 1차 소스"가 되는 것입니다. 링크 구매·키워드 반복·숨김 텍스트는 하지 않습니다.

## 지금 적용된 것

| 레인 | 항목 | 상태 |
|---|---|---|
| SEO | 서버 렌더링 HTML(JS 없이 본문·메타·JSON-LD 전부 존재) | 적용 (FastAPI 서버 렌더) |
| SEO | `robots.txt` + `sitemap.xml` 참조, 회원·API·구독 경로 차단 | 적용 |
| SEO | 사이트맵에 `/`, `/harness`, `/harness/{id}`(최근 60건), `/outcomes`, `/analyses`, `/analyses/{id}`, `/features/*`, `/pricing`, 정책, 종목 페이지 | 적용 |
| SEO | 페이지별 고유 title/description, canonical, `noindex`(회원·구독·운영 페이지) | 적용 |
| SEO | og:title/description/url/type/site_name/locale, twitter:card | 셸에서 자동 |
| SEO | JSON-LD: 전역 `Organization`(#organization) + `WebSite`(SearchAction) 1회 선언, 페이지 노드 참조 | 적용 |
| SEO | 페이지 노드: 홈 `WebPage`(dateModified), 선별 기록 `Article`+`BreadcrumbList`, 요금제 `FAQPage`(가시 텍스트와 동일)+`Product/Offer`, 종목·리포트 페이지 기존 JSON-LD 유지 | 적용 |
| AEO | 첫 문단 직답: 홈 h1이 "N개 후보 중 M개 통과", 종목·리포트 페이지 첫 문장이 페이지 정의 | 적용 |
| AEO | 수치에 기준일·단위 병기("5거래일 수익률 +4.00% (2026-05-12 기준)") | 리포트·검증 페이지 적용 |
| GEO | `/llms.txt`(핵심 페이지, 데이터 출처·갱신 주기·자체 산출 지표·인용 표기) | 적용 |
| GEO | AI 크롤러 정책: GPTBot·OAI-SearchBot·ChatGPT-User·ClaudeBot·Claude-SearchBot·Claude-User·PerplexityBot·Perplexity-User·Google-Extended·CCBot 모두 Allow(공개 경로) | 적용 |
| NEO | Yeti(네이버) Allow, `naver-site-verification` 메타(`TRADINGAGENTS_NAVER_SITE_VERIFICATION`) | 코드 적용, 등록은 아래 |
| LLMO | 서비스명 표기 통일 "TradingAgents Korea", Organization `sameAs`(GitHub, 텔레그램 봇) | 적용 |

## 운영자가 직접 해야 하는 것 (계정 필요)

1. **Google Search Console** 등록 → 소유 확인 토큰을 Vercel 환경변수 `TRADINGAGENTS_GOOGLE_SITE_VERIFICATION`에 넣고 재배포. 사이트맵 `https://trading-agents-seven.vercel.app/sitemap.xml` 제출.
2. **Bing Webmaster Tools** 등록(GSC에서 가져오기 지원). Copilot·ChatGPT 검색이 Bing 색인을 씁니다.
3. **네이버 서치어드바이저** 등록 → 토큰을 `TRADINGAGENTS_NAVER_SITE_VERIFICATION`에 넣고 재배포, 사이트맵 제출, 주요 페이지 수집 요청.
4. 배포 후 Google Rich Results Test / schema.org validator로 `/`, `/pricing`, `/harness` JSON-LD 확인.
5. 2주 뒤 재측정: GSC·Bing·네이버 노출/클릭, Perplexity·ChatGPT 검색에 "코스피200 종목 선별 검증" 류 질문을 던져 출처 표시 여부 기록.

## 2026-09-09 추가 적용

| 항목 | 내용 |
|---|---|
| 브랜드 | `brand.py`: SVG 마크(청록 라운드 사각형 + 상승선), `/favicon.svg`, `/favicon.ico`(16·32·48), `/apple-touch-icon.png`, `/icon-{192,512}.png`, `/site.webmanifest`. 헤더 로고와 OG 이미지 푸터에 같은 마크 사용 |
| OG 이미지 | `og_image.py`: Pillow + Pretendard(`site/assets/fonts`)로 1200×630 PNG를 요청 시 생성·메모. `/og/default.png`, `/og/home.png`(오늘의 결론·선별 과정 수치), `/og/harness.png`, `/og/harness/{id}.png`, `/og/stocks/{code}.png`(판정 이력 요약), `/og/{pricing,outcomes,analyses,features}.png`. 셸이 기본 이미지를 자동 지정하고 페이지가 덮어씀. `twitter:card=summary_large_image` |
| IndexNow | `seo.submit_indexnow`: 키는 `TRADINGAGENTS_INDEXNOW_KEY`(8~128자 영숫자), 키 파일 `/indexnow/{key}.txt`. 선별 실행이 저장되면 파이프라인이 `/`, `/harness`, `/harness/{id}`, 관련 `/stocks/{code}/history`를 자동 핑(실패해도 매매에 영향 없음). 수동 핑: `POST /api/admin/seo/indexnow {"paths":[...]}`(운영 토큰 또는 관리자 세션) |
| 질문 = 페이지 | `/stocks/{code}/history` "○○ AI 판정 이력": 첫 문장이 직답("최근 N회 선별에서 M회 통과, 마지막 판정 …"), 판정 이력 표(날짜→선별 기록 링크, 결과, 규칙 점수, 20일 예상, AI 판정, 검증 결과), FAQ 3문답 + FAQPage/Article/Breadcrumb JSON-LD, 전용 OG 이미지. 종목 페이지·선별 기록 표에서 링크, 사이트맵 자동 포함 |

운영자 할 일 추가: IndexNow 키를 하나 정해(예: 32자 영숫자) Vercel 환경변수 `TRADINGAGENTS_INDEXNOW_KEY`에 넣고 재배포하면 핑이 켜집니다.

## 다음 단계 (코드)

- `lastmod` 정확성: 사이트맵의 lastmod를 생성일이 아니라 각 실행·리포트의 갱신 시각으로.
- About 페이지(운영 주체·연락처)와 `Organization.contactPoint`.
- "코스피200 오늘 선정 종목" 같은 날짜별 질문 페이지(`/harness/{date}` 별칭).

## 도메인 연결 (2026-09-10 시작)

- 선택: `agenttrust.kr` (www 포함). Vercel 프로젝트 `trading-agents`에 두 도메인을 붙였습니다.
- DNS(ITEasy 웹DNS): `@ A 76.76.21.21`, `www CNAME cname.vercel-dns.com`. 네임서버는 ksdom.kr 유지.
- 전파 뒤 순서: Vercel env `TRADINGAGENTS_SITE_BASE_URL=https://agenttrust.kr`, `TRADINGAGENTS_CANONICAL_HOST=agenttrust.kr`(vercel.app·www → 301, `/api/*`·`/health`·`/indexnow/*`는 제외) → 재배포 → Supabase Auth Site URL·Redirect URLs에 `https://agenttrust.kr/**` 추가 → 텔레그램 웹훅 재등록(`/api/admin/notifications/telegram/setup`) → 포트원 리다이렉트 확인 → IndexNow 키 등록 → 서치 콘솔 3종 등록.

### 2026-09-10 도메인 전환 완료 상태

- `https://agenttrust.kr` 운영 중(www·vercel.app → 301). 인증서 발급 완료, 텔레그램 웹훅 새 주소로 재등록.
- Vercel env: `TRADINGAGENTS_SITE_BASE_URL`, `TRADINGAGENTS_CANONICAL_HOST`, `TRADINGAGENTS_INDEXNOW_KEY`(32자 hex, 키 파일은 **사이트 루트** `/{key}.txt` — IndexNow는 키 파일 디렉터리 아래 URL만 인정), `TRADINGAGENTS_VERIFICATION_FILES`(구글 HTML·네이버 HTML·BingSiteAuth.xml), `TRADINGAGENTS_NAVER_SITE_VERIFICATION`, `TRADINGAGENTS_BING_SITE_VERIFICATION`.
- IndexNow 수동 핑 202 확인. 남은 것: 각 콘솔에서 "확인/소유확인" 클릭, 사이트맵 제출, Supabase Redirect URLs에 `https://agenttrust.kr/**` 추가.
- 운영 점검: `POST /api/admin/seo/selfcheck {"paths":[...]}`(운영 토큰)로 배포 안에서 canonical 호스트의 공개 URL을 직접 받아 상태·타입·크기·응답 시간·앞부분을 확인할 수 있습니다(사내망에서 새 도메인이 막힐 때 사용). 2026-09-10 확인: sitemap 200(8초, 콜드 스타트), robots·llms·구글/네이버/Bing 확인 파일·IndexNow 키 파일 모두 200.
- 네이버 확인 파일 내용은 `naver-site-verification: <파일명>` 한 줄이어야 합니다(토큰만 넣으면 "파일을 찾을 수 없음").
