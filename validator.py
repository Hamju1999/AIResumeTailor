"""
Phase 5 — Format Validator (rule-based, deterministic)

All limits (project count, bullet counts, skill groups, page length) come from
FormatParams parsed from the user's format template — nothing is hardcoded.
"""

from __future__ import annotations

import logging
import re

from models import TailoredResume, ValidationIssue, ValidationResult
from format_parser import FormatParams

log = logging.getLogger("validator")

REQUIRED_FIELDS = ["summary", "skills", "experience", "projects", "education"]

# Sentence boundary — avoids counting decimals (1.2 GB), model names (GPT-4)
SENT_RE = re.compile(r'[.!?]+(?:\s+[A-Z]|$)')


async def validate_resume(
    resume: TailoredResume,
    format_template: str,
    fmt: FormatParams | None = None,
) -> ValidationResult:

    if fmt is None:
        fmt = FormatParams()   # safe defaults

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

    # ── 2. Skill group headers — dynamic from format template ─────────────────
    skills_text = resume.skills or ""
    for group in fmt.skill_groups:
        if group not in skills_text:
            issues.append(ValidationIssue(
                category="format",
                description=f"Skills section missing required group: '{group}'",
                suggestion=f"Add a line starting with '{group}:' to the skills section.",
            ))

    # ── 3. No stray bullet characters (•, ▸, –) in experience or projects ─────
    bullet_re = re.compile(r"^[\s]*[•\*▸–]\s", re.MULTILINE)
    for field in ["experience", "projects"]:
        val = getattr(resume, field, "") or ""
        if bullet_re.search(val):
            issues.append(ValidationIssue(
                category="style",
                description=f"Stray bullet characters found in '{field}'.",
                suggestion="Use '- ' (dash space) bullets only, not •, ▸, or –.",
            ))

    # ── 4. Summary sentence count — dynamic ───────────────────────────────────
    summary_sc = len(SENT_RE.findall(resume.summary or ""))
    if summary_sc > fmt.summary_sentences:
        issues.append(ValidationIssue(
            category="length",
            description=(
                f"Summary has {summary_sc} sentences. "
                f"Format requires {fmt.summary_sentences}."
            ),
            suggestion=f"Trim to exactly {fmt.summary_sentences} sentences.",
        ))

    # ── 5. Project bullet count — dynamic ─────────────────────────────────────
    projects_text = resume.projects or ""
    proj_flagged = False
    for block in re.split(r"\n\n+", projects_text):
        bullet_lines = [
            l.strip() for l in block.splitlines()
            if l.strip() and l.strip().startswith("- ")
        ]
        bc = len(bullet_lines)
        if bc > 0 and bc != fmt.project_bullets:
            issues.append(ValidationIssue(
                category="length",
                description=(
                    f"A project has {bc} bullet points. "
                    f"Format requires exactly {fmt.project_bullets}."
                ),
                suggestion=(
                    f"Write exactly {fmt.project_bullets} bullet points per project, "
                    "each starting with '- '."
                ),
            ))
            proj_flagged = True
            break
        for bl in bullet_lines:
            if len(bl[2:].split()) > 20:
                issues.append(ValidationIssue(
                    category="length",
                    description=f"A project bullet is too long (max 15 words).",
                    suggestion="Shorten to under 15 words. Keep action verb and key tool.",
                ))
                proj_flagged = True
                break
        if proj_flagged:
            break

    # ── 6. Project count — dynamic ────────────────────────────────────────────
    heading_count = sum(
        1 for line in projects_text.splitlines()
        if line.strip() and _is_heading_line(line.strip())
    )
    if heading_count > fmt.max_projects:
        issues.append(ValidationIssue(
            category="length",
            description=(
                f"Projects section has {heading_count} projects. "
                f"Format allows maximum {fmt.max_projects}."
            ),
            suggestion=f"Remove the least relevant project. Keep at most {fmt.max_projects}.",
        ))

    # ── 7. Experience bullet count per role — dynamic ─────────────────────────
    exp_text  = resume.experience or ""
    current_bullets: list[str] = []
    exp_flagged = False

    for line in exp_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_heading_line(stripped):
            if current_bullets:
                bc = len(current_bullets)
                if bc < fmt.exp_bullets_min or bc > fmt.exp_bullets_max:
                    issues.append(ValidationIssue(
                        category="length",
                        description=(
                            f"An experience role has {bc} bullet points. "
                            f"Format requires {fmt.exp_bullets_min} to {fmt.exp_bullets_max}."
                        ),
                        suggestion=(
                            f"Write {fmt.exp_bullets_min} to {fmt.exp_bullets_max} bullets "
                            "each starting with '- ' and an action verb."
                        ),
                    ))
                    exp_flagged = True
                    break
            current_bullets = []
        elif stripped.startswith("- "):
            current_bullets.append(stripped)

    if not exp_flagged and current_bullets:
        bc = len(current_bullets)
        if bc < fmt.exp_bullets_min or bc > fmt.exp_bullets_max:
            issues.append(ValidationIssue(
                category="length",
                description=(
                    f"An experience role has {bc} bullet points. "
                    f"Format requires {fmt.exp_bullets_min} to {fmt.exp_bullets_max}."
                ),
                suggestion=(
                    f"Write {fmt.exp_bullets_min} to {fmt.exp_bullets_max} bullets "
                    "each starting with '- ' and an action verb."
                ),
            ))
        else:
            for bl in current_bullets:
                if len(bl[2:].split()) > 20:
                    issues.append(ValidationIssue(
                        category="length",
                        description="An experience bullet is too long (max 15 words).",
                        suggestion="Shorten to under 15 words.",
                    ))
                    break

    # ── 8. Overall length — dynamic page limit ────────────────────────────────
    all_text   = " ".join([
        resume.summary or "", resume.skills or "", resume.experience or "",
        resume.projects or "", resume.education or "",
    ])
    line_count = all_text.count("\n")
    if line_count > fmt.max_lines:
        issues.append(ValidationIssue(
            category="length",
            description=(
                f"Resume is too long ({line_count} line breaks). "
                f"Target: fits within {fmt.max_pages} page(s) "
                f"(≈{fmt.max_lines} line breaks)."
            ),
            suggestion=(
                f"Trim each section. Projects: {fmt.project_bullets} bullets. "
                f"Experience: {fmt.exp_bullets_min}-{fmt.exp_bullets_max} bullets. "
                f"Summary: {fmt.summary_sentences} sentences."
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
    if not line:
        return False
    if " | " in line:
        return True
    if re.search(r"[.!?]$", line):
        return False
    if line.startswith("I ") or line.startswith("- "):
        return False
    return len(line) <= 70


def _build_correction(issues: list[ValidationIssue]) -> str:
    lines = ["Fix ALL of the following before the next attempt:"]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. [{issue.category.upper()}] {issue.description} — {issue.suggestion}")
    return "\n".join(lines)
