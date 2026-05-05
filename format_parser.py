"""
Format Parser — reads the user's format template and extracts structured parameters.

Called once during pipeline startup via load_content() in pipeline.py.
Results are cached in memory for the entire run.

Extracts:
  max_pages          — how many pages the resume should be (1, 2, or 3)
  max_lines          — line count proxy derived from max_pages
  skill_groups       — exact skill group heading names from the template
  max_projects       — maximum number of projects to include
  project_bullets    — bullet points per project
  exp_bullets_min    — minimum experience bullets per role
  exp_bullets_max    — maximum experience bullets per role
  summary_sentences  — number of sentences in the summary
  section_order      — ordered list of section names

All downstream modules (prompts.py, validator.py) read from the returned
FormatParams object rather than hardcoded values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("format_parser")

# ── Cached result ─────────────────────────────────────────────────────────────
_cached_params: "FormatParams | None" = None


@dataclass
class FormatParams:
    """Structured parameters extracted from the format template."""
    max_pages:         int        = 1
    max_lines:         int        = 65      # line count proxy for validator
    skill_groups:      list[str]  = field(default_factory=lambda: [
                                       "Programming & Engineering",
                                       "Applied AI & NLP",
                                       "Analytics & Visualization",
                                   ])
    skill_groups_fixed: bool = True
    max_projects:      int        = 3
    project_bullets:   int        = 3
    exp_bullets_min:   int        = 4
    exp_bullets_max:   int        = 5
    summary_sentences: int        = 2
    section_order:     list[str]  = field(default_factory=lambda: [
                                       "summary", "skills", "experience",
                                       "projects", "education", "certifications",
                                   ])
    raw_notes:         str        = ""     # parser's notes for debugging


# Pages → approximate line count proxy used by the validator
_PAGE_LINES = {1: 65, 2: 130, 3: 195}


async def parse(format_template: str) -> FormatParams:
    """
    Parse the format template using Claude.
    Results are cached — subsequent calls return the same object.
    If parsing fails, returns safe defaults.
    """
    global _cached_params
    if _cached_params is not None:
        return _cached_params

    params = await _parse_with_llm(format_template)
    _cached_params = params
    log.info(
        f"Format parsed: {params.max_pages}p | "
        f"{len(params.skill_groups)} skill groups: {params.skill_groups} | "
        f"{params.max_projects} projects × {params.project_bullets} bullets | "
        f"exp {params.exp_bullets_min}-{params.exp_bullets_max} bullets"
    )
    return params


async def parse_sync(format_template: str) -> FormatParams:
    """Synchronous wrapper for use outside async context."""
    import asyncio
    return asyncio.get_event_loop().run_until_complete(parse(format_template))


def reset():
    """Clear the cache. Call this if the format template changes between runs."""
    global _cached_params
    _cached_params = None


async def _parse_with_llm(format_template: str) -> FormatParams:
    """Ask Claude to extract structured parameters from the format template."""
    try:
        import llm_client
        data = await llm_client.call(
            system=_PARSER_SYSTEM,
            user=f"FORMAT TEMPLATE:\n---\n{format_template}\n---\n\nExtract the parameters. Output only the JSON.",
            expect_json=True,
        )
        return _build_params(data)
    except Exception as e:
        log.warning(f"Format parsing failed ({e}) — using defaults")
        return _infer_from_text(format_template)


_PARSER_SYSTEM = """\
You are a resume format specification parser.
Read the format template and extract structured parameters.
Output ONLY valid JSON — no preamble, no explanation.

{
  "max_pages": <integer: how many pages the resume should be. Default 1 if not stated>,
  "skill_groups": [<list of exact skill group heading names as they appear in the template>],
  "max_projects": <integer: maximum number of projects to include. Default 3>,
  "project_bullets": <integer: bullet points per project. Default 3>,
  "exp_bullets_min": <integer: minimum experience bullets per role. Default 4>,
  "exp_bullets_max": <integer: maximum experience bullets per role. Default 5>,
  "summary_sentences": <integer: sentences in the summary. Default 2>,
  "section_order": [<ordered list of section names: summary, skills, experience, projects, education, certifications, volunteer, references — include only sections mentioned>],
  "notes": "<one sentence: anything unusual about this format that the tailor should know>"
}

