"""
Visa Sponsor Checker - cross-references employer names against
USCIS H1B and STEM OPT employer data.
Data source: USCIS H1B Employer Data Hub (public, updated annually)
https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub
The employer list is cached locally in output/h1b_sponsors.json.
Cache refreshes automatically if older than 30 days.
"""

from __future__ import annotations
import json
import logging
import re
import time
from pathlib import Path
import config

log = logging.getLogger("visa_sponsors")
CACHE_PATH = config.OUTPUT_DIR / "h1b_sponsors.json"
CACHE_TTL_DAYS = 30

# Known large STEM OPT / H1B sponsors (fallback if download fails)
# Source: USCIS top H1B petitioners + common tech/data employers
_FALLBACK_SPONSORS = {
    "amazon", "google", "microsoft", "meta", "apple", "ibm", "oracle",
    "salesforce", "intel", "qualcomm", "nvidia", "adobe", "cisco",
    "deloitte", "accenture", "cognizant", "infosys", "tata consultancy",
    "wipro", "hcl", "capgemini", "ernst & young", "kpmg", "pwc",
    "jpmorgan", "jp morgan", "bank of america", "wells fargo", "citibank",
    "goldman sachs", "morgan stanley", "blackrock", "bloomberg",
    "unitedhealth", "anthem", "cigna", "cvs health", "aetna",
    "boeing", "lockheed martin", "raytheon", "general dynamics",
    "ge", "general electric", "honeywell", "siemens", "abb",
    "johnson & johnson", "pfizer", "merck", "abbvie", "bristol myers",
    "mayo clinic", "cleveland clinic", "johns hopkins", "northwestern",
    "mckinsey", "boston consulting", "bain", "booz allen",
    "uber", "lyft", "airbnb", "stripe", "square", "palantir",
    "snowflake", "databricks", "tableau", "splunk", "elastic",
    "servicenow", "workday", "sap", "epic systems",
    "northrop grumman", "l3harris", "leidos", "saic",
}
# Companies explicitly known NOT to sponsor (commonly flagged)
_NON_SPONSORS = {
    "staffmark", "kelly services", "manpower", "adecco", "randstad",
    "robert half", "spherion", "snagajob", "indeed flex",
}
# Sponsorship language patterns in job descriptions
_WILL_SPONSOR = re.compile(
    r"\b("
    r"will\s+sponsor|able\s+to\s+sponsor|open\s+to\s+sponsor(?:ing)?|"
    r"sponsor(?:ing)?\s+(?:h[\-\s]?1b?|opt|work\s+visa|visa)|"
    r"visa\s+sponsorship\s+(?:is\s+)?(?:available|provided|offered)|"
    r"sponsorship\s+(?:is\s+)?available|we\s+sponsor|"
    r"support\s+(?:h[\-\s]?1b?|opt|visa\s+transfer)|"
    r"(?:h[\-\s]?1b?)\s+(?:transfer\s+)?(?:welcome|accepted|considered)|"
    r"welcome\s+(?:h[\-\s]?1b?|visa|sponsorship)"
    r")\b",
    re.IGNORECASE,
)

_WONT_SPONSOR = re.compile(
    r"\b("
    r"(?:not?|no|cannot|will\s+not|unable\s+to|does?\s+not|not\s+able\s+to)\s+"
    r"(?:sponsor|provide\s+(?:visa\s+)?sponsorship|support\s+(?:visa|h[\-\s]?1b?)|"
    r"offer\s+(?:visa\s+)?sponsorship)|"
    r"sponsorship\s+(?:\w+\s+){0,4}(?:is\s+)?(?:not|unavailable|not\s+available|not\s+provided)|"
    r"must\s+(?:be\s+)?(?:authorized|eligible)\s+to\s+work|"
    r"no\s+(?:visa\s+)?sponsorship|"
    r"authorization\s+to\s+work\s+in\s+the\s+(?:us|united\s+states)\s+"
    r"(?:is\s+)?required(?:\s+now\s+and\s+in\s+the\s+future)?|"
    r"must\s+not\s+require\s+(?:\w+\s+(?:or\s+)?\w+\s+)?sponsorship"
    r")\b",
    re.IGNORECASE,
)

