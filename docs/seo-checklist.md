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

## 다음 단계 (코드)

- OG 이미지: 페이지 유형별 1200×630 이미지 생성 라우트(`/og/{page}.png`). 지금은 이미지 없이 `summary` 카드.
- IndexNow: 선별 실행 완료 시 새 `/harness/{id}` URL을 Bing·네이버에 핑(발행 파이프라인에 내장).
- 질문 = 페이지: "○○ 종목 AI 판정", "코스피200 오늘 선정 종목" 같은 검색 질문별 안정 URL(종목 페이지에 선별 이력 섹션 추가).
- `lastmod` 정확성: 사이트맵의 lastmod를 생성일이 아니라 각 실행·리포트의 갱신 시각으로.
- About 페이지(운영 주체·연락처)와 `Organization.contactPoint`.
