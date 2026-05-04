"""
Grammar Fixer — fixes grammar and punctuation in resume text fields.

Uses Claude itself to correct grammatical errors, missing commas,
and punctuation issues. Runs AFTER tailoring and BEFORE verification
so the verifier checks the grammar-corrected version.

Fixes applied:
  - Missing commas
  - Grammar errors
  - Hyphen handling:
      KEEP: compound adjectives that are grammatically standard
            (end-to-end, large-scale, two-stage, real-time, state-of-the-art, etc.)
      REMOVE: unnecessary connectors (hands on, multi agent → handled by sanitizer)
  - Full stops at end of skill lines
  - Skills full stop at end if missing
"""

from __future__ import annotations

import logging

from models import TailoredResume

log = logging.getLogger("grammar_fixer")

# Compound adjectives that should KEEP their hyphen — standard English usage
KEEP_HYPHENATED = {
    "end-to-end", "large-scale", "small-scale", "two-stage", "multi-stage",
    "real-time", "state-of-the-art", "high-fidelity", "high-performance",
    "high-quality", "high-stakes", "large-scale", "rule-based", "data-driven",
    "entry-level", "cross-functional", "open-source", "well-defined",
    "long-term", "short-term", "full-stack", "on-demand", "plug-in",
}

GRAMMAR_SYSTEM = """\
You are a professional resume grammar editor. Fix ONLY grammar, punctuation, \
and sentence structure in the text provided. 

Rules:
1. Fix missing commas, incorrect grammar, and awkward phrasing.
2. Keep the EXACT same meaning, facts, and word choices — do not paraphrase.
3. Keep these hyphenated compounds as-is (they are correct):
   end-to-end, large-scale, two-stage, real-time, state-of-the-art,
   high-fidelity, high-performance, data-driven, rule-based, cross-functional.
4. Do NOT change technical terms, names, tools, or any factual content.
5. Keep first-person voice (I built, I engineered, I designed).
6. Output ONLY the corrected text — no explanation, no preamble.
"""


async def fix_grammar(resume: TailoredResume) -> TailoredResume:
    """
    Fix grammar and punctuation in narrative fields.
    Skills get a simpler treatment (full stop enforcement only, no LLM call).
    Returns a new TailoredResume with corrected text.
    """
    import llm_client

    data = resume.model_dump()

    # Fix narrative fields via LLM
    for field in ["summary", "experience", "projects"]:
        val = data.get(field, "") or ""
        if val.strip():
            try:
                fixed = await llm_client.call(
                    system=GRAMMAR_SYSTEM,
                    user=val,
                    expect_json=False,
                )
                data[field] = fixed.strip()
                log.debug(f"Grammar fixed: {field}")
            except Exception as e:
                log.warning(f"Grammar fix skipped for {field}: {e}")

    # Fix skills: ensure each line ends with a full stop
    skills = data.get("skills", "") or ""
    if skills.strip():
        data["skills"] = _fix_skills_punctuation(skills)

    # Fix certifications: ensure each line ends with a full stop
    certs = data.get("certifications", "") or ""
    if certs.strip():
        data["certifications"] = _fix_cert_punctuation(certs)

    return TailoredResume(**data)


def _fix_skills_punctuation(skills: str) -> str:
    """
    Ensure each skill line ends with a full stop.
    'Programming & Engineering: Python, SQL, Apache Spark'
    → 'Programming & Engineering: Python, SQL, Apache Spark.'
    """
    lines = skills.splitlines()
    fixed = []
    for line in lines:
        line = line.rstrip()
        if line and not line.endswith("."):
            line = line + "."
        fixed.append(line)
    return "\n".join(fixed)


def _fix_cert_punctuation(certs: str) -> str:
    """Ensure each certification line ends with a full stop."""
    lines = certs.splitlines()
    fixed = []
    for line in lines:
        line = line.rstrip()
        if line and not line.endswith("."):
            line = line + "."
        fixed.append(line)
    return "\n".join(fixed)
