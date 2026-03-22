"""Cover letter generation: LLM-powered, profile-driven, with validation.

Generates concise, engineering-voice cover letters tailored to specific job
postings. All personal data (name, skills, achievements) comes from the user's
profile at runtime. No hardcoded personal information.
"""

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from jobpilot.config import COVER_LETTER_DIR, BASE_COVER_LETTERS_DIR, load_profile
from jobpilot.database import get_connection
from jobpilot.llm import get_client
from jobpilot.scoring.utils import get_safe_name_from_profile
from jobpilot.scoring.validator import (
    BANNED_WORDS,
    LLM_LEAK_PHRASES,
    sanitize_text,
    validate_cover_letter,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # max cross-run retries before giving up


# ── PDF Generation ──────────────────────────────────────────────────────

def generate_cover_letter_pdf(
    cover_letter_text: str,
    output_path: Path,
    profile: dict | None = None,
) -> Path:
    """Generate a well-formatted PDF from cover letter text.
    
    Creates a professional PDF with proper formatting, margins, and typography.
    
    Args:
        cover_letter_text: The cover letter text content
        output_path: Path where the PDF should be saved
        profile: Optional profile dict for contact info in header
        
    Returns:
        Path to the generated PDF file
    """
    from playwright.sync_api import sync_playwright
    
    personal = profile.get("personal", {}) if profile else {}
    full_name = personal.get("full_name", "")
    email = personal.get("email", "")
    phone = personal.get("phone", "")
    city = personal.get("city", "")
    province_state = personal.get("province_state", "")
    
    # Build contact info header
    contact_lines = []
    if full_name:
        contact_lines.append(full_name)
    if email:
        contact_lines.append(email)
    if phone:
        contact_lines.append(phone)
    if city or province_state:
        location = ", ".join(filter(None, [city, province_state]))
        if location:
            contact_lines.append(location)
    
    contact_header = "<br>".join(contact_lines) if contact_lines else ""
    
    # Format the cover letter text - preserve paragraph structure
    # Split by double newlines for paragraphs, single newlines for line breaks within paragraphs
    paragraphs = cover_letter_text.split("\n\n")
    formatted_paragraphs = []
    for para in paragraphs:
        if para.strip():
            # Replace single newlines with <br> within paragraphs
            para_formatted = para.strip().replace("\n", "<br>")
            formatted_paragraphs.append(f"<p>{para_formatted}</p>")
    formatted_text = "".join(formatted_paragraphs)
    
    # Create professional HTML with proper formatting
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
@page {{
    size: A4;
    margin: 1in;
}}
body {{
    font-family: 'Calibri', 'Segoe UI', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
    margin: 0;
    padding: 0;
}}
.header {{
    margin-bottom: 1.5em;
    text-align: right;
    font-size: 10pt;
    color: #333;
    line-height: 1.4;
}}
.content {{
    text-align: left;
}}
.content p {{
    margin: 0 0 1em 0;
    text-align: justify;
}}
.content p:last-child {{
    margin-bottom: 0;
}}
.signature {{
    margin-top: 1.5em;
}}
</style>
</head>
<body>
<div class="header">
{contact_header}
</div>
<div class="content">
{formatted_text}
</div>
</body>
</html>"""
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")
        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            margin={
                "top": "1in",
                "right": "1in",
                "bottom": "1in",
                "left": "1in",
            },
        )
        browser.close()
    
    log.info("Cover letter PDF generated: %s", output_path)
    return output_path


# ── Helpers ──────────────────────────────────────────────────────────────

def _strip_preamble(text: str) -> str:
    """Remove LLM preamble before 'Dear Hiring Manager,' if present.

    Gemini and other models sometimes output "Here is the cover letter:" or
    similar meta-commentary before the actual letter text. Strip everything
    before the first occurrence of "Dear" so the validator's start-check passes.
    """
    dear_idx = text.lower().find("dear")
    if dear_idx > 0:
        return text[dear_idx:]
    return text


# ── Core Generation ──────────────────────────────────────────────────────

def get_or_generate_cover_letter(
    job: dict, profile: dict,
    max_retries: int = 3, validation_mode: str = "normal",
    save_files: bool = True,
) -> tuple[str, str | None, str | None]:
    """Get or generate cover letter for a job.
    
    Unified function that handles all cover letter generation logic:
    1. Get role_category and find base cover letter (multiple fallback strategies)
    2. If found, customize it with LLM
    3. If not found, generate new cover letter using LLM
    4. Optionally save txt and pdf files and update database
    
    Args:
        job: Job dict with title, site, full_description, role_category, url
        profile: User profile dict
        max_retries: Maximum retry attempts
        validation_mode: "strict", "normal", or "lenient"
        save_files: If True, save txt and pdf files and update database
        
    Returns:
        Tuple of (cover_letter_text, txt_path, pdf_path)
        txt_path and pdf_path are None if save_files is False or save failed
    """
    # 1. Get role_category (should already be set from scoring/tailoring)
    role_category = job.get("role_category")
    
    # 2. Check base cover letters: try {name}_{category}.txt, then {category}.txt, then any .txt file
    base_cl_text = None
    
    if role_category:
        name_safe = get_safe_name_from_profile(profile)
        
        # Try 1: {name}_{category}.txt (personalized)
        base_cl_path = BASE_COVER_LETTERS_DIR / f"{name_safe}_{role_category}.txt"
        if base_cl_path.exists():
            base_cl_text = base_cl_path.read_text(encoding="utf-8")
            log.info(f"Found personalized base cover letter: {base_cl_path}")
        else:
            # Try 2: {category}.txt (generic for this category)
            base_cl_path = BASE_COVER_LETTERS_DIR / f"{role_category}.txt"
            if base_cl_path.exists():
                base_cl_text = base_cl_path.read_text(encoding="utf-8")
                log.info(f"Found category base cover letter: {base_cl_path}")
            else:
                # Try 3: Any .txt file in base_cover_letters (use first available as fallback)
                txt_files = list(BASE_COVER_LETTERS_DIR.glob("*.txt"))
                # Exclude templates_meta.json if it's somehow a .txt
                txt_files = [f for f in txt_files if f.name != "templates_meta.txt"]
                if txt_files:
                    base_cl_path = txt_files[0]
                    base_cl_text = base_cl_path.read_text(encoding="utf-8")
                    log.info(f"Found generic base cover letter: {base_cl_path}")

    
    # 4. Customize with LLM (works for both base template and generic template)
    cover_letter_text = _generate_with_llm(
        base_cover_letter=base_cl_text,
        job=job,
        profile=profile,
        max_retries=max_retries,
        validation_mode=validation_mode,
    )
    
    # 5. Save files if requested
    if save_files:
        txt_path, pdf_path = _save_cover_letter_files(cover_letter_text, job, profile)
        return cover_letter_text, txt_path, pdf_path
    return cover_letter_text, None, None


def _save_cover_letter_files(
    cover_letter_text: str, job: dict, profile: dict
) -> tuple[str, str | None]:
    """Save cover letter as both txt and pdf files.
    
    Args:
        cover_letter_text: The cover letter text content
        job: Job dict with url, title, site
        profile: User profile dict
        
    Returns:
        Tuple of (txt_path, pdf_path) where pdf_path may be None if generation failed
    """
    # Build safe filename prefix
    safe_title = re.sub(r"[^\w\s-]", "", job.get("title", "unknown"))[:50].strip().replace(" ", "_")
    safe_site = re.sub(r"[^\w\s-]", "", job.get("site", "unknown"))[:20].strip().replace(" ", "_")
    prefix = f"{safe_site}_{safe_title}"
    
    COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save txt file
    txt_path = COVER_LETTER_DIR / f"{prefix}_CL.txt"
    txt_path.write_text(cover_letter_text, encoding="utf-8")
    log.info("Saved cover letter txt: %s", txt_path)
    
    # Generate and save PDF with formatting
    pdf_path = COVER_LETTER_DIR / f"{prefix}_CL.pdf"
    pdf_path_str = None
    try:
        generate_cover_letter_pdf(cover_letter_text, pdf_path, profile)
        pdf_path_str = str(pdf_path)
        log.info("Saved cover letter PDF: %s", pdf_path)
        
        # Check PDF page count after generation (unified validation at 542)
        pdf_validation = validate_cover_letter(cover_letter_text, mode="normal", pdf_path=pdf_path_str)
        if not pdf_validation["passed"]:
            for error in pdf_validation["errors"]:
                if "PDF exceeds" in error or "pages" in error:
                    log.warning("Cover letter PDF validation failed: %s", error)
    except Exception as e:
        log.warning("Failed to generate cover letter PDF: %s", e)
        pdf_path_str = None
    
    return str(txt_path), pdf_path_str


def _generate_with_llm(
    base_cover_letter: str,
    job: dict, profile: dict,
    max_retries: int = 3, validation_mode: str = "normal",
) -> str:
    """Generate a customized cover letter using LLM.
    
    Unified function that takes a base template (from file or generic) and customizes it
    with company and job-specific information.
    
    Args:
        base_cover_letter: Base cover letter template text
        job:              Job dict with title, site, location, full_description.
        profile:          User profile dict (for sign-off name only).
        max_retries:       Maximum retry attempts.
        validation_mode:  "strict", "normal", or "lenient".
    
    Returns:
        The customized cover letter text (best attempt even if validation failed).
    """
    personal = profile.get("personal", {})
    sign_off_name = personal.get("preferred_name") or personal.get("full_name", "")
    
    # Build the full banned list from the validator
    all_banned = ", ".join(f'"{w}"' for w in BANNED_WORDS)
    leak_banned = ", ".join(f'"{p}"' for p in LLM_LEAK_PHRASES)
    
    avoid_notes: list[str] = []
    letter = ""
    client = get_client()
    
    # Extract company-specific information from job description
    company_context = ""
    job_desc = job.get('full_description', '') or ''
    if job_desc:
        desc_snippet = job_desc[:3000]
        company_context = f"\n\nCOMPANY CONTEXT FROM JOB DESCRIPTION:\n{desc_snippet}\n\nUse specific details from this context to personalize the cover letter for {job.get('site', 'the company')}."
    
    # Build prompt
    customization_prompt = f"""You are generating a Dutch-style cover letter for a specific job application.

BASE COVER LETTER TEMPLATE (use as content foundation):
{base_cover_letter}

TARGET COMPANY: {job.get('site', 'Unknown Company')}
TARGET POSITION: {job.get('title', 'Unknown Position')}
LOCATION: {job.get('location', 'N/A')}

TASK: Generate a cover letter following the Dutch-style 4-paragraph structure. Use the base cover letter template as your content foundation, but restructure it into the required format below.

REQUIRED STRUCTURE (4 PARAGRAPHS):

PARAGRAPH 1 - Opening Positioning:
- Directly state your intention in 2-3 sentences
- Clearly specify the position you're applying for
- Briefly mention your relevant background
- Explain why you're worth continuing to read
- DO NOT put the most useful information in the second paragraph
- Use content from the base template but make it direct and focused

PARAGRAPH 2-3 - Core Evidence:
- Use ONE/TWO precise example to prove your advantages
- Prioritize the experience most relevant to the job tasks
- Describe: SCENARIO (what was the situation), ACTIONS (what you did), RESULTS (what you achieved)
- Dutch recruitment values one precise example more than five vague experiences
- Extract the best example from the base template content

PARAGRAPH 4 - Employer Fit:
- Explain why THIS specific team/company
- Write about specific points that attract you: the role, product, client, team setup, or mission
- Show you understand what problems they are solving (not just praising the company)
- Reference specific details from the job description about their challenges, goals, or approach
- Use content from base template but make it specific to this company and role

PARAGRAPH 5 - Concise Closing:
- Concisely propose the next step
- Express willingness for further communication
- Natural, crisp, and professional
- Avoid forced emotional expression
- Keep it brief and business-appropriate

KEY FORMULA: Ideally, at least one paragraph should simultaneously answer: "Why this role, Why this team, Why you can help"

CONTENT GUIDELINES:
- Use the base cover letter template as your content foundation
- Extract relevant experiences, skills, and achievements from the base template
- Customize all content to be specific to {job.get('site', 'the company')} and the {job.get('title', 'position')} role
- Reference specific details from the job description throughout
{company_context}

BANNED WORDS AND PHRASES (automated validator rejects ANY of these — do not use even once):
{all_banned}

ALSO BANNED (meta-commentary the validator catches):
{leak_banned}

BANNED PUNCTUATION: No em dashes (—) or en dashes (–). Use commas or periods.

Sign off: just "{sign_off_name}"

Output ONLY the cover letter text. No preamble. Start with "Dear Hiring Manager," and end with the sign-off name. Ensure exactly 4 paragraphs separated by blank lines."""

    for attempt in range(max_retries + 1):
        prompt = customization_prompt
        if avoid_notes:
            prompt += "\n\n## AVOID THESE ISSUES:\n" + "\n".join(
                f"- {n}" for n in avoid_notes[-5:]
            )
        
        job_context = f"""JOB DETAILS:
Company: {job.get('site', 'Unknown Company')}
Position: {job.get('title', 'Unknown Position')}
Location: {job.get('location', 'N/A')}

JOB DESCRIPTION:
{job.get('full_description', 'No description available')[:8000]}

Generate a Dutch-style cover letter with exactly 5 paragraphs:
1. Opening Positioning: Directly state intention, position, relevant background (2-3 sentences)
2. Core Evidence: One/Two precise examples with scenario, actions, results
3. Employer Fit: Why this team - specific points about role/product/client/team/mission, show understanding of problems they solve
4. Concise Closing: Natural, crisp closing expressing willingness for further communication

Use the base template content as foundation, but restructure into this format and customize for {job.get('site', 'the company')} and the {job.get('title', 'position')} role."""
        
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": job_context},
        ]
        
        letter = client.chat(messages, max_tokens=1024, temperature=0.7)
        letter = sanitize_text(letter)
        letter = _strip_preamble(letter)
        
        # Unified validation
        validation = validate_cover_letter(letter, mode=validation_mode)
        if validation["passed"]:
            return letter
        
        avoid_notes.extend(validation["errors"])
        log.debug(
            "Cover letter customization attempt %d/%d failed: %s",
            attempt + 1, max_retries + 1, validation["errors"],
        )
    
    return letter  # last attempt even if failed


# ── Batch Entry Point ────────────────────────────────────────────────────

def run_cover_letters(min_score: int = 7, limit: int = 20,
                      validation_mode: str = "normal") -> dict:
    """Generate cover letters for high-scoring jobs that have tailored resumes.

    Args:
        min_score:       Minimum fit_score threshold.
        limit:           Maximum jobs to process.
        validation_mode: "strict", "normal", or "lenient".

    Returns:
        {"generated": int, "errors": int, "elapsed": float}
    """
    profile = load_profile()
    conn = get_connection()

    # Fetch jobs that have tailored resumes but no cover letter yet
    jobs = conn.execute(
        "SELECT * FROM jobs "
        "WHERE fit_score >= ? AND tailored_resume_path IS NOT NULL "
        "AND full_description IS NOT NULL "
        "AND (cover_letter_path IS NULL OR cover_letter_path = '') "
        "AND COALESCE(cover_attempts, 0) < ? "
        "ORDER BY fit_score DESC LIMIT ?",
        (min_score, MAX_ATTEMPTS, limit),
    ).fetchall()

    if not jobs:
        log.info("No jobs needing cover letters (score >= %d).", min_score)
        return {"generated": 0, "errors": 0, "elapsed": 0.0}

    # Convert rows to dicts
    if jobs and not isinstance(jobs[0], dict):
        columns = jobs[0].keys()
        jobs = [dict(zip(columns, row)) for row in jobs]

    COVER_LETTER_DIR.mkdir(parents=True, exist_ok=True)
    log.info(
        "Generating cover letters for %d jobs (score >= %d)...",
        len(jobs), min_score,
    )
    t0 = time.time()
    completed = 0
    results: list[dict] = []
    error_count = 0

    for job in jobs:
        completed += 1
        try:
            # Use unified function - handles all logic (base template lookup, LLM customization, file saving)
            letter, txt_path, pdf_path = get_or_generate_cover_letter(
                job=job,
                profile=profile,
                max_retries=3,
                validation_mode=validation_mode,
                save_files=True,
            )

            result = {
                "url": job["url"],
                "path": txt_path,
                "pdf_path": pdf_path,
                "title": job["title"],
                "site": job["site"],
            }
            results.append(result)

            elapsed = time.time() - t0
            rate = completed / elapsed if elapsed > 0 else 0
            log.info(
                "%d/%d [OK] | %.1f jobs/min | %s",
                completed, len(jobs), rate * 60, result["title"][:40],
            )
        except Exception as e:
            result = {
                "url": job["url"], "title": job["title"], "site": job["site"],
                "path": None, "pdf_path": None, "error": str(e),
            }
            error_count += 1
            results.append(result)
            log.error("%d/%d [ERROR] %s -- %s", completed, len(jobs), job["title"][:40], e)

    # Persist to DB: increment attempt counter for ALL, save path only for successes
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    for r in results:
        if r.get("path"):
            conn.execute(
                "UPDATE jobs SET cover_letter_path=?, cover_letter_at=?, "
                "cover_attempts=COALESCE(cover_attempts,0)+1 WHERE url=?",
                (r["path"], now, r["url"]),
            )
            saved += 1
        else:
            conn.execute(
                "UPDATE jobs SET cover_attempts=COALESCE(cover_attempts,0)+1 WHERE url=?",
                (r["url"],),
            )
    conn.commit()

    elapsed = time.time() - t0
    log.info("Cover letters done in %.1fs: %d generated, %d errors", elapsed, saved, error_count)

    return {
        "generated": saved,
        "errors": error_count,
        "elapsed": elapsed,
    }
