"""
Calibration Layer — runs after grammar fix, before verification.

Four controls implemented dynamically (no hardcoded word lists):
  1. Entry-level mode  — detects and downgrades senior-scope language by property
  2. De-abstraction    — detects and simplifies abstract/jargon language by property
  3. Credibility filter — detects and grounds unrealistic claims by property
  4. ATS layer         — natural keyword presence without stuffing
"""

from __future__ import annotations

import logging
from models import TailoredResume

log = logging.getLogger("calibrator")

CALIBRATION_SYSTEM = """\
You are a resume calibration editor for entry-level and internship candidates.
Your job is to apply four calibration controls using JUDGMENT, not a fixed word list.
For each control, you are given the PROPERTY that makes language problematic —
detect any word or phrase that has that property and fix it accordingly.
Change ONLY wording. Never change facts, tools, dates, numbers, or content selection.
Output ONLY valid JSON with keys: summary, experience, projects.

========================================================================
CONTROL 1 — ENTRY-LEVEL SCOPE DETECTION
========================================================================
PROPERTY TO DETECT: Any verb or phrase that implies the candidate had
complete ownership, strategic authority, or senior-level responsibility
for an entire system in production — which is not credible for a 6-month
intern or a student project.

HOW TO IDENTIFY IT:
  Ask: "Would a hiring manager believe a 6-month intern said this?"
  If the answer is no or maybe not → it needs to be downgraded.

HOW TO FIX IT:
  Replace with a verb that describes the specific action the candidate
  actually performed. The replacement must describe WHAT was built or done,
  not the seniority level of the person doing it.
  
  PRINCIPLE: Same contribution, lower claimed authority.
  The work was real. The scope claim is inflated. Fix the claim, keep the work.

  Examples of the PROPERTY (not a complete list — detect any word with this property):
  - Verbs that imply full executive or senior ownership of a system
  - Phrases that imply the candidate was directing a team or strategy
  - Language that sounds like a CTO or senior architect wrote it
  - Any phrase where the verb makes the action sound larger than the task itself

========================================================================
CONTROL 2 — ABSTRACTION AND JARGON DETECTION
========================================================================
PROPERTY TO DETECT: Any word or phrase where a recruiter with general
technical knowledge (not deep AI specialization) would need to pause
and decode what it means before understanding what was actually built.

HOW TO IDENTIFY IT:
  Ask: "If I removed this word and described what the system actually DOES
  in plain English, would the sentence be clearer?"
  If yes → the word is too abstract and needs to be replaced.

HOW TO FIX IT:
  Describe what the system DOES, not what it IS CALLED or what PATTERN it uses.
  Replace architectural labels with functional descriptions.
  Replace technology jargon with what the technology did in this context.

  PRINCIPLE: Name the action and outcome. Do not name the pattern or paradigm.

  Examples of the PROPERTY (not a complete list — detect any word with this property):
  - Architecture pattern names used as nouns ("framework", "orchestration layer",
    "agentic workflow", "multi-agent system") without describing what they do
  - AI/ML jargon that names a technique without saying what it achieved
  - Compound technical labels that obscure the underlying action
  - Any noun that names a category of system rather than describing a specific system

SUMMARY-SPECIFIC RULE:
  The summary must pass this test: can a recruiter understand in one reading
  exactly what this person built and what tools they used?
  If the summary contains abstract architectural terms or AI paradigm labels
  that require specialist knowledge to decode, replace them with plain descriptions.

========================================================================
CONTROL 3 — CREDIBILITY AND SCOPE CALIBRATION
========================================================================
PROPERTY TO DETECT: Any outcome claim, result metric, or scope description
that would be difficult to believe for work completed during a 6-month
internship or a university course project.

HOW TO IDENTIFY IT:
  Ask: "Is this claim believable given that this is an intern or student project?"
  Ask: "Is this outcome specifically stated in the original, or was it inferred?"
  If a metric was not in the original text, it should not appear in the output.
  If the claim implies production-scale impact without supporting context, soften it.

HOW TO FIX IT:
  - Keep all real numbers from the original (record counts, file counts, AIC values).
  - Remove or soften outcome claims that were not explicitly in the original.
  - Add internship context to bullets that sound like senior production work.
  - Describe HOW a result was achieved, not just THAT it was achieved.
    This makes the claim concrete and therefore more credible.

  PRINCIPLE: Specific + concrete = credible. Vague + grand = not credible.
  "Built a Tesseract pipeline to extract data from 300 shipping PDFs" is
  more credible than "Engineered a production-grade OCR extraction system."

CONTROL 3b — OUTCOME AND BUSINESS LANGUAGE INJECTION:
For every bullet that describes an action without any result, add a brief outcome.
Rules:
  a) If a bullet ends with what was built but not why it mattered, append the
     business consequence. Use language the business cares about:
     time saved, errors reduced, process automated, team unblocked, data made reliable.
  b) Translate technical actions into business outcomes where the master resume supports it:
     "consolidated 300+ Excel workbooks" → "...reducing manual reconciliation time"
     "built OCR pipeline" → "...replacing a manual 3-day process"
     "designed LLM validation framework" → "...reducing data entry errors in business-critical records"
  c) Only add outcomes that are plausible given the described work and scope.
     Do not invent specific percentages or dollar figures not in the original text.
  d) Outcome language should be plain: "saving X hours", "reducing errors",
     "enabling faster reporting" — not corporate buzzwords.
  e) Every bullet should answer: "so what?" If it doesn't, fix it.

CONTROL 3c — TOOL AND PLATFORM VISIBILITY:
Ensure modern tools appear naturally in bullets when the work used them.
  a) If cloud platforms (AWS S3, GCP, Azure) are mentioned in the experience
     or projects, ensure at least one bullet per section names the specific service.
  b) If AI tools (specific LLM APIs, OpenRouter, LangChain) were used, name them
     in the relevant bullet — not just in the skills section.
  c) If BI or data warehouse tools appear in the master resume, surface them
     in context: "queried via SQL on Snowflake" not just "used SQL".

========================================================================
CONTROL 4 — ATS NATURAL KEYWORD INTEGRATION
========================================================================
PROPERTY TO DETECT: Missing technical keywords that recruiters and ATS
systems scan for, OR keyword stuffing where the same term appears so many
times it reads as a list rather than natural work description.

HOW TO IDENTIFY IT:
  - Check the MATCHED KEYWORDS list provided. Each must appear at least once.
  - Check whether any term appears more than twice in the combined text.
  - Check whether keywords are appended (in brackets, parentheses at line end)
    rather than woven into the description of the work itself.

HOW TO FIX IT:
  - If a keyword is absent: revise ONE bullet to naturally include it as part
    of describing what was done.
  - If a keyword is stuffed: reduce to the most meaningful occurrence and
    remove redundant repetitions.
  - Keywords must describe the actual work, not be appended for scanning.

========================================================================
SKILLS LINE RULES (applies to skills field if it contains issues)
========================================================================
PROPERTY TO DETECT: Skill lines that are too dense to scan in 6 seconds,
or that list sub-techniques at a granularity that adds noise without signal.

HOW TO FIX IT:
  - Prompt engineering techniques (chain-of-thought, few-shot, guardrails,
    negative constraint, and similar sub-techniques) should be collapsed into
    "Prompt Engineering" — one term representing the category.
  - Maximum 6 items per skill group line.
  - Each line ends with a full stop.

========================================================================
OUTPUT FORMAT
========================================================================
Return ONLY this JSON — no preamble, no explanation, no markdown fences:
{
  "summary":    "<calibrated — 2 sentences, each ≤22 words, passes the 6-second test>",
  "experience": "<calibrated — same bullet structure with '- ' prefix, each bullet ≤20 words>",
  "projects":   "<calibrated — same bullet structure with '- ' prefix, each bullet ≤20 words>"
}
"""


