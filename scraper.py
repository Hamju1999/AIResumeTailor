"""
Phase 1 + 2 — Job Discovery & Extraction

Entry-level / internship enforcement:
  LinkedIn: f_E=1,2 (experience level: internship + entry level)
  Indeed:   explvl=entry_level
  Dice:     query appended with "(entry level OR intern)"
  All:      _filter_by_seniority() post-scrape title check

Quality filters (post-scrape):
  _filter_by_relevance(): drops off-topic titles and spam companies
  _filter_by_seniority(): drops senior/staff/principal/lead/director titles
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import config
from models import Job, RawJob

log = logging.getLogger("scraper")


# ── Filter patterns ───────────────────────────────────────────────────────────

# Seniority keywords that disqualify a job title
_SENIOR_PATTERN = re.compile(
    r"\b("
    r"senior|sr\.?|staff|principal|lead|director|manager|"
    r"vp|vice\s+president|head\s+of|chief|executive|president|"
    r"distinguished|fellow|architect(?!\s+engineer)"
    r")\b",
    re.IGNORECASE,
)

# At least one of these must be in the job title for it to be relevant
_DS_KEYWORD_PATTERN = re.compile(
    r"\b("
    r"data|scientist|analyst|analytics|engineer|"
    r"machine\s+learning|\bml\b|\bai\b|artificial\s+intelligence|"
    r"nlp|llm|deep\s+learning|big\s+data|"
    r"applied|research|quantitative|statistician|bioinformat|computational"
    r")\b",
    re.IGNORECASE,
)

# Company names matching these patterns indicate spam or low-quality aggregators
_SPAM_COMPANY_PATTERN = re.compile(
    r"chatgpt\s+jobs|openai\s+jobs|gpt\s+jobs|"
    r"remote\s+jobs\s+worldwide|jobs\s+via|jooble|jobgether|"
    r"trabajo\.com|snagajob|jobs\s+for\s+humanity|"
    r"crowdstaffing|lensa|zippia|staffing\s+solutions"
    r"|\bjobs\s*$",   # company name that is just "XYZ Jobs"
    re.IGNORECASE,
)

MIN_DESC_LEN = 200   # characters — stub listings with < this are skipped


def _is_senior_title(title: str) -> bool:
    return bool(_SENIOR_PATTERN.search(title))

def _is_relevant_title(title: str) -> bool:
    return bool(_DS_KEYWORD_PATTERN.search(title))

def _is_spam_company(company: str) -> bool:
    return bool(_SPAM_COMPANY_PATTERN.search(company.strip()))


# ── HTTP session ──────────────────────────────────────────────────────────────

_SESSION: requests.Session | None = None

def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })
    return _SESSION


def _get(url: str, params: dict | None = None, timeout: int = 15) -> requests.Response | None:
    for attempt in range(3):
        try:
            r = _session().get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                log.warning(f"Rate-limited — waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                log.debug(f"HTTP {r.status_code}: {url[:80]}")
                return None
            return r
        except requests.RequestException as e:
            log.debug(f"Request error ({attempt+1}/3): {e}")
            time.sleep(2 * (attempt + 1))
    return None


# ── Public entry point ────────────────────────────────────────────────────────

async def discover_jobs() -> list[Job]:
    """
    For each title, search locations in priority order until RESULTS_PER_TITLE reached.
    Post-scrape pipeline: date → relevance → seniority → dedup.
    """
    all_raw: list[RawJob] = []

    scrapers = {
        "linkedin":    _scrape_linkedin,
        "indeed":      _scrape_indeed,
        "dice":        _scrape_dice,
        "glassdoor":   _scrape_glassdoor,
        "handshake":   _scrape_handshake,
        "interstride": _scrape_interstride,
    }
    active = [b for b in config.JOB_BOARDS if b in scrapers]
    if not active:
        log.warning("No supported boards in config.JOB_BOARDS")
        return []

    for title in config.JOB_TITLES:
        title_raw: list[RawJob] = []

        for location in config.LOCATIONS:
            if len(title_raw) >= config.RESULTS_PER_TITLE:
                break

            remaining = config.RESULTS_PER_TITLE - len(title_raw)
            log.info(f"  [{location}] '{title}' — need {remaining} more")

            for board in active:
                if len(title_raw) >= config.RESULTS_PER_TITLE:
                    break
                try:
                    raw = await asyncio.to_thread(scrapers[board], title, location)
                    added = 0
                    for job in raw:
                        if len(title_raw) >= config.RESULTS_PER_TITLE:
                            break
                        title_raw.append(job)
                        added += 1
                    if added:
                        log.info(f"    [{board}] +{added}")
                except Exception as e:
                    log.warning(f"    [{board}] failed: {e}")
                await asyncio.sleep(config.SCRAPE_DELAY_SEC)

        all_raw.extend(title_raw)

    log.info(f"Raw total: {len(all_raw)}")

    dated    = _filter_by_date(all_raw)
    relevant = _filter_by_relevance(dated)
    levelled = _filter_by_seniority(relevant)
    jobs     = _deduplicate(levelled)

    log.info(f"After date filter:      {len(dated)}")
    log.info(f"After relevance filter: {len(relevant)}")
    log.info(f"After seniority filter: {len(levelled)}")
    log.info(f"After dedup:            {len(jobs)}")
    return jobs


# ── LinkedIn ──────────────────────────────────────────────────────────────────
# f_E=1,2  → experience: 1=Internship, 2=Entry level
# f_JT=F,I → job type: F=Full-time, I=Internship
# f_TPR    → time posted in seconds (7 days = 604800)

_LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LI_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

def _scrape_linkedin(title: str, location: str) -> list[RawJob]:
    results: list[RawJob] = []
    seen: set[str] = set()

    for start in range(0, config.RESULTS_PER_TITLE, 25):
        r = _get(_LI_SEARCH, params={
            "keywords": title,
            "location": location,
            "f_TPR":    f"r{config.DAYS_OLD * 86400}",
            "f_JT":     "F,I",
            "f_E":      {"entry": "1,2", "mid": "3", "senior": "4"}.get(config.EXPERIENCE_LEVEL, "1,2"),
            "start":    start,
            "count":    25,
        })
        if r is None:
            break

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all("div", class_=re.compile(r"base-search-card"))
        if not cards:
            break

        for card in cards:
            try:
                urn = card.get("data-entity-urn", "")
                m = re.search(r"jobPosting:(\d+)", urn)
                if not m:
                    continue
                job_id = m.group(1)
                if job_id in seen:
                    continue
                seen.add(job_id)

                a = card.find("a", class_="base-card__full-link") or card.find("a")
                url = (a.get("href", "").split("?")[0]) if a else \
                      f"https://www.linkedin.com/jobs/view/{job_id}"

                t_el = card.find("h3")
                c_el = card.find("h4")
                l_el = card.select_one(".job-search-card__location")
                d_el = card.find("time")

                job_title = t_el.get_text(strip=True) if t_el else title
                company   = c_el.get_text(strip=True) if c_el else "Unknown"

                # Early checks before fetching full description (saves requests)
                if _is_senior_title(job_title):
                    log.debug(f"LI: skip senior '{job_title}'")
                    continue
                if not _is_relevant_title(job_title):
                    log.debug(f"LI: skip irrelevant '{job_title}'")
                    continue
                if _is_spam_company(company):
                    log.debug(f"LI: skip spam company '{company}'")
                    continue

                description = _li_description(job_id)
                if not description or len(description) < MIN_DESC_LEN:
                    continue

                results.append(RawJob(
                    job_url=url,
                    title=job_title,
                    company=company,
                    location=(l_el.get_text(strip=True) if l_el else location),
                    date_posted=_parse_iso(d_el.get("datetime")) if d_el else None,
                    description=description,
                    board="linkedin",
                ))
                time.sleep(0.8)

            except Exception as e:
                log.debug(f"LinkedIn card error: {e}")

        if len(results) >= config.RESULTS_PER_TITLE:
            break
        time.sleep(1.5)

    return results


def _li_description(job_id: str) -> str:
    r = _get(_LI_DETAIL.format(job_id=job_id))
    if r is None:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for sel in [".description__text", ".show-more-less-html__markup", ".job-details"]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(separator="\n", strip=True)
    return soup.get_text(separator="\n", strip=True)[:3000]


# ── Indeed ────────────────────────────────────────────────────────────────────
# explvl=entry_level → server-side experience level filter

_INDEED_RSS = "https://www.indeed.com/rss"

def _scrape_indeed(title: str, location: str) -> list[RawJob]:
    results: list[RawJob] = []
    r = _get(_INDEED_RSS, params={
        "q":       title,
        "l":       location,
        "fromage": config.DAYS_OLD,
        "limit":   min(config.RESULTS_PER_TITLE, 50),
        "sort":    "date",
        "explvl":  {"entry": "entry_level", "mid": "mid_level", "senior": "senior_level"}.get(config.EXPERIENCE_LEVEL, "entry_level"),
    })
    if r is None:
        return []

    soup = BeautifulSoup(r.text, "xml")
    for item in soup.find_all("item")[:config.RESULTS_PER_TITLE]:
        try:
            link_el = item.find("link") or item.find("guid")
            url = link_el.text.strip() if link_el else ""
            if not url:
                continue

            title_el = item.find("title")
            date_el  = item.find("pubDate")
            src_el   = item.find("source")

            job_title = title_el.text.strip() if title_el else title
            # Strip company suffix Indeed sometimes appends: "Title - Company"
            job_title = re.split(r"\s+[-|]\s+", job_title)[0].strip()
            company   = src_el.text.strip() if src_el else "Unknown"

            if _is_senior_title(job_title):
                log.debug(f"Indeed: skip senior '{job_title}'")
                continue
            if not _is_relevant_title(job_title):
                log.debug(f"Indeed: skip irrelevant '{job_title}'")
                continue
            if _is_spam_company(company):
                log.debug(f"Indeed: skip spam company '{company}'")
                continue

            description = _indeed_description(url)
            if not description or len(description) < MIN_DESC_LEN:
                continue

            results.append(RawJob(
                job_url=url,
                title=job_title,
                company=company,
                location=location,
                date_posted=_parse_rfc2822(date_el.text) if date_el else None,
                description=description,
                board="indeed",
            ))
            time.sleep(1.0)
        except Exception as e:
            log.debug(f"Indeed item error: {e}")

    return results


def _indeed_description(url: str) -> str:
    r = _get(url)
    if r is None:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for sel in [
        "#jobDescriptionText",
        ".jobsearch-jobDescriptionText",
        "[data-testid='jobDescriptionText']",
        ".job-description",
    ]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(separator="\n", strip=True)
    return ""


# ── Dice ──────────────────────────────────────────────────────────────────────
# No reliable career-level API param — append to query to bias ranking

_DICE_API = "https://job-search-api.svc.dhigroupinc.com/v1/dice/jobs/search"

def _scrape_dice(title: str, location: str) -> list[RawJob]:
    results: list[RawJob] = []
    r = _get(_DICE_API, params={
        "q":                      f"{title} (entry level OR intern)",
        "countryCode2":           "US",
        "radius":                 50,
        "radiusUnit":             "mi",
        "pageSize":               min(config.RESULTS_PER_TITLE, 20),
        "facets":                 "employmentType|postedDate",
        "filters.postedDate":     "ONE_WEEK",
        "filters.employmentType": "FULLTIME",
        "fields":                 "id,title,companyName,location,date,description,applyUrl",
        "culture":                "en",
    })
    if r is None:
        return []

    try:
        data = r.json()
    except Exception:
        return []

    for job in data.get("data", [])[:config.RESULTS_PER_TITLE]:
        try:
            url       = job.get("applyUrl") or \
                        f"https://www.dice.com/job-detail/{job.get('id','')}"
            job_title = job.get("title", title)
            company   = job.get("companyName", "Unknown")

            if _is_senior_title(job_title):
                log.debug(f"Dice: skip senior '{job_title}'")
                continue
            if not _is_relevant_title(job_title):
                log.debug(f"Dice: skip irrelevant '{job_title}'")
                continue
            if _is_spam_company(company):
                log.debug(f"Dice: skip spam company '{company}'")
                continue

            desc = job.get("description", "")
            if desc:
                desc = BeautifulSoup(desc, "html.parser").get_text(separator="\n", strip=True)
            if not desc or len(desc) < MIN_DESC_LEN:
                continue

            results.append(RawJob(
                job_url=url,
                title=job_title,
                company=company,
                location=job.get("location", location),
                date_posted=_parse_iso(job.get("date")),
                description=desc,
                board="dice",
            ))
        except Exception as e:
            log.debug(f"Dice job error: {e}")

    return results


# ── Glassdoor ─────────────────────────────────────────────────────────────────
# No reliable experience filter via guest endpoint — relies on post-scrape filters

_GD_SEARCH = "https://www.glassdoor.com/Job/jobs.htm"

def _scrape_glassdoor(title: str, location: str) -> list[RawJob]:
    results: list[RawJob] = []
    r = _get(_GD_SEARCH, params={
        "sc.keyword": title,
        "locT":       "C",
        "locKeyword": location,
        "fromAge":    config.DAYS_OLD,
        "sortBy":     "date",
    })
    if r is None:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = (
        soup.find_all("li", class_=re.compile(r"JobsList_jobListItem")) or
        soup.find_all("li", {"data-test": re.compile(r"jobListing")}) or
        soup.find_all("div", class_=re.compile(r"jobCard"))
    )

    for card in cards[:config.RESULTS_PER_TITLE]:
        try:
            a = (
                card.find("a", class_=re.compile(r"jobLink|JobCard_trackingLink")) or
                card.find("a")
            )
            if not a:
                continue
            url = urljoin("https://www.glassdoor.com", a.get("href", ""))

            t_el = card.find(class_=re.compile(r"JobCard_seoLink|jobTitle"))
            c_el = card.find(class_=re.compile(r"EmployerProfile_name|employer-name"))
            l_el = card.find(class_=re.compile(r"JobCard_location|location"))

            job_title = t_el.get_text(strip=True) if t_el else title
            company   = c_el.get_text(strip=True) if c_el else "Unknown"

            if _is_senior_title(job_title):
                log.debug(f"GD: skip senior '{job_title}'")
                continue
            if not _is_relevant_title(job_title):
                log.debug(f"GD: skip irrelevant '{job_title}'")
                continue
            if _is_spam_company(company):
                log.debug(f"GD: skip spam company '{company}'")
                continue

            description = _gd_description(url)
            if not description or len(description) < MIN_DESC_LEN:
                continue

            results.append(RawJob(
                job_url=url,
                title=job_title,
                company=company,
                location=(l_el.get_text(strip=True) if l_el else location),
                date_posted=None,
                description=description,
                board="glassdoor",
            ))
            time.sleep(1.5)
        except Exception as e:
            log.debug(f"Glassdoor card error: {e}")

    return results


def _gd_description(url: str) -> str:
    r = _get(url)
    if r is None:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for sel in [
        "[data-test='jobDescriptionContent']",
        ".JobDetails_jobDescription",
        "#JobDescriptionContainer",
        ".desc",
    ]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(separator="\n", strip=True)
    return ""



# ── Handshake ─────────────────────────────────────────────────────────────────
# Public job search — no auth required for browsing
_HANDSHAKE_SEARCH = "https://app.joinhandshake.com/stu/postings"

def _scrape_handshake(title: str, location: str) -> list[RawJob]:
    """
    Handshake public job search. Targets early-career / internship / new-grad roles.
    Uses the public API endpoint that the Handshake website itself calls.
    """
    results: list[RawJob] = []
    try:
        r = _get(
            "https://app.joinhandshake.com/stu/postings",
            params={
                "page":                1,
                "per_page":            min(config.RESULTS_PER_TITLE, 25),
                "sort_direction":      "desc",
                "sort_column":         "created_at",
                "job_type_names[]":    ["Job", "Internship"],
                "query":               title,
                "location":            location,
                "distance":            50,
            },
        )
        if r is None:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        # Handshake renders server-side HTML for public pages
        cards = soup.find_all("li", attrs={"data-hook": "posting-item"}) or                 soup.find_all("div", class_=re.compile(r"posting|job-card"))
        for card in cards[:config.RESULTS_PER_TITLE]:
            try:
                a      = card.find("a")
                url    = urljoin("https://app.joinhandshake.com", a.get("href", "")) if a else ""
                if not url:
                    continue
                t_el   = card.find(class_=re.compile(r"title|name|posting"))
                c_el   = card.find(class_=re.compile(r"company|employer"))
                title_ = t_el.get_text(strip=True) if t_el else title
                company= c_el.get_text(strip=True) if c_el else "Unknown"

                if _is_senior_title(title_):
                    continue
                if not _is_relevant_title(title_):
                    continue

                desc = _get_description_from_page(url)
                if not desc or len(desc) < MIN_DESC_LEN:
                    continue

                results.append(RawJob(
                    job_url=url, title=title_, company=company,
                    location=location, date_posted=None,
                    description=desc, board="handshake",
                ))
                time.sleep(1.0)
            except Exception as e:
                log.debug(f"Handshake card error: {e}")
    except Exception as e:
        log.debug(f"Handshake scrape error: {e}")
    return results


# ── Interstride ───────────────────────────────────────────────────────────────
# Targets international student / OPT / STEM OPT job seekers specifically.
# Public job board — no auth required for basic listing pages.
_INTERSTRIDE_SEARCH = "https://app.interstride.com/jobs"

def _scrape_interstride(title: str, location: str) -> list[RawJob]:
    """
    Interstride job board targeting OPT/CPT/H1B-friendly postings.
    Scrapes the public job listing page.
    """
    results: list[RawJob] = []
    try:
        r = _get(
            "https://interstride.com/jobs/",
            params={
                "s":        title,
                "location": location,
                "type":     "job",
            },
        )
        if r is None:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        cards = (
            soup.find_all("article", class_=re.compile(r"job|posting")) or
            soup.find_all("div",     class_=re.compile(r"job-listing|job-card"))
        )
        for card in cards[:config.RESULTS_PER_TITLE]:
            try:
                a      = card.find("a")
                url    = urljoin("https://interstride.com", a.get("href", "")) if a else ""
                if not url:
                    continue
                t_el   = card.find(class_=re.compile(r"title|job-title"))
                c_el   = card.find(class_=re.compile(r"company|employer"))
                title_ = t_el.get_text(strip=True) if t_el else title
                company= c_el.get_text(strip=True) if c_el else "Unknown"

                if _is_senior_title(title_):
                    continue
                if not _is_relevant_title(title_):
                    continue
                if _is_spam_company(company):
                    continue

                desc = _get_description_from_page(url)
                if not desc or len(desc) < MIN_DESC_LEN:
                    continue

                results.append(RawJob(
                    job_url=url, title=title_, company=company,
                    location=location, date_posted=None,
                    description=desc, board="interstride",
                ))
                time.sleep(1.0)
            except Exception as e:
                log.debug(f"Interstride card error: {e}")
    except Exception as e:
        log.debug(f"Interstride scrape error: {e}")
    return results


def _get_description_from_page(url: str) -> str:
    """Generic description extractor — tries common selectors across job boards."""
    r = _get(url)
    if r is None:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for sel in [
        ".description__text", ".show-more-less-html__markup",
        "#jobDescriptionText", ".jobsearch-jobDescriptionText",
        "[data-testid='jobDescriptionText']", ".JobDetails_jobDescription",
        "[data-test='jobDescriptionContent']", ".job-description",
        ".posting-description", ".job-details-body", "article", "main",
    ]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 150:
                return text
    return ""


# ── Post-scrape filters ───────────────────────────────────────────────────────

def _filter_by_relevance(jobs: list[RawJob]) -> list[RawJob]:
    """Drop off-topic titles and spam companies."""
    kept, dropped = [], 0
    for j in jobs:
        if not _is_relevant_title(j.title):
            log.debug(f"Relevance: dropped '{j.title}' @ {j.company}")
            dropped += 1
        elif _is_spam_company(j.company):
            log.debug(f"Spam company: dropped '{j.company}'")
            dropped += 1
        else:
            kept.append(j)
    if dropped:
        log.info(f"Relevance filter: dropped {dropped} off-topic or spam listings")
    return kept


def _filter_by_seniority(jobs: list[RawJob]) -> list[RawJob]:
    """Drop senior/staff/principal/lead/director titles."""
    kept, dropped = [], 0
    for j in jobs:
        if _is_senior_title(j.title) and config.EXPERIENCE_LEVEL != "senior":
            log.debug(f"Seniority: dropped '{j.title}' @ {j.company}")
            dropped += 1
        else:
            kept.append(j)
    if dropped:
        log.info(f"Seniority filter: dropped {dropped} senior/lead/director titles")
    return kept


def _filter_by_date(jobs: list[RawJob]) -> list[RawJob]:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=config.DAYS_OLD)
    result = []
    for j in jobs:
        if j.date_posted is None:
            result.append(j)
        else:
            dp = j.date_posted
            if dp.tzinfo is None:
                dp = dp.replace(tzinfo=timezone.utc)
            if dp >= cutoff:
                result.append(j)
    return result


def _deduplicate(jobs: list[RawJob]) -> list[Job]:
    seen: set[str] = set()
    result: list[Job] = []
    for r in jobs:
        job_id = hashlib.md5(r.job_url.encode()).hexdigest()[:12]
        if job_id in seen:
            continue
        seen.add(job_id)
        result.append(Job(**r.model_dump(), job_id=job_id))
    return result


def _parse_iso(val) -> Optional[datetime]:
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(str(val)[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_rfc2822(val: str) -> Optional[datetime]:
    if not val:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(val)
    except Exception:
        return None
