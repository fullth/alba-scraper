"""양천구 인근 일일/단기 알바 스크래퍼 (알바몬 + 잡코리아).

GitHub Actions cron으로 매일 19시 (KST) 실행.
신규 공고를 data/seen.json과 diff하여 신규만 Gmail로 발송.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup


# 양천구(I190) + 강서구(I140) + 영등포구(I150) + 구로구(I130) 인근 4개 자치구
# albamon area code (sigu)
ALBAMON_AREAS = {
    "I190": "양천구",
    "I140": "강서구",
    "I150": "영등포구",
    "I130": "구로구",
}

# 일일/하루/단기 키워드 (사이트 자체 분류 약하므로 후처리 필터에 사용)
SHORT_TERM_KEYWORDS = [
    "일일", "하루", "당일", "단기", "1일", "1day", "원데이",
]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SEEN_FILE = DATA_DIR / "seen.json"
HISTORY_FILE = DATA_DIR / "history.json"

DATA_DIR.mkdir(exist_ok=True)


@dataclass
class Job:
    source: str
    job_id: str
    title: str
    company: str
    area: str
    wage: str
    work_time: str
    posted: str
    url: str
    raw_text: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.job_id}"

    def is_short_term(self) -> bool:
        haystack = f"{self.title} {self.company} {self.raw_text}".lower()
        return any(kw.lower() in haystack for kw in SHORT_TERM_KEYWORDS)


def fetch(url: str, *, retries: int = 3, sleep: float = 1.5) -> str | None:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200 and resp.text:
                return resp.text
            print(f"  status={resp.status_code} (try {attempt+1})", file=sys.stderr)
        except requests.RequestException as exc:
            print(f"  request err: {exc} (try {attempt+1})", file=sys.stderr)
        time.sleep(sleep * (attempt + 1))
    return None


def scrape_albamon(area_code: str, area_name: str) -> list[Job]:
    jobs: list[Job] = []
    for page in range(1, 4):  # 1~3 페이지 (60~150건)
        url = (
            "https://www.albamon.com/jobs/total?"
            + urlencode(
                {
                    "areas": area_code,
                    "pageNo": page,
                    "size": 50,
                    "sortType": "POSTED_DATE",
                }
            )
        )
        html = fetch(url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("li.list-item-recruit, li[class*='list-item-recruit']")
        if not items:
            break
        for li in items:
            link = li.select_one("a[href*='/jobs/detail/']")
            if not link:
                continue
            href = link.get("href", "")
            m = re.search(r"/jobs/detail/(\d+)", href)
            if not m:
                continue
            job_id = m.group(1)
            title_el = li.select_one(".list-item-recruit__recruit-title, [class*='recruit-title']")
            title = title_el.get_text(strip=True) if title_el else ""
            company_el = li.select_one("[class*='company-name']")
            company = company_el.get_text(strip=True) if company_el else ""
            area_el = li.select_one(".list-item-recruit__contents--keyword-area")
            area = area_el.get_text(" ", strip=True) if area_el else area_name
            salary_el = li.select_one(".list-item-recruit__salary, [class*='salary']")
            wage = salary_el.get_text(" ", strip=True) if salary_el else ""
            time_el = li.select_one("[class*='work-time'], [class*='workTime']")
            work_time = time_el.get_text(" ", strip=True) if time_el else ""
            posted_el = li.select_one("[class*='register-date'], [class*='registerDate'], [class*='posted']")
            posted = posted_el.get_text(" ", strip=True) if posted_el else ""
            jobs.append(
                Job(
                    source="albamon",
                    job_id=job_id,
                    title=title,
                    company=company,
                    area=area,
                    wage=wage,
                    work_time=work_time,
                    posted=posted,
                    url=f"https://www.albamon.com/jobs/detail/{job_id}",
                    raw_text=li.get_text(" ", strip=True),
                )
            )
        time.sleep(1.0)
    return jobs


def scrape_jobkorea(area_code: str, area_name: str) -> list[Job]:
    """잡코리아 검색 (지역코드 + 키워드 일일알바)."""
    jobs: list[Job] = []
    for page in range(1, 4):
        url = (
            "https://www.jobkorea.co.kr/Search/?"
            + urlencode(
                {
                    "stext": "일일알바",
                    "local": f"I000,{area_code}",
                    "Page_No": page,
                    "tabType": "recruit",
                }
            )
        )
        html = fetch(url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("article.list-item, article[class*='Flex_gap']")
        if not items:
            items = soup.select("article")
        for li in items:
            link = li.select_one("a[href*='Recruit/GI_Read'], a[href*='/recruit/']")
            href = ""
            job_id = ""
            if link:
                href = link.get("href", "")
                m = re.search(r"GI_Read/(\d+)|/recruit/(\d+)", href)
                if m:
                    job_id = m.group(1) or m.group(2)
            if not job_id:
                continue
            title_el = li.select_one("[class*='title']") or link
            title = title_el.get_text(strip=True) if title_el else ""
            company_el = li.select_one("[class*='corp'], [class*='company']")
            company = company_el.get_text(strip=True) if company_el else ""
            text = li.get_text(" ", strip=True)
            jobs.append(
                Job(
                    source="jobkorea",
                    job_id=job_id,
                    title=title[:200],
                    company=company[:100],
                    area=area_name,
                    wage="",
                    work_time="",
                    posted="",
                    url=(
                        href
                        if href.startswith("http")
                        else f"https://www.jobkorea.co.kr{href}"
                    ),
                    raw_text=text,
                )
            )
        time.sleep(1.0)
    return jobs


def load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))


def save_seen(keys: Iterable[str]) -> None:
    SEEN_FILE.write_text(
        json.dumps(sorted(set(keys)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_history(new_jobs: list[Job]) -> None:
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            history = []
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    history.append(
        {
            "scraped_at": today,
            "new_count": len(new_jobs),
            "jobs": [asdict(j) for j in new_jobs],
        }
    )
    history = history[-60:]  # 최근 60회만 유지
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def render_email_html(new_jobs: list[Job], total_seen: int) -> str:
    if not new_jobs:
        return (
            "<p>오늘 새로 등록된 양천구 인근 일일/단기 알바가 없습니다.</p>"
            f"<p>전체 누적 추적: {total_seen}건</p>"
        )
    by_source: dict[str, list[Job]] = {}
    for job in new_jobs:
        by_source.setdefault(job.source, []).append(job)
    parts = [
        "<h2 style='margin:0 0 12px'>양천구 인근 신규 일일/단기 알바</h2>",
        f"<p>발견 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')} (KST)<br>",
        f"신규 {len(new_jobs)}건 / 누적 추적 {total_seen}건</p>",
    ]
    for src, jobs in by_source.items():
        parts.append(f"<h3>{src} — {len(jobs)}건</h3>")
        parts.append("<ul style='padding-left:18px'>")
        for j in jobs:
            parts.append(
                "<li style='margin-bottom:10px'>"
                f"<a href='{j.url}' style='font-weight:600;color:#1a73e8;text-decoration:none'>{j.title or '(제목 없음)'}</a><br>"
                f"<span style='color:#555'>{j.company}</span> · "
                f"<span>{j.area}</span> · "
                f"<span style='color:#d73a49'>{j.wage}</span> · "
                f"<span>{j.work_time}</span> · "
                f"<span style='color:#888'>{j.posted}</span>"
                "</li>"
            )
        parts.append("</ul>")
    return "\n".join(parts)


def send_gmail(subject: str, html_body: str) -> None:
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    to_addr = os.environ.get("GMAIL_TO") or user
    if not user or not password:
        print("GMAIL_USER / GMAIL_APP_PASSWORD 누락 - 메일 발송 건너뜀", file=sys.stderr)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [to_addr], msg.as_string())
    print(f"메일 발송 완료 -> {to_addr}")


def main() -> int:
    print("=== 양천구 인근 알바 스크래퍼 시작 ===")
    all_jobs: list[Job] = []
    for code, name in ALBAMON_AREAS.items():
        print(f"[albamon] {name}({code}) 스크래핑...")
        jobs = scrape_albamon(code, name)
        print(f"  -> {len(jobs)}건")
        all_jobs.extend(jobs)
    for code, name in ALBAMON_AREAS.items():
        print(f"[jobkorea] {name}({code}) 스크래핑...")
        jobs = scrape_jobkorea(code, name)
        print(f"  -> {len(jobs)}건")
        all_jobs.extend(jobs)

    short_term = [j for j in all_jobs if j.is_short_term()]
    print(f"전체 {len(all_jobs)}건 중 단기 키워드 매칭 {len(short_term)}건")

    seen = load_seen()
    new_jobs = [j for j in short_term if j.key not in seen]
    print(f"신규 {len(new_jobs)}건")

    seen_after = seen | {j.key for j in short_term}
    save_seen(seen_after)
    append_history(new_jobs)

    if new_jobs or os.environ.get("FORCE_EMAIL"):
        subject = f"[양천구 알바] 신규 {len(new_jobs)}건 ({datetime.now().strftime('%m/%d %H:%M')})"
        send_gmail(subject, render_email_html(new_jobs, len(seen_after)))
    else:
        print("신규 없음 - 메일 발송 생략")
    return 0


if __name__ == "__main__":
    sys.exit(main())
