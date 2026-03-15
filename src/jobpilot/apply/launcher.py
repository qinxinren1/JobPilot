"""Apply orchestration: acquire jobs, spawn Claude Code sessions, track results.

This is the main entry point for the apply pipeline. It pulls jobs from
the database, launches Chrome + Claude Code for each one, parses the
result, and updates the database. Supports parallel workers via --workers.
"""

import atexit
import json
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.live import Live

from jobpilot import config
from jobpilot.database import get_connection
from jobpilot.apply import chrome, dashboard, prompt as prompt_mod
from jobpilot.config import TAILORED_DIR, load_profile
from jobpilot.apply.chrome import (
    launch_chrome, cleanup_worker, kill_all_chrome,
    reset_worker_dir, cleanup_on_exit, _kill_process_tree,
    BASE_CDP_PORT,
)
from jobpilot.apply.dashboard import (
    init_worker, update_state, add_event, get_state,
    render_full, get_totals,
)

logger = logging.getLogger(__name__)

# Blocked sites loaded from config/sites.yaml
def _load_blocked():
    from jobpilot.config import load_blocked_sites
    return load_blocked_sites()

# How often to poll the DB when the queue is empty (seconds)
POLL_INTERVAL = config.DEFAULTS["poll_interval"]

# Thread-safe shutdown coordination
_stop_event = threading.Event()

# Track active Claude Code processes for skip (Ctrl+C) handling
_claude_procs: dict[int, subprocess.Popen] = {}
_claude_lock = threading.Lock()

# Register cleanup on exit
atexit.register(cleanup_on_exit)
if platform.system() != "Windows":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


# ---------------------------------------------------------------------------
# MCP config
# ---------------------------------------------------------------------------

def _make_mcp_config(cdp_port: int) -> dict:
    """Build MCP config dict for a specific CDP port."""
    return {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": [
                    "@playwright/mcp@latest",
                    f"--cdp-endpoint=http://localhost:{cdp_port}",
                    f"--viewport-size={config.DEFAULTS['viewport']}",
                ],
            },
            "gmail": {
                "command": "npx",
                "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
            },
        }
    }


# ---------------------------------------------------------------------------
# Auto-enrichment for direct URL apply
# ---------------------------------------------------------------------------

