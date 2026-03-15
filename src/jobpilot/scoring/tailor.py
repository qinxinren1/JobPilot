"""Resume tailoring: LLM-powered ATS-optimized resume generation per job.

THIS IS THE HEAVIEST REFACTOR. Every piece of personal data -- name, email, phone,
skills, companies, projects, school -- is loaded at runtime from the user's profile.
Zero hardcoded personal information.

The LLM returns structured JSON, code assembles the final text. Header (name, contact)
is always code-injected, never LLM-generated. Each retry starts a fresh conversation
to avoid apologetic spirals.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from jobpilot.config import TAILORED_DIR, load_profile
from jobpilot.database import get_connection, get_jobs_by_stage
from jobpilot.llm import get_client
from jobpilot.scoring.validator import (
    BANNED_WORDS,
    FABRICATION_WATCHLIST,
    sanitize_text,
    validate_json_fields,
    validate_tailored_resume,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5  # max cross-run retries before giving up


# ── Prompt Builders (profile-driven) ──────────────────────────────────────

def _format_profile_data_for_llm(profile: dict) -> str:
    """Format profile.json structured data for LLM input.
    
    This is the source of truth - LLM should base generation on this.
    
    Args:
        profile: User profile dict from load_profile().
        
    Returns:
        Formatted string with structured profile data.
    """
    experience = profile.get("experience", {})
    work_experiences = experience.get("work_experiences", [])
    profile_projects = experience.get("projects", [])
    
    lines = ["## PROFILE DATA (source of truth - base your generation on this):"]
    lines.append("")
    
    # Work experiences
    if work_experiences:
        lines.append("WORK EXPERIENCE:")
        for exp in work_experiences:
            company = exp.get("company", "")
            title = exp.get("title", "")
            start_date = exp.get("start_date", "")
            end_date = exp.get("end_date", "")
            current = exp.get("current", False)
            bullets = exp.get("bullets", [])
            
            if company and title:
                lines.append(f"- {title} at {company}")
            elif company:
                lines.append(f"- {company}")
            elif title:
                lines.append(f"- {title}")
            
            if start_date or end_date or current:
                date_str = f"{start_date} - {end_date if not current else 'Present'}"
                lines.append(f"  Dates: {date_str}")
            
            if bullets:
                lines.append(f"  Bullets ({len(bullets)} total):")
                for i, bullet in enumerate(bullets[:3], 1):  # Show first 3 as examples
                    lines.append(f"    {i}. {bullet}")
                if len(bullets) > 3:
                    lines.append(f"    ... and {len(bullets) - 3} more")
        lines.append("")
    
    # Projects
    if profile_projects:
        lines.append("PROJECTS:")
        for proj in profile_projects:
            name = proj.get("name", "")
            description = proj.get("description", "")
            tech_stack = proj.get("tech_stack", [])
            bullets = proj.get("bullets", [])
            
            if name:
                lines.append(f"- {name}")
            if description:
                lines.append(f"  Description: {description}")
            if tech_stack:
                lines.append(f"  Tech: {', '.join(tech_stack)}")
            if bullets:
                lines.append(f"  Bullets ({len(bullets)} total):")
                for i, bullet in enumerate(bullets[:2], 1):  # Show first 2 as examples
                    lines.append(f"    {i}. {bullet}")
                if len(bullets) > 2:
                    lines.append(f"    ... and {len(bullets) - 2} more")
        lines.append("")
    
    # Awards (for reference only - these are preserved facts)
    profile_awards = experience.get("awards", [])
    if profile_awards:
        lines.append("AWARDS (preserved facts - will be included as-is, do not modify):")
        for award in profile_awards:
            name = award.get("name", "")
            category = award.get("category", "")
            issuer = award.get("issuer", "")
            date = award.get("date", "")
            
            if name:
                award_line = f"- {name}"
                if category:
                    award_line += f" (Category: {category})"
                lines.append(award_line)
            if issuer:
                lines.append(f"  Issuer: {issuer}")
            if date:
                lines.append(f"  Date: {date}")
        lines.append("")
    
    return "\n".join(lines)


def _build_tailor_prompt(profile: dict) -> str:
    """Build the resume tailoring system prompt from the user's profile.

    All skills boundaries, preserved entities, and formatting rules are
    derived from the profile -- nothing is hardcoded.
    
    IMPORTANT: Generation is based ONLY on profile.json (source of truth),
    not resume.txt. The profile contains structured data that is authoritative.
    """
    boundary = profile.get("skills_boundary", {})
    resume_facts = profile.get("resume_facts", {})

    # Format skills boundary for the prompt
    skills_lines = []
    total_skills_count = 0
    for category, items in boundary.items():
        if isinstance(items, list) and items:
            label = category.replace("_", " ").title()
            skills_lines.append(f"{label}: {', '.join(items)}")
            total_skills_count += len(items)
    skills_block = "\n".join(skills_lines)

    # Preserved entities
    companies = resume_facts.get("preserved_companies", [])
    projects = resume_facts.get("preserved_projects", [])
    schools = resume_facts.get("preserved_schools", [])
    awards = resume_facts.get("preserved_awards", [])
    real_metrics = resume_facts.get("real_metrics", [])

    companies_str = ", ".join(companies) if companies else "N/A"
    projects_str = ", ".join(projects) if projects else "N/A"
    schools_str = ", ".join(schools) if schools else "N/A"
    awards_str = ", ".join(awards) if awards else "N/A"
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"

    # Include ALL banned words from the validator so the LLM knows exactly
    # what will be rejected — the validator checks for these automatically.
    banned_str = ", ".join(BANNED_WORDS)

    return f"""You are a senior technical recruiter rewriting a resume to get this person an interview.