Rules for skill_groups:
  Extract the EXACT text used for each skill group in the template.
  For example: ["Programming and Engineering", "AI and Machine Learning", "Analytics and Visualisation"]
  If the template does not define skill groups explicitly, return an empty list [].
  Only return group names if they are literally written in the format template.

Rules for max_pages:
  1 = US/Canada standard (one page strict)
  2 = common for mid-level or detailed formats
  3 = Australian, UK, New Zealand, or explicitly multi-page formats
"""

def _groups_are_explicit(groups) -> bool:
    """
    Returns True only if the LLM found skill groups explicitly stated
    in the format template — not if it fell back to the defaults.
    The defaults are the three standard US groups. If the returned groups
    exactly match the defaults, treat as not explicitly specified.
    """
    if not groups:
        return False
    defaults = {
        "Programming & Engineering",
        "Applied AI & NLP",
        "Analytics & Visualization",
    }
    return set(groups) != defaults

def _build_params(data: dict) -> FormatParams:
    """Convert parsed JSON dict into a FormatParams object."""
    max_pages = int(data.get("max_pages") or 1)
    return FormatParams(
        max_pages         = max_pages,
        max_lines         = _PAGE_LINES.get(max_pages, 65),
        skill_groups      = data.get("skill_groups") or [
                                "Programming & Engineering",
                                "Applied AI & NLP",
                                "Analytics & Visualization",
                            ],
        skill_groups_fixed = _groups_are_explicit(data.get("skill_groups")),
        max_projects      = int(data.get("max_projects") or 3),
        project_bullets   = int(data.get("project_bullets") or 3),
        exp_bullets_min   = int(data.get("exp_bullets_min") or 4),
        exp_bullets_max   = int(data.get("exp_bullets_max") or 5),
        summary_sentences = int(data.get("summary_sentences") or 2),
        section_order     = data.get("section_order") or [
                                "summary", "skills", "experience",
                                "projects", "education", "certifications",
                            ],
        raw_notes         = data.get("notes") or "",
    )


def _infer_from_text(text: str) -> FormatParams:
    """
    Fallback: try to infer key parameters from the format template text
    using simple heuristics when the LLM call fails.
    """
    import re
    text_lower = text.lower()

    # Page count
    max_pages = 1
    if "2-3 page" in text_lower or "2 to 3 page" in text_lower or "three page" in text_lower:
        max_pages = 3
    elif "2 page" in text_lower or "two page" in text_lower:
        max_pages = 2
    if "australia" in text_lower or "uk resume" in text_lower or "new zealand" in text_lower:
        max_pages = 3

    # Skill groups — look for lines with ":" that seem like group headings
    skill_groups = []
    for line in text.splitlines():
        line = line.strip()
        if ":" in line and len(line) < 80 and not line.startswith("#"):
            label = line.split(":")[0].strip()
            # Heuristic: skill group labels are short and not full sentences
            if 3 < len(label.split()) <= 5 and not re.search(r"[.!?]", label):
                skill_groups.append(label)

    if len(skill_groups) < 2:
        skill_groups = [
            "Programming & Engineering",
            "Applied AI & NLP",
            "Analytics & Visualization",
        ]
    # Cap at 5 groups
    skill_groups = skill_groups[:5]
    # Only treat as fixed if the heuristic actually found groups
    # (not if we fell back to the three standard defaults)
    defaults = {
        "Programming & Engineering",
        "Applied AI & NLP",
        "Analytics & Visualization",
    }
    skill_groups_fixed = bool(skill_groups) and set(skill_groups) != defaults

    # Project count
    max_projects = 3
    m = re.search(r"(\d+)\s+project", text_lower)
    if m:
        max_projects = min(int(m.group(1)), 6)

    return FormatParams(
        max_pages         = max_pages,
        max_lines         = _PAGE_LINES.get(max_pages, 65),
        skill_groups      = skill_groups,
        skill_groups_fixed = skill_groups_fixed,
        max_projects      = max_projects,
        project_bullets   = 3,
        exp_bullets_min   = 4,
        exp_bullets_max   = 5,
        summary_sentences = 2,
        raw_notes         = "Inferred from text (LLM parsing unavailable)",
    )
