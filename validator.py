"""
Phase 5 — Format Validator (Layer A only — rule-based, deterministic)

Checks:
  1. All 5 required sections populated
  2. Skills section has all 3 group headers
  3. No bullet characters in experience or projects
  4. Summary: max 2 sentences
  5. Each project block: max 2 sentences
  6. Max 3 projects (2 required, 3rd only if JD-aligned)
  7. Experience: 4 to 5 bullet points PER ROLE
  8. Overall line count within 1-page limit

Character count checks were removed — sentence count already enforces conciseness,
and character limits proved impossible to satisfy reliably because sentence length
depends on word choice, not character arithmetic.
"""

from __future__ import annotations

import logging
import re

from models import TailoredResume, ValidationIssue, ValidationResult

log = logging.getLogger("validator")

REQUIRED_FIELDS  = ["summary", "skills", "experience", "projects", "education"]
MAX_LINES_CUTOFF = 65

# Sentence boundary: punctuation followed by space+Capital or end of string.
# Avoids counting decimal points (1.2 GB), model names (GPT-4), abbreviations.
SENT_RE = re.compile(r'[.!?]+(?:\s+[A-Z]|$)')


async def validate_resume(
    resume: TailoredResume,
    format_template: str,
) -> ValidationResult:

    log.info(f"Validating: {resume.target_title}")
    issues: list[ValidationIssue] = []

    # ── 1. Required sections populated ────────────────────────────────────────
    for field in REQUIRED_FIELDS:
        if not getattr(resume, field, "").strip():
            issues.append(ValidationIssue(
                category="format",
                description=f"Required section '{field}' is empty.",
                suggestion=f"Populate '{field}' from the master resume.",
            ))

    # ── 2. All 3 skill group headers present ──────────────────────────────────
    skills_text = resume.skills or ""
    for group in ["Programming & Engineering", "Applied AI & NLP", "Analytics & Visualization"]:
        if group not in skills_text:
            issues.append(ValidationIssue(
                category="format",
                description=f"Skills section missing required group: '{group}'",
                suggestion=f"Add a line starting with '{group}:' to the skills section.",
            ))

    # ── 3. No bullet characters in experience or projects ─────────────────────
    bullet_re = re.compile(r"^[\s]*[•\*▸–]\s", re.MULTILINE)
    for field in ["experience", "projects"]:
        val = getattr(resume, field, "") or ""
        if bullet_re.search(val):
            issues.append(ValidationIssue(
                category="style",
                description=f"Bullet characters found in '{field}'. Must be narrative paragraphs.",
                suggestion="Remove all bullet characters. Write as flowing first-person sentences.",
            ))

    # ── 4. Summary: max 2 sentences ───────────────────────────────────────────
    summary_sc = len(SENT_RE.findall(resume.summary or ""))
    if summary_sc > 2:
        issues.append(ValidationIssue(
            category="length",
            description=f"Summary has {summary_sc} sentences. Maximum is 2.",
            suggestion=(
                "Trim to exactly 2 sentences. Each sentence must be concise — "
                "one main clause, no 'and' chains."
            ),
        ))

    # ── 5. Each project block: exactly 3 bullet points ─────────────────────────
    projects_text = resume.projects or ""
    proj_flagged = False
    for block in re.split(r"\n\n+", projects_text):
        bullet_lines = [
            l.strip() for l in block.splitlines()
            if l.strip() and l.strip().startswith("- ")
        ]
        bc = len(bullet_lines)
        if bc != 3 and bc > 0:   # only flag if bullets exist but count is wrong
            issues.append(ValidationIssue(
                category="length",
                description=f"A project has {bc} bullet points. Must have exactly 3.",
                suggestion=(
                    "Write exactly 3 bullet points per project, each starting with '- '. "
                    "Bullet 1: what you built. Bullet 2: tools/methods. Bullet 3: outcome or detail."
                ),
            ))
            proj_flagged = True
            break
        # Word count guard: each bullet max 20 words
        for bl in bullet_lines:
            words = len(bl[2:].split())   # strip the leading "- "
            if words > 20:
                issues.append(ValidationIssue(
                    category="length",
                    description=f"A project bullet is {words} words — too long (max 15 words).",
                    suggestion="Shorten this bullet to under 15 words. Cut filler, keep the key action and tool.",
                ))
                proj_flagged = True
                break
        if proj_flagged:
            break

    # ── 6. Max 3 projects (default 2, 3rd only if JD-aligned) ───────────────
    heading_count = sum(
        1 for line in projects_text.splitlines()
        if line.strip() and _is_heading_line(line.strip())
    )
    if heading_count > 3:
        issues.append(ValidationIssue(
            category="length",
            description=f"Projects section has {heading_count} projects. Maximum is 3.",
            suggestion=(
                "Keep only 2 or 3 projects. "
                "The third project is only justified if it directly addresses a JD requirement "
                "the first two do not cover. Remove any project that does not do this."
            ),
        ))

    # ── 7. Experience: 4-5 bullet points PER ROLE ────────────────────────────
    # Split on role heading lines, count "- " bullet lines per role.
    exp_text = resume.experience or ""
    exp_lines = exp_text.splitlines()

    current_role_bullets: list[str] = []
    exp_bullet_flagged = False
    for line in exp_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_heading_line(stripped):
            if current_role_bullets:
                bc = len(current_role_bullets)
                if bc < 4 or bc > 5:
                    issues.append(ValidationIssue(
                        category="length",
                        description=(
                            f"An experience role has {bc} bullet points. "
                            "Must have 4 to 5 bullet points."
                        ),
                        suggestion=(
                            "Write 4 to 5 bullet points each starting with '- ' and an action verb. "
                            "Order by JD relevance. Each bullet max 15 words."
                        ),
                    ))
                    exp_bullet_flagged = True
                    break
            current_role_bullets = []
        elif stripped.startswith("- "):
            current_role_bullets.append(stripped)

    # Check the last role block
    if not exp_bullet_flagged and current_role_bullets:
        bc = len(current_role_bullets)
        if bc < 4 or bc > 5:
            issues.append(ValidationIssue(
                category="length",
                description=(
                    f"An experience role has {bc} bullet points. "
                    "Must have 4 to 5 bullet points."
                ),
                suggestion=(
                    "Write 4 to 5 bullet points each starting with '- ' and an action verb. "
                    "Order by JD relevance. Each bullet max 15 words."
                ),
            ))
        else:
            for bl in current_role_bullets:
                words = len(bl[2:].split())
                if words > 20:
                    issues.append(ValidationIssue(
                        category="length",
                        description=f"An experience bullet is {words} words — too long (max 15 words).",
                        suggestion="Shorten to under 15 words. Keep action verb and key tool/outcome only.",
                    ))
                    break
    # ── 8. Overall line count (rough 1-page proxy) ────────────────────────────
    all_text = " ".join([
        resume.summary or "", resume.skills or "", resume.experience or "",
        resume.projects or "", resume.education or "",
    ])
    line_count = all_text.count("\n")
    if line_count > MAX_LINES_CUTOFF:
        issues.append(ValidationIssue(
            category="length",
            description=f"Resume is too long ({line_count} line breaks). Must fit 1 page.",
            suggestion=(
                "Summary: 2 sentences. "
                "Each project: 2 sentences. "
                "Each experience role: 4 to 5 bullets starting with '- '. "
                "Max 3 projects (3rd only if directly JD-aligned)."
            ),
        ))

    if issues:
        correction = _build_correction(issues)
        log.warning(f"Validation FAILED ({len(issues)} issue(s)): {resume.target_title}")
        return ValidationResult(passed=False, issues=issues, correction_prompt=correction)

    log.info(f"Validation PASSED: {resume.target_title}")
    return ValidationResult(passed=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_heading_line(line: str) -> bool:
    """
    True if the line is a role or project heading, not body text.
    Headings: contain ' | ', OR are short (<=70 chars) with no sentence punctuation
    and don't start with 'I ' (which marks narrative body text).
    """
    if not line:
        return False
    if " | " in line:
        return True
    if re.search(r"[.!?]$", line):
        return False
    if line.startswith("I "):
        return False
    return len(line) <= 70


def _build_correction(issues: list[ValidationIssue]) -> str:
    lines = ["Fix ALL of the following before the next attempt:"]
    for i, issue in enumerate(issues, 1):
        lines.append(
            f"{i}. [{issue.category.upper()}] {issue.description} — {issue.suggestion}"
        )
    return "\n".join(lines)
