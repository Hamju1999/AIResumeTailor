"""
Entry point.

Usage:
    python main.py                        # full run
    python main.py --dry-run              # scrape only, skip LLM phases
    python main.py --limit 5              # process first N jobs only
    python main.py --titles "Data Scientist,ML Engineer"
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Try rich for nicer output; fall back to stdlib logging
try:
    from rich.logging import RichHandler
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

log = logging.getLogger("main")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Agentic Job Application Pipeline")
    p.add_argument("--dry-run", action="store_true",
                   help="Scrape jobs only; skip tailoring, verification, validation")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap the number of jobs processed (0 = unlimited)")
    p.add_argument("--titles", type=str, default="",
                   help="Comma-separated job titles to override config")
    p.add_argument("--api-key", type=str, default="",
                   help="Anthropic API key (alternative to env var)")
    return p.parse_args()

async def main() -> None:
    args = parse_args()
    # Apply CLI overrides 
    import config
    if args.api_key:
        config.ANTHROPIC_API_KEY = args.api_key
    elif not config.ANTHROPIC_API_KEY:
        config.ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    if args.titles:
        config.JOB_TITLES = [t.strip() for t in args.titles.split(",")]
        log.info(f"Override job titles: {config.JOB_TITLES}")
    # Create output dirs
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.RESUME_DIR.mkdir(parents=True, exist_ok=True)
    # Preflight checks
    if not config.MASTER_RESUME_PATH.exists():
        log.error(
            f"[red]master_resume.txt not found at {config.MASTER_RESUME_PATH}[/red]\n"
            "Export your resume as plain text and save it there, then re-run."
        )
        sys.exit(1)
    if not config.FORMAT_TEMPLATE_PATH.exists():
        log.error(
            f"[red]format_template.txt not found at {config.FORMAT_TEMPLATE_PATH}[/red]\n"
            "Save your format spec there, then re-run."
        )
        sys.exit(1)
    if not args.dry_run and not config.ANTHROPIC_API_KEY:
        log.error("[red]No API key found.[/red] Set ANTHROPIC_API_KEY env var or use --api-key.")
        sys.exit(1)
    # Dry run: scrape + print job list
    if args.dry_run:
        log.info("[yellow]DRY RUN - scraping only, no LLM calls[/yellow]")
        import scraper
        jobs = await scraper.discover_jobs()
        if args.limit:
            jobs = jobs[: args.limit]
        log.info(f"Found {len(jobs)} jobs:")
        for j in jobs:
            log.info(f"  [{j.board}] {j.title} @ {j.company} - {j.job_url}")
        return
    # Full pipeline run
    if args.limit:
        # Monkey-patch scraper to cap results
        import scraper as _scraper
        _orig = _scraper.discover_jobs
        async def _capped():
            jobs = await _orig()
            return jobs[: args.limit]
        _scraper.discover_jobs = _capped
        log.info(f"Job cap set to {args.limit}")

    import pipeline
    manifest = await pipeline.run()

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info(f"Run ID   : {manifest.run_id}")
    log.info(f"Total    : {manifest.total_found} jobs scraped")
    log.info(f"Passed   : {manifest.total_passed}")
    log.info(f"Failed   : {manifest.total_failed}")
    log.info(f"Output   : {config.OUTPUT_DIR}")
    log.info("=" * 60)
    if manifest.results:
        log.info("\nJob-Resume pairs:")
        for r in manifest.results:
            log.info(f"  ✅  {r.job.title} @ {r.job.company}")
            log.info(f"      {r.job.job_url}")
            log.info(f"      Resume: {r.resume_path}")
    if manifest.failures:
        log.info("\nFailed jobs:")
        for f in manifest.failures:
            log.info(f"  ❌  {f.job.title} @ {f.job.company} - {f.reason}")

if __name__ == "__main__":
    asyncio.run(main())