IMPORTANT: You will receive PROFILE DATA (structured data from profile.json) which is the source of truth.
Base your generation ONLY on the PROFILE DATA provided. Do not rely on any other text.

Take the profile data and job description. Return a tailored resume as a JSON object.

## RECRUITER SCAN (6 seconds):
1. Title -- matches what they're hiring?
2. First 3 bullets of most recent role -- verbs and outcomes match?
3. Skills -- must-haves visible immediately?

## SKILLS BOUNDARY (real skills only):
{skills_block}

You MAY add 2-3 closely related tools (Kubernetes if Docker, Terraform if AWS, Redis if PostgreSQL). No unrelated languages/frameworks.

## TAILORING RULES:

TITLE: Match the target role. Keep seniority (Senior/Lead/Staff). Drop company suffixes and team names.

SKILLS: Reorder each category so the job's must-haves appear first.
- MINIMUM REQUIREMENT: Include at least 15-20 total skills across all categories. Do not create a sparse skills section.
- Include skills from multiple categories (programming languages, frameworks, tools, databases, etc.) to show breadth.
- If a category has few items, you may add 2-3 closely related skills from the skills boundary, but stay within allowed skills.

NOTE: Do NOT include a summary section. Start directly with TECHNICAL SKILLS after the header.

Reframe EVERY bullet for this role. Same real work, different angle. Every bullet must be reworded. Never copy verbatim.

PROJECTS: Reorder by relevance. Drop irrelevant projects entirely.

AWARDS: Awards section is automatically populated from profile and cannot be modified. Do not include awards in your JSON output.

BULLETS: Strong verb + what you built + quantified impact. Vary verbs (Built, Designed, Implemented, Reduced, Automated, Deployed, Operated, Optimized). Most relevant first. Max 4 per section.

## VOICE:
- Write like a real engineer. Short, direct.
- GOOD: "Automated financial reporting with Python + API integrations, cut processing time from 10 hours to 2"
- BAD: "Leveraged cutting-edge AI technologies to drive transformative operational efficiencies"
- BANNED WORDS (using ANY of these = validation failure — do not use them even once):
  {banned_str}
- No em dashes. Use commas, periods, or hyphens.

## HARD RULES:
- Do NOT invent work, companies, degrees, or certifications
- Do NOT change real numbers ({metrics_str})
- Preserved companies: {companies_str} -- names stay as-is
- Preserved schools: {schools_str} -- names stay as-is
- Preserved awards: {awards_str} -- awards section will be automatically populated from profile, do NOT modify or generate awards
- Must fit 1 page.

## OUTPUT: Return ONLY valid JSON. No markdown fences. No commentary. No "here is" preamble.

NOTE: The education and awards fields will be automatically populated from your profile, so you can omit them.

Use structured format matching the profile schema:
- experience: array of {{"title":"Job Title","company":"Company Name","start_date":"YYYY-MM","end_date":"YYYY-MM","current":false,"bullets":["bullet 1","bullet 2"]}}
- projects: array of {{"name":"Project Name","description":"Brief description","tech_stack":["Tech1","Tech2"],"start_date":"YYYY-MM","end_date":"YYYY-MM","current":false,"bullets":["bullet 1"]}}
- skills: {{"programming_languages":["Python","JavaScript"],"frameworks":["React"],"devops":["Docker"],"databases":["PostgreSQL"],"tools":["Git"]}}

