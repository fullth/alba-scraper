"""양천구 인근 일일/단기 알바 스크래퍼 (알바몬 + 잡코리아).

GitHub Actions cron으로 매일 19시 (KST) 실행.
신규 공고를 data/seen.json과 diff하여 신규만 Gmail + Telegram으로 발송.
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
SUBSCRIBERS_FILE = ROOT / "subscribers.json"

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


JOBKOREA_KEYWORDS = ["일일알바", "당일알바", "단기알바", "하루알바"]


def scrape_jobkorea(area_code: str, area_name: str) -> list[Job]:
    """잡코리아 검색.

    잡코리아 SSR이 local 파라미터 일부 무시 → 키워드에 지역명을 직접 박는다.
    "{area_name} {keyword}" 조합으로 4개 키워드를 순회 + 결과는 Job.area에 area_name 기록 후
    is_short_term() + 후속 dedup으로 정리.
    """
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for keyword in JOBKOREA_KEYWORDS:
        for page in range(1, 3):  # 키워드 × 2페이지
            stext = f"{area_name} {keyword}"
            url = (
                "https://www.jobkorea.co.kr/Search/?"
                + urlencode(
                    {
                        "stext": stext,
                        "Page_No": page,
                        "tabType": "recruit",
                    }
                )
            )
            html = fetch(url)
            if not html:
                break
            soup = BeautifulSoup(html, "html.parser")
            # 새 잡코리아 마크업: <div class="flex w-full gap-5 p-7"> 컨테이너
            items = soup.select("div.flex.w-full.gap-5.p-7")
            if not items:
                # 구버전 fallback
                items = soup.select("article")
            for li in items:
                link = li.select_one("a[href*='/Recruit/GI_Read/']")
                if not link:
                    continue
                href = link.get("href", "")
                m = re.search(r"GI_Read/(\d+)", href)
                if not m:
                    continue
                job_id = m.group(1)
                if job_id in seen_ids:
                    continue
                # 텍스트 한 번 추출 후 줄 단위 파싱
                # 예: "신입 지원 가능 | 스크랩 | 제목 | 회사 | 지역 | 카테고리 | 급여 | 즉시지원 | 등록일 | 마감"
                text = li.get_text(" \n ", strip=True)
                lines = [ln.strip() for ln in text.split("\n") if ln.strip() and ln.strip() != "•"]
                lines = [ln for ln in lines if ln not in ("스크랩", "신입 지원 가능")]
                # 양천구가 실제 지역에 들어있는지 확인 (잡코리아는 키워드 매칭 결과라 다른 지역 섞일 수 있음)
                title = lines[0] if lines else ""
                company = lines[1] if len(lines) > 1 else ""
                actual_area = next((ln for ln in lines if any(g in ln for g in ["서울", "경기", "인천"])), area_name)
                wage = next((ln for ln in lines if "원" in ln and any(k in ln for k in ["시급", "일급", "월급", "연봉", "건별", "주급"])), "")
                posted = next((ln for ln in lines if re.search(r"\d{2}/\d{2}", ln) and "등록" in ln), "")
                full_url = href if href.startswith("http") else f"https://www.jobkorea.co.kr{href}"
                jobs.append(
                    Job(
                        source="jobkorea",
                        job_id=job_id,
                        title=title[:200],
                        company=company[:100],
                        area=actual_area[:60],
                        wage=wage[:60],
                        work_time="",
                        posted=posted[:30],
                        url=full_url,
                        raw_text=text.replace("\n", " ")[:500],
                    )
                )
                seen_ids.add(job_id)
            time.sleep(0.8)
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


def _area_summary() -> str:
    return ", ".join(ALBAMON_AREAS.values())


def render_email_html(new_jobs: list[Job], total_seen: int) -> str:
    area_label = _area_summary()
    if not new_jobs:
        return (
            f"<p>오늘 새로 등록된 {area_label} 일일/단기 알바가 없습니다.</p>"
            f"<p>전체 누적 추적: {total_seen}건</p>"
        )
    by_source: dict[str, list[Job]] = {}
    for job in new_jobs:
        by_source.setdefault(job.source, []).append(job)
    parts = [
        f"<h2 style='margin:0 0 12px'>{area_label} 신규 일일/단기 알바</h2>",
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


def render_telegram_text(new_jobs: list[Job], total_seen: int) -> str:
    """Telegram MarkdownV2 본문 (제한적 마크다운 + 링크)."""
    area_label = _area_summary()
    if not new_jobs:
        return f"오늘 새로 등록된 {area_label} 일일/단기 알바 없음.\n누적 추적 {total_seen}건."

    by_source: dict[str, list[Job]] = {}
    for job in new_jobs:
        by_source.setdefault(job.source, []).append(job)

    lines = [
        f"🔔 *{area_label}* 신규 일일/단기 알바 *{len(new_jobs)}건*",
        f"_{datetime.now().strftime('%Y-%m-%d %H:%M')} (KST) · 누적 {total_seen}건_",
        "",
    ]
    # 알림 너무 길지 않게 사이트별 상위 10건씩
    for src, jobs in by_source.items():
        lines.append(f"*[{src}] {len(jobs)}건*")
        for j in jobs[:10]:
            title = (j.title or "(제목 없음)")[:80]
            meta_parts = [p for p in [j.area, j.wage, j.posted] if p]
            meta = " · ".join(meta_parts)[:120]
            lines.append(f"• [{title}]({j.url})")
            if meta:
                lines.append(f"  {meta}")
            if j.company:
                lines.append(f"  {j.company[:40]}")
        if len(jobs) > 10:
            lines.append(f"  …외 {len(jobs) - 10}건")
        lines.append("")
    text = "\n".join(lines).strip()
    # Telegram 메시지 한도 4096자
    return text[:4000]


def load_subscribers() -> list[dict]:
    if not SUBSCRIBERS_FILE.exists():
        return []
    try:
        data = json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data.get("subscribers", []) if isinstance(data, dict) else []


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN 누락 - 텔레그램 발송 건너뜀", file=sys.stderr)
        return

    # 수신자 = subscribers.json + (옵션) Secret TELEGRAM_CHAT_ID 합집합
    chat_ids: set[str] = set()
    for sub in load_subscribers():
        cid = sub.get("chat_id") if isinstance(sub, dict) else sub
        if cid:
            chat_ids.add(str(cid))
    fallback = os.environ.get("TELEGRAM_CHAT_ID")
    if fallback:
        chat_ids.add(fallback)

    if not chat_ids:
        print("Telegram 수신자 없음 - 발송 건너뜀", file=sys.stderr)
        return

    api = f"https://api.telegram.org/bot{token}/sendMessage"
    sent = 0
    failed = 0
    for cid in chat_ids:
        try:
            resp = requests.post(
                api,
                json={
                    "chat_id": cid,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if resp.status_code == 200 and resp.json().get("ok"):
                sent += 1
            else:
                failed += 1
                print(f"Telegram 발송 실패 chat_id={cid}: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        except requests.RequestException as exc:
            failed += 1
            print(f"Telegram 발송 예외 chat_id={cid}: {exc}", file=sys.stderr)
        time.sleep(0.05)  # API 한도 (초당 30건) 여유
    print(f"Telegram 발송 완료: 성공 {sent}건 / 실패 {failed}건")


def main() -> int:
    print(f"=== {_area_summary()} 알바 스크래퍼 시작 ===")
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

    # 잡코리아 결과는 키워드 매칭이라 실제 지역 필터 한 번 더
    target_gus = set(ALBAMON_AREAS.values())

    def in_target_area(job: Job) -> bool:
        if job.source != "jobkorea":
            return True
        haystack = f"{job.area} {job.raw_text}"
        return any(g in haystack for g in target_gus)

    filtered = [j for j in all_jobs if in_target_area(j)]
    short_term = [j for j in filtered if j.is_short_term()]
    print(
        f"전체 {len(all_jobs)}건 → 지역 필터 {len(filtered)}건 → 단기 키워드 매칭 {len(short_term)}건"
    )

    seen = load_seen()
    new_jobs = [j for j in short_term if j.key not in seen]
    print(f"신규 {len(new_jobs)}건")

    seen_after = seen | {j.key for j in short_term}
    save_seen(seen_after)
    append_history(new_jobs)

    should_notify = bool(new_jobs) or bool(os.environ.get("FORCE_EMAIL"))
    if should_notify:
        subject = f"[알바 알림] {_area_summary()} 신규 {len(new_jobs)}건 ({datetime.now().strftime('%m/%d %H:%M')})"
        send_gmail(subject, render_email_html(new_jobs, len(seen_after)))
        send_telegram(render_telegram_text(new_jobs, len(seen_after)))
    else:
        print("신규 없음 - 알림 발송 생략")
    return 0


if __name__ == "__main__":
    sys.exit(main())
