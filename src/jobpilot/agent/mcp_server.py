"""MCP server for job application agent.

This MCP server exposes agent functionality to Claude Desktop,
allowing you to manage jobs and run applications directly from Claude.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP
from playwright.sync_api import sync_playwright

from jobpilot.agent.config import (
    load_results, load_profile, ensure_agent_dirs
)
from jobpilot.database import get_connection, init_db, get_job_stage
from jobpilot.enrichment.detail import scrape_detail_page
from jobpilot.scoring.scorer import score_job
from jobpilot.scoring.tailor import tailor_resume
from jobpilot.config import TAILORED_DIR, load_env

logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_env()

# Initialize FastMCP server
mcp = FastMCP("JobPilot Agent")



@mcp.tool()
def list_jobs() -> dict[str, Any]:
    """List all jobs from the database that are ready to apply.
    
    Returns:
        List of jobs and statistics from database
    """
    conn = get_connection()
    
    # Get jobs ready to apply (have tailored resume, not yet applied)
    jobs = conn.execute("""
        SELECT url, title, company, site, application_url, fit_score, 
               tailored_resume_path, cover_letter_path, apply_status, applied_at
        FROM jobs
        WHERE tailored_resume_path IS NOT NULL
        ORDER BY fit_score DESC NULLS LAST, discovered_at DESC
    """).fetchall()
    
    # Convert to dicts
    jobs_list = [dict(job) for job in jobs]
    
    # Get statistics from database
    stats = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN applied_at IS NOT NULL THEN 1 ELSE 0 END) as applied,
            SUM(CASE WHEN apply_status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN applied_at IS NULL AND apply_status IS NULL THEN 1 ELSE 0 END) as pending
        FROM jobs
        WHERE tailored_resume_path IS NOT NULL
    """).fetchone()
    
    return {
        "total_jobs": stats[0] if stats else 0,
        "jobs": jobs_list,
        "statistics": {
            "applied": stats[1] if stats else 0,
            "failed": stats[2] if stats else 0,
            "pending": stats[3] if stats else 0,
        },
    }


@mcp.tool()
def run_agent_batch(
    limit: int | None = None,
    workers: int = 1,
    model: str = "sonnet",
    headless: bool = False,
    dry_run: bool = False,
    min_score: int = 7,
) -> dict[str, Any]:
    """Run agent to process multiple jobs from the database.
    
    Args:
        limit: Maximum number of jobs to process (None = all)
        workers: Number of parallel workers (default: 1)
        model: Claude model to use (default: sonnet)
        headless: Run browser in headless mode (default: False)
        dry_run: Don't actually submit (default: False)
        min_score: Minimum fit_score threshold (default: 7)
    
    Returns:
        Batch processing results
    """
    from jobpilot.agent.apply_agent import run_agent
    
    try:
        # This will process jobs from database and update database automatically
        run_agent(
            limit=limit,
            workers=workers,
            model=model,
            headless=headless,
            dry_run=dry_run,
            min_score=min_score,
        )
        
        results = load_results()
        recent_results = results[-limit:] if limit and limit <= len(results) else results[-10:]
        
        return {
            "status": "success",
            "message": "Processed jobs from database",
            "recent_results": recent_results,
        }
    except Exception as e:
        logger.exception("Error running agent batch")
        return {
            "status": "error",
            "message": str(e),
        }