async def calibrate(
    resume: TailoredResume,
    job_description: str = "",
) -> TailoredResume:
    """
    Apply the calibration layer to summary, experience, and projects.
    Skills are calibrated rule-based (collapsing sub-techniques, capping items).
    Returns a new TailoredResume with calibrated text.
    """
    import llm_client

    user_msg = f"""\
MATCHED KEYWORDS (must each appear naturally at least once in the output):
{', '.join(resume.matched_keywords or [])}

CURRENT SUMMARY:
{resume.summary or ""}

CURRENT EXPERIENCE:
{resume.experience or ""}

CURRENT PROJECTS:
{resume.projects or ""}

Apply all four controls using the property-based detection rules.
Return only the JSON.\
"""

    try:
        data = await llm_client.call(
            system=CALIBRATION_SYSTEM,
            user=user_msg,
            expect_json=True,
        )

        updated = resume.model_dump()
        for field in ["summary", "experience", "projects"]:
            val = data.get(field, "").strip()
            if val:
                updated[field] = val

        # Rule-based skills calibration — no LLM call needed
        if updated.get("skills"):
            updated["skills"] = _calibrate_skills(updated["skills"])

        log.info("Calibration applied")
        return TailoredResume(**updated)

    except Exception as e:
        log.warning(f"Calibration skipped (resume unchanged): {e}")
        return resume


def _calibrate_skills(skills: str) -> str:
    """
    Rule-based skills cleanup.
    Collapses prompt engineering sub-techniques (any level of specificity)
    into the parent category "Prompt Engineering".
    Caps each group at 6 items. Ensures full stop at line end.
    """
    import re

    # Detect any prompt engineering sub-technique by property:
    # short technique names inside parentheses after "Prompt Engineering",
    # or listed as standalone items that are sub-methods of prompting.
    # Rather than listing them, detect by pattern: short (1-3 word) technique
    # names that appear inside parentheses following "Prompt Engineering".
    pe_parens = re.compile(
        r"Prompt Engineering\s*\([^)]+\)",
        re.IGNORECASE,
    )

    lines = skills.splitlines()
    calibrated = []
    for line in lines:
        line = line.rstrip()
        if not line:
            continue

        # Collapse "Prompt Engineering (sub, techniques, here)" → "Prompt Engineering"
        cleaned = pe_parens.sub("Prompt Engineering", line)

        # Clean up comma artifacts
        cleaned = re.sub(r",\s*,", ",", cleaned)
        cleaned = re.sub(r",\s*\.", ".", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

        # Cap at 6 items per group line
        if ":" in cleaned:
            label, _, items_str = cleaned.partition(":")
            items = [i.strip() for i in items_str.rstrip(".").split(",") if i.strip()]
            if len(items) > 6:
                items = items[:6]
            cleaned = f"{label.strip()}: {', '.join(items)}."

        if not cleaned.endswith("."):
            cleaned += "."

        calibrated.append(cleaned)

    return "\n".join(calibrated)
