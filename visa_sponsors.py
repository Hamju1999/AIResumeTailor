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

def sponsorship_label(company_name: str, sponsors: set[str] | None = None) -> str:
    """Returns a human-readable sponsorship label for UI display."""
    norm = _normalise(company_name)
    if any(ns in norm for ns in _NON_SPONSORS):
        return "unlikely_sponsor"
    if is_sponsor(company_name, sponsors):
        return "known_sponsor"
    return "unknown"