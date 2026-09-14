# 매일 쇼츠 발행 자동화

렌더는 **이 PC 에서만** 됩니다. 프레임은 로컬 GPU 로 헤드리스 크롬이 그리고, 목소리는 로컬
VoxCPM 이 냅니다. 그래서 어느 구성을 쓰든 이 PC 는 켜져 있어야 합니다.

n8n 이 어디 있느냐에 따라 둘 중 하나를 고르면 됩니다.

## A. n8n 이 웹에 있을 때 — `daily-short-hosted.json` (권장)

이 PC 가 만들어서 n8n 으로 **밀어 넣습니다.** 외부에서 이 PC 로 들어올 일이 없어
포트포워딩도 터널도 필요 없습니다. n8n 은 업로드와 알림만 맡습니다.

```
이 PC (작업 스케줄러 08:40)
  → 스토리 선택 → 렌더 → mp4 를 n8n 웹훅으로 POST
       → n8n: 유튜브 업로드 → 텔레그램 알림 → videoId 회신
  → 이 PC: 발행 기록에 videoId 기록
```

**설치**

1. n8n 에서 `daily-short-hosted.json` 을 Import 합니다.
2. **영상 수신** 노드에 Header Auth 자격증명을 만듭니다. 이름 `X-Shorts-Token`,
   값은 임의의 긴 문자열.
3. **유튜브 업로드** 에 YouTube OAuth2, **텔레그램** 두 노드에 자격증명과 `chatId` 를 넣습니다.
4. 워크플로를 저장하고 **Active** 로 켠 뒤, 웹훅 Production URL 을 복사합니다.
5. `automation\daily-short.cmd` 를 열어 `TRADINGAGENTS_SHORTS_WEBHOOK` 에 그 URL,
   `TRADINGAGENTS_SHORTS_WEBHOOK_TOKEN` 에 2 번의 값을 넣습니다.
6. 작업 스케줄러에 등록합니다.

```
schtasks /create /tn "AgentTrust Daily Short" /tr "D:\Codex\TradingAgents\automation\daily-short.cmd" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:40 /rl highest /f
```

## B. n8n 이 이 PC 에 있을 때 — `daily-short-local.json`

n8n 이 `Execute Command` 로 이 저장소의 CLI 를 직접 부릅니다. 배선은 더 단순하지만
n8n 을 하나 더 운영해야 하고, 유튜브 OAuth 리디렉션 주소를 `localhost` 로 등록해야 합니다.
이미 웹 n8n 이 있다면 A 를 쓰는 편이 낫습니다.

## 채워야 하는 것

| 항목 | 어디에 |
|---|---|
| YouTube OAuth2 | n8n · 유튜브 업로드 노드 |
| Telegram 자격증명과 `chatId` | n8n · 텔레그램 노드 (성공 알림, 실패 알림) |
| Header Auth 토큰 | n8n · 영상 수신 노드 ↔ `daily-short.cmd` 의 같은 값 |
| OpenAI (선택) | 로컬 워크플로의 제목 다듬기 노드 · 기본은 꺼져 있음 |

대본과 화면의 숫자는 전부 계좌 데이터에서 나오므로 **LLM 은 필요 없습니다.** 제목만
다듬고 싶을 때 켜세요.

## 처음 돌릴 때

- `--privacy private` 으로 며칠 돌려 결과를 확인한 뒤 `public` 으로 올리세요.
- 유튜브 API 심사를 통과하기 전에는 API 로 올린 영상이 **비공개로 잠깁니다.**
  심사 신청은 지금 해두는 게 좋습니다.
- **유튜브 업로드** 노드에서 바이너리 필드 이름이 `video` 인지 확인하세요.
  n8n 버전에 따라 항목 위치가 다를 수 있습니다.

## 직접 확인해보기

```
tradingagents shorts-plan --table          오늘 무엇이 발동했는지, 점수와 함께
tradingagents shorts-daily --dry-run       고르고 만들되 전송은 하지 않음
tradingagents shorts --story record        그 영상만 따로 만들기
```

## 발행 기록

`shorts-out/published.json` 에 무엇을 언제 올렸는지 쌓입니다. 내일의 선택기가 이 파일을 보고
최근에 쓴 이야기를 피합니다. 경로는 `TRADINGAGENTS_SHORTS_LEDGER` 로 바꿀 수 있습니다.