def detect_sponsorship_in_jd(jd_text: str) -> str:
    """
    Scan job description text for explicit sponsorship statements.
    Returns:
        "will_sponsor"   — JD explicitly states sponsorship is available
        "wont_sponsor"   — JD explicitly states no sponsorship
        "not_mentioned"  — no explicit statement found
    """
    if _WONT_SPONSOR.search(jd_text):
        return "wont_sponsor"
    if _WILL_SPONSOR.search(jd_text):
        return "will_sponsor"
    return "not_mentioned"

def _check_h1b_grader(company_name: str) -> bool:
    """
    Check h1bgrader.com for H1B sponsorship history.
    Returns True if company appears in their sponsor database.
    """
    try:
        import requests
        norm = _normalise(company_name)
        # H1B Grader has a search endpoint
        r = requests.get(
            "https://h1bgrader.com/api/search",
            params={"q": company_name, "type": "employer"},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if r.status_code == 200:
            data = r.json()
            employers = data.get("employers") or data.get("results") or []
            for emp in employers:
                name = emp.get("name") or emp.get("employer_name") or ""
                if _normalise(name) == norm or norm in _normalise(name):
                    count = emp.get("petition_count") or emp.get("total") or 0
                    if int(count) > 0:
                        return True
    except Exception as e:
        log.debug(f"H1B Grader check failed for '{company_name}': {e}")
    return False

_EVERIFY_CACHE_PATH = None   # set on first use

def check_everify_cached(company_name: str) -> bool:
    """
    E-Verify check with local CSV cache (downloaded once, valid 30 days).
    The full E-Verify participant list is a public CSV from e-verify.gov.
    """
    global _EVERIFY_CACHE_PATH
    import time
    cache_path = config.OUTPUT_DIR / "everify_employers.json"
    _EVERIFY_CACHE_PATH = cache_path
    # Load cache if fresh
    everify_set: set[str] = set()
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            age = (time.time() - data.get("ts", 0)) / 86400
            if age < 30:
                everify_set = set(data.get("employers", []))
        except Exception:
            pass
    # Fetch if not cached
    if not everify_set:
        try:
            import requests, csv, io
            # Public bulk data from e-verify.gov
            r = requests.get(
                "https://www.e-verify.gov/sites/default/files/everify/"
                "bulk-data/E-VerifyParticipants.csv",
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200:
                reader = csv.reader(io.StringIO(r.text))
                next(reader, None)  # skip header
                for row in reader:
                    if row:
                        everify_set.add(_normalise(row[0]))
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps({"ts": time.time(),
                                "employers": sorted(everify_set)},
                               indent=2),
                    encoding="utf-8",
                )
                log.info(f"E-Verify list cached: {len(everify_set):,} employers")
        except Exception as e:
            log.warning(f"E-Verify bulk download failed: {e}")
    if not everify_set:
        return False
    norm = _normalise(company_name)
    if norm in everify_set:
        return True
    # Partial match
    for emp in everify_set:
        if len(emp) > 4 and (emp in norm or norm in emp):
            return True
    return False

def _normalise(name: str) -> str:
    """Normalise company name for fuzzy matching."""
    name = name.lower().strip()
    name = re.sub(r"\b(inc|llc|corp|ltd|co|group|holdings|services|solutions"
                  r"|technologies|technology|systems|consulting|partners"
                  r"|associates|international|global|america|americas"
                  r"|north america|usa|us)\b\.?", "", name)
    name = re.sub(r"[^\w\s]", "", name)
    return re.sub(r"\s+", " ", name).strip()

def _load_cache() -> set[str]:
    """Load cached sponsor list if fresh, else return empty set."""
    if not CACHE_PATH.exists():
        return set()
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        age_days = (time.time() - data.get("ts", 0)) / 86400
        if age_days > CACHE_TTL_DAYS:
            return set()
        return set(data.get("sponsors", []))
    except Exception:
        return set()

def _save_cache(sponsors: set[str]) -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({"ts": time.time(), "sponsors": sorted(sponsors)},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

def _fetch_uscis_sponsors() -> set[str]:
    """
    Attempt to fetch H1B employer list from USCIS public data.
    Falls back gracefully if unavailable.
    """
    try:
        import requests
        # USCIS H1B Employer Data Hub - public CSV endpoint
        url = (
            "https://www.uscis.gov/sites/default/files/document/data/"
            "h1b_datahubexport-2024.csv"
        )
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        sponsors: set[str] = set()
        for line in r.text.splitlines()[1:]:   # skip header
            parts = line.split(",")
            if parts:
                name = _normalise(parts[0].strip().strip('"'))
                if name and len(name) > 2:
                    sponsors.add(name)

        log.info(f"Loaded {len(sponsors):,} H1B sponsors from USCIS")
        return sponsors
    except Exception as e:
        log.warning(f"USCIS data fetch failed ({e}) — using fallback list")
        return set()

def load_sponsors() -> set[str]:
    """
    Return normalised set of known H1B/STEM OPT sponsor company names.
    Uses cache if fresh, otherwise fetches from USCIS, falls back to
    built-in list if all else fails.
    """
    cached = _load_cache()
    if cached:
        return cached
    fetched = _fetch_uscis_sponsors()
    sponsors = fetched if fetched else {_normalise(s) for s in _FALLBACK_SPONSORS}
    _save_cache(sponsors)
    return sponsors

def is_sponsor(company_name: str, sponsors: set[str] | None = None) -> bool:
    """
    Returns True if the company is a known H1B/STEM OPT sponsor.
    Accepts a pre-loaded sponsors set for performance in batch checks.
    """
    if sponsors is None:
        sponsors = load_sponsors()
    norm = _normalise(company_name)
    # Exact match
    if norm in sponsors:
        return True
    # Non-sponsor override
    if any(ns in norm for ns in _NON_SPONSORS):
        return False
    # Partial match - company name contains or is contained by a known sponsor
    for s in sponsors:
        if len(s) > 4 and (s in norm or norm in s):
            return True
    return False

def sponsorship_label(
    company_name: str,
    jd_text: str = "",
    sponsors: set[str] | None = None,
    check_everify: bool = True,
) -> dict:
    """
    Returns a full sponsorship assessment dict:
    {
        "h1b":      "known_sponsor" | "unknown" | "unlikely_sponsor",
        "stem_opt": "everify_confirmed" | "unknown",
        "jd_says":  "will_sponsor" | "wont_sponsor" | "not_mentioned",
        "verdict":  "apply" | "skip" | "apply_with_caution",
        "summary":  "<one line human-readable>"
    }
    """
    if sponsors is None:
        sponsors = load_sponsors()
    # JD explicit statement — highest confidence
    jd_says = detect_sponsorship_in_jd(jd_text) if jd_text else "not_mentioned"
    if jd_says == "wont_sponsor":
        return {
            "h1b": "unknown", "stem_opt": "unknown",
            "jd_says": "wont_sponsor",
            "verdict": "skip",
            "summary": "JD explicitly states no sponsorship."
        }
    # H1B check — USCIS data + H1B Grader
    norm = _normalise(company_name)
    uscis_known = is_sponsor(company_name, sponsors)
    h1b_grader  = _check_h1b_grader(company_name) if not uscis_known else True
    non_sponsor = any(ns in norm for ns in _NON_SPONSORS)
    if non_sponsor:
        h1b = "unlikely_sponsor"
    elif uscis_known or h1b_grader:
        h1b = "known_sponsor"
    else:
        h1b = "unknown"
    # STEM OPT / E-Verify
    stem_opt = "unknown"
    if check_everify:
        try:
            if check_everify_cached(company_name):
                stem_opt = "everify_confirmed"
        except Exception:
            pass
    # JD says will sponsor — best case
    if jd_says == "will_sponsor":
        verdict = "apply"
        summary = "JD explicitly offers sponsorship."
    elif h1b == "known_sponsor" and stem_opt == "everify_confirmed":
        verdict = "apply"
        summary = f"{company_name} is a known H1B sponsor and E-Verify participant."
    elif h1b == "known_sponsor":
        verdict = "apply"
        summary = f"{company_name} has a history of H1B sponsorship."
    elif stem_opt == "everify_confirmed":
        verdict = "apply_with_caution"
        summary = f"{company_name} is E-Verify registered (STEM OPT eligible) but H1B history unknown."
    elif h1b == "unlikely_sponsor":
        verdict = "skip"
        summary = f"{company_name} appears unlikely to sponsor based on company type."
    else:
        verdict = "apply_with_caution"
        summary = f"No confirmed sponsorship data for {company_name}."
    return {
        "h1b": h1b, "stem_opt": stem_opt,
        "jd_says": jd_says, "verdict": verdict, "summary": summary,
    }