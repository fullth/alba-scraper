# yangcheon-alba-scraper

양천구 인근 (양천/강서/영등포/구로) 일일/단기 알바를 매일 KST 19시에 스크래핑하고 Gmail로 발송한다.

## 동작

- 알바몬 + 잡코리아 두 사이트에서 4개 자치구 검색 결과 수집
- "일일/하루/당일/단기/원데이" 등 키워드 매칭 후 신규만 알림
- `data/seen.json`으로 중복 알림 방지
- `data/history.json`에 최근 60회 기록 누적

## GitHub Secrets 필요값

| 이름 | 설명 |
|------|------|
| `GMAIL_USER` | 발신자 Gmail 주소 (앱 비밀번호 발급한 계정) |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (16자) |
| `GMAIL_TO` | 수신자 (생략 시 GMAIL_USER로 자기 자신에게 발송) |

## 수동 실행

GitHub Actions → "양천구 알바 스크래핑" → Run workflow.
"신규 없어도 메일 강제 발송"을 체크하면 빈 결과여도 알림 발송.

## 로컬 실행

```bash
pip install -r requirements.txt
GMAIL_USER=xxx@gmail.com GMAIL_APP_PASSWORD=xxxx GMAIL_TO=xxx@gmail.com FORCE_EMAIL=1 python scrape.py
```
