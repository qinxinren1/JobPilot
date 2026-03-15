"""Job fit scoring: LLM-powered evaluation of candidate-job match quality.

Scores jobs on a 1-10 scale by comparing the user's resume against each
job description. All personal data is loaded at runtime from the user's
profile.json (source of truth).

If resume templates are available, uses the best matching template's HTML
instead of generating from profile.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from jobpilot.config import load_profile
from jobpilot.database import get_connection, get_jobs_by_stage, init_resume_templates_table
from jobpilot.llm import get_client
from jobpilot.resume.formatter import generate_resume_text_from_profile

log = logging.getLogger(__name__)


# ── Scoring Prompt ────────────────────────────────────────────────────────

SCORE_PROMPT = """You are a job fit evaluator. Given a candidate's resume and a job description, score how well the candidate fits the role.

SCORING CRITERIA:
- 9-10: Perfect match. Candidate has direct experience in nearly all required skills and qualifications.
- 7-8: Strong match. Candidate has most required skills, minor gaps easily bridged.
- 5-6: Moderate match. Candidate has some relevant skills but missing key requirements.
- 3-4: Weak match. Significant skill gaps, would need substantial ramp-up.
- 1-2: Poor match. Completely different field or experience level.

IMPORTANT FACTORS:
- Weight technical skills heavily (programming languages, frameworks, tools)
- Consider transferable experience (automation, scripting, API work)
- Factor in the candidate's project experience
- Be realistic about experience level vs. job requirements (years of experience, seniority)

RESPOND IN EXACTLY THIS FORMAT (no other text):
SCORE: [1-10]
KEYWORDS: [comma-separated ATS keywords from the job description that match or could match the candidate]
REASONING: [2-3 sentences explaining the score]"""


RESUME_QUALITY_PROMPT = """You are a resume quality evaluator. Given a candidate's resume, evaluate its overall quality and effectiveness.

SCORING CRITERIA:
- 9-10: Excellent resume. Clear structure, strong achievements with metrics, relevant skills well-presented, professional formatting.
- 7-8: Good resume. Well-organized, good achievements, minor improvements possible in presentation or detail.
- 5-6: Average resume. Basic information present but lacks impact, missing metrics, or could be better organized.
- 3-4: Below average. Unclear structure, vague descriptions, missing key information.
- 1-2: Poor resume. Major issues with formatting, content, or completeness.

IMPORTANT FACTORS:
- Structure and organization (clear sections, logical flow)
- Achievement descriptions (quantified results, impact)
- Skills presentation (relevant, well-categorized)
- Professional formatting and readability
- Completeness (contact info, experience, education)

RESPOND IN EXACTLY THIS FORMAT (no other text):
RESUME_SCORE: [1-10]
RESUME_REASONING: [2-3 sentences explaining the resume quality score]"""


def classify_job_role(job: dict, profile: dict) -> str | None:
    """Classify a job into a target role category based on job description.
    
    Uses LLM to match the job against target_roles in the profile.
    
    Args:
        job: Job dict with title and full_description.
        profile: User profile dict containing target_roles.
        
    Returns:
        Role category key (e.g., "frontend", "backend") if matched, None otherwise.
    """
    target_roles = profile.get("target_roles", {})
    if not target_roles:
        return None
    
    # Build role options for the prompt
    role_options = []
    for key, role in target_roles.items():
        name = role.get("name", key)
        skills = role.get("skills_emphasis", [])
        skills_str = ", ".join(skills[:5]) if skills else "N/A"
        role_options.append(f"- {key}: {name} (Skills: {skills_str})")
    
    job_text = (
        f"TITLE: {job.get('title', 'N/A')}\n"
        f"COMPANY: {job.get('site', 'N/A')}\n"
        f"DESCRIPTION:\n{(job.get('full_description') or job.get('description') or '')[:3000]}"
    )
    
    prompt = f"""Analyze this job posting and determine which target role category it best matches.

Available role categories:
{chr(10).join(role_options)}

Job information:
{job_text}

