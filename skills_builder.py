"""
skills_builder.py
=================
Rebuilds the Technical Skills section so it reflects the FULL skill set of the
picked projects and experience, as documented in the MASTER resume - not just the
few skills that survived compression into the tailored bullets, and not the global
skills inventory (which lists everything regardless of what was picked).

Design (honesty by input-scoping):
  1. Identify the picked project names and experience role headers from the resume.
  2. Locate each one's section in the master (robust header detection that tolerates
     hyphens / mixed-case parentheticals; token-overlap matching).
  3. Concatenate ONLY those picked sections into a scoped evidence block.
  4. Ask the LLM to extract + group the skills used in that block, under the format's
     group headings. Because the input contains only picked work, skills from
     unpicked projects (e.g. Apache Spark, PCA) cannot appear - no instruction needed.
  5. Deterministic backstop: drop any emitted skill not present in the evidence block.

The skills field is replaced in place. On any failure the original skills survive.
"""
from __future__ import annotations
import logging
import re

import llm_client

log = logging.getLogger("skills_builder")

# Light stopword set so distinctive tokens (labelmaster, restail, heart, failure)
# drive matching rather than generic words (data, analysis, project).
_STOP = {
    "the", "and", "for", "with", "using", "via", "data", "analysis", "analytics",
    "project", "projects", "system", "app", "application", "model", "modeling",
    "pipeline", "intern", "department", "inc", "llc", "chicago", "uae", "usa",
}


# --------------------------------------------------------------------------- #
# Master parsing
# --------------------------------------------------------------------------- #
def _is_allcaps_header(s: str) -> bool:
    """All-caps lead before any '(' or '|'. Tolerates hyphens, so 'HEART-FAILURE
    RISK ANALYSIS (Statistical Modeling)' and 'DATA SCIENCE INTERN | Labelmaster'
    are both detected."""
    head = re.split(r"[(|]", s, 1)[0]
    letters = [c for c in head if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _is_title_header(s: str) -> bool:
    """Title-case header with a parenthetical, e.g. 'TidyClust (Extending Spark ML
    Clustering)' or 'Engram (Long-Term Context Engine for AI Models)'."""
    return bool(s) and s[:1].isupper() and "(" in s


def _parse_sections(master: str) -> list[tuple[str, str]]:
    """Split the master into (header, body) sections. A header is a short,
    non-indented, non-bullet line that is either all-caps, a '=== divider ===',
    or a title-case line with a parenthetical immediately followed by a bullet.
    The bullet-lookahead prevents prose lines with parentheses from false-splitting."""
    lines = master.splitlines()
    n = len(lines)
    sections: list[tuple[str, str]] = []
    cur_head: str | None = None
    cur_body: list[str] = []

    def _bullet_follows(idx: int) -> bool:
        seen = 0
        for j in range(idx + 1, n):
            nxt = lines[j].strip()
            if not nxt:
                continue
            seen += 1
            if nxt.startswith("-") or nxt.startswith("•"):
                return True
            if seen >= 2:
                return False
        return False

    for i, line in enumerate(lines):
        s = line.strip()
        indented = line[:1] in (" ", "\t")
        is_bullet = s.startswith("-") or s.startswith("•")
        header = False
        if s and not indented and not is_bullet and len(s) <= 90:
            if s.startswith("===") or _is_allcaps_header(s):
                header = True
            elif _is_title_header(s) and _bullet_follows(i):
                header = True
        if header:
            if cur_head is not None:
                sections.append((cur_head, "\n".join(cur_body)))
            cur_head, cur_body = s, []
        else:
            cur_body.append(line)
    if cur_head is not None:
        sections.append((cur_head, "\n".join(cur_body)))
    return sections


_MONTHS = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec", "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
}


def _tokens(s: str) -> set[str]:
    """Distinctive tokens for matching. Drops stopwords, month names, and pure
    numbers (years) so date ranges in role headers don't dilute the overlap score
    (e.g. 'Labelmaster ... | May 2025 - Aug 2025' still matches its master section)."""
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return {
        t for t in s.split()
        if len(t) > 2 and not t.isdigit() and t not in _STOP and t not in _MONTHS
    }


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# --------------------------------------------------------------------------- #
# Picked-item extraction + matching
# --------------------------------------------------------------------------- #
def _name_lines(section_text: str) -> list[str]:
    """Header/name lines in a resume section = non-blank, non-bullet lines."""
    out = []
    for ln in (section_text or "").splitlines():
        s = ln.strip().rstrip(":")
        if s and not s.startswith("-") and not s.startswith("•"):
            out.append(s)
    return out


def _match_section(picked_name: str, sections: list[tuple[str, str]]) -> str | None:
    """Return the body of the master section best matching a picked item name,
    by token overlap. Requires at least half the picked tokens to match."""
    want = _tokens(picked_name)
    if not want:
        return None
    best_body, best_score = None, 0.0
    for head, body in sections:
        have = _tokens(head)
        if not have:
            continue
        score = len(want & have) / len(want)
        if score > best_score:
            best_score, best_body = score, body
    return best_body if best_score >= 0.5 else None


