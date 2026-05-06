# alba-scraper

일일/단기 알바를 매일 KST 19시에 스크래핑하고 Gmail + Telegram으로 발송한다.

기본값은 양천구 인근 (양천/강서/영등포/구로) 4개 자치구이며, 다른 지역으로 바꾸려면 `scrape.py`의 `ALBAMON_AREAS` 매핑만 교체하면 된다.

## 동작

- 알바몬 + 잡코리아 두 사이트에서 4개 자치구 검색 결과 수집
- "일일/하루/당일/단기/원데이" 등 키워드 매칭 후 신규만 알림
- 알림 채널: Gmail (1명) + Telegram (다중 사용자, `subscribers.json`)
- `data/seen.json`으로 중복 알림 방지
- `data/history.json`에 최근 60회 기록 누적

## 지역 변경 방법

`scrape.py` 상단의 `ALBAMON_AREAS` 딕셔너리 **한 곳만** 바꾸면 알바몬/잡코리아/메일 제목/후처리 필터에 모두 반영된다.

- 키 = 알바몬 sigu 코드 (알바몬 검색 URL에 사용)
- 값 = 한글 지역명 (잡코리아 키워드 검색 + 메일 제목 + 결과 후처리 필터에 사용)

```python
ALBAMON_AREAS = {
    "I190": "양천구",
    "I140": "강서구",
    "I150": "영등포구",
    "I130": "구로구",
}
```

알바몬 sigu 코드는 다음 API에서 모두 조회 가능하다.

```
https://api-code.albamon.com/codes/areas/korean/sigu/codes
```

키워드를 바꾸고 싶으면 같은 파일 위쪽의 `SHORT_TERM_KEYWORDS` (단기 매칭 후처리) 또는 `JOBKOREA_KEYWORDS` (잡코리아에 보내는 검색어)를 수정한다.

## GitHub Secrets 필요값

| 이름 | 설명 |
|------|------|
| `GMAIL_USER` | 발신자 Gmail 주소 (앱 비밀번호 발급한 계정) |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (16자) |
| `GMAIL_TO` | 수신자 (생략 시 GMAIL_USER로 자기 자신에게 발송) |
| `TELEGRAM_BOT_TOKEN` | BotFather에서 발급한 봇 HTTP API 토큰 |
| `TELEGRAM_CHAT_ID` | (선택) `subscribers.json`과 별도로 항상 받을 단일 chat_id |

### Gmail 앱 비밀번호 발급

1. 2단계 인증 활성화: https://myaccount.google.com/security
2. 앱 비밀번호 생성: https://myaccount.google.com/apppasswords
3. 앱 이름 입력 → 만들기 → 16자 비밀번호 복사
4. 위 `GMAIL_APP_PASSWORD` 시크릿에 붙여넣기 (공백 제거)

### Telegram 봇 만들기

1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 대화 열기
2. `/newbot` 입력 → 이름 / 유저네임 (영문, 끝에 `bot` 필수) 입력
3. HTTP API 토큰을 `TELEGRAM_BOT_TOKEN` 시크릿에 등록

## Telegram 알림 받기 (개인 등록 방법)

본인 chat_id를 알아내서 `subscribers.json`에 추가하면 매일 같은 알림을 받을 수 있다.

1. 위에서 만든 봇 검색해 채팅방 들어가 `/start` 한 번 누르기
2. chat_id 확인 두 가지 방법 중 하나
   - 텔레그램에서 [@userinfobot](https://t.me/userinfobot) 검색해 대화 → 본인 정보에 표시되는 `Id` 숫자
   - 또는 브라우저로 `https://api.telegram.org/bot<TOKEN>/getUpdates` 열기 → 응답 JSON의 `chat.id` 숫자
3. `subscribers.json` 파일에 본인 정보 추가 후 PR 또는 직접 push

```json
{
  "subscribers": [
    { "name": "Levi", "chat_id": 123456789 },
    { "name": "친구1", "chat_id": 987654321 }
  ]
}
```

`name`은 식별용, `chat_id`만 발송에 사용한다. 봇이 푸시 보낼 수 있으려면 사용자가 봇과 한 번이라도 대화 시작해야 한다 (`/start`).

## 수동 실행

GitHub Actions → "알바 스크래핑" → Run workflow.
"신규 없어도 메일 강제 발송"을 체크하면 빈 결과여도 알림 발송.

## 로컬 실행

```bash
pip install -r requirements.txt
GMAIL_USER=xxx@gmail.com GMAIL_APP_PASSWORD=xxxx GMAIL_TO=xxx@gmail.com \
  TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=123456789 \
  FORCE_EMAIL=1 python scrape.py
```