Respond with ONLY the role category key (e.g., "frontend", "backend", "fullstack") if there's a match, or "NONE" if no category matches well enough."""
    
    try:
        client = get_client()
        response = client.chat(
            [
                {"role": "system", "content": "You are a job-role classifier. Respond with only the role category key or 'NONE'."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=20,
            temperature=0.1,
        )
        
        role_key = response.strip().lower()
        if role_key == "none" or role_key not in target_roles:
            return None
        
        return role_key
    except Exception as e:
        log.warning("Failed to classify job role for '%s': %s", job.get("title", "?"), e)
        return None


def _find_matching_resume_template(conn, job: dict, profile: dict = None) -> dict | None:
    """Find the best matching resume template for a job.
    
    Matching logic (only 2 strategies):
    1. Match by role_category: If job has role_category, find template with matching role_category
    2. Use default template (is_default=1) if no role_category match
    
    Args:
        conn: Database connection
        job: Job dict with title, full_description, and optionally role_category
        profile: Optional user profile dict (used for role classification if job doesn't have role_category)
        
    Returns:
        Template dict with keys: file_path, job_position, name, role_category, or None if no templates exist
    """
    init_resume_templates_table(conn)
    
    # Get or classify job role category
    job_role_category = job.get("role_category")
    if not job_role_category and profile:
        # Try to classify the job if not already classified
        job_role_category = classify_job_role(job, profile)
        if job_role_category:
            # Save the classification to the database
            try:
                conn.execute(
                    "UPDATE jobs SET role_category = ? WHERE url = ?",
                    (job_role_category, job.get("url", ""))
                )
                conn.commit()
            except Exception as e:
                log.debug("Failed to save role_category to database: %s", e)
    
    # Strategy 1: Match by role_category (highest priority)
    if job_role_category:
        rows = conn.execute(
            "SELECT file_path, job_position, name, role_category "
            "FROM resume_templates "
            "WHERE role_category = ? AND file_path IS NOT NULL "
            "ORDER BY is_default DESC, uploaded_at DESC",
            (job_role_category,)
        ).fetchall()
        
        if rows:
            # Prefer default template if available, otherwise use most recent
            for row in rows:
                return {
                    "file_path": row[0],
                    "job_position": row[1],
                    "name": row[2],
                    "role_category": row[3]
                }
    
    # Strategy 2: Use default template
    default_row = conn.execute(
        "SELECT file_path, job_position, name, role_category "
        "FROM resume_templates "
        "WHERE is_default = 1 AND file_path IS NOT NULL "
        "LIMIT 1"
    ).fetchone()
    
    if default_row and default_row[0]:
        return {
            "file_path": default_row[0],
            "job_position": default_row[1],
            "name": default_row[2],
            "role_category": default_row[3]
        }
    
    return None


def _extract_text_from_html(html_path: str | Path) -> str:
    """Extract plain text from HTML resume file.
    
    Args:
        html_path: Path to HTML file
        
    Returns:
        Plain text content extracted from HTML
    """
    html_file = Path(html_path)
    if not html_file.exists():
        raise FileNotFoundError(f"HTML file not found: {html_path}")
    
    html_content = html_file.read_text(encoding="utf-8")
    
    # Remove script and style tags
    html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove HTML tags but keep text content
    text = re.sub(r'<[^>]+>', ' ', html_content)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n', text)  # Remove multiple blank lines
    text = text.strip()
    
    return text


def _parse_score_response(response: str) -> dict:
    """Parse the LLM's score response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        {"score": int, "keywords": str, "reasoning": str}
    """
    score = 0
    keywords = ""
    reasoning = response

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score = int(re.search(r"\d+", line).group())
                score = max(1, min(10, score))
            except (AttributeError, ValueError):
                score = 0
        elif line.startswith("KEYWORDS:"):
            keywords = line.replace("KEYWORDS:", "").strip()
        elif line.startswith("REASONING:"):
            reasoning = line.replace("REASONING:", "").strip()

    return {"score": score, "keywords": keywords, "reasoning": reasoning}


def _parse_resume_quality_response(response: str) -> dict:
    """Parse the LLM's resume quality response into structured data.

    Args:
        response: Raw LLM response text.

    Returns:
        {"resume_score": int, "resume_reasoning": str}
    """
    resume_score = 0
    resume_reasoning = response

    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("RESUME_SCORE:"):
            try:
                resume_score = int(re.search(r"\d+", line).group())
                resume_score = max(1, min(10, resume_score))
            except (AttributeError, ValueError):
                resume_score = 0
        elif line.startswith("RESUME_REASONING:"):
            resume_reasoning = line.replace("RESUME_REASONING:", "").strip()

    return {"resume_score": resume_score, "resume_reasoning": resume_reasoning}


def score_job(profile: dict, job: dict, conn=None) -> dict:
    """Score a single job against the candidate's resume.

    If a matching resume template is found, uses its HTML content.
    Otherwise, generates resume text from profile.json.

    Args:
        profile: User profile dict (source of truth).
        job: Job dict with keys: title, site, location, full_description.
        conn: Optional database connection (will create if not provided).

    Returns:
        {"score": int, "keywords": str, "reasoning": str, "resume_source": str, 
         "resume_score": int, "resume_reasoning": str}
    """
    resume_text = None
    resume_source = "profile"
    
    # Try to find matching resume template
    if conn is None:
        conn = get_connection()
    
    try:
        template = _find_matching_resume_template(conn, job, profile)
        if template and template.get("file_path"):
            try:
                resume_text = _extract_text_from_html(template["file_path"])
                resume_source = f"template:{template.get('name', 'unknown')}"
                log.debug("Using resume template '%s' for scoring job: %s", 
                         template.get("name"), job.get("title", "?"))
            except Exception as e:
                log.warning("Failed to read resume template HTML '%s': %s. Falling back to profile.", 
                           template["file_path"], e)
    except Exception as e:
        log.debug("Error finding resume template: %s. Falling back to profile.", e)
    
    # Fallback to profile-generated resume if no template found or failed
    if not resume_text:
        resume_text = generate_resume_text_from_profile(profile)
        resume_source = "profile"
    
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
    )

    messages = [
        {"role": "system", "content": SCORE_PROMPT},
        {"role": "user", "content": f"RESUME:\n{resume_text}\n\n---\n\nJOB POSTING:\n{job_text}"},
    ]

    try:
        client = get_client()
        
        # Score job fit
        response = client.chat(messages, max_tokens=512, temperature=0.2)
        result = _parse_score_response(response)
        result["resume_source"] = resume_source  # Track which resume was used
        
        # Also evaluate resume quality
        try:
            resume_quality_messages = [
                {"role": "system", "content": RESUME_QUALITY_PROMPT},
                {"role": "user", "content": f"RESUME:\n{resume_text}"},
            ]
            resume_quality_response = client.chat(resume_quality_messages, max_tokens=256, temperature=0.2)
            resume_quality = _parse_resume_quality_response(resume_quality_response)
            result["resume_score"] = resume_quality["resume_score"]
            result["resume_reasoning"] = resume_quality["resume_reasoning"]
        except Exception as e:
            log.warning("Failed to evaluate resume quality for job '%s': %s", job.get("title", "?"), e)
            result["resume_score"] = 0
            result["resume_reasoning"] = f"Resume quality evaluation error: {e}"
        
        return result
    except Exception as e:
        log.error("LLM error scoring job '%s': %s", job.get("title", "?"), e)
        return {
            "score": 0, 
            "keywords": "", 
            "reasoning": f"LLM error: {e}", 
            "resume_source": resume_source,
            "resume_score": 0,
            "resume_reasoning": f"LLM error: {e}"
        }


def run_scoring(limit: int = 0, rescore: bool = False) -> dict:
    """Score unscored jobs that have full descriptions.

    All scoring is based on profile.json (source of truth), not resume.txt.

    Args:
        limit: Maximum number of jobs to score in this run.
        rescore: If True, re-score all jobs (not just unscored ones).

    Returns:
        {"scored": int, "errors": int, "elapsed": float, "distribution": list}
    """
    profile = load_profile()
    conn = get_connection()

    if rescore:
        query = "SELECT * FROM jobs WHERE full_description IS NOT NULL"
        if limit > 0:
            query += f" LIMIT {limit}"
        jobs = conn.execute(query).fetchall()
    else:
        jobs = get_jobs_by_stage(conn=conn, stage="pending_score", limit=limit)

    if not jobs:
        log.info("No unscored jobs with descriptions found.")
        return {"scored": 0, "errors": 0, "elapsed": 0.0, "distribution": []}

    # Convert sqlite3.Row to dicts if needed
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    log.info("Scoring %d jobs sequentially...", len(jobs))
    t0 = time.time()
    completed = 0
    errors = 0
    results: list[dict] = []

    for job in jobs:
        result = score_job(profile, job, conn=conn)
        result["url"] = job["url"]
        completed += 1

        if result["score"] == 0:
            errors += 1

        results.append(result)

        resume_source_info = f" [{result.get('resume_source', 'profile')}]" if result.get('resume_source') else ""
        log.info(
            "[%d/%d] score=%d%s  %s",
            completed, len(jobs), result["score"], resume_source_info, job.get("title", "?")[:60],
        )

    # Write scores to DB
    now = datetime.now(timezone.utc).isoformat()
    for r in results:
        resume_score = r.get("resume_score", 0)
        conn.execute(
            "UPDATE jobs SET fit_score = ?, resume_score = ?, score_reasoning = ?, scored_at = ? WHERE url = ?",
            (r["score"], resume_score, f"{r['keywords']}\n{r['reasoning']}", now, r["url"]),
        )
    conn.commit()

    elapsed = time.time() - t0
    log.info("Done: %d scored in %.1fs (%.1f jobs/sec)", len(results), elapsed, len(results) / elapsed if elapsed > 0 else 0)

    # Score distribution
    dist = conn.execute("""
        SELECT fit_score, COUNT(*) FROM jobs
        WHERE fit_score IS NOT NULL
        GROUP BY fit_score ORDER BY fit_score DESC
    """).fetchall()
    distribution = [(row[0], row[1]) for row in dist]

    return {
        "scored": len(results),
        "errors": errors,
        "elapsed": elapsed,
        "distribution": distribution,
    }
