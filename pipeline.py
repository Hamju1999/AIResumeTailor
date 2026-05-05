"""
Pipeline Orchestrator - fixed:
  1. run_id properly shared so resume paths are correct
  2. Sequential job processing (semaphore=1) to respect 30k tokens/min rate limit
  3. Inter-job delay between LLM calls
  4. Zip looks in the right folder
"""

from __future__ import annotations

import asyncio
import csv
import logging
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import config
import scraper
import tailor
import verifier
import validator
from models import (
    FailedJob, Job, JobResult, JobStatus, PipelineRun, TailoredResume,
)
from resume_builder import build_docx
import format_parser
from format_parser import FormatParams
from grammar_fixer import fix_grammar
from calibrator import calibrate

log = logging.getLogger("pipeline")

_master_resume:   str = ""
_format_template: str = ""
_run_id:          str = ""   # set once in run(), read everywhere


# ── Content loading ───────────────────────────────────────────────────────────

async def load_content() -> None:
    global _master_resume, _format_template

    for attr, path in [("_master_resume", config.MASTER_RESUME_PATH),
                       ("_format_template", config.FORMAT_TEMPLATE_PATH)]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"{attr} file not found: {p}")
        globals()[attr] = _load_file(p)

    log.info(f"Master resume loaded ({len(_master_resume):,} chars)")
    log.info(f"Format template loaded ({len(_format_template):,} chars)")
    # Parse format template to extract dynamic parameters
    global _format_params
    _format_params = await format_parser.parse(_format_template)


def _load_file(p: Path) -> str:
    if p.suffix.lower() == ".pdf":
        import pdf_reader
        return pdf_reader.extract_text(p)
    return p.read_text(encoding="utf-8").strip()


# ── Main entry point ──────────────────────────────────────────────────────────

async def run() -> PipelineRun:
    global _run_id
    await load_content()

    _run_id = uuid.uuid4().hex[:8]
    started = datetime.utcnow()

    log.info(f"=== Pipeline run {_run_id} started ===")

    # Phase 1+2
    jobs: list[Job] = await scraper.discover_jobs()
    log.info(f"Processing {len(jobs)} jobs through Phases 3-5 ...")

    # Phase 3-5: SEQUENTIAL - one job at a time to respect 30k tokens/min limit.
    # Each job makes 3 LLM calls × ~10k tokens = ~30k tokens. Running in parallel
    # blows the rate limit immediately. Sequential with a small inter-job pause
    # keeps us under the limit without throttling retries.
    results:  list[JobResult] = []
    failures: list[FailedJob] = []

    for i, job in enumerate(jobs):
        outcome = await _process_job(job)
        if isinstance(outcome, JobResult):
            results.append(outcome)
        else:
            failures.append(outcome)

        # Brief pause between jobs to let the token-per-minute window breathe
        if i < len(jobs) - 1:
            await asyncio.sleep(config.INTER_JOB_DELAY_SEC)

    manifest = PipelineRun(
        run_id=_run_id,
        started_at=started,
        finished_at=datetime.utcnow(),
        total_found=len(jobs),
        total_passed=len(results),
        total_failed=len(failures),
        results=results,
        failures=failures,
    )

    _save_outputs(manifest)
    log.info(
        f"=== Run {_run_id} complete | "
        f"passed={len(results)} failed={len(failures)} total={len(jobs)} ==="
    )
    return manifest


# ── Per-job processing (Phases 3-5) ──────────────────────────────────────────