def _auto_enrich_and_tailor(url: str, worker_id: int = 0, min_score: int = 7) -> dict | None:
    """Automatically enrich, score, and tailor a job URL if it's not in the database.
    
    This function performs the full pipeline:
    1. Enrich: Scrape job details and application URL
    2. Score: Evaluate job fit against profile
    3. Tailor: Generate tailored resume (if score >= min_score)
    
    Args:
        url: Job listing URL or application URL.
        worker_id: Worker identifier for logging.
        min_score: Minimum fit_score to proceed with tailoring.
    
    Returns:
        Job dict ready for application, or None if enrichment failed.
    """
    from jobpilot.enrichment.detail import scrape_detail_page
    from jobpilot.scoring.scorer import score_job
    from jobpilot.scoring.tailor import tailor_resume
    from playwright.sync_api import sync_playwright
    
    conn = get_connection()
    
    # Check if job already exists with tailored resume
    existing = conn.execute(
        "SELECT url, title, site, application_url, tailored_resume_path, fit_score, "
        "full_description, location FROM jobs WHERE url = ? OR application_url = ?",
        (url, url)
    ).fetchone()
    
    if existing and existing["tailored_resume_path"]:
        # Already enriched and tailored, return it
        logger.info(f"[worker-{worker_id}] Job already in DB with tailored resume: {url[:80]}")
        return dict(existing)
    
    # Determine job_url (use existing URL if found, otherwise use input URL)
    job_url = existing["url"] if existing else url
    
    # Step 1: Enrich - scrape job details (only if not already enriched)
    if not existing or not existing["full_description"]:
        logger.info(f"[worker-{worker_id}] Job not found or missing description, enriching: {url[:80]}")
        add_event(f"[W{worker_id}] Enriching job: {url[:60]}...")
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()
                
                enrich_result = scrape_detail_page(page, url)
                
                full_description = enrich_result.get("full_description")
                application_url = enrich_result.get("application_url")
                
                # Extract title, site, and location
                title = enrich_result.get("title")
                site = enrich_result.get("site")
                location = enrich_result.get("location") or ""
                
                
                # Insert or update job in database
                now = datetime.now(timezone.utc).isoformat()
                
                if existing:
                    # Update existing job
                    job_url = existing["url"]
                    conn.execute("""
                        UPDATE jobs SET 
                            title = ?, site = ?, full_description = ?, application_url = ?,
                            location = ?, detail_scraped_at = ?
                        WHERE url = ?
                    """, (title, site, full_description, application_url, location, now, job_url))
                else:
                    # Insert new job
                    conn.execute("""
                        INSERT INTO jobs (url, title, site, description, full_description, 
                                       application_url, location, strategy, discovered_at, detail_scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (url, title, site, full_description[:500], full_description, 
                          application_url, location, "manual", now, now))
                    job_url = url
                
                conn.commit()
                logger.info(f"[worker-{worker_id}] Enriched job: {title[:40]} @ {site}")
                add_event(f"[W{worker_id}] Enriched: {title[:30]} @ {site[:20]}")
                
        except Exception as e:
            logger.exception(f"[worker-{worker_id}] Enrichment failed for {url}")
            add_event(f"[W{worker_id}] Enrichment error: {str(e)[:40]}")
            return None
    else:
        logger.info(f"[worker-{worker_id}] Job already enriched, skipping enrichment step")
    
    # Step 2: Score the job (also find template for Step 3)
    profile = load_profile()
    matched_template = None
    try:
        job_row = conn.execute(
            "SELECT url, title, site, location, full_description FROM jobs WHERE url = ?",
            (job_url,)
        ).fetchone()
        job_dict = dict(job_row)
        
        # Find template (used by score_job and will be used by Step 3)
        from jobpilot.scoring.scorer import _find_matching_resume_template
        matched_template = _find_matching_resume_template(conn, job_dict, profile)
        
        score_result = score_job(profile, job_dict, conn)
        fit_score = score_result.get("score", 0)
        resume_score = score_result.get("resume_score", 0)
        keywords = score_result.get("keywords", "")
        reasoning = score_result.get("reasoning", "")
        score_reasoning = f"{keywords}\n{reasoning}".strip() if keywords or reasoning else None
        
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE jobs SET fit_score = ?, resume_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?
        """, (fit_score, resume_score, score_reasoning, now, job_url))
        conn.commit()
        
        logger.info(f"[worker-{worker_id}] Scored job: {fit_score}/10, resume: {resume_score}/10")
        add_event(f"[W{worker_id}] Scored: {fit_score}/10 (resume: {resume_score}/10)")
        
        # Check if score meets minimum threshold
        if fit_score < min_score:
            logger.warning(f"[worker-{worker_id}] Job score {fit_score} below minimum {min_score}, skipping tailor")
            add_event(f"[W{worker_id}] Score too low ({fit_score} < {min_score}), skipping")
            return None
        
    except Exception as e:
        logger.exception(f"[worker-{worker_id}] Scoring failed for {url}")
        add_event(f"[W{worker_id}] Scoring error: {str(e)[:40]}")
        # Continue anyway, score will be 0
    
    # Step 3: Tailor resume (use template from Step 2, check base resume first)
    found_resume = None
    try:
        role_category = job_dict.get("role_category")
        
        # If resume_score is high enough, skip tailoring - just use existing resume
        skip_tailor = resume_score >= 7
        
        # Check base resume first (higher priority than template)
        if role_category:
            # 1. Check target_roles.base_resume_path
            target_roles = profile.get("target_roles", {})
            role_config = target_roles.get(role_category, {})
            base_resume_path = role_config.get("base_resume_path")
            if base_resume_path:
                base_path = Path(base_resume_path)
                if base_path.suffix == ".html":
                    found_resume = {"html": base_path.read_text(encoding="utf-8"), "pdf_path": None, "source": f"base_resume:{role_category}"}
                elif base_path.suffix == ".pdf":
                    found_resume = {"html": None, "pdf_path": base_path, "source": f"base_resume:{role_category}"}
                else:  # .txt
                    text = base_path.read_text(encoding="utf-8")
                    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 1in; }}
