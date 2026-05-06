# alba-scraper

일일/단기 알바를 매일 KST 19시에 스크래핑하고 Gmail로 발송한다.

기본값은 양천구 인근 (양천/강서/영등포/구로) 4개 자치구이며, 다른 지역으로 바꾸려면 `scrape.py`의 `ALBAMON_AREAS` 매핑만 교체하면 된다.

## 동작

- 알바몬 + 잡코리아 두 사이트에서 4개 자치구 검색 결과 수집
- "일일/하루/당일/단기/원데이" 등 키워드 매칭 후 신규만 알림
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

### Gmail 앱 비밀번호 발급

1. 2단계 인증 활성화: https://myaccount.google.com/security
2. 앱 비밀번호 생성: https://myaccount.google.com/apppasswords
3. 앱 이름 입력 → 만들기 → 16자 비밀번호 복사
4. 위 `GMAIL_APP_PASSWORD` 시크릿에 붙여넣기 (공백 제거)

## 수동 실행

GitHub Actions → "알바 스크래핑" → Run workflow.
"신규 없어도 메일 강제 발송"을 체크하면 빈 결과여도 알림 발송.

## 로컬 실행

```bash
pip install -r requirements.txt
GMAIL_USER=xxx@gmail.com GMAIL_APP_PASSWORD=xxxx GMAIL_TO=xxx@gmail.com FORCE_EMAIL=1 python scrape.py
```
