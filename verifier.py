"""
Phase 4 - Hallucination Verifier + JD Alignment Checker

Part A: Cross-checks every factual claim against the master resume.
Part B: Verifies that the resume is genuinely tailored to the job description
        (summary is specific, projects are relevant, experience leads with the
        right aspect, skills are ordered by JD relevance).
Returns a VerificationResult with pass/fail and structured issues.
"""

from __future__ import annotations

import logging

import llm_client
import prompts
from models import TailoredResume, VerificationIssue, VerificationResult

log = logging.getLogger("verifier")


async def verify_resume(
    resume: TailoredResume,
    master_resume: str,
    job_description: str = "",
) -> VerificationResult:
    """
    Call the Verifier Agent with the tailored resume JSON, master resume,
    and job description. Returns a VerificationResult.
    """
    log.info(f"Verifying: {resume.target_title}")

    resume_json = resume.model_dump_json(
        indent=2, exclude={"matched_keywords", "tailoring_notes"}
    )

    user_msg = prompts.verifier_user(
        tailored_resume_json=resume_json,
        master_resume=master_resume,
        job_description=job_description,
    )

    data = await llm_client.call(
        system=prompts.VERIFIER_SYSTEM,
        user=user_msg,
        expect_json=True,
    )

    passed     = bool(data.get("passed", False))
    raw_issues = data.get("issues", [])

    issues = [
        VerificationIssue(
            field=i.get("field", "unknown"),
            claim=i.get("claim", ""),
            reason=i.get("reason", ""),
            correction=i.get("correction", ""),
        )
        for i in raw_issues
        if isinstance(i, dict)
    ]

    correction_prompt = data.get("correction_prompt", "")

    if not passed:
        log.warning(f"Verification FAILED ({len(issues)} issue(s)): {resume.target_title}")
        for issue in issues:
            log.debug(f"  [{issue.field}] {issue.claim!r} - {issue.reason}")

    return VerificationResult(
        passed=passed,
        issues=issues,
        correction_prompt=correction_prompt,
    )