body {{ font-family: 'Calibri', 'Segoe UI', Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #1a1a1a; white-space: pre-wrap; }}
</style>
</head>
<body>
{text}
</body>
</html>"""
                    found_resume = {"html": html, "pdf_path": None, "source": f"base_resume:{role_category}"}
            
            # 2. Check BASE_RESUMES_DIR
            if not found_resume:
                from jobpilot.config import BASE_RESUMES_DIR
                personal = profile["personal"]
                full_name = personal.get("full_name", "")
                name_safe = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(" ", "_")
                base_html = BASE_RESUMES_DIR / f"{name_safe}_{role_category}.html"
                base_pdf = BASE_RESUMES_DIR / f"{name_safe}_{role_category}.pdf"
                base_txt = BASE_RESUMES_DIR / f"{name_safe}_{role_category}.txt"
                if base_html.exists():
                    found_resume = {"html": base_html.read_text(encoding="utf-8"), "pdf_path": None, "source": f"base_resumes_dir:{role_category}"}
                elif base_pdf.exists():
                    found_resume = {"html": None, "pdf_path": base_pdf, "source": f"base_resumes_dir:{role_category}"}
                elif base_txt.exists():
                    text = base_txt.read_text(encoding="utf-8")
                    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 1in; }}
body {{ font-family: 'Calibri', 'Segoe UI', Arial, sans-serif; font-size: 11pt; line-height: 1.6; color: #1a1a1a; white-space: pre-wrap; }}
</style>
</head>
<body>
{text}
</body>
</html>"""
                    found_resume = {"html": html, "pdf_path": None, "source": f"base_resumes_dir:{role_category}"}
        
        # 3. Use template from Step 2 (already found during scoring)
        if not found_resume and matched_template and matched_template.get("file_path"):
            template_path = Path(matched_template["file_path"])
            if template_path.suffix == ".html":
                found_resume = {"html": template_path.read_text(encoding="utf-8"), "pdf_path": None, "source": f"template:{matched_template.get('name', 'unknown')}"}
            elif template_path.suffix == ".pdf":
                html_path = template_path.with_suffix(".html")
                if html_path.exists():
                    found_resume = {"html": html_path.read_text(encoding="utf-8"), "pdf_path": None, "source": f"template_html:{matched_template.get('name', 'unknown')}"}
                else:
                    found_resume = {"html": None, "pdf_path": template_path, "source": f"template_pdf:{matched_template.get('name', 'unknown')}"}
        
        # Use found resume or generate tailored
        if found_resume:
            if skip_tailor:
                logger.info(f"[worker-{worker_id}] Resume score {resume_score} >= 7, using existing resume without tailoring")
                add_event(f"[W{worker_id}] Resume score {resume_score}/10, skipping tailor")
            tailored_html = found_resume.get("html")
            base_resume_pdf_path = found_resume.get("pdf_path")
            resume_source = found_resume.get("source")
            logger.info(f"[worker-{worker_id}] Using resume from Step 2: {resume_source}")
            add_event(f"[W{worker_id}] Using resume: {resume_source}")
            tailor_report = {
                "status": "approved",
                "attempts": 1,
                "skipped_tailoring": True,
                "resume_source": resume_source,
            }
        else:
            if skip_tailor:
                # Resume score is high but no resume found - should not happen, but handle gracefully
                logger.warning(f"[worker-{worker_id}] Resume score {resume_score} >= 7 but no resume found, generating tailored")
                add_event(f"[W{worker_id}] Resume score high but no resume, generating")
            else:
                logger.info(f"[worker-{worker_id}] No base resume found, generating tailored resume")
                add_event(f"[W{worker_id}] Generating tailored resume")
            tailored_html, tailor_report = tailor_resume(
                job=job_dict,
                profile=profile,
                max_retries=3,
                validation_mode="normal",
            )
            resume_source = "tailored"
            base_resume_pdf_path = None
        
        # Save resume (HTML or use PDF directly)
        TAILORED_DIR.mkdir(parents=True, exist_ok=True)
        
        title_safe = re.sub(r'[^\w\s-]', '', job_dict.get("title", "job")).strip()
        title_safe = re.sub(r'[-\s]+', '_', title_safe)[:50]
        prefix = f"{title_safe}_{job_dict.get('site', 'company')[:30]}"
        prefix = re.sub(r'[^\w-]', '', prefix)
        
        # If we have a PDF base resume, use it directly
        if base_resume_pdf_path:
            # Copy PDF to tailored directory
            pdf_path_obj = TAILORED_DIR / f"{prefix}.pdf"
            shutil.copy(str(base_resume_pdf_path), str(pdf_path_obj))
            resume_path = str(pdf_path_obj)
            logger.info(f"[worker-{worker_id}] Using base resume PDF: {resume_path}")
        elif tailored_html:
            # Save HTML and generate PDF
            html_path = TAILORED_DIR / f"{prefix}.html"
            html_path.write_text(tailored_html, encoding="utf-8")
            
            # Generate PDF from HTML using Playwright
            pdf_path = None
            pdf_path_obj = TAILORED_DIR / f"{prefix}.pdf"
            
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.set_content(tailored_html, wait_until="networkidle")
                    page.pdf(
                        path=str(pdf_path_obj),
                        format="A4",
                        print_background=True,
                    )
                    browser.close()
                
                if pdf_path_obj.exists():
                    pdf_path = str(pdf_path_obj)
                    logger.info(f"[worker-{worker_id}] Generated PDF: {pdf_path}")
                else:
                    logger.warning(f"[worker-{worker_id}] PDF file not created: {pdf_path_obj}")
            except Exception as e:
                logger.warning(f"[worker-{worker_id}] PDF generation failed: {e}")
            
            # Store PDF path (prefer PDF, fallback to HTML)
            resume_path = pdf_path if pdf_path and Path(pdf_path).exists() else str(html_path)
        else:
            # Fallback: should not happen, but handle gracefully
            logger.error(f"[worker-{worker_id}] No resume HTML or PDF found")
            return None
        
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE jobs SET tailored_resume_path = ?, tailored_at = ? WHERE url = ?
        """, (resume_path, now, job_url))
        conn.commit()
        
        logger.info(f"[worker-{worker_id}] Tailored resume saved: {resume_path}")
        add_event(f"[W{worker_id}] Tailored resume ready")
        
    except Exception as e:
        logger.exception(f"[worker-{worker_id}] Tailoring failed for {url}")
        add_event(f"[W{worker_id}] Tailoring error: {str(e)[:40]}")
        return None
    
    # Return the complete job dict
    row = conn.execute("""
        SELECT url, title, site, application_url, tailored_resume_path,
               fit_score, location, full_description, cover_letter_path
        FROM jobs WHERE url = ?
    """, (job_url,)).fetchone()
    
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def acquire_job(target_url: str | None = None, min_score: int = 7,
                worker_id: int = 0, auto_enrich: bool = True) -> dict | None:
    """Atomically acquire the next job to apply to.

    Args:
        target_url: Apply to a specific URL instead of picking from queue.
        min_score: Minimum fit_score threshold.
        worker_id: Worker claiming this job (for tracking).
        auto_enrich: If True and job not found, automatically enrich/tailor it.

    Returns:
        Job dict or None if the queue is empty.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        if target_url:
            like = f"%{target_url.split('?')[0].rstrip('/')}%"
            row = conn.execute("""
                SELECT url, title, site, application_url, tailored_resume_path,
                       fit_score, location, full_description, cover_letter_path
                FROM jobs
                WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
                  AND tailored_resume_path IS NOT NULL
                  AND (apply_status IS NULL OR apply_status != 'in_progress')
                LIMIT 1
            """, (target_url, target_url, like, like)).fetchone()
            
            # If not found and auto_enrich is enabled, try to enrich it
            if not row and auto_enrich:
                conn.rollback()
                logger.info(f"[worker-{worker_id}] Job not in DB, attempting auto-enrich: {target_url}")
                job = _auto_enrich_and_tailor(target_url, worker_id, min_score)
                if job:
                    # Re-acquire with the enriched job (disable auto_enrich to avoid infinite loop)
                    return acquire_job(target_url=target_url, min_score=min_score, 
                                      worker_id=worker_id, auto_enrich=False)
                else:
                    logger.warning(f"[worker-{worker_id}] Auto-enrich failed for {target_url}")
                    return None
        else:
            blocked_sites, blocked_patterns = _load_blocked()
            # Build parameterized filters to avoid SQL injection
            params: list = [min_score]
            site_clause = ""
            if blocked_sites:
                placeholders = ",".join("?" * len(blocked_sites))
                site_clause = f"AND site NOT IN ({placeholders})"
                params.extend(blocked_sites)
            url_clauses = ""
            if blocked_patterns:
                url_clauses = " ".join(f"AND url NOT LIKE ?" for _ in blocked_patterns)
                params.extend(blocked_patterns)
            row = conn.execute(f"""
                SELECT url, title, site, application_url, tailored_resume_path,
                       fit_score, location, full_description, cover_letter_path
                FROM jobs
                WHERE tailored_resume_path IS NOT NULL
                  AND (apply_status IS NULL OR apply_status = 'failed')
                  AND (apply_attempts IS NULL OR apply_attempts < ?)
                  AND fit_score >= ?
                  {site_clause}
                  {url_clauses}
                ORDER BY fit_score DESC, url
                LIMIT 1
            """, [config.DEFAULTS["max_apply_attempts"]] + params).fetchone()

        if not row:
            conn.rollback()
            return None

        # Skip manual ATS sites (unsolvable CAPTCHAs)
        from jobpilot.config import is_manual_ats
        apply_url = row["application_url"] or row["url"]
        if is_manual_ats(apply_url):
            conn.execute(
                "UPDATE jobs SET apply_status = 'manual', apply_error = 'manual ATS' WHERE url = ?",
                (row["url"],),
            )
            conn.commit()
            logger.info("Skipping manual ATS: %s", row["url"][:80])
            return None

        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE jobs SET apply_status = 'in_progress',
                           agent_id = ?,
                           last_attempted_at = ?
            WHERE url = ?
        """, (f"worker-{worker_id}", now, row["url"]))
        conn.commit()

        return dict(row)
    except Exception:
        conn.rollback()
        raise


def mark_result(url: str, status: str, error: str | None = None,
                permanent: bool = False, duration_ms: int | None = None,
                task_id: str | None = None) -> None:
    """Update a job's apply status in the database."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?
            WHERE url = ?
        """, (now, duration_ms, task_id, url))
    else:
        attempts = 99 if permanent else "COALESCE(apply_attempts, 0) + 1"
        conn.execute(f"""
            UPDATE jobs SET apply_status = ?, apply_error = ?,
                           apply_attempts = {attempts}, agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?
            WHERE url = ?
        """, (status, error or "unknown", duration_ms, task_id, url))
    conn.commit()


def release_lock(url: str) -> None:
    """Release the in_progress lock without changing status."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET apply_status = NULL, agent_id = NULL WHERE url = ? AND apply_status = 'in_progress'",
        (url,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Utility modes (--gen, --mark-applied, --mark-failed, --reset-failed)
# ---------------------------------------------------------------------------

def gen_prompt(target_url: str, min_score: int = 7,
               model: str = "sonnet", worker_id: int = 0) -> Path | None:
    """Generate a prompt file and print the Claude CLI command for manual debugging.

    Returns:
        Path to the generated prompt file, or None if no job found.
    """
    job = acquire_job(target_url=target_url, min_score=min_score, worker_id=worker_id)
    if not job:
        return None

    # Read resume text
    resume_path = job.get("tailored_resume_path")
    txt_path = Path(resume_path).with_suffix(".txt") if resume_path else None
    resume_text = ""
    if txt_path and txt_path.exists():
        resume_text = txt_path.read_text(encoding="utf-8")

    prompt = prompt_mod.build_prompt(job=job, tailored_resume=resume_text)

    # Release the lock so the job stays available
    release_lock(job["url"])

    # Write prompt file
    config.ensure_dirs()
    site_slug = (job.get("site") or "unknown")[:20].replace(" ", "_")
    prompt_file = config.LOG_DIR / f"prompt_{site_slug}_{job['title'][:30].replace(' ', '_')}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Write MCP config for reference
    port = BASE_CDP_PORT + worker_id
    mcp_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
    mcp_path.write_text(json.dumps(_make_mcp_config(port)), encoding="utf-8")

    return prompt_file


def mark_job(url: str, status: str, reason: str | None = None) -> None:
    """Manually mark a job's apply status in the database.

    Args:
        url: Job URL to mark.
        status: Either 'applied' or 'failed'.
        reason: Failure reason (only for status='failed').
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL
            WHERE url = ?
        """, (now, url))
    else:
        conn.execute("""
            UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                           apply_attempts = 99, agent_id = NULL
            WHERE url = ?
        """, (reason or "manual", url))
    conn.commit()


def reset_failed() -> int:
    """Reset all failed jobs so they can be retried.

    Returns:
        Number of jobs reset.
    """
    conn = get_connection()
    cursor = conn.execute("""
        UPDATE jobs SET apply_status = NULL, apply_error = NULL,
                       apply_attempts = 0, agent_id = NULL
        WHERE apply_status = 'failed'
          OR (apply_status IS NOT NULL AND apply_status != 'applied'
              AND apply_status != 'in_progress')
    """)
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Per-job execution
# ---------------------------------------------------------------------------

def run_job(job: dict, port: int, worker_id: int = 0,
            model: str = "sonnet", dry_run: bool = False) -> tuple[str, int]:
    """Spawn a Claude Code session for one job application.

    Returns:
        Tuple of (status_string, duration_ms). Status is one of:
        'applied', 'expired', 'captcha', 'login_issue',
        'failed:reason', or 'skipped'.
    """
    # Read tailored resume (HTML format, extract text for prompt)
    resume_path = job.get("tailored_resume_path")
    resume_text = ""
    if resume_path:
        resume_file = Path(resume_path)
        # Try HTML first (new format), then fall back to .txt (legacy)
        if resume_file.suffix == ".html" and resume_file.exists():
            # Extract text from HTML for prompt
            html_content = resume_file.read_text(encoding="utf-8")
            # Simple HTML to text extraction (remove tags, keep content)
            import re
            # Remove script and style tags
            resume_text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            resume_text = re.sub(r'<style[^>]*>.*?</style>', '', resume_text, flags=re.DOTALL | re.IGNORECASE)
            # Remove HTML tags but keep text content
            resume_text = re.sub(r'<[^>]+>', ' ', resume_text)
            # Clean up whitespace
            resume_text = re.sub(r'\s+', ' ', resume_text).strip()
        elif resume_file.with_suffix(".txt").exists():
            # Legacy .txt format support
            resume_text = resume_file.with_suffix(".txt").read_text(encoding="utf-8")

    # Build the prompt
    agent_prompt = prompt_mod.build_prompt(
        job=job,
        tailored_resume=resume_text,
        dry_run=dry_run,
    )

    # Write per-worker MCP config
    mcp_config_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
    mcp_config_path.write_text(json.dumps(_make_mcp_config(port)), encoding="utf-8")

    # Find claude command (check PATH and common locations)
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        # Try common installation locations
        home = Path.home()
        candidates = [
            home / ".local" / "bin" / "claude",
            home / ".local" / "share" / "claude" / "versions" / "latest",
            Path("/usr/local/bin/claude"),
        ]
        for candidate in candidates:
            if candidate.exists():
                claude_cmd = str(candidate)
                break
    
    if not claude_cmd:
        raise FileNotFoundError(
            "Claude Code CLI not found. Install from https://claude.ai/code "
            "or ensure 'claude' is in your PATH."
        )

    # Build claude command
    cmd = [
        claude_cmd,
        "--model", model,
        "-p",
        "--mcp-config", str(mcp_config_path),
        "--permission-mode", "bypassPermissions",
        "--no-session-persistence",
        "--disallowedTools", (
            "mcp__gmail__draft_email,mcp__gmail__modify_email,"
            "mcp__gmail__delete_email,mcp__gmail__download_attachment,"
            "mcp__gmail__batch_modify_emails,mcp__gmail__batch_delete_emails,"
            "mcp__gmail__create_label,mcp__gmail__update_label,"
            "mcp__gmail__delete_label,mcp__gmail__get_or_create_label,"
            "mcp__gmail__list_email_labels,mcp__gmail__create_filter,"
            "mcp__gmail__list_filters,mcp__gmail__get_filter,"
            "mcp__gmail__delete_filter"
        ),
        "--output-format", "stream-json",
        "--verbose", "-",
    ]

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    worker_dir = reset_worker_dir(worker_id)

    update_state(worker_id, status="applying", job_title=job["title"],
                 company=job.get("site", ""), score=job.get("fit_score", 0),
                 start_time=time.time(), actions=0, last_action="starting")
    add_event(f"[W{worker_id}] Starting: {job['title'][:40]} @ {job.get('site', '')}")

    worker_log = config.LOG_DIR / f"worker-{worker_id}.log"
    ts_header = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_header = (
        f"\n{'=' * 60}\n"
        f"[{ts_header}] {job['title']} @ {job.get('site', '')}\n"
        f"URL: {job.get('application_url') or job['url']}\n"
        f"Score: {job.get('fit_score', 'N/A')}/10\n"
        f"{'=' * 60}\n"
    )

    start = time.time()
    stats: dict = {}
    proc = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(worker_dir),
        )
        with _claude_lock:
            _claude_procs[worker_id] = proc

        proc.stdin.write(agent_prompt)
        proc.stdin.close()

        text_parts: list[str] = []
        with open(worker_log, "a", encoding="utf-8") as lf:
            lf.write(log_header)

            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    msg_type = msg.get("type")
                    if msg_type == "assistant":
                        for block in msg.get("message", {}).get("content", []):
                            bt = block.get("type")
                            if bt == "text":
                                text_parts.append(block["text"])
                                lf.write(block["text"] + "\n")
                            elif bt == "tool_use":
                                name = (
                                    block.get("name", "")
                                    .replace("mcp__playwright__", "")
                                    .replace("mcp__gmail__", "gmail:")
                                )
                                inp = block.get("input", {})
                                if "url" in inp:
                                    desc = f"{name} {inp['url'][:60]}"
                                elif "ref" in inp:
                                    desc = f"{name} {inp.get('element', inp.get('text', ''))}"[:50]
                                elif "fields" in inp:
                                    desc = f"{name} ({len(inp['fields'])} fields)"
                                elif "paths" in inp:
                                    desc = f"{name} upload"
                                else:
                                    desc = name

                                lf.write(f"  >> {desc}\n")
                                ws = get_state(worker_id)
                                cur_actions = ws.actions if ws else 0
                                update_state(worker_id,
                                             actions=cur_actions + 1,
                                             last_action=desc[:35])
                    elif msg_type == "result":
                        stats = {
                            "input_tokens": msg.get("usage", {}).get("input_tokens", 0),
                            "output_tokens": msg.get("usage", {}).get("output_tokens", 0),
                            "cache_read": msg.get("usage", {}).get("cache_read_input_tokens", 0),
                            "cache_create": msg.get("usage", {}).get("cache_creation_input_tokens", 0),
                            "cost_usd": msg.get("total_cost_usd", 0),
                            "turns": msg.get("num_turns", 0),
                        }
                        text_parts.append(msg.get("result", ""))
                except json.JSONDecodeError:
                    text_parts.append(line)
                    lf.write(line + "\n")

        proc.wait(timeout=300)
        returncode = proc.returncode
        proc = None

        if returncode and returncode < 0:
            return "skipped", int((time.time() - start) * 1000)

        output = "\n".join(text_parts)
        elapsed = int(time.time() - start)
        duration_ms = int((time.time() - start) * 1000)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_log = config.LOG_DIR / f"claude_{ts}_w{worker_id}_{job.get('site', 'unknown')[:20]}.txt"
        job_log.write_text(output, encoding="utf-8")

        if stats:
            cost = stats.get("cost_usd", 0)
            ws = get_state(worker_id)
            prev_cost = ws.total_cost if ws else 0.0
            update_state(worker_id, total_cost=prev_cost + cost)

        def _clean_reason(s: str) -> str:
            return re.sub(r'[*`"]+$', '', s).strip()

        for result_status in ["APPLIED", "EXPIRED", "CAPTCHA", "LOGIN_ISSUE"]:
            if f"RESULT:{result_status}" in output:
                add_event(f"[W{worker_id}] {result_status} ({elapsed}s): {job['title'][:30]}")
                update_state(worker_id, status=result_status.lower(),
                             last_action=f"{result_status} ({elapsed}s)")
                return result_status.lower(), duration_ms

        if "RESULT:FAILED" in output:
            for out_line in output.split("\n"):
                if "RESULT:FAILED" in out_line:
                    reason = (
                        out_line.split("RESULT:FAILED:")[-1].strip()
                        if ":" in out_line[out_line.index("FAILED") + 6:]
                        else "unknown"
                    )
                    reason = _clean_reason(reason)
                    PROMOTE_TO_STATUS = {"captcha", "expired", "login_issue"}
                    if reason in PROMOTE_TO_STATUS:
                        add_event(f"[W{worker_id}] {reason.upper()} ({elapsed}s): {job['title'][:30]}")
                        update_state(worker_id, status=reason,
                                     last_action=f"{reason.upper()} ({elapsed}s)")
                        return reason, duration_ms
                    add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason[:30]}")
                    update_state(worker_id, status="failed",
                                 last_action=f"FAILED: {reason[:25]}")
                    return f"failed:{reason}", duration_ms
            return "failed:unknown", duration_ms

        add_event(f"[W{worker_id}] NO RESULT ({elapsed}s)")
        update_state(worker_id, status="failed", last_action=f"no result ({elapsed}s)")
        return "failed:no_result_line", duration_ms

    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        elapsed = int(time.time() - start)
        add_event(f"[W{worker_id}] TIMEOUT ({elapsed}s)")
        update_state(worker_id, status="failed", last_action=f"TIMEOUT ({elapsed}s)")
        return "failed:timeout", duration_ms
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        add_event(f"[W{worker_id}] ERROR: {str(e)[:40]}")
        update_state(worker_id, status="failed", last_action=f"ERROR: {str(e)[:25]}")
        return f"failed:{str(e)[:100]}", duration_ms
    finally:
        with _claude_lock:
            _claude_procs.pop(worker_id, None)
        if proc is not None and proc.poll() is None:
            _kill_process_tree(proc.pid)


