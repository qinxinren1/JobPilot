"""Prompt builder for the job application agent.

Builds Claude Code prompts with ATS-specific instructions,
profile data, navigation guidance, and application rules.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from jobpilot.agent.config import (
    load_profile, PROFILE_PATH, TAILORED_DIR, COVER_LETTER_DIR,
    APPLY_WORKER_DIR, BASE_RESUMES_DIR
)
from jobpilot.agent.ats_detector import get_ats_specific_instructions, detect_ats_type


def _build_profile_summary(profile: dict) -> str:
    """Format applicant profile section."""
    p = profile
    personal = p["personal"]
    work_auth = p["work_authorization"]
    comp = p["compensation"]
    exp = p.get("experience", {})
    avail = p.get("availability", {})
    
    lines = [
        f"Name: {personal['full_name']}",
        f"Email: {personal['email']}",
        f"Phone: {personal['phone']}",
    ]
    
    # Address
    addr_parts = [
        personal.get("address", ""),
        personal.get("city", ""),
        personal.get("province_state", ""),
        personal.get("country", ""),
        personal.get("postal_code", ""),
    ]
    lines.append(f"Address: {', '.join(p for p in addr_parts if p)}")
    
    # Links
    if personal.get("linkedin_url"):
        lines.append(f"LinkedIn: {personal['linkedin_url']}")
    if personal.get("github_url"):
        lines.append(f"GitHub: {personal['github_url']}")
    if personal.get("portfolio_url"):
        lines.append(f"Portfolio: {personal['portfolio_url']}")
    
    # Work authorization
    lines.append(f"Work Auth: {work_auth.get('legally_authorized_to_work', 'Yes')}")
    lines.append(f"Sponsorship Needed: {work_auth.get('require_sponsorship', 'No')}")
    if work_auth.get("work_permit_type"):
        lines.append(f"Work Permit: {work_auth['work_permit_type']}")
    
    # Compensation
    currency = comp.get("salary_currency", "USD")
    lines.append(f"Salary Expectation: ${comp['salary_expectation']} {currency}")
    
    # Experience
    if exp.get("years_of_experience_total"):
        lines.append(f"Years Experience: {exp['years_of_experience_total']}")
    if exp.get("education_level"):
        lines.append(f"Education: {exp['education_level']}")
    
    # Availability
    lines.append(f"Available: {avail.get('earliest_start_date', 'Immediately')}")
    
    return "\n".join(lines)


def _build_captcha_section() -> str:
    """Build CAPTCHA solving instructions."""
    capsolver_key = os.environ.get("CAPSOLVER_API_KEY", "")
    
    if not capsolver_key:
        return """== CAPTCHA ==
CAPSOLVER_API_KEY not configured. If you encounter a CAPTCHA:
1. Try manual fallback (audio challenge, simple text puzzles)
2. If unsolvable -> RESULT:CAPTCHA
"""
    
    return f"""== CAPTCHA ==
API key configured: {capsolver_key[:10]}...
If CAPTCHA appears:
1. Detect type (hCaptcha, reCAPTCHA, Turnstile, FunCaptcha)
2. Use CapSolver API to solve (createTask -> poll -> inject token)
3. If API fails -> manual fallback or RESULT:CAPTCHA

Detection script:
browser_evaluate function: () => {{
  const r = {{}};
  // Check for hCaptcha
  const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
  if (hc) {{ r.type = 'hcaptcha'; r.sitekey = hc.dataset.sitekey || hc.dataset.hcaptchaSitekey; }}
  // Check for reCAPTCHA
  const rc = document.querySelector('.g-recaptcha');
  if (rc) {{ r.type = 'recaptchav2'; r.sitekey = rc.dataset.sitekey; }}
  // Check for Turnstile
  const cf = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
  if (cf) {{ r.type = 'turnstile'; r.sitekey = cf.dataset.sitekey; }}
  return r.type ? r : null;
}}

