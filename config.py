"""
ResTail — Configuration

Personal settings (name, contact, files, locations, job titles, API key)
are stored in user_config.json after you run the setup wizard.
This file reads those settings dynamically — do not hardcode personal info here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
RESUME_DIR = OUTPUT_DIR / "resumes"
USER_CONFIG_PATH = BASE_DIR / "user_config.json"

# ── Load user config ───────────────────────────────────────────────────────────
def _load_user_config() -> dict:
    if USER_CONFIG_PATH.exists():
        try:
            return json.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

_cfg = _load_user_config()

# ── File paths ─────────────────────────────────────────────────────────────────
MASTER_RESUME_PATH   = Path(_cfg.get("master_resume_path",   str(BASE_DIR / "master_resume.txt")))
FORMAT_TEMPLATE_PATH = Path(_cfg.get("format_template_path", str(BASE_DIR / "format_template.txt")))

# ── LLM ───────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = _cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 4096

# ── Profile (from user_config.json) ───────────────────────────────────────────
USER_NAME     = _cfg.get("full_name", "YOUR NAME")
USER_CONTACT  = _cfg.get("contact_line", "City, State | phone | email | LinkedIn | GitHub")
LINKEDIN_URL  = _cfg.get("linkedin_url", "")
GITHUB_URL    = _cfg.get("github_url", "")
PORTFOLIO_URL = _cfg.get("portfolio_url", "")

# ── Scraping ───────────────────────────────────────────────────────────────────
DAYS_OLD          = 7
RESULTS_PER_TITLE = 15

LOCATIONS: list[str] = _cfg.get("locations") or [
    "New York, New York",
    "San Francisco, California",
    "Austin, Texas",
    "Chicago, Illinois",
    "Seattle, Washington",
]

JOB_BOARDS: list[str] = [
    "linkedin",
    "indeed",
    "dice",
    "glassdoor",
]

JOB_TITLES: list[str] = _cfg.get("job_titles") or [
    "Data Scientist",
    "Machine Learning Engineer",
    "AI Engineer",
    "Data Analyst",
    "Data Engineer",
]

# Options: "entry", "mid", "senior"
EXPERIENCE_LEVEL: str = _cfg.get("experience_level", "entry")

# ── Pipeline controls ──────────────────────────────────────────────────────────
MAX_RETRIES           = 2
SCRAPE_DELAY_SEC      = 1.5
INTER_JOB_DELAY_SEC   = 8
INTER_AGENT_DELAY_SEC = 3


def is_setup_complete() -> bool:
    """Returns True if the user has completed first-run setup."""
    cfg = _load_user_config()
    required = ["full_name", "contact_line", "master_resume_path", "format_template_path"]
    if not all(cfg.get(k) for k in required):
        return False
    if not Path(cfg["master_resume_path"]).exists():
        return False
    if not Path(cfg["format_template_path"]).exists():
        return False
    return True


def reload():
    """Reload config from disk (called after setup wizard saves new config)."""
    global _cfg, USER_NAME, USER_CONTACT, LINKEDIN_URL, GITHUB_URL, PORTFOLIO_URL
    global MASTER_RESUME_PATH, FORMAT_TEMPLATE_PATH, ANTHROPIC_API_KEY, LOCATIONS, JOB_TITLES
    _cfg = _load_user_config()
    USER_NAME            = _cfg.get("full_name", "YOUR NAME")
    USER_CONTACT         = _cfg.get("contact_line", "City, State | phone | email | LinkedIn | GitHub")
    LINKEDIN_URL         = _cfg.get("linkedin_url", "")
    GITHUB_URL           = _cfg.get("github_url", "")
    PORTFOLIO_URL        = _cfg.get("portfolio_url", "")
    MASTER_RESUME_PATH   = Path(_cfg.get("master_resume_path",   str(BASE_DIR / "master_resume.txt")))
    FORMAT_TEMPLATE_PATH = Path(_cfg.get("format_template_path", str(BASE_DIR / "format_template.txt")))
    ANTHROPIC_API_KEY    = _cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    LOCATIONS            = _cfg.get("locations") or LOCATIONS
    JOB_TITLES           = _cfg.get("job_titles") or JOB_TITLES
