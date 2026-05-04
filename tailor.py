"""
Phase 3 — Resume Tailor Agent

Takes one Job + master resume + format template and returns a TailoredResume.
Accepts optional correction notes on retry attempts.
"""

from __future__ import annotations

import logging

import llm_client
import prompts
from models import Job, TailoredResume

log = logging.getLogger("tailor")


async def tailor_resume(
    job: Job,
    master_resume: str,
    format_template: str,
    correction_notes: str = "",
    fmt=None,
) -> TailoredResume:
    """
    Call the Tailor Agent and parse the result into a TailoredResume.
    Raises on JSON parse failure — let the pipeline handle retries.
    """
    log.info(f"Tailoring: {job.title} @ {job.company}")

    user_msg = prompts.tailor_user(
        master_resume=master_resume,
        job_description=job.description,
        company=job.company,
        job_title=job.title,
        format_template=format_template,
        correction_notes=correction_notes,
    )

    data = await llm_client.call(
        system=prompts.get_tailor_system(fmt),
        user=user_msg,
        expect_json=True,
    )

    return TailoredResume(
        name=data.get("name", ""),
        contact=data.get("contact", ""),
        target_title=data.get("target_title", job.title),
        summary=data.get("summary", ""),
        skills=data.get("skills", ""),
        experience=data.get("experience", ""),
        projects=data.get("projects", ""),
        education=data.get("education", ""),
        certifications=data.get("certifications"),
        matched_keywords=data.get("matched_keywords", []),
        tailoring_notes=data.get("tailoring_notes", ""),
    )