# ---------------------------------------------------------------------------
# Permanent failure classification
# ---------------------------------------------------------------------------

PERMANENT_FAILURES: set[str] = {
    "expired", "captcha", "login_issue",
    "not_eligible_location", "not_eligible_salary",
    "already_applied", "account_required",
    "not_a_job_application", "unsafe_permissions",
    "unsafe_verification", "sso_required",
    "site_blocked", "cloudflare_blocked", "blocked_by_cloudflare",
}

PERMANENT_PREFIXES: tuple[str, ...] = ("site_blocked", "cloudflare", "blocked_by")


def _is_permanent_failure(result: str) -> bool:
    """Determine if a failure should never be retried."""
    reason = result.split(":", 1)[-1] if ":" in result else result
    return (
        result in PERMANENT_FAILURES
        or reason in PERMANENT_FAILURES
        or any(reason.startswith(p) for p in PERMANENT_PREFIXES)
    )


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

def worker_loop(worker_id: int = 0, limit: int = 1,
                target_url: str | None = None,
                min_score: int = 7, headless: bool = False,
                model: str = "sonnet", dry_run: bool = False) -> tuple[int, int]:
    """Run jobs sequentially until limit is reached or queue is empty.

    Args:
        worker_id: Numeric worker identifier.
        limit: Max jobs to process (0 = continuous).
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome headless.
        model: Claude model name.
        dry_run: Don't click Submit.

    Returns:
        Tuple of (applied_count, failed_count).
    """
    applied = 0
    failed = 0
    continuous = limit == 0
    jobs_done = 0
    empty_polls = 0
    port = BASE_CDP_PORT + worker_id

    while not _stop_event.is_set():
        if not continuous and jobs_done >= limit:
            break

        update_state(worker_id, status="idle", job_title="", company="",
                     last_action="waiting for job", actions=0)

        job = acquire_job(target_url=target_url, min_score=min_score,
                          worker_id=worker_id)
        if not job:
            if not continuous:
                add_event(f"[W{worker_id}] Queue empty")
                update_state(worker_id, status="done", last_action="queue empty")
                break
            empty_polls += 1
            update_state(worker_id, status="idle",
                         last_action=f"polling ({empty_polls})")
            if empty_polls == 1:
                add_event(f"[W{worker_id}] Queue empty, polling every {POLL_INTERVAL}s...")
            # Use Event.wait for interruptible sleep
            if _stop_event.wait(timeout=POLL_INTERVAL):
                break  # Stop was requested during wait
            continue

        empty_polls = 0

        chrome_proc = None
        try:
            add_event(f"[W{worker_id}] Launching Chrome...")
            chrome_proc = launch_chrome(worker_id, port=port, headless=headless)

            result, duration_ms = run_job(job, port=port, worker_id=worker_id,
                                            model=model, dry_run=dry_run)

            if result == "skipped":
                release_lock(job["url"])
                add_event(f"[W{worker_id}] Skipped: {job['title'][:30]}")
                continue
            elif result == "applied":
                mark_result(job["url"], "applied", duration_ms=duration_ms)
                applied += 1
                update_state(worker_id, jobs_applied=applied,
                             jobs_done=applied + failed)
            else:
                reason = result.split(":", 1)[-1] if ":" in result else result
                mark_result(job["url"], "failed", reason,
                            permanent=_is_permanent_failure(result),
                            duration_ms=duration_ms)
                failed += 1
                update_state(worker_id, jobs_failed=failed,
                             jobs_done=applied + failed)

        except KeyboardInterrupt:
            release_lock(job["url"])
            if _stop_event.is_set():
                break
            add_event(f"[W{worker_id}] Job skipped (Ctrl+C)")
            continue
        except Exception as e:
            logger.exception("Worker %d launcher error", worker_id)
            add_event(f"[W{worker_id}] Launcher error: {str(e)[:40]}")
            release_lock(job["url"])
            failed += 1
            update_state(worker_id, jobs_failed=failed)
        finally:
            if chrome_proc:
                cleanup_worker(worker_id, chrome_proc)

        jobs_done += 1
        if target_url:
            break

    update_state(worker_id, status="done", last_action="finished")
    return applied, failed