async def _process_job(job: Job) -> JobResult | FailedJob:
    """
    Phases 3→4→5 for a single job with retry loop.
    On verification or validation failure: inject correction notes and re-tailor.
    """
    correction_notes = ""
    last_status      = JobStatus.PENDING

    for attempt in range(1, config.MAX_RETRIES + 2):
        try:
            # Phase 3 - Tailor
            last_status = JobStatus.TAILORING
            resume: TailoredResume = await tailor.tailor_resume(
                job=job,
                master_resume=_master_resume,
                format_template=_format_template,
                correction_notes=correction_notes,
                fmt=_format_params,
            )

            # Auto-fix hyphens and semicolons before any validation.
            resume = _sanitize_resume(resume)

            # Grammar fix - corrects punctuation and commas.
            await asyncio.sleep(config.INTER_AGENT_DELAY_SEC)
            resume = await fix_grammar(resume)
            log.debug("Grammar fix applied")

            await asyncio.sleep(config.INTER_AGENT_DELAY_SEC)

            # Phase 4 - Verify (MUST run before calibration).
            # Calibration rewrites wording; if it runs first, calibrated phrasing
            # gets flagged as fabrication - causing issue counts to grow on retry.
            last_status = JobStatus.VERIFYING
            ver = await verifier.verify_resume(resume, _master_resume, job.description)
            if not ver.passed:
                correction_notes = _merge(correction_notes, ver.correction_prompt)
                if attempt <= config.MAX_RETRIES:
                    log.info(f"Retry {attempt}/{config.MAX_RETRIES} (verification): {job.title} @ {job.company}")
                    await asyncio.sleep(config.INTER_AGENT_DELAY_SEC)
                    continue
                return FailedJob(
                    job=job, last_status=JobStatus.VERIFYING, attempts=attempt,
                    reason="Verification failed: " + "; ".join(i.claim for i in ver.issues[:2]),
                )

            # Calibration runs AFTER verification - tone/abstraction fix on verified content.
            await asyncio.sleep(config.INTER_AGENT_DELAY_SEC)
            resume = await calibrate(resume, job_description=job.description)

            await asyncio.sleep(config.INTER_AGENT_DELAY_SEC)

            # Phase 5 - Validate (on calibrated output)
            last_status = JobStatus.VALIDATING
            val = await validator.validate_resume(resume, _format_template, _format_params)
            if not val.passed:
                correction_notes = _merge(correction_notes, val.correction_prompt)
                if attempt <= config.MAX_RETRIES:
                    log.info(f"Retry {attempt}/{config.MAX_RETRIES} (validation): {job.title} @ {job.company}")
                    await asyncio.sleep(config.INTER_AGENT_DELAY_SEC)
                    continue
                return FailedJob(
                    job=job, last_status=JobStatus.VALIDATING, attempts=attempt,
                    reason="Validation failed: " + "; ".join(i.description[:80] for i in val.issues[:2]),
                )

            # All passed - build docx
            resume_path = _resume_path(job)
            build_docx(resume, resume_path)

            return JobResult(
                job=job, resume=resume, resume_path=str(resume_path),
                status=JobStatus.PASSED, attempts=attempt,
                verification=ver, validation=val,
            )

        except Exception as exc:
            log.error(f"Error attempt {attempt} for {job.job_id}: {exc}", exc_info=True)
            if attempt > config.MAX_RETRIES:
                return FailedJob(
                    job=job, last_status=last_status, attempts=attempt,
                    reason=f"Exception: {type(exc).__name__}: {str(exc)[:120]}",
                )
            wait = config.INTER_AGENT_DELAY_SEC * (attempt + 1)
            log.info(f"Waiting {wait}s before retry {attempt + 1}...")
            await asyncio.sleep(wait)
            correction_notes = f"Previous attempt raised: {exc}. Fix and retry."

    return FailedJob(
        job=job, last_status=last_status, attempts=config.MAX_RETRIES + 1,
        reason="Exhausted all retries.",
    )


# ── Output (Phase 6) ──────────────────────────────────────────────────────────