@mcp.tool()
def get_job_status(
    url: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """Get job status by URL or keyword search.
    
    Args:
        url: Job URL (exact match)
        keyword: Search keyword (matches title, company, or site)
    
    Returns:
        Job status information including all pipeline stages
    """
    init_db()
    conn = get_connection()
    
    if not url and not keyword:
        return {
            "status": "error",
            "message": "Either url or keyword must be provided",
        }
    
    # Build query based on provided parameters
    if url:
        # Exact URL match
        like = f"%{url.split('?')[0].rstrip('/')}%"
        row = conn.execute("""
            SELECT url, title, company, site, location, salary,
                   full_description, application_url, detail_scraped_at, detail_error,
                   fit_score, resume_score, score_reasoning, scored_at,
                   tailored_resume_path, tailored_at, tailor_attempts,
                   cover_letter_path, cover_letter_at, cover_attempts,
                   applied_at, apply_status, apply_error, apply_attempts,
                   agent_id, last_attempted_at, apply_duration_ms,
                   discovered_at, strategy
            FROM jobs
            WHERE url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?
            LIMIT 1
        """, (url, url, like, like)).fetchone()
    else:
        # Keyword search in title, company, or site
        keyword_pattern = f"%{keyword}%"
        row = conn.execute("""
            SELECT url, title, company, site, location, salary,
                   full_description, application_url, detail_scraped_at, detail_error,
                   fit_score, resume_score, score_reasoning, scored_at,
                   tailored_resume_path, tailored_at, tailor_attempts,
                   cover_letter_path, cover_letter_at, cover_attempts,
                   applied_at, apply_status, apply_error, apply_attempts,
                   agent_id, last_attempted_at, apply_duration_ms,
                   discovered_at, strategy
            FROM jobs
            WHERE title LIKE ? OR company LIKE ? OR site LIKE ?
            ORDER BY discovered_at DESC
            LIMIT 10
        """, (keyword_pattern, keyword_pattern, keyword_pattern)).fetchone()
    
    if not row:
        return {
            "status": "not_found",
            "message": f"Job not found: {url or keyword}",
        }
    
    job = dict(row)
    
    # Determine current stage using database utility function
    current_stage = get_job_stage(job)
    
    # Build status summary
    stages = {
        "discover": {
            "status": "completed" if job.get("discovered_at") else "pending",
            "timestamp": job.get("discovered_at"),
        },
        "enrich": {
            "status": "completed" if job.get("detail_scraped_at") else "pending",
            "timestamp": job.get("detail_scraped_at"),
            "has_description": job.get("full_description") is not None,
            "has_application_url": job.get("application_url") is not None,
            "error": job.get("detail_error"),
        },
        "score": {
            "status": "completed" if job.get("scored_at") else "pending",
            "timestamp": job.get("scored_at"),
            "fit_score": job.get("fit_score"),
            "resume_score": job.get("resume_score"),
            "keywords": job.get("score_reasoning", "").split("\n")[0] if job.get("score_reasoning") else "",
        },
        "tailor": {
            "status": "completed" if job.get("tailored_resume_path") else "pending",
            "timestamp": job.get("tailored_at"),
            "resume_path": job.get("tailored_resume_path"),
            "attempts": job.get("tailor_attempts", 0),
        },
        "cover": {
            "status": "completed" if job.get("cover_letter_path") else "pending",
            "timestamp": job.get("cover_letter_at"),
            "cover_letter_path": job.get("cover_letter_path"),
            "attempts": job.get("cover_attempts", 0),
        },
        "apply": {
            "status": job.get("apply_status") or "pending",
            "timestamp": job.get("applied_at") or job.get("last_attempted_at"),
            "error": job.get("apply_error"),
            "attempts": job.get("apply_attempts", 0),
            "duration_ms": job.get("apply_duration_ms"),
            "agent_id": job.get("agent_id"),
        },
    }
    
    return {
        "status": "success",
        "job": {
            "url": job.get("url"),
            "title": job.get("title"),
            "company": job.get("company"),
            "site": job.get("site"),
            "location": job.get("location"),
            "salary": job.get("salary"),
        },
        "current_stage": current_stage,
        "stages": stages,
        "timeline": {
            "discovered_at": job.get("discovered_at"),
            "detail_scraped_at": job.get("detail_scraped_at"),
            "scored_at": job.get("scored_at"),
            "tailored_at": job.get("tailored_at"),
            "cover_letter_at": job.get("cover_letter_at"),
            "applied_at": job.get("applied_at"),
        },
    }


@mcp.tool()
def get_profile() -> dict[str, Any]:
    """Get the user's profile information.
    
    Returns:
        Profile data
    """
    try:
        profile = load_profile()
        return {
            "status": "success",
            "profile": profile,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


@mcp.tool()
def get_results(limit: int = 10) -> dict[str, Any]:
    """Get recent application results.
    
    Args:
        limit: Maximum number of results to return (default: 10)
    
    Returns:
        Recent results and statistics
    """
    results = load_results()
    recent = results[-limit:] if limit else results
    
    stats = {
        "applied": sum(1 for r in recent if r.get("status") == "applied"),
        "failed": sum(1 for r in recent if r.get("status") == "failed"),
        "expired": sum(1 for r in recent if r.get("status") == "expired"),
        "skipped": sum(1 for r in recent if r.get("status") == "skipped"),
    }
    
    return {
        "total": len(results),
        "recent": recent,
        "statistics": stats,
    }



@mcp.tool()
def add_job(
    url: str,
    min_score: int = 7,
    model: str = "sonnet",
    headless: bool = False,
    dry_run: bool = False,
    auto_tailor: bool = True,
) -> dict[str, Any]:
    """Add job from url workflow: enrich + score + tailor + apply for a single job URL.
    
    This function provides a streamlined flow:
    1. Enrich: Extract job details and application URL
    2. Score: Evaluate job fit
    3. Tailor: Generate tailored resume (if score >= min_score and auto_tailor=True)
    4. Apply: Start application process using Playwright
    
    Args:
        url: Job listing URL
        min_score: Minimum fit_score to proceed with tailoring and application (default: 7)
        model: Claude model to use for application (default: sonnet)
        headless: Run browser in headless mode (default: False)
        dry_run: Don't actually submit (default: False)
        auto_tailor: Automatically tailor resume if score >= min_score (default: True)
    
    Returns:
        Complete workflow result with enrich, score, tailor, and apply status
    """
    ensure_agent_dirs()
    init_db()
    conn = get_connection()
    
    result = {
        "status": "pending",
        "url": url,
        "enrich": {},
        "score": {},
        "tailor": {},
        "apply": {},
        "current_stage": "unknown",
    }
    
    # First, check current job status in database
    logger.info(f"Checking current job status: {url}")
    existing = conn.execute("""
        SELECT url, full_description, application_url, detail_scraped_at,
               fit_score, scored_at, tailored_resume_path, tailored_at,
               apply_status, applied_at
        FROM jobs WHERE url = ?
    """, (url,)).fetchone()
    
    # Determine current stage using database utility function
    existing_dict = {}
    current_stage = "discover"  # Default: not in database yet
    
    if existing:
        existing_dict = dict(existing)
        current_stage = get_job_stage(existing_dict)
    
    result["current_stage"] = current_stage
    logger.info(f"Job current stage: {current_stage}")
    
    # Step 1: Enrich - Extract job details and application URL
    logger.info(f"Step 1: Enriching job from URL: {url}")
    
    full_description = None
    application_url = None
    
    # Check if already enriched
    if current_stage in ("enrich", "score", "tailor", "apply_failed", "apply_in_progress", "applied"):
        # Already enriched, use existing data
        full_description = existing_dict.get("full_description")
        application_url = existing_dict.get("application_url")
        
        logger.info("Job already enriched, skipping enrichment step")
        result["enrich"] = {
            "status": "skipped",
            "full_description": full_description is not None,
            "application_url": application_url is not None,
            "message": "Already enriched, using existing data",
        }
    else:
        # Need to enrich (job doesn't exist or not fully enriched)
        logger.info("Job needs enrichment, running enrichment")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()
                
                enrich_result = scrape_detail_page(page, url)
                browser.close()
                
                full_description = enrich_result.get("full_description")
                application_url = enrich_result.get("application_url")
                enrich_error = enrich_result.get("error")
                
                result["enrich"] = {
                    "status": enrich_result.get("status", "error"),
                    "full_description": full_description is not None,
                    "application_url": application_url is not None,
                    "tier_used": enrich_result.get("tier_used"),
                }
                
                # Check for URL normalization errors (e.g., LinkedIn search results without job ID)
                if enrich_error and "LinkedIn search results" in enrich_error:
                    result["status"] = "error"
                    result["message"] = enrich_error
                    result["error"] = "invalid_url_format"
                    return result
                
                if not full_description:
                    result["status"] = "error"
                    result["message"] = "Failed to extract job description"
                    if enrich_error:
                        result["message"] += f": {enrich_error}"
                    return result
                
                # Update or insert job
                now = datetime.now(timezone.utc).isoformat()
                if existing:
                    # Update existing job
                    conn.execute("""
                        UPDATE jobs SET full_description = ?, application_url = ?, detail_scraped_at = ?
                        WHERE url = ?
                    """, (full_description, application_url, now, url))
                else:
                    # Insert new job
                    conn.execute("""
                        INSERT INTO jobs (url, title, company, full_description, application_url,
                                        site, strategy, discovered_at, detail_scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        url,
                        "Unknown Title",  # Will be updated if we can extract it
                        "Unknown Company",
                        full_description,
                        application_url,
                        "Manual",
                        "mcp_agent",
                        now,
                        now,
                    ))
                conn.commit()
                
                logger.info(f"Enrichment complete: description={full_description is not None}, application_url={application_url is not None}")
                
        except Exception as e:
            logger.error(f"Enrichment failed: {e}", exc_info=True)
            result["status"] = "error"
            result["message"] = f"Enrichment failed: {str(e)}"
            result["enrich"] = {"status": "error", "error": str(e)}
            return result
    
    # Verify we have full_description before proceeding
    if not full_description:
        result["status"] = "error"
        result["message"] = "No full_description available, cannot proceed"
        return result
    
    # Step 2: Score - Evaluate job fit
    logger.info(f"Step 2: Scoring job: {url}")
    
    # Check if already scored
    if current_stage in ("score", "tailor", "apply_failed", "apply_in_progress", "applied"):
        # Already scored, use existing score
        fit_score = existing_dict.get("fit_score")
        logger.info(f"Job already scored: {fit_score}/10, skipping scoring step")
        result["score"] = {
            "status": "skipped",
            "fit_score": fit_score,
            "message": "Already scored, using existing score",
        }
        
        # Check if score meets threshold
        if fit_score is not None and fit_score < min_score:
            result["status"] = "score_too_low"
            result["message"] = f"Job score {fit_score} is below minimum {min_score}"
            return result
    else:
        # Need to score
        try:
            profile = load_profile()
            if not profile:
                raise ValueError("Profile not found")
            
            # Get job data from database
            job_row = conn.execute("""
                SELECT url, title, site, company, location, full_description
                FROM jobs WHERE url = ?
            """, (url,)).fetchone()
            
            if not job_row:
                raise ValueError("Job not found in database after enrichment")
            
            job_dict = dict(job_row)
            score_result = score_job(profile, job_dict, conn=conn)
            
            fit_score = score_result.get("score", 0)
            resume_score = score_result.get("resume_score", 0)
            
            # Update database with score
            now_scored = datetime.now(timezone.utc).isoformat()
            score_reasoning = f"{score_result.get('keywords', '')}\n{score_result.get('reasoning', '')}"
            conn.execute("""
                UPDATE jobs SET fit_score = ?, resume_score = ?, score_reasoning = ?, scored_at = ?
                WHERE url = ?
            """, (fit_score, resume_score, score_reasoning, now_scored, url))
            conn.commit()
            
            result["score"] = {
                "fit_score": fit_score,
                "resume_score": resume_score,
                "keywords": score_result.get("keywords", ""),
                "reasoning": score_result.get("reasoning", ""),
            }
            
            logger.info(f"Scoring complete: fit_score={fit_score}, resume_score={resume_score}")
            
            # Check if score meets threshold
            if fit_score < min_score:
                result["status"] = "score_too_low"
                result["message"] = f"Job score {fit_score} is below minimum {min_score}"
                return result
                
        except Exception as e:
            logger.error(f"Scoring failed: {e}", exc_info=True)
            result["status"] = "error"
            result["message"] = f"Scoring failed: {str(e)}"
            result["score"] = {"status": "error", "error": str(e)}
            return result
    
    # Step 3: Tailor - Generate tailored resume (if enabled)
    if auto_tailor:
        logger.info(f"Step 3: Tailoring resume for job: {url}")
        
        # Check if already tailored
        if current_stage in ("tailor", "apply_failed", "apply_in_progress", "applied"):
            # Already tailored, use existing resume
            tailored_resume_path = existing_dict.get("tailored_resume_path")
            logger.info(f"Job already tailored: {tailored_resume_path}, skipping tailoring step")
            result["tailor"] = {
                "status": "skipped",
                "resume_path": tailored_resume_path,
                "message": "Already tailored, using existing resume",
            }
        else:
            # Need to tailor
            try:
                profile = load_profile()
                job_row = conn.execute("""
                    SELECT url, title, site, company, location, full_description, fit_score
                    FROM jobs WHERE url = ?
                """, (url,)).fetchone()
                job_dict = dict(job_row)
                
                tailored_html, tailor_report = tailor_resume(
                    job=job_dict,
                    profile=profile,
                    max_retries=3,
                    validation_mode="normal",
                )
                
                # Save tailored resume (same logic as tailor.py)
                TAILORED_DIR.mkdir(parents=True, exist_ok=True)
                import re
                
                # Generate filename from job title
                title_safe = re.sub(r'[^\w\s-]', '', job_dict.get("title", "job")).strip()
                title_safe = re.sub(r'[-\s]+', '_', title_safe)[:50]
                prefix = f"{title_safe}_{job_dict.get('site', 'company')[:30]}"
                prefix = re.sub(r'[^\w-]', '', prefix)
                
                html_path = TAILORED_DIR / f"{prefix}.html"
                html_path.write_text(tailored_html, encoding="utf-8")
                
                # Also save .txt version for apply agent
                txt_path = html_path.with_suffix(".txt")
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(tailored_html, "html.parser")
                txt_path.write_text(soup.get_text(separator="\n", strip=True), encoding="utf-8")
                
                # Update database with tailored resume path
                conn.execute("""
                    UPDATE jobs SET tailored_resume_path = ? WHERE url = ?
                """, (str(html_path), url))
                conn.commit()
                
                resume_path = html_path
                
                result["tailor"] = {
                    "status": tailor_report.get("status", "unknown"),
                    "resume_path": str(resume_path),
                    "attempts": tailor_report.get("attempts", 0),
                }
                
                logger.info(f"Tailoring complete: resume_path={resume_path}")
                
            except Exception as e:
                logger.error(f"Tailoring failed: {e}", exc_info=True)
                result["tailor"] = {"status": "error", "error": str(e)}
                # Continue to apply even if tailoring failed (might use base resume)
    
    


@mcp.tool()
def remove_job(url: str) -> dict[str, Any]:
    """Mark a job as skipped in the database (won't be processed for application).
    
    Args:
        url: Job URL to mark as skipped
    
    Returns:
        Removal status
    """
    conn = get_connection()
    
    like = f"%{url.split('?')[0].rstrip('/')}%"
    cursor = conn.execute("""
        UPDATE jobs 
        SET apply_status = 'skipped', apply_error = 'Manually removed'
        WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
          AND tailored_resume_path IS NOT NULL
    """, (url, url, like, like))
    
    conn.commit()
    
    if cursor.rowcount > 0:
        return {
            "status": "success",
            "message": "Job marked as skipped in database",
            "rows_updated": cursor.rowcount,
        }
    else:
        return {
            "status": "not_found",
            "message": f"Job not found in database: {url}",
        }


if __name__ == "__main__":
    # Run the MCP server
    mcp.run()