# ---------------------------------------------------------------------------
# Main entry point (called from cli.py)
# ---------------------------------------------------------------------------

def main(limit: int = 1, target_url: str | None = None,
         min_score: int = 7, headless: bool = False, model: str = "sonnet",
         dry_run: bool = False, continuous: bool = False,
         poll_interval: int = 60, workers: int = 1) -> None:
    """Launch the apply pipeline.

    Args:
        limit: Max jobs to apply to (0 or with continuous=True means run forever).
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome in headless mode.
        model: Claude model name.
        dry_run: Don't click Submit.
        continuous: Run forever, polling for new jobs.
        poll_interval: Seconds between DB polls when queue is empty.
        workers: Number of parallel workers (default 1).
    """
    global POLL_INTERVAL
    POLL_INTERVAL = poll_interval
    _stop_event.clear()

    config.ensure_dirs()
    console = Console()

    if continuous:
        effective_limit = 0
        mode_label = "continuous"
    else:
        effective_limit = limit
        mode_label = f"{limit} jobs"

    # Initialize dashboard for all workers
    for i in range(workers):
        init_worker(i)

    worker_label = f"{workers} worker{'s' if workers > 1 else ''}"
    console.print(f"Launching apply pipeline ({mode_label}, {worker_label}, poll every {POLL_INTERVAL}s)...")
    console.print("[dim]Ctrl+C = skip current job(s) | Ctrl+C x2 = stop[/dim]")

    # Double Ctrl+C handler
    _ctrl_c_count = 0

    def _sigint_handler(sig, frame):
        nonlocal _ctrl_c_count
        _ctrl_c_count += 1
        if _ctrl_c_count == 1:
            console.print("\n[yellow]Skipping current job(s)... (Ctrl+C again to STOP)[/yellow]")
            # Kill all active Claude processes to skip current jobs
            with _claude_lock:
                for wid, cproc in list(_claude_procs.items()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
        else:
            console.print("\n[red bold]STOPPING[/red bold]")
            _stop_event.set()
            with _claude_lock:
                for wid, cproc in list(_claude_procs.items()):
                    if cproc.poll() is None:
                        _kill_process_tree(cproc.pid)
            kill_all_chrome()
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        with Live(render_full(), console=console, refresh_per_second=2) as live:
            # Daemon thread for display refresh only (no business logic)
            _dashboard_running = True

            def _refresh():
                while _dashboard_running:
                    live.update(render_full())
                    time.sleep(0.5)

            refresh_thread = threading.Thread(target=_refresh, daemon=True)
            refresh_thread.start()

            if workers == 1:
                # Single worker — run directly in main thread
                total_applied, total_failed = worker_loop(
                    worker_id=0,
                    limit=effective_limit,
                    target_url=target_url,
                    min_score=min_score,
                    headless=headless,
                    model=model,
                    dry_run=dry_run,
                )
            else:
                # Multi-worker — distribute limit across workers
                if effective_limit:
                    base = effective_limit // workers
                    extra = effective_limit % workers
                    limits = [base + (1 if i < extra else 0)
                              for i in range(workers)]
                else:
                    limits = [0] * workers  # continuous mode

                with ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="apply-worker") as executor:
                    futures = {
                        executor.submit(
                            worker_loop,
                            worker_id=i,
                            limit=limits[i],
                            target_url=target_url,
                            min_score=min_score,
                            headless=headless,
                            model=model,
                            dry_run=dry_run,
                        ): i
                        for i in range(workers)
                    }

                    results: list[tuple[int, int]] = []
                    for future in as_completed(futures):
                        wid = futures[future]
                        try:
                            results.append(future.result())
                        except Exception:
                            logger.exception("Worker %d crashed", wid)
                            results.append((0, 0))

                total_applied = sum(r[0] for r in results)
                total_failed = sum(r[1] for r in results)

            _dashboard_running = False
            refresh_thread.join(timeout=2)
            live.update(render_full())

        totals = get_totals()
        console.print(
            f"\n[bold]Done: {total_applied} applied, {total_failed} failed "
            f"(${totals['cost']:.3f})[/bold]"
        )
        console.print(f"Logs: {config.LOG_DIR}")

    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        kill_all_chrome()