def _save_outputs(manifest: PipelineRun) -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    resume_dir = config.RESUME_DIR / manifest.run_id

    # 1. Manifest JSON
    manifest_path = config.OUTPUT_DIR / f"manifest_{manifest.run_id}.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    log.info(f"Manifest → {manifest_path}")

    # 2. Job links CSV
    csv_path = config.OUTPUT_DIR / f"job_links_{manifest.run_id}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Status", "Job Title", "Company", "Board", "Location",
                    "Job URL", "Resume File", "Attempts"])
        for r in manifest.results:
            w.writerow(["PASSED", r.job.title, r.job.company, r.job.board,
                        r.job.location or "", r.job.job_url,
                        Path(r.resume_path).name if r.resume_path else "", r.attempts])
        for f_ in manifest.failures:
            w.writerow(["FAILED", f_.job.title, f_.job.company, f_.job.board,
                        f_.job.location or "", f_.job.job_url, "", f_.attempts])
    log.info(f"Job links CSV → {csv_path}")

    # 3. Markdown index
    index_path = config.OUTPUT_DIR / f"index_{manifest.run_id}.md"
    lines = [
        f"# Job-Resume Pairs - Run {manifest.run_id}",
        f"Generated: {manifest.finished_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**{manifest.total_passed} resumes ready  |  {manifest.total_failed} failed**\n",
        "---\n", "## ✅ Passed\n",
    ]
    for r in manifest.results:
        lines.append(
            f"- **{r.job.title}** @ {r.job.company} ({r.job.board})\n"
            f"  🔗 {r.job.job_url}\n"
            f"  📄 `{Path(r.resume_path).name if r.resume_path else 'n/a'}`\n"
        )
    if manifest.failures:
        lines += ["\n---\n", "## ❌ Failed\n"]
        for f_ in manifest.failures:
            lines.append(f"- **{f_.job.title}** @ {f_.job.company} - {f_.reason}\n")
    index_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Index → {index_path}")

    # 4. Resumes zip - .docx only (PDF removed)
    zip_path = config.OUTPUT_DIR / f"resumes_{manifest.run_id}.zip"
    docx_files = list(resume_dir.glob("*.docx")) if resume_dir.exists() else []
    if docx_files:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in docx_files:
                zf.write(f, f.name)
        log.info(f"Resumes zip ({len(docx_files)} docx) → {zip_path}")
    else:
        log.warning(f"No .docx files in {resume_dir} - nothing to zip.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resume_path(job: Job) -> Path:
    """Save inside output/resumes/<run_id>/  consistent with zip lookup."""
    safe = lambda s, n: "".join(c if c.isalnum() else "_" for c in s)[:n]
    filename = f"{safe(job.company, 30)}_{safe(job.title, 25)}_{job.job_id}.docx"
    path = config.RESUME_DIR / _run_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _merge(a: str, b: str) -> str:
    if not a: return b
    if not b: return a
    return f"{a}\n\nAdditional corrections:\n{b}"


# ── Text sanitization ─────────────────────────────────────────────────────────

def _sanitize_resume(resume: TailoredResume) -> TailoredResume:
    """
    Auto-remove hyphens (as sentence connectors) and semicolons from all
    narrative text fields. Applied after tailoring, before verification.

    Hyphen rule:
      word-word  → word word        (e.g. hands-on → hands on)
      word-DIGIT → kept as-is       (e.g. GPT-4, Python-3.8, Gemini-2.5)
    Semicolon rule:
      ;  → ,                        (safe substitution preserving sentence flow)
    """
    fields = ["summary", "experience", "projects", "skills", "certifications"]
    data = resume.model_dump()

    for field in fields:
        val = data.get(field)
        if val and isinstance(val, str):
            val = _fix_hyphens(val)
            val = _fix_semicolons(val)
            data[field] = val

    return TailoredResume(**data)


# Compound adjectives whose hyphens are grammatically correct - keep them
_KEEP_HYPHENATED = {
    "end-to-end", "large-scale", "small-scale", "two-stage", "multi-stage",
    "real-time", "state-of-the-art", "high-fidelity", "high-performance",
    "high-quality", "high-stakes", "rule-based", "data-driven",
    "entry-level", "cross-functional", "open-source", "well-defined",
    "long-term", "short-term", "full-stack",
}


def _fix_hyphens(text: str) -> str:
    """
    Remove unnecessary hyphens but preserve:
      - word-DIGIT: GPT-4, Python-3.8, claude-3.5
      - valid compound adjectives: end-to-end, large-scale, real-time, etc.
    """
    import re as _re
    def _replace(m):
        full  = m.group(0)
        w1, w2 = m.group(1), m.group(2)
        if w2 and w2[0].isdigit():
            return full   # keep: GPT-4
        if full.lower() in _KEEP_HYPHENATED:
            return full   # keep: end-to-end, large-scale
        return f"{w1} {w2}"   # remove: hands-on, multi-agent
    return _re.sub(r"(\w+)-(\w+)", _replace, text)


def _fix_semicolons(text: str) -> str:
    """Replace all semicolons with commas."""
    return text.replace(";", ",")