def _gather_evidence(resume, master: str) -> tuple[str, list[str]]:
    """Collect the master bodies for every picked project and experience role.
    Returns (evidence_text, matched_names)."""
    sections = _parse_sections(master)
    picked = _name_lines(resume.projects) + _name_lines(resume.experience)
    bodies, matched = [], []
    for name in picked:
        body = _match_section(name, sections)
        if body:
            bodies.append(f"### {name}\n{body}")
            matched.append(name)
        else:
            log.warning(f"No master section matched picked item: {name!r}")
    return "\n\n".join(bodies), matched


# --------------------------------------------------------------------------- #
# Honesty backstop
# --------------------------------------------------------------------------- #
def _supported(term: str, evidence_norm: str) -> bool:
    t = _norm(term)
    if len(t) < 2:
        return False
    if t in evidence_norm:
        return True
    if t.endswith("s") and t[:-1] in evidence_norm:  # crude plural
        return True
    return False


def _filter_to_evidence(groups: dict, evidence: str) -> dict:
    """Drop any emitted skill (and parenthetical sub-item) absent from the
    picked-section evidence. This guarantees honesty even if the LLM strays."""
    ev = _norm(evidence)
    out: dict[str, list[str]] = {}
    for group, items in groups.items():
        kept = []
        for item in items:
            m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", str(item).strip())
            if m:
                head = m.group(1).strip()
                subs = [s.strip() for s in m.group(2).split(",") if s.strip()]
                if not _supported(head, ev):
                    continue
                ksubs = [s for s in subs if _supported(s, ev)]
                kept.append(f"{head} ({', '.join(ksubs)})" if ksubs else head)
            elif _supported(str(item), ev):
                kept.append(str(item).strip())
        if kept:
            out[group] = kept
    return out


def _assemble(groups: dict, cap: int = 6) -> str:
    lines = []
    for group, items in groups.items():
        if not items:
            continue
        items = items[:cap]
        lines.append(f"{group}: {', '.join(items)}.")
    return "\n".join(lines)


def _existing_group_labels(skills: str) -> list[str]:
    """The group labels the tailor already chose (field-appropriate), parsed from
    the current skills field: each line is 'Label: items.'."""
    labels = []
    for line in (skills or "").splitlines():
        line = line.strip()
        if ":" in line:
            lbl = line.split(":", 1)[0].strip()
            if lbl:
                labels.append(lbl)
    return labels


# --------------------------------------------------------------------------- #
# Prompt + entry point
# --------------------------------------------------------------------------- #
_SYSTEM = """\
You build the Technical Skills section of a resume.
You are given the FULL descriptions of ONLY the projects and work experience that
were selected for this resume, plus the exact skill-group headings to use.

RULES - any violation is rejected:
1. List ONLY skills, tools, libraries, languages, methods, and techniques that are
   explicitly named or unambiguously used in the SELECTED DESCRIPTIONS below.
2. Never add a skill that is not in the descriptions, even if it is common or implied.
3. Use the skill's own name as written in the descriptions.
4. Group skills under EXACTLY the provided headings - do not rename, add, or drop a heading.
5. Within each group, order by relevance to the job description, most relevant first.
6. A skill belongs in at most one group. Do not pad. Quality over quantity.
7. Output ONLY valid JSON, no preamble, no fences:
   {"groups": {"<Heading One>": ["skill", "skill"], "<Heading Two>": ["skill"]}}
"""


async def build_skills(resume, master: str, fmt, job_description: str = ""):
    """Rebuild resume.skills from the master descriptions of the picked items.
    Returns a new skills string, or the original on any failure."""
    evidence, matched = _gather_evidence(resume, master)
    if not evidence:
        log.warning("Skills rebuild skipped: no picked sections matched in master")
        return resume.skills

    # Heading source: if the format FIXES the groups, honor them. Otherwise use the
    # field-appropriate groups the tailor already generated (so a medical, architecture,
    # or any-field resume keeps its own group names, not the data-science defaults).
    if getattr(fmt, "skill_groups_fixed", False) and getattr(fmt, "skill_groups", None):
        headings = list(fmt.skill_groups)
    else:
        headings = _existing_group_labels(resume.skills) or list(getattr(fmt, "skill_groups", []) or [])
    heading_block = "\n".join(f"- {h}" for h in headings) if headings else "- Technical Skills"

    user = (
        f"SKILL-GROUP HEADINGS (use exactly these):\n{heading_block}\n\n"
        f"JOB DESCRIPTION (for ordering only):\n{job_description[:2000]}\n\n"
        f"SELECTED DESCRIPTIONS (the only allowed source of skills):\n---\n{evidence}\n---\n\n"
        f"Return only the JSON."
    )
    try:
        data = await llm_client.call(system=_SYSTEM, user=user, expect_json=True)
        groups = data.get("groups", {}) or {}
        if not isinstance(groups, dict) or not groups:
            log.warning("Skills rebuild skipped: empty LLM result")
            return resume.skills
        groups = _filter_to_evidence(groups, evidence)   # honesty backstop
        result = _assemble(groups)
        if not result.strip():
            log.warning("Skills rebuild skipped: nothing survived evidence filter")
            return resume.skills
        log.info(f"Skills rebuilt from {len(matched)} picked section(s)")
        return result
    except Exception as e:
        log.warning(f"Skills rebuild skipped ({type(e).__name__}): {e}")
        return resume.skills
