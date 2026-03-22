"""Main job application agent orchestrator.

Handles job queue, Chrome lifecycle, Claude Code invocation,
and result tracking. All data stored in ~/.jobpilot/.
"""

import json
import logging
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from jobpilot.agent.config import (
    ensure_agent_dirs, save_result,
    load_settings, CHROME_WORKER_DIR, APPLY_WORKER_DIR, AGENT_LOGS_DIR,
    TAILORED_DIR
)
from jobpilot.agent.prompts import build_prompt
from jobpilot.agent.ats_detector import detect_ats_type, is_manual_ats

logger = logging.getLogger(__name__)

# Chrome CDP port base
BASE_CDP_PORT = 9222

# Track Chrome processes for cleanup
_chrome_procs: dict[int, subprocess.Popen] = {}


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children."""
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        else:
            import os
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
    except Exception:
        logger.debug(f"Failed to kill process tree for PID {pid}", exc_info=True)


def launch_chrome(worker_id: int, headless: bool = False) -> subprocess.Popen:
    """Launch Chrome with CDP enabled.
    
    Returns:
        Chrome process handle
    """
    from jobpilot.config import get_chrome_path
    
    chrome_path = get_chrome_path()
    port = BASE_CDP_PORT + worker_id
    
    # Worker profile directory
    worker_dir = CHROME_WORKER_DIR / f"worker-{worker_id}"
    worker_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={worker_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,720",
        "--disable-blink-features=AutomationControlled",
        "--disable-session-crashed-bubble",
        "--disable-features=InfiniteSessionRestore",
        "--hide-crash-restore-bubble",
        "--noerrdialogs",
        "--password-store=basic",
        "--disable-popup-blocking",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--deny-permission-prompts",
        "--disable-notifications",
    ]
    
    if headless:
        cmd.append("--headless=new")
    
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if platform.system() != "Windows":
        import os
        kwargs["preexec_fn"] = os.setsid
    
    proc = subprocess.Popen(cmd, **kwargs)
    _chrome_procs[worker_id] = proc
    
    # Wait for Chrome to start
    time.sleep(3)
    
    logger.info(f"Launched Chrome worker {worker_id} on port {port}")
    return proc


def cleanup_chrome(worker_id: int) -> None:
    """Cleanup Chrome process for a worker."""
    if worker_id in _chrome_procs:
        proc = _chrome_procs[worker_id]
        if proc.poll() is None:
            _kill_process_tree(proc.pid)
        del _chrome_procs[worker_id]


def kill_all_chrome() -> None:
    """Kill all Chrome processes."""
    for worker_id in list(_chrome_procs.keys()):
        cleanup_chrome(worker_id)


def make_mcp_config(cdp_port: int) -> dict:
    """Build MCP config for Claude Code."""
    settings = load_settings()
    viewport = settings.get("viewport", "1280x720")
    
    return {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": [
                    "@playwright/mcp@latest",
                    f"--cdp-endpoint=http://localhost:{cdp_port}",
                    f"--viewport-size={viewport}",
                ],
            },
        }
    }


def run_job_application(
    job: dict,
    worker_id: int = 0,
    model: str = "sonnet",
    headless: bool = False,
    dry_run: bool = False
) -> dict:
    """Run single job application via Claude Code.
    
    Returns:
        Result dict with status, duration_ms, error, etc.
    """
    start_time = time.time()
    
    # Check if manual ATS
    apply_url = job.get("application_url") or job.get("url", "")
    if apply_url and is_manual_ats(apply_url):
        return {
            "status": "skipped",
            "reason": "manual_ats",
            "duration_ms": 0,
        }
    
    # Detect ATS type
    ats_type = detect_ats_type(apply_url) if apply_url else "unknown"
    logger.info(f"Detected ATS type: {ats_type} for {apply_url}")
    
    # Load resume text
    resume_path = job.get("tailored_resume_path")
    resume_text = ""
    if resume_path:
        txt_path = Path(resume_path).with_suffix(".txt")
        if txt_path.exists():
            resume_text = txt_path.read_text(encoding="utf-8")
        else:
            # Try to find any .txt file in tailored_resumes
            if TAILORED_DIR.exists():
                txt_files = list(TAILORED_DIR.glob("*.txt"))
                if txt_files:
                    resume_text = txt_files[0].read_text(encoding="utf-8")
    
    # Load cover letter
    cover_letter_text = ""
    cl_path = job.get("cover_letter_path")
    if cl_path:
        cl_txt = Path(cl_path).with_suffix(".txt")
        if cl_txt.exists():
            cover_letter_text = cl_txt.read_text(encoding="utf-8")
    
    # Build prompt
    try:
        prompt = build_prompt(
            job=job,
            tailored_resume_text=resume_text,
            cover_letter_text=cover_letter_text,
            dry_run=dry_run,
            ats_type=ats_type,
        )
    except Exception as e:
        logger.error(f"Failed to build prompt: {e}")
        return {
            "status": "failed",
            "reason": f"prompt_build_error: {str(e)}",
            "duration_ms": int((time.time() - start_time) * 1000),
        }
    
    # Write MCP config
    port = BASE_CDP_PORT + worker_id
    mcp_config_path = APPLY_WORKER_DIR / f"mcp-{worker_id}.json"
    mcp_config_path.write_text(
        json.dumps(make_mcp_config(port), indent=2),
        encoding="utf-8"
    )
    
    # Find Claude CLI
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        # Try common locations
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
        return {
            "status": "failed",
            "reason": "claude_cli_not_found",
            "duration_ms": int((time.time() - start_time) * 1000),
        }
    
    # Launch Chrome
    chrome_proc = None
    try:
        chrome_proc = launch_chrome(worker_id, headless=headless)
        
        # Build Claude command
        cmd = [
            claude_cmd,
            "--model", model,
            "-p",
            "--mcp-config", str(mcp_config_path),
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
            "--output-format", "stream-json",
            "-",
        ]
        
        # Run Claude
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        
        proc.stdin.write(prompt)
        proc.stdin.close()
        
        # Parse output
        output_lines = []
        text_parts = []
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "assistant":
                    for block in msg.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                            output_lines.append(block["text"])
                        elif block.get("type") == "tool_use":
                            tool_name = block.get("name", "").replace("mcp__playwright__", "")
                            output_lines.append(f"  >> {tool_name}")
            except json.JSONDecodeError:
                text_parts.append(line)
                output_lines.append(line)
        
        proc.wait(timeout=300)
        output = "\n".join(text_parts)
        
        # Save log
        log_file = AGENT_LOGS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_w{worker_id}_{job.get('title', 'job')[:30].replace(' ', '_')}.txt"
        log_file.write_text(output, encoding="utf-8")
        
        # Parse result
        duration_ms = int((time.time() - start_time) * 1000)
        result = _parse_result(output, duration_ms)
        
        return result
        
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "status": "failed",
            "reason": "timeout",
            "duration_ms": duration_ms,
        }
    except Exception as e:
        logger.exception(f"Error running job application: {e}")
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "status": "failed",
            "reason": f"error: {str(e)[:100]}",
            "duration_ms": duration_ms,
        }
    finally:
        # Cleanup Chrome
        if chrome_proc:
            cleanup_chrome(worker_id)


def _parse_result(output: str, duration_ms: int) -> dict:
    """Parse RESULT code from Claude output."""
    output_upper = output.upper()
    
    if "RESULT:APPLIED" in output_upper:
        return {"status": "applied", "duration_ms": duration_ms}
    
    if "RESULT:EXPIRED" in output_upper:
        return {"status": "expired", "duration_ms": duration_ms}
    
    if "RESULT:CAPTCHA" in output_upper:
        return {"status": "failed", "reason": "captcha", "duration_ms": duration_ms}
    
    if "RESULT:LOGIN_ISSUE" in output_upper:
        return {"status": "failed", "reason": "login_issue", "duration_ms": duration_ms}
    
    if "RESULT:FAILED" in output_upper:
        # Extract reason
        for line in output.split("\n"):
            if "RESULT:FAILED" in line.upper():
                parts = line.split(":", 2)
                reason = parts[2].strip() if len(parts) > 2 else "unknown"
                return {"status": "failed", "reason": reason, "duration_ms": duration_ms}
    
    return {"status": "failed", "reason": "no_result", "duration_ms": duration_ms}


def run_agent(
    limit: Optional[int] = None,
    target_url: Optional[str] = None,
    workers: int = 1,
    model: str = "sonnet",
    headless: bool = False,
    dry_run: bool = False,
    min_score: int = 7,
) -> None:
    """Main agent entry point.
    
    Reads jobs from database (jobs table),
    processes them, saves results to ~/.jobpilot/agent_results.json
    """
    ensure_agent_dirs()
    
    # Register cleanup on exit
    import atexit
    atexit.register(kill_all_chrome)
    if platform.system() != "Windows":
        signal.signal(signal.SIGTERM, lambda *_: (kill_all_chrome(), sys.exit(0)))
    
    # Load jobs from database
    from jobpilot.database import get_connection, init_db
    from jobpilot.config import load_blocked_sites
    
    init_db()
    conn = get_connection()
    blocked_sites, blocked_patterns = load_blocked_sites()
    
    # Build query
    params: list = [min_score]
    site_clause = ""
    if blocked_sites:
        placeholders = ",".join("?" * len(blocked_sites))
        site_clause = f"AND site NOT IN ({placeholders})"
        params.extend(blocked_sites)
    url_clauses = ""
    if blocked_patterns:
        url_clauses = " ".join("AND url NOT LIKE ?" for _ in blocked_patterns)
        params.extend(blocked_patterns)
    
    if target_url:
        like = f"%{target_url.split('?')[0].rstrip('/')}%"
        query = f"""
            SELECT url, title, site, company, application_url, tailored_resume_path,
                   fit_score, location, full_description, cover_letter_path
            FROM jobs
            WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
              AND tailored_resume_path IS NOT NULL
              AND (apply_status IS NULL OR apply_status = 'failed')
              AND (apply_attempts IS NULL OR apply_attempts < 5)
              AND fit_score >= ?
              {site_clause}
              {url_clauses}
        """
        params = [target_url, target_url, like, like] + params
    else:
        query = f"""
            SELECT url, title, site, company, application_url, tailored_resume_path,
                   fit_score, location, full_description, cover_letter_path
            FROM jobs
            WHERE tailored_resume_path IS NOT NULL
              AND (apply_status IS NULL OR apply_status = 'failed')
              AND (apply_attempts IS NULL OR apply_attempts < 5)
              AND fit_score >= ?
              {site_clause}
              {url_clauses}
            ORDER BY fit_score DESC, discovered_at DESC
        """
        if limit:
            query += " LIMIT ?"
            params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    
    if not rows:
        logger.warning("No jobs found in database ready for application")
        return
    
    # Convert to dicts
    jobs = [dict(row) for row in rows]
    
    logger.info(f"Found {len(jobs)} jobs ready for application")
    
    # Process jobs
    processed = 0
    for i, job in enumerate(jobs):
        if limit and processed >= limit:
            break
        
        worker_id = i % workers
        
        logger.info(f"Processing job {i+1}/{len(jobs)}: {job.get('title', 'Unknown')} (Score: {job.get('fit_score', 'N/A')})")
        
        result = run_job_application(
            job=job,
            worker_id=worker_id,
            model=model,
            headless=headless,
            dry_run=dry_run,
        )
        
        # Update database with result
        from datetime import timezone as tz
        now = datetime.now(tz.utc).isoformat()
        job_url = job.get("url")
        status = result.get("status", "unknown")
        reason = result.get("reason", "")
        duration_ms = result.get("duration_ms", 0)
        
        if status == "applied":
            conn.execute("""
                UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                               apply_error = NULL, apply_duration_ms = ?
                WHERE url = ?
            """, (now, duration_ms, job_url))
        elif status == "expired":
            conn.execute("""
                UPDATE jobs SET apply_status = 'expired', apply_error = 'Job expired',
                               apply_attempts = COALESCE(apply_attempts, 0) + 1,
                               apply_duration_ms = ?
                WHERE url = ?
            """, (duration_ms, job_url))
        else:
            # failed or other status
            permanent = status in ("expired", "manual")
            attempts = 99 if permanent else "COALESCE(apply_attempts, 0) + 1"
            conn.execute(f"""
                UPDATE jobs SET apply_status = ?, apply_error = ?,
                               apply_attempts = {attempts}, apply_duration_ms = ?
                WHERE url = ?
            """, (status, reason or "unknown", duration_ms, job_url))
        conn.commit()
        
        # Save result to JSON (for backward compatibility)
        result.update({
            "job_url": job_url,
            "job_title": job.get("title"),
            "company": job.get("company") or job.get("site"),
            "timestamp": now,
        })
        save_result(result)
        
        processed += 1
        logger.info(f"Result: {status} ({reason})")
        
        # Cleanup after each job
        cleanup_chrome(worker_id)
    
    logger.info(f"Processed {processed} jobs")
    kill_all_chrome()
