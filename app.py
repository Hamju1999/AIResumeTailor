"""
ResTail Web UI — Flask app on localhost:5000

First run: redirects to /setup where user uploads their files and enters their info.
Config is saved to user_config.json (persistent, gitignored).
Subsequent runs: goes straight to the main UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, send_file, url_for)

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

import config

app = Flask(__name__, template_folder=BASE_DIR / "templates")
app.secret_key = os.urandom(24)

# ── In-memory run state ───────────────────────────────────────────────────────
_run_state = {
    "status": "idle", "run_id": None, "logs": [],
    "results": [], "failures": [], "total": 0,
    "passed": 0, "failed": 0, "started": None, "finished": None,
}
_log_queue: queue.Queue = queue.Queue()
_state_lock = threading.Lock()


class QueueHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        entry = {"ts": datetime.now().strftime("%H:%M:%S"), "level": record.levelname, "msg": msg}
        with _state_lock:
            _run_state["logs"].append(entry)
        _log_queue.put(entry)


_queue_handler = QueueHandler()
_queue_handler.setLevel(logging.DEBUG)
_queue_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
logging.getLogger().addHandler(_queue_handler)
logging.getLogger().setLevel(logging.INFO)


# ── Setup check ───────────────────────────────────────────────────────────────

def _redirect_if_not_setup():
    if not config.is_setup_complete():
        return redirect(url_for("setup"))
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    redir = _redirect_if_not_setup()
    if redir:
        return redir
    return render_template("index.html")


@app.route("/setup", methods=["GET"])
def setup():
    existing = {}
    if config.USER_CONFIG_PATH.exists():
        try:
            existing = json.loads(config.USER_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return render_template("setup.html", existing=existing)


@app.route("/api/setup", methods=["POST"])
def api_setup():
    """Save user configuration and uploaded files."""
    try:
        form = request.form
        files = request.files

        # Load existing config to preserve file paths if not re-uploading
        existing = {}
        if config.USER_CONFIG_PATH.exists():
            try:
                existing = json.loads(config.USER_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Required text fields
        full_name    = form.get("full_name", "").strip()
        contact_line = form.get("contact_line", "").strip()
        if not full_name or not contact_line:
            return jsonify({"error": "Full name and contact line are required."}), 400

        # Handle master resume upload
        master_path = existing.get("master_resume_path", "")
        mr_file = files.get("master_resume")
        if mr_file and mr_file.filename:
            suffix = Path(mr_file.filename).suffix.lower() or ".txt"
            dest = BASE_DIR / f"master_resume{suffix}"
            mr_file.save(str(dest))
            master_path = str(dest)

        # Handle format template upload
        fmt_path = existing.get("format_template_path", "")
        ft_file = files.get("format_template")
        if ft_file and ft_file.filename:
            suffix = Path(ft_file.filename).suffix.lower() or ".txt"
            dest = BASE_DIR / f"format_template{suffix}"
            ft_file.save(str(dest))
            fmt_path = str(dest)

        if not master_path or not Path(master_path).exists():
            return jsonify({"error": "Master resume file is required."}), 400
        if not fmt_path or not Path(fmt_path).exists():
            return jsonify({"error": "Format template file is required."}), 400

        # Locations — one per line, filter empty
        locations_raw = form.get("locations", "")
        locations = [l.strip() for l in locations_raw.splitlines() if l.strip()]
        if not locations:
            return jsonify({"error": "At least one location is required."}), 400

        # Job titles — one per line
        titles_raw = form.get("job_titles", "")
        job_titles = [t.strip() for t in titles_raw.splitlines() if t.strip()]
        if not job_titles:
            return jsonify({"error": "At least one job title is required."}), 400

        cfg = {
            "full_name":             full_name,
            "contact_line":          contact_line,
            "linkedin_url":          form.get("linkedin_url", "").strip(),
            "github_url":            form.get("github_url", "").strip(),
            "portfolio_url":         form.get("portfolio_url", "").strip(),
            "master_resume_path":    master_path,
            "format_template_path":  fmt_path,
            "locations":             locations,
            "job_titles":            job_titles,
            "anthropic_api_key":     form.get("anthropic_api_key", "").strip(),
        }

        config.USER_CONFIG_PATH.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        config.reload()

        logging.getLogger("setup").info("Setup complete — configuration saved.")
        return jsonify({"ok": True, "redirect": "/"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/setup/status")
def api_setup_status():
    return jsonify({"complete": config.is_setup_complete()})


@app.route("/api/state")
def api_state():
    with _state_lock:
        return jsonify(dict(_run_state))


@app.route("/api/run", methods=["POST"])
def api_run():
    if not config.is_setup_complete():
        return jsonify({"error": "Setup not complete. Go to /setup first."}), 400

    with _state_lock:
        if _run_state["status"] == "running":
            return jsonify({"error": "A run is already in progress."}), 409

    data = request.get_json(force=True) or {}
    custom_urls: list[str] = [u.strip() for u in data.get("custom_urls", []) if u.strip()]
    limit: int = int(data.get("limit", 0))

    with _state_lock:
        _run_state.update({
            "status": "running", "run_id": None, "logs": [],
            "results": [], "failures": [], "total": 0,
            "passed": 0, "failed": 0,
            "started": datetime.now().isoformat(), "finished": None,
        })
    while not _log_queue.empty():
        try:
            _log_queue.get_nowait()
        except queue.Empty:
            break

    thread = threading.Thread(target=_run_pipeline, args=(custom_urls, limit), daemon=True)
    thread.start()
    return jsonify({"ok": True})


@app.route("/api/logs/stream")
def api_logs_stream():
    def generate():
        yield "data: {}\n\n"
        while True:
            try:
                entry = _log_queue.get(timeout=30)
                yield f"data: {json.dumps(entry)}\n\n"
            except queue.Empty:
                with _state_lock:
                    if _run_state["status"] != "running":
                        yield 'data: {"done": true}\n\n'
                        break
                yield ": keepalive\n\n"
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/download/<run_id>/<file_type>")
def api_download(run_id: str, file_type: str):
    if not re.match(r"^[a-f0-9]{8}$", run_id):
        return "Invalid run ID", 400
    files = {
        "csv":   config.OUTPUT_DIR / f"job_links_{run_id}.csv",
        "zip":   config.OUTPUT_DIR / f"resumes_{run_id}.zip",
        "index": config.OUTPUT_DIR / f"index_{run_id}.md",
    }
    path = files.get(file_type)
    if not path or not path.exists():
        return "File not found", 404
    return send_file(str(path), as_attachment=True)


@app.route("/api/history")
def api_history():
    runs = []
    for f in sorted(config.OUTPUT_DIR.glob("manifest_*.json"), reverse=True)[:20]:
        try:
            d = json.loads(f.read_text())
            runs.append({
                "run_id": d.get("run_id"), "started_at": d.get("started_at"),
                "finished_at": d.get("finished_at"),
                "total_passed": d.get("total_passed", 0),
                "total_failed": d.get("total_failed", 0),
                "total_found":  d.get("total_found", 0),
            })
        except Exception:
            pass
    return jsonify(runs)


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_pipeline(custom_urls: list[str], limit: int) -> None:
    log = logging.getLogger("ui.runner")
    try:
        if custom_urls:
            log.info(f"Mode: custom URLs ({len(custom_urls)} links provided)")
            manifest = asyncio.run(_run_custom_urls(custom_urls))
        else:
            log.info(f"Mode: full scrape" + (f" (limit {limit})" if limit else ""))
            manifest = asyncio.run(_run_full_pipeline(limit))

        with _state_lock:
            _run_state.update({
                "status": "done", "run_id": manifest.run_id,
                "total": manifest.total_found, "passed": manifest.total_passed,
                "failed": manifest.total_failed, "finished": datetime.now().isoformat(),
                "results":  [_job_result_dict(r) for r in manifest.results],
                "failures": [_failed_job_dict(f) for f in manifest.failures],
            })
    except Exception as exc:
        logging.getLogger("ui.runner").error(f"Pipeline error: {exc}", exc_info=True)
        with _state_lock:
            _run_state.update({"status": "error", "finished": datetime.now().isoformat()})


async def _run_full_pipeline(limit: int):
    import pipeline as pl
    import scraper
    if limit:
        _orig = scraper.discover_jobs
        async def _capped():
            jobs = await _orig()
            return jobs[:limit]
        scraper.discover_jobs = _capped
    manifest = await pl.run()
    if limit:
        scraper.discover_jobs = _orig
    return manifest


async def _run_custom_urls(urls: list[str]):
    import hashlib
    import pipeline as pl
    from scraper import _get
    from models import Job, RawJob
    from bs4 import BeautifulSoup

    log = logging.getLogger("ui.custom")
    pl.load_content()
    jobs = []

    for url in urls:
        log.info(f"Fetching custom URL: {url}")
        try:
            r = _get(url)
            if r is None:
                log.warning(f"Could not fetch: {url}")
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            desc = ""
            for sel in [".description__text", ".show-more-less-html__markup",
                        "#jobDescriptionText", ".jobsearch-jobDescriptionText",
                        "[data-testid='jobDescriptionText']", ".JobDetails_jobDescription",
                        "[data-test='jobDescriptionContent']", ".job-description",
                        "article", "main"]:
                el = soup.select_one(sel)
                if el:
                    desc = el.get_text(separator="\n", strip=True)
                    if len(desc) > 200:
                        break
            if not desc or len(desc) < 100:
                log.warning(f"No usable description: {url}")
                continue
            title = ""
            for sel in ["h1", ".top-card-layout__title", ".jobsearch-JobInfoHeader-title",
                        "[data-test='job-title']", ".JobDetails_jobTitle"]:
                el = soup.select_one(sel)
                if el:
                    title = el.get_text(strip=True); break
            company = ""
            for sel in [".topcard__org-name-link", ".jobsearch-InlineCompanyRating",
                        "[data-test='employer-name']", ".JobDetails_companyName"]:
                el = soup.select_one(sel)
                if el:
                    company = el.get_text(strip=True); break
            job_id = hashlib.md5(url.encode()).hexdigest()[:12]
            jobs.append(Job(
                job_url=url, title=title or "Job", company=company or "Company",
                location="", date_posted=datetime.utcnow(),
                description=desc, board="custom", job_id=job_id,
            ))
            log.info(f"  Loaded: {title or 'Job'} @ {company or 'Company'}")
        except Exception as e:
            log.error(f"Error fetching {url}: {e}")

    if not jobs:
        log.error("No usable jobs loaded from provided URLs.")
        from models import PipelineRun
        return PipelineRun(run_id=uuid.uuid4().hex[:8], started_at=datetime.utcnow(),
                           finished_at=datetime.utcnow())

    log.info(f"Processing {len(jobs)} custom jobs through AI phases ...")
    run_id = uuid.uuid4().hex[:8]
    pl._run_id = run_id
    results, failures = [], []
    for i, job in enumerate(jobs):
        outcome = await pl._process_job(job)
        if hasattr(outcome, "resume_path"):
            results.append(outcome)
        else:
            failures.append(outcome)
        if i < len(jobs) - 1:
            await asyncio.sleep(config.INTER_JOB_DELAY_SEC)

    from models import PipelineRun
    manifest = PipelineRun(
        run_id=run_id, started_at=datetime.utcnow(), finished_at=datetime.utcnow(),
        total_found=len(jobs), total_passed=len(results), total_failed=len(failures),
        results=results, failures=failures,
    )
    pl._save_outputs(manifest)
    return manifest


def _job_result_dict(r) -> dict:
    docx_path = Path(r.resume_path) if r.resume_path else None
    return {
        "title": r.job.title, "company": r.job.company, "board": r.job.board,
        "location": r.job.location or "", "job_url": r.job.job_url,
        "resume_file": docx_path.name if docx_path else "", "attempts": r.attempts,
    }


def _failed_job_dict(f) -> dict:
    return {"title": f.job.title, "company": f.job.company, "reason": f.reason}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.RESUME_DIR.mkdir(parents=True, exist_ok=True)
    print("\n" + "="*55)
    print("  ResTail")
    print("  Open your browser: http://localhost:5000")
    if not config.is_setup_complete():
        print("  First run detected — setup wizard will open.")
    print("="*55 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