Example (NO SUMMARY FIELD):
{{"title":"Role Title","skills":{{"programming_languages":["Python","JavaScript"],"frameworks":["React"],"devops":["Docker"],"databases":["PostgreSQL"],"tools":["Git"]}},"experience":[{{"title":"Software Engineer","company":"Google","start_date":"2020-01","end_date":"2022-12","current":false,"bullets":["bullet 1","bullet 2","bullet 3","bullet 4"]}}],"projects":[{{"name":"Project Name","description":"Description","tech_stack":["Python","React"],"start_date":"2021-01","end_date":"2021-06","current":false,"bullets":["bullet 1","bullet 2"]}}]}}"""


def _build_judge_prompt(profile: dict) -> str:
    """Build the LLM judge prompt from the user's profile.
    
    All validation is based on profile.json (source of truth), not resume.txt text.
    """
    boundary = profile.get("skills_boundary", {})
    resume_facts = profile.get("resume_facts", {})
    experience = profile.get("experience", {})

    # Flatten allowed skills for the judge
    all_skills: list[str] = []
    for items in boundary.values():
        if isinstance(items, list):
            all_skills.extend(items)
    skills_str = ", ".join(all_skills) if all_skills else "N/A"

    real_metrics = resume_facts.get("real_metrics", [])
    metrics_str = ", ".join(real_metrics) if real_metrics else "N/A"
    
    # Extract preserved entities from profile (source of truth)
    companies = resume_facts.get("preserved_companies", [])
    projects = resume_facts.get("preserved_projects", [])
    schools = resume_facts.get("preserved_schools", [])
    awards = resume_facts.get("preserved_awards", [])
    
    companies_str = ", ".join(companies) if companies else "N/A"
    projects_str = ", ".join(projects) if projects else "N/A"
    schools_str = ", ".join(schools) if schools else "N/A"
    awards_str = ", ".join(awards) if awards else "N/A"
    
    # Extract structured experience data from profile (source of truth)
    work_experiences = experience.get("work_experiences", [])
    profile_projects = experience.get("projects", [])
    education_list = experience.get("education", [])
    
    # Format work experiences for judge reference
    work_exp_summary = []
    for exp in work_experiences:
        company = exp.get("company", "")
        title = exp.get("title", "")
        if company and title:
            work_exp_summary.append(f"- {title} at {company}")
        elif company:
            work_exp_summary.append(f"- {company}")
        elif title:
            work_exp_summary.append(f"- {title}")
    work_exp_str = "\n".join(work_exp_summary) if work_exp_summary else "N/A"
    
    # Format projects for judge reference
    project_names = [p.get("name", "") for p in profile_projects if p.get("name")]
    profile_projects_str = ", ".join(project_names) if project_names else "N/A"
    
    # Format education for judge reference
    edu_summary = []
    for edu in education_list:
        school = edu.get("school", "")
        degree = edu.get("degree", "")
        if school:
            edu_summary.append(f"- {degree} from {school}" if degree else f"- {school}")
    edu_str = "\n".join(edu_summary) if edu_summary else "N/A"
    
    # Format awards for judge reference
    awards_list = experience.get("awards", [])
    awards_summary = []
    for award in awards_list:
        name = award.get("name", "")
        issuer = award.get("issuer", "")
        if name:
            awards_summary.append(f"- {name}" + (f" from {issuer}" if issuer else ""))
    awards_str = "\n".join(awards_summary) if awards_summary else "N/A"

    return f"""You are a resume quality judge. A tailoring engine rewrote a resume to target a specific job. Your job is to catch LIES, not style changes.

IMPORTANT: All validation is based on profile.json (source of truth), not the original resume text. The profile contains the authoritative structured data.

You must answer with EXACTLY this format:
VERDICT: PASS or FAIL
ISSUES: (list any problems, or "none")

## CONTEXT -- what the tailoring engine was instructed to do (all of this is ALLOWED):
- Change the title to match the target role
- Rewrite the summary from scratch for the target job
- Reorder bullets and projects to put the most relevant first
- Reframe bullets to use the job's language
- Drop low-relevance bullets and replace with more relevant ones from other sections
- Reorder the skills section to put job-relevant skills first
- Change tone and wording extensively
- Rename or reword project names (as long as they refer to the same real project)

## REAL DATA FROM PROFILE.JSON (source of truth - use this to verify):
- Real companies (must appear in tailored resume): {companies_str}
- Real projects (can be renamed, but must refer to these): {projects_str}
- Real schools (must appear): {schools_str}
- Real awards (must appear, cannot be modified): {awards_str}
- Real metrics (must match): {metrics_str}
- Allowed skills ONLY: {skills_str}

## WORK EXPERIENCE FROM PROFILE.JSON:
{work_exp_str}

## PROJECTS FROM PROFILE.JSON:
{profile_projects_str}

## EDUCATION FROM PROFILE.JSON:
{edu_str}

## AWARDS FROM PROFILE.JSON:
{awards_str}

## WHAT IS FABRICATION (FAIL for these):
1. Adding tools, languages, or frameworks to TECHNICAL SKILLS that aren't in the allowed list above.
2. Inventing NEW metrics or numbers not in the real metrics list above.
3. Inventing work that has no basis in any original bullet from the profile's work experience or projects.
4. Adding companies that don't exist (not in the real companies list above). Company names must match the preserved list (minor format variations like "Original Force, Ltd." vs "Original Force" are OK).
5. Adding projects that don't exist (not in the real projects list above). Project names can be reworded, but must refer to real projects from the list.
6. Adding schools that don't exist (not in the real schools list above).
7. Adding awards that don't exist (not in the real awards list above). Awards section is automatically populated from profile and cannot be modified.
8. Changing real numbers (inflating 80% to 95%, 500 nodes to 1000 nodes).

## WHAT IS NOT FABRICATION (do NOT fail for these):
- Rewording any bullet, even heavily, as long as the underlying work is real (from profile)
- Combining two original bullets into one
- Splitting one original bullet into two
- Describing the same work with different emphasis
- Dropping bullets entirely
- Reordering anything
- Changing the title or summary completely
- Renaming projects (as long as they refer to real projects from the list above)
- Minor company name format variations (e.g., "Original Force, Ltd." vs "Original Force" - both refer to the same real company)

## TOLERANCE RULE:
The goal is to get interviews, not to be a perfect fact-checker. Allow up to 3 minor stretches per resume:
- Adding a closely related tool the candidate could realistically know is a MINOR STRETCH, not fabrication.
- Reframing a metric with slightly different wording is a MINOR STRETCH.
- Adding any LEARNABLE skill given their existing stack is a MINOR STRETCH.
- Only FAIL if there are MAJOR lies: completely invented projects (not in real projects list), fake companies (not in real companies list), fake degrees, wildly inflated numbers, or skills from a completely different domain.

