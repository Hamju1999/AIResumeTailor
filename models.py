"""
Shared data models.
All pipeline stages communicate through these typed structures.
"""

from __future__ import annotations
from enum import Enum
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

# Enums
class JobStatus(str, Enum):
    PENDING   = "pending"
    TAILORING = "tailoring"
    VERIFYING = "verifying"
    VALIDATING = "validating"
    PASSED    = "passed"
    FAILED    = "failed"

# Phase 1-2: Scraping / Extraction 
class RawJob(BaseModel):
    """Exactly what comes off the scraper - nothing more."""
    job_url:     str
    title:       str
    company:     str
    location:    Optional[str] = None
    date_posted: Optional[datetime] = None
    description: str
    board:       str                      # which job board it came from

class Job(RawJob):
    """Deduplicated, cleaned job ready for processing."""
    job_id: str = Field(description="Stable hash of url for dedup")

# Phase 3: Tailored Resume
class TailoredResume(BaseModel):
    """
    Structured resume sections produced by the Tailor Agent.
    The resume_builder converts this into a .docx.
    Fields map 1:1 to the format template sections.
    """
    # Header
    name:          str
    contact:       str           # single line: email · phone · location · linkedin
    target_title:  str           # job title being applied to
    # Body sections (plain text, may include newlines for bullets)
    summary:       str
    skills:        str           # formatted as per template
    experience:    str
    projects:      str
    education:     str
    certifications: Optional[str] = None
    # Metadata - not rendered, used by verifier / validator
    matched_keywords: list[str] = Field(default_factory=list)
    tailoring_notes:  str = ""

# Phase 4: Verification
class VerificationIssue(BaseModel):
    field:       str            # which resume section
    claim:       str            # the specific claim flagged
    reason:      str            # why it's unsupported
    correction:  str            # suggested fix

class VerificationResult(BaseModel):
    passed:      bool
    issues:      list[VerificationIssue] = Field(default_factory=list)
    correction_prompt: str = ""    # injected back into Phase 3 on retry

# Phase 5: Validation
class ValidationIssue(BaseModel):
    category:    str            # grammar | format | length | structure
    description: str
    suggestion:  str

class ValidationResult(BaseModel):
    passed:            bool
    issues:            list[ValidationIssue] = Field(default_factory=list)
    correction_prompt: str = ""

# Phase 6: Output 
class JobResult(BaseModel):
    """Final output entry - one per successfully processed job."""
    job:              Job
    resume:           TailoredResume
    resume_path:      Optional[str] = None   # path to generated .docx
    status:           JobStatus = JobStatus.PASSED
    attempts:         int = 1
    verification:     Optional[VerificationResult] = None
    validation:       Optional[ValidationResult]   = None
    processed_at:     datetime = Field(default_factory=datetime.utcnow)

class FailedJob(BaseModel):
    """Jobs that exhausted all retries."""
    job:         Job
    last_status: JobStatus
    reason:      str
    attempts:    int

class PipelineRun(BaseModel):
    """Top-level manifest written to output/manifest.json."""
    run_id:      str
    started_at:  datetime
    finished_at: Optional[datetime] = None
    total_found: int = 0
    total_passed: int = 0
    total_failed: int = 0
    results:     list[JobResult]  = Field(default_factory=list)
    failures:    list[FailedJob]  = Field(default_factory=list)