If detected, use CapSolver API to solve, then inject token.
"""


def build_prompt(
    job: dict,
    tailored_resume_text: str,
    cover_letter_text: str = "",
    dry_run: bool = False,
    ats_type: str = "unknown"
) -> str:
    """Build complete prompt for Claude Code agent.
    
    Args:
        job: Job dict with url, title, company, application_url
        tailored_resume_text: Plain text resume content
        cover_letter_text: Cover letter text
        dry_run: If True, don't submit
        ats_type: Detected ATS type
    
    Returns:
        Complete prompt string
    """
    profile = load_profile()
    personal = profile["personal"]
    
    # Resolve resume PDF path
    resume_path = job.get("tailored_resume_path")
    if not resume_path:
        # Fallback to base resume
        if BASE_RESUMES_DIR.exists():
            pdf_files = list(BASE_RESUMES_DIR.glob("*.pdf"))
            if pdf_files:
                resume_path = str(pdf_files[0])
            else:
                raise ValueError("No resume PDF found")
        else:
            raise ValueError("No resume PDF found")
    
    src_pdf = Path(resume_path).with_suffix(".pdf")
    if not src_pdf.exists():
        raise ValueError(f"Resume PDF not found: {src_pdf}")
    
    # Copy to worker dir with clean filename
    full_name = personal["full_name"]
    name_slug = full_name.replace(" ", "_")
    dest_dir = APPLY_WORKER_DIR / "current"
    dest_dir.mkdir(parents=True, exist_ok=True)
    upload_pdf = dest_dir / f"{name_slug}_Resume.pdf"
    shutil.copy(str(src_pdf), str(upload_pdf))
    
    # Cover letter PDF
    cl_upload_path = ""
    if cover_letter_text:
        cl_path = job.get("cover_letter_path")
        if cl_path and Path(cl_path).exists():
            cl_pdf = Path(cl_path).with_suffix(".pdf")
            if cl_pdf.exists():
                cl_upload = dest_dir / f"{name_slug}_Cover_Letter.pdf"
                shutil.copy(str(cl_pdf), str(cl_upload))
                cl_upload_path = str(cl_upload)
    
    # Build sections
    profile_summary = _build_profile_summary(profile)
    captcha_section = _build_captcha_section()
    ats_instructions = get_ats_specific_instructions(ats_type)
    
    # Navigation section
    job_url = job.get("url", "")
    application_url = job.get("application_url")
    
    if application_url and application_url != job_url:
        navigation_section = f"""== NAVIGATION TO APPLICATION FORM ==
You are currently on the job listing page: {job_url}

The application form is at: {application_url}

Steps:
1. Navigate directly to: {application_url}
2. If that URL doesn't work, go back to {job_url} and look for the "Apply" button
3. Once you reach a page with form fields (name, email, resume upload, etc.), you're on the application form
4. If you're still on a job description page, continue searching for the Apply button
"""
    else:
        navigation_section = f"""== NAVIGATION TO APPLICATION FORM ==
You are currently on the job listing/description page: {job_url}

Your goal: Find and navigate to the actual application form (the page with input fields for name, email, resume upload, etc.)

General navigation strategy:
1. Look for buttons with text containing: "Apply", "Application", "Submit"
2. Check for links with href containing: "/apply", "/application", "/form"
3. Look in common locations:
   - Top of job description
   - Sidebar
   - Bottom of job description
   - Header/navigation area
4. If no obvious button, try clicking on job title or "View Details"
5. Some sites require clicking through multiple pages before reaching form
6. Check for popups or modals that may contain application form