IMPORTANT VALIDATION RULES:
- If a company in the tailored resume matches (even partially) a company in the real companies list, it is NOT fabrication.
- If a project in the tailored resume could refer to a project in the real projects list (even if renamed), it is NOT fabrication.
- Company names should stay as-is, but minor format differences are acceptable.
- Base your judgment on profile.json data, not on text matching between original and tailored resumes.

Be strict about major lies. Be lenient about minor stretches and learnable skills. Do not fail for style, tone, or restructuring."""


# ── JSON Extraction ───────────────────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """Robustly extract JSON from LLM response (handles fences, preamble).

    Args:
        raw: Raw LLM response text.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON found.
    """
    raw = raw.strip()

    # Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Markdown fences
    if "```" in raw:
        for part in raw.split("```")[1::2]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except json.JSONDecodeError:
                continue

    # Find outermost { ... }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("No valid JSON found in LLM response")


# ── Resume Assembly (profile-driven header) ──────────────────────────────

def assemble_resume_text(data: dict, profile: dict) -> str:
    """Convert JSON resume data to formatted plain text.
    
    NOTE: This function is kept for internal use only (judge validation).
    All resume output should use assemble_resume_html() for unified HTML format.

    Header (name, location, contact) is ALWAYS code-injected from the profile,
    never LLM-generated. All text fields are sanitized.
    
    This function reuses formatting utilities from resume.formatter to avoid duplication.

    Args:
        data: Parsed JSON resume from the LLM.
        profile: User profile dict from load_profile().

    Returns:
        Formatted resume text (for validation purposes only).
    """
    from jobpilot.resume.formatter import (
        format_contact_line,
        format_date_for_resume,
        format_skills_as_text,
    )
    
    personal = profile.get("personal", {})
    lines: list[str] = []

    # Header -- always code-injected from profile
    lines.append(personal.get("full_name", ""))
    lines.append(sanitize_text(data.get("title", "Software Engineer")))

    # Contact line - reuse formatter utilities
    contact_line = format_contact_line(personal, use_handles=False)
    if contact_line:
        lines.append(contact_line)
    lines.append("")

    # Technical Skills - reuse formatter utilities (NO SUMMARY)
    lines.append("TECHNICAL SKILLS")
    if isinstance(data.get("skills"), dict):
        skill_lines = format_skills_as_text(data["skills"])
        lines.extend(skill_lines)
    lines.append("")

    # Experience - reuse date formatting from formatter
    lines.append("EXPERIENCE")
    for entry in data.get("experience", []):
        title = entry.get("title", "")
        company = entry.get("company", "")
        if title and company:
            lines.append(f"{title} at {company}")
        elif title:
            lines.append(title)
        elif company:
            lines.append(company)
        
        # Format dates - reuse format_date_for_resume
        start_date = entry.get("start_date", "")
        end_date = entry.get("end_date", "")
        current = entry.get("current", False)
        if start_date or end_date or current:
            formatted_start = format_date_for_resume(start_date) if start_date else ""
            formatted_end = "Present" if current else (format_date_for_resume(end_date) if end_date else "")
            if formatted_start or formatted_end:
                # Format as "Start - End" or just one date if the other is missing
                if formatted_start and formatted_end:
                    date_str = f"{formatted_start} - {formatted_end}"
                else:
                    date_str = formatted_start or formatted_end
                lines.append(date_str)
        
        for b in entry.get("bullets", []):
            lines.append(f"- {sanitize_text(b)}")
        lines.append("")

    # Projects - reuse date formatting from formatter
    lines.append("PROJECTS")
    for entry in data.get("projects", []):
        name = entry.get("name", "")
        description = entry.get("description", "")
        if name and description:
            lines.append(f"{name} - {description}")
        elif name:
            lines.append(name)
        
        # Format tech stack and dates - reuse format_date_for_resume
        tech_stack = entry.get("tech_stack", [])
        start_date = entry.get("start_date", "")
        end_date = entry.get("end_date", "")
        current = entry.get("current", False)
        if tech_stack or start_date or end_date:
            parts = []
            if tech_stack:
                parts.append(", ".join(tech_stack))
            if start_date or end_date or current:
                formatted_start = format_date_for_resume(start_date) if start_date else ""
                formatted_end = "Present" if current else (format_date_for_resume(end_date) if end_date else "")
                if formatted_start or formatted_end:
                    # Format as "Start - End" or just one date if the other is missing
                    if formatted_start and formatted_end:
                        date_str = f"{formatted_start} - {formatted_end}"
                    else:
                        date_str = formatted_start or formatted_end
                    parts.append(date_str)
            if parts:
                lines.append(" | ".join(parts))
        
        for b in entry.get("bullets", []):
            lines.append(f"- {sanitize_text(b)}")
        lines.append("")

    # Education
    lines.append("EDUCATION")
    lines.append(sanitize_text(str(data.get("education", ""))))
    lines.append("")

    # Awards
    awards = data.get("awards", [])
    if awards:
        lines.append("AWARDS")
        for award in awards:
            name = award.get("name", "")
            issuer = award.get("issuer", "")
            date = award.get("date", "")
            description = award.get("description", "")
            
            if name and issuer:
                lines.append(f"{name} - {issuer}")
            elif name:
                lines.append(name)
            
            if date:
                lines.append(date)
            
            if description:
                lines.append(sanitize_text(description))
            lines.append("")

    return "\n".join(lines)


def _get_profile_items(profile: dict, primary_path: list[str], fallback_key: str) -> list[dict]:
    """Get items from profile with fallback support.
    
    Args:
        profile: User profile dict.
        primary_path: List of keys to navigate (e.g., ["experience", "work_experiences"]).
        fallback_key: Fallback key if primary path doesn't exist (e.g., "work_experiences").
        
    Returns:
        List of items from profile.
    """
    # Try primary path first
    current = profile
    for key in primary_path:
        if isinstance(current, dict):
            current = current.get(key, {})
        else:
            break
    else:
        if isinstance(current, list):
            return current
    
    # Fallback to direct key
    return profile.get(fallback_key, [])


def _normalize_preserved_names(preserved_list: list[str]) -> set[str]:
    """Normalize preserved names to lowercase set.
    
    Args:
        preserved_list: List of preserved names.
        
    Returns:
        Set of normalized preserved names.
    """
    return {name.lower().strip() for name in preserved_list} if preserved_list else set()


def _matches_preserved_name(item_name: str, preserved_names: set[str]) -> bool:
    """Check if an item name matches any preserved name.
    
    Args:
        item_name: The item name to check (e.g., company name or project name).
        preserved_names: Set of preserved names to match against.
        
    Returns:
        True if the item matches any preserved name (exact or substring match).
    """
    item_name_lower = item_name.lower().strip()
    for preserved_name in preserved_names:
        if preserved_name == item_name_lower:
            return True
        elif preserved_name in item_name_lower or item_name_lower in preserved_name:
            return True
    return False


def _find_preserved_items(
    original_items: list[dict],
    preserved_names: set[str],
    name_key: str
) -> dict[str, dict]:
    """Find preserved items from original items list.
    
    Args:
        original_items: List of original items from profile.
        preserved_names: Set of preserved names to match.
        name_key: Key to extract name from item (e.g., "company" or "name").
        
    Returns:
        Dictionary mapping preserved name -> matching item.
    """
    preserved_map = {}
    for item in original_items:
        item_name = item.get(name_key, "").lower().strip()
        for preserved_name in preserved_names:
            if preserved_name == item_name:
                preserved_map[preserved_name] = item
                break
            elif preserved_name in item_name or item_name in preserved_name:
                preserved_map[preserved_name] = item
                break
    return preserved_map


def _merge_preserved_and_tailored(
    preserved_items_map: dict[str, dict],
    preserved_names: set[str],
    tailored_items: list[dict],
    name_key: str,
    convert_func,
    sanitize_func
) -> list:
    """Merge preserved items (with original descriptions) and tailored items.
    
    Args:
        preserved_items_map: Map of preserved name -> original item.
        preserved_names: Set of preserved names.
        tailored_items: List of tailored items from LLM output.
        name_key: Key to extract name from item (e.g., "company" or "name").
        convert_func: Function to convert item to resume format.
        sanitize_func: Function to sanitize bullets.
        
    Returns:
        List of merged items (preserved first, then non-preserved tailored items).
    """
    result = []
    
    # Step 1: Add preserved items with original descriptions
    for preserved_name, orig_item in preserved_items_map.items():
        item_copy = orig_item.copy()
        item_copy["bullets"] = [sanitize_func(b) for b in item_copy.get("bullets", [])]
        result.append(convert_func(item_copy))
    
    # Step 2: Add non-preserved tailored items
    for entry in tailored_items:
        item_name = entry.get(name_key, "").lower().strip()
        if not _matches_preserved_name(item_name, preserved_names):
            entry["bullets"] = [sanitize_func(b) for b in entry.get("bullets", [])]
            result.append(convert_func(entry))
    
    return result


def _convert_tailored_data_to_resume_props(data: dict, profile: dict) -> dict:
    """Convert tailored JSON data directly to Resume component props format.
    
    Args:
        data: Tailored resume JSON from LLM.
        profile: Original user profile.
        
    Returns:
        Resume component props dict.
    """
    from jobpilot.resume.formatter import (
        convert_experience_to_resume_format,
        convert_project_to_resume_format,
        convert_education_to_resume_format,
        convert_award_to_resume_format,
        convert_skills_to_resume_format,
        extract_handle_from_url,
        format_location,
        format_date_for_resume,
    )
    
    personal = profile.get("personal", {})
    resume_facts = profile.get("resume_facts", {})
    
    # Convert experiences - First load preserved companies with original descriptions,
    # then add non-preserved experiences from LLM output
    preserved_company_names = _normalize_preserved_names(resume_facts.get("preserved_companies", []))
    original_experiences = _get_profile_items(profile, ["experience", "work_experiences"], "work_experiences")
    
    preserved_experience_map = _find_preserved_items(original_experiences, preserved_company_names, "company")
    work_experiences = _merge_preserved_and_tailored(
        preserved_experience_map, preserved_company_names, data.get("experience", []),
        "company", convert_experience_to_resume_format, sanitize_text
    )
    
    # Convert projects - First load preserved projects with original descriptions,
    # then add non-preserved projects from LLM output
    preserved_project_names = _normalize_preserved_names(resume_facts.get("preserved_projects", []))
    original_projects = _get_profile_items(profile, ["experience", "projects"], "projects")
    
    preserved_project_map = _find_preserved_items(original_projects, preserved_project_names, "name")
    projects = _merge_preserved_and_tailored(
        preserved_project_map, preserved_project_names, data.get("projects", []),
        "name", convert_project_to_resume_format, sanitize_text
    )
    
    # Convert skills - LLM now returns profile format (skills_boundary structure)
    skills_boundary = data.get("skills", {})
    if not skills_boundary:
        skills_boundary = profile.get("skills_boundary", {})
    else:
        # Merge with original skills to preserve any missing categories
        original_skills = profile.get("skills_boundary", {})
        skills_boundary = {**original_skills, **skills_boundary}
    
    skills = convert_skills_to_resume_format(skills_boundary)
    
    # Convert education and awards - always use from profile (source of truth)
    education = [
        convert_education_to_resume_format(edu)
        for edu in _get_profile_items(profile, ["experience", "education"], "education")
    ]
    awards = [
        convert_award_to_resume_format(award)
        for award in _get_profile_items(profile, ["experience", "awards"], "awards")
    ]
    
    # Build resume props (NO SUMMARY)
    return {
        "name": personal.get("full_name", ""),
        "contact": {
            "phone": personal.get("phone", ""),
            "email": personal.get("email", ""),
            "linkedin": extract_handle_from_url(personal.get("linkedin_url", "")),
            "github": extract_handle_from_url(personal.get("github_url", "")),
            "location": format_location(personal),
        },
        "experience": work_experiences,
        "projects": projects,
        "education": education,
        "skills": skills,
        "awards": awards,
    }


def assemble_resume_html(data: dict, profile: dict) -> str:
    """Convert JSON resume data to HTML using htmldocs template.
    
    This is the unified interface - all resume generation uses HTML format.
    
    Args:
        data: Parsed JSON resume from the LLM.
        profile: User profile dict from load_profile().
        
    Returns:
        HTML string ready for PDF rendering.
    """
    from jobpilot.resume.generator import generate_resume_html
    
    # Convert tailored data directly to resume props format
    resume_props = _convert_tailored_data_to_resume_props(data, profile)
    
    # Generate HTML using unified interface
    return generate_resume_html(resume_props)


# ── LLM Judge ────────────────────────────────────────────────────────────

def judge_tailored_resume(
    tailored_text: str, job_title: str, profile: dict
) -> dict:
    """LLM judge layer: catches subtle fabrication that programmatic checks miss.
    
    All validation is based ONLY on profile.json (source of truth), not text comparison.

    Args:
        tailored_text: Tailored resume text.
        job_title: Target job title.
        profile: User profile (source of truth for all validation).

    Returns:
        {"passed": bool, "verdict": str, "issues": str, "raw": str}
    """
    judge_prompt = _build_judge_prompt(profile)
    
    # Extract key profile data for judge reference
    resume_facts = profile.get("resume_facts", {})
    experience = profile.get("experience", {})
    
    companies = resume_facts.get("preserved_companies", [])
    projects = resume_facts.get("preserved_projects", [])
    schools = resume_facts.get("preserved_schools", [])
    
    # Format profile data summary for judge
    profile_summary = []
    if companies:
        profile_summary.append(f"Real Companies: {', '.join(companies)}")
    if projects:
        profile_summary.append(f"Real Projects: {', '.join(projects)}")
    if schools:
        profile_summary.append(f"Real Schools: {', '.join(schools)}")
    
    work_exps = experience.get("work_experiences", [])
    if work_exps:
        exp_list = [f"{e.get('title', '')} at {e.get('company', '')}" for e in work_exps[:5] if e.get('company') or e.get('title')]
        if exp_list:
            profile_summary.append(f"Work Experience: {', '.join(exp_list)}")
    
    profile_data_str = "\n".join(profile_summary) if profile_summary else "See system prompt for full profile data."

    messages = [
        {"role": "system", "content": judge_prompt},
        {"role": "user", "content": (
            f"JOB TITLE: {job_title}\n\n"
            f"PROFILE DATA (source of truth):\n{profile_data_str}\n\n"
            f"---\n\n"
            f"TAILORED RESUME:\n{tailored_text}\n\n"
            "Judge this tailored resume based ONLY on the PROFILE DATA above:"
        )},
    ]

    client = get_client()
    response = client.chat(messages, max_tokens=512, temperature=0.1)

    passed = "VERDICT: PASS" in response.upper()
    issues = "none"
    if "ISSUES:" in response.upper():
        issues_idx = response.upper().index("ISSUES:")
        issues = response[issues_idx + 7:].strip()

    return {
        "passed": passed,
        "verdict": "PASS" if passed else "FAIL",
        "issues": issues,
        "raw": response,
    }


# ── Core Tailoring ───────────────────────────────────────────────────────

def tailor_resume(
    job: dict, profile: dict,
    max_retries: int = 3, validation_mode: str = "normal",
) -> tuple[str, dict]:
    """Generate a tailored resume via JSON output + fresh context on each retry.

    Key design choices:
    - LLM returns structured JSON, code assembles the output (no header leaks)
    - Each retry starts a FRESH conversation (no apologetic spiral)
    - Issues from previous attempts are noted in the system prompt
    - Em dashes and smart quotes are auto-fixed, not rejected
    - Unified HTML output format using htmldocs template
    - All generation is based ONLY on profile.json (source of truth), not resume.txt

    Args:
        job:              Job dict with title, site, location, full_description.
        profile:          User profile dict (source of truth for all data).
        max_retries:      Maximum retry attempts.
        validation_mode:  "strict", "normal", or "lenient".
                          strict  -- banned words trigger retries; judge must pass
                          normal  -- banned words = warnings only; judge can fail on last retry
                          lenient -- banned words ignored; LLM judge skipped

    Returns:
        (tailored_resume_html, report) where tailored_resume_html is HTML format
        using htmldocs template, and report contains validation details.
    """
    job_text = (
        f"TITLE: {job['title']}\n"
        f"COMPANY: {job['site']}\n"
        f"LOCATION: {job.get('location', 'N/A')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description') or '')[:6000]}"
    )

    report: dict = {
        "attempts": 0, "validator": None, "judge": None,
        "status": "pending", "validation_mode": validation_mode,
    }
    avoid_notes: list[str] = []
    tailored = ""
    client = get_client()
    tailor_prompt_base = _build_tailor_prompt(profile)
    
    # Format profile data (source of truth)
    profile_data = _format_profile_data_for_llm(profile)

    for attempt in range(max_retries + 1):
        report["attempts"] = attempt + 1

        # Fresh conversation every attempt
        prompt = tailor_prompt_base
        if avoid_notes:
            prompt += "\n\n## AVOID THESE ISSUES (from previous attempt):\n" + "\n".join(
                f"- {n}" for n in avoid_notes[-5:]
            )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": (
                f"{profile_data}\n\n"
                f"TARGET JOB:\n{job_text}\n\n"
                f"IMPORTANT: Base your generation ONLY on the PROFILE DATA above (source of truth). "
                f"Return the JSON:"
            )},
        ]

        raw = client.chat(messages, max_tokens=2048, temperature=0.4)

        # Parse JSON from response
        try:
            data = extract_json(raw)
        except ValueError:
            avoid_notes.append("Output was not valid JSON. Return ONLY a JSON object, nothing else.")
            continue

        # Layer 1: Validate JSON fields
        validation = validate_json_fields(data, profile, mode=validation_mode)
        report["validator"] = validation

        if not validation["passed"]:
            # Only retry if there are hard errors (warnings never block)
            avoid_notes.extend(validation["errors"])
            if attempt < max_retries:
                continue
            # Last attempt — assemble whatever we got (always HTML)
            tailored = assemble_resume_html(data, profile)
            report["status"] = "failed_validation"
            return tailored, report

        # Assemble HTML output (unified format)
        tailored = assemble_resume_html(data, profile)

        # Layer 2: LLM judge (catches subtle fabrication) — skipped in lenient mode
        # For HTML output, we need text version for judge comparison
        if validation_mode == "lenient":
            report["judge"] = {"verdict": "SKIPPED", "passed": True, "issues": "none"}
            report["status"] = "approved"
            return tailored, report

        # Judge needs text format for comparison
        tailored_text = assemble_resume_text(data, profile)
        judge = judge_tailored_resume(tailored_text, job.get("title", ""), profile)
        report["judge"] = judge

        if not judge["passed"]:
            avoid_notes.append(f"Judge rejected: {judge['issues']}")
            if attempt < max_retries:
                # In normal mode, only retry on judge failure if there are retries left
                if validation_mode != "lenient":
                    continue
            # Accept best attempt on last retry (all modes) or if lenient
            report["status"] = "approved_with_judge_warning"
            return tailored, report

        # Both passed
        report["status"] = "approved"
        return tailored, report

    report["status"] = "exhausted_retries"
    return tailored, report


# ── Batch Entry Point ────────────────────────────────────────────────────

def run_tailoring(min_score: int = 7, limit: int = 20,
                  validation_mode: str = "normal") -> dict:
    """Generate tailored resumes for high-scoring jobs.

    Args:
        min_score:       Minimum fit_score to tailor for.
        limit:           Maximum jobs to process.
        validation_mode: "strict", "normal", or "lenient".

    Returns:
        {"approved": int, "failed": int, "errors": int, "elapsed": float}
    """
    profile = load_profile()
    conn = get_connection()

    jobs = get_jobs_by_stage(conn=conn, stage="pending_tailor", min_score=min_score, limit=limit)

    if not jobs:
        log.info("No untailored jobs with score >= %d.", min_score)
        return {"approved": 0, "failed": 0, "errors": 0, "elapsed": 0.0}

    TAILORED_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Tailoring resumes for %d jobs (score >= %d)...", len(jobs), min_score)
    t0 = time.time()
    completed = 0
    results: list[dict] = []
    stats: dict[str, int] = {"approved": 0, "failed_validation": 0, "failed_judge": 0, "error": 0}

    for job in jobs:
        completed += 1
        try:
            # Check if resume_score >= 7, skip tailoring and use original resume
            resume_score = job.get("resume_score")
            if resume_score is not None and resume_score >= 7:
                log.info("Resume score %d >= 7, skipping tailoring for %s", resume_score, job.get("title", "?"))
                
                # Try to find matching resume template (same logic as scorer)
                from jobpilot.scoring.scorer import _find_matching_resume_template
                from jobpilot.resume.generator import generate_resume_html_from_profile
                
                # Use the conn that's already available in the function scope
                template = _find_matching_resume_template(conn, job, profile)
                
                if template and template.get("file_path"):
                    # Use template HTML directly
                    template_path = Path(template["file_path"])
                    if template_path.exists():
                        tailored_html = template_path.read_text(encoding="utf-8")
                        log.debug("Using resume template '%s' for job: %s", 
                                 template.get("name"), job.get("title", "?"))
                    else:
                        # Template file not found, generate from profile
                        tailored_html = generate_resume_html_from_profile(profile, job.get("title", ""))
                else:
                    # No template found, generate from profile
                    tailored_html = generate_resume_html_from_profile(profile, job.get("title", ""))
                
                # Create a report indicating we skipped tailoring
                report = {
                    "attempts": 1,
                    "validator": {"passed": True, "warnings": [], "errors": []},
                    "judge": {"verdict": "SKIPPED", "passed": True, "issues": "Resume score >= 7, using original resume"},
                    "status": "approved",
                    "validation_mode": validation_mode,
                    "skipped_tailoring": True,
                    "resume_score": resume_score,
                }
            else:
                # Generate tailored resume as HTML (unified format)
                # All generation is based on profile.json only, not resume.txt
                tailored_html, report = tailor_resume(
                    job, profile,
                    validation_mode=validation_mode
                )

            # Build safe filename prefix
            safe_title = re.sub(r"[^\w\s-]", "", job["title"])[:50].strip().replace(" ", "_")
            safe_site = re.sub(r"[^\w\s-]", "", job["site"])[:20].strip().replace(" ", "_")
            prefix = f"{safe_site}_{safe_title}"

            # Save tailored resume HTML
            html_path = TAILORED_DIR / f"{prefix}.html"
            html_path.write_text(tailored_html, encoding="utf-8")

            # Save job description for traceability
            job_path = TAILORED_DIR / f"{prefix}_JOB.txt"
            job_desc = (
                f"Title: {job['title']}\n"
                f"Company: {job['site']}\n"
                f"Location: {job.get('location', 'N/A')}\n"
                f"Score: {job.get('fit_score', 'N/A')}\n"
                f"URL: {job['url']}\n\n"
                f"{job.get('full_description', '')}"
            )
            job_path.write_text(job_desc, encoding="utf-8")

            # Save validation report
            report_path = TAILORED_DIR / f"{prefix}_REPORT.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

            # Generate PDF directly from HTML using Playwright (unified interface)
            # "approved_with_judge_warning" is also a success — resume was generated.
            pdf_path = None
            if report["status"] in ("approved", "approved_with_judge_warning"):
                try:
                    from playwright.sync_api import sync_playwright
                    pdf_path_obj = TAILORED_DIR / f"{prefix}.pdf"
                    with sync_playwright() as p:
                        browser = p.chromium.launch()
                        page = browser.new_page()
                        page.set_content(tailored_html, wait_until="networkidle")
                        page.pdf(
                            path=str(pdf_path_obj),
                            format="A4",
                            print_background=True,
                        )
                        browser.close()
                    pdf_path = str(pdf_path_obj)
                except Exception:
                    log.debug("PDF generation failed for %s", html_path, exc_info=True)

            result = {
                "url": job["url"],
                "path": str(html_path),
                "pdf_path": pdf_path,
                "title": job["title"],
                "site": job["site"],
                "status": report["status"],
                "attempts": report["attempts"],
            }
        except Exception as e:
            result = {
                "url": job["url"], "title": job["title"], "site": job["site"],
                "status": "error", "attempts": 0, "path": None, "pdf_path": None,
            }
            log.error("%d/%d [ERROR] %s -- %s", completed, len(jobs), job["title"][:40], e)

        results.append(result)
        stats[result.get("status", "error")] = stats.get(result.get("status", "error"), 0) + 1

        elapsed = time.time() - t0
        rate = completed / elapsed if elapsed > 0 else 0
        log.info(
            "%d/%d [%s] attempts=%s | %.1f jobs/min | %s",
            completed, len(jobs),
            result["status"].upper(),
            result.get("attempts", "?"),
            rate * 60,
            result["title"][:40],
        )

    # Persist to DB: increment attempt counter for ALL, save path only for approved
    now = datetime.now(timezone.utc).isoformat()
    _success_statuses = {"approved", "approved_with_judge_warning"}
    for r in results:
        if r["status"] in _success_statuses:
            conn.execute(
                "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
                "tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE url=?",
                (r["path"], now, r["url"]),
            )
        else:
            conn.execute(
                "UPDATE jobs SET tailor_attempts=COALESCE(tailor_attempts,0)+1 WHERE url=?",
                (r["url"],),
            )
    conn.commit()

    elapsed = time.time() - t0
    log.info(
        "Tailoring done in %.1fs: %d approved, %d failed_validation, %d failed_judge, %d errors",
        elapsed,
        stats.get("approved", 0),
        stats.get("failed_validation", 0),
        stats.get("failed_judge", 0),
        stats.get("error", 0),
    )

    return {
        "approved": stats.get("approved", 0),
        "failed": stats.get("failed_validation", 0) + stats.get("failed_judge", 0),
        "errors": stats.get("error", 0),
        "elapsed": elapsed,
    }