IMPORTANT:
- The job listing page is NOT the application form
- You need to click through to reach the form
- Once you see form fields (text inputs, file uploads, dropdowns), you're on the application form
- If you can't find the application form after 3 attempts, output RESULT:FAILED:application_form_not_found
"""
    
    submit_instruction = (
        "IMPORTANT: Do NOT click the final Submit/Apply button. Review the form, verify all fields, then output RESULT:APPLIED with a note that this was a dry run."
        if dry_run
        else "BEFORE clicking Submit/Apply, take a snapshot and review EVERY field on the page. Verify all data matches the APPLICANT PROFILE and TAILORED RESUME -- name, email, phone, location, work auth, resume uploaded, cover letter if applicable. If anything is wrong or missing, fix it FIRST. Only click Submit after confirming everything is correct."
    )
    
    # Phone digits only
    phone_digits = "".join(c for c in personal.get("phone", "") if c.isdigit())
    
    prompt = f"""You are an autonomous job application agent. Your ONE mission: get this candidate an interview. You have all the information and tools. Think strategically. Act decisively. Submit the application.

== JOB ==
Job Listing URL: {job_url}
Application URL: {application_url or "Need to navigate from listing page"}
Title: {job['title']}
Company: {job.get('company', 'Unknown')}

== FILES ==
Resume PDF (upload this): {upload_pdf}
Cover Letter PDF (upload if asked): {cl_upload_path or "N/A"}

== RESUME TEXT (use when filling text fields) ==
{tailored_resume_text}

== COVER LETTER TEXT (paste if text field, upload PDF if file field) ==
{cover_letter_text or "N/A - Skip if optional. If required, write 2 factual sentences about relevant experience."}

== APPLICANT PROFILE ==
{profile_summary}

{navigation_section}

== ATS TYPE: {ats_type.upper()} ==
{ats_instructions}

== YOUR MISSION ==
1. Navigate to the application form (see NAVIGATION section above)
2. Detect and solve any CAPTCHAs (see CAPTCHA section)
3. Handle login if needed (try email/password from profile, or create account)
4. Upload resume PDF (ALWAYS upload fresh, delete any existing resume first)
5. Upload cover letter if there's a field for it
6. Fill ALL form fields from APPLICANT PROFILE
7. Check ALL pre-filled fields (ATS auto-fill is often WRONG - fix mismatches)
8. Answer screening questions truthfully from profile
9. {submit_instruction}
10. After submit: verify success (look for "thank you" or "application received")

== RESULT CODES (output EXACTLY one) ==
RESULT:APPLIED -- submitted successfully
RESULT:EXPIRED -- job closed or no longer accepting applications
RESULT:CAPTCHA -- blocked by unsolvable captcha
RESULT:LOGIN_ISSUE -- could not sign in or create account
RESULT:FAILED:application_form_not_found -- could not navigate to application form
RESULT:FAILED:reason -- any other failure (brief reason)

== HARD RULES (never break these) ==
- Never lie about: citizenship, work authorization, criminal history, education credentials
- Never grant camera, microphone, screen sharing, or location permissions
- Never do video/audio verification, selfie capture, ID photo upload
- Never enter payment info, bank details, or SSN/SIN
- Never install browser extensions or download executables
- If site requests unsafe permissions -> RESULT:FAILED:unsafe_permissions

== FORM FILLING TIPS ==
- Phone field with country prefix: just type digits {phone_digits}
- Date fields: {datetime.now().strftime('%m/%d/%Y')}
- Multi-page forms: fill all fields on each page, click Next/Continue, repeat
- Dropdown won't fill? Click to open it, then click the option
- Checkbox won't check? Use browser_click instead of fill_form
- File upload not working? Try clicking upload button first, then browser_file_upload
- Validation errors after submit? Take snapshot AND screenshot, fix all errors, retry

{captcha_section}

== WHEN TO GIVE UP ==
- Same page after 3 attempts with no progress -> RESULT:FAILED:stuck
- Job is closed/expired/page says "no longer accepting" -> RESULT:EXPIRED
- Page is broken/500 error/blank -> RESULT:FAILED:page_error
- Cannot find application form after 3 navigation attempts -> RESULT:FAILED:application_form_not_found
Stop immediately. Output your RESULT code. Do not loop.
"""
    
    return prompt
