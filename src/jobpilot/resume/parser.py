"""Resume parsing utilities for extracting structured data from resume files."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file.
        
    Returns:
        Extracted text content.
    """
    try:
        import PyPDF2
    except ImportError:
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "PDF parsing requires either PyPDF2 or pdfplumber. "
                "Install with: pip install PyPDF2 or pip install pdfplumber"
            )
    
    text = ""
    
    # Try pdfplumber first (better quality)
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text
    except ImportError:
        pass
    
    # Fallback to PyPDF2
    try:
        import PyPDF2
        with open(pdf_path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
        return text
    except Exception as e:
        log.error(f"Failed to extract text from PDF: {e}")
        raise


def parse_resume_with_llm(text: str) -> dict[str, Any]:
    """Use LLM to extract structured information from resume text.
    
    Args:
        text: Resume text content.
        
    Returns:
        Structured profile data.
    """
    from jobpilot.llm import get_client
    
    prompt = """Extract structured information from this resume text and return it as JSON.

Extract the following information:
- Personal: full_name, email, phone, city, province_state, country, postal_code, linkedin_url, github_url, portfolio_url, website_url
- Work experiences: array of {company, title, start_date, end_date, current (boolean), location, bullets (array of strings)}
- Projects: array of {name, description, tech_stack (array), start_date, end_date, current (boolean), url}
- Education: array of {school, degree, field, start_date, end_date, gpa, honors (array)}
- Skills: programming_languages (array), frameworks (array), devops (array), databases (array), tools (array)
- Experience summary: years_of_experience_total, education_level, current_job_title, current_company, target_role

Return ONLY valid JSON, no markdown, no explanation. Use this structure:
{
  "personal": {...},
  "work_experiences": [...],
  "projects": [...],
  "education": [...],
  "skills_boundary": {...},
  "experience": {...}
}

RESUME TEXT:
""" + text[:8000]  # Limit text length
    
    try:
        client = get_client()
        messages = [
            {"role": "system", "content": "You are a resume parser. Extract structured data from resumes and return only valid JSON."},
            {"role": "user", "content": prompt}
        ]
        
        response = client.chat(messages, max_tokens=2048, temperature=0.1)
        
        # Extract JSON from response
        json_text = response.strip()
        # Remove markdown code blocks if present
        if json_text.startswith("```"):
            json_text = json_text.split("```")[1]
            if json_text.startswith("json"):
                json_text = json_text[4:]
        json_text = json_text.strip()
        
        import json
        parsed_data = json.loads(json_text)
        
        # Ensure experience object exists
        if "experience" not in parsed_data:
            parsed_data["experience"] = {}
        
        # Move root-level work_experiences, projects, education to experience.*
        # and remove root-level duplicates
        if "work_experiences" in parsed_data:
            if "work_experiences" not in parsed_data["experience"]:
                parsed_data["experience"]["work_experiences"] = parsed_data["work_experiences"]
            del parsed_data["work_experiences"]
        
        if "projects" in parsed_data:
            if "projects" not in parsed_data["experience"]:
                parsed_data["experience"]["projects"] = parsed_data["projects"]
            del parsed_data["projects"]
        
        if "education" in parsed_data:
            if "education" not in parsed_data["experience"]:
                parsed_data["experience"]["education"] = parsed_data["education"]
            del parsed_data["education"]
        
        return parsed_data
    except Exception as e:
        log.error(f"LLM parsing failed: {e}")
        raise RuntimeError(f"Failed to parse resume with LLM: {e}") from e


# ---------------------------------------------------------------------------
# LLM-based Resume Merging
# ---------------------------------------------------------------------------

def merge_resume_data_with_llm(existing_profile: dict, new_data: dict) -> dict:
    """Merge new resume data into existing profile using LLM for intelligent matching.
    
    Uses LLM to:
    1. Identify duplicate/similar work experiences, projects, and education
    2. Merge duplicates intelligently (combining the best information)
    3. Add new unique entries
    
    Args:
        existing_profile: Current profile data.
        new_data: New data extracted from uploaded resume.
        
    Returns:
        Merged profile data.
    """
    from jobpilot.llm import get_client
    import json
    
    merged = existing_profile.copy() if existing_profile else {}
    
    # Merge personal info (prefer new data if it's more complete)
    if "personal" in new_data:
        if "personal" not in merged:
            merged["personal"] = {}
        personal = merged["personal"]
        for key, value in new_data["personal"].items():
            if value and (not personal.get(key) or len(str(value)) > len(str(personal.get(key, "")))):
                personal[key] = value
    
    # Prepare existing and new data for LLM merging
    # All data should be in experience.* format only
    existing_experiences = merged.get("experience", {}).get("work_experiences", [])
    new_experiences = new_data.get("experience", {}).get("work_experiences", [])
    
    existing_projects = merged.get("experience", {}).get("projects", [])
    new_projects = new_data.get("experience", {}).get("projects", [])
    
    existing_education = merged.get("experience", {}).get("education", [])
    new_education = new_data.get("experience", {}).get("education", [])
    
    # Use LLM to merge work experiences
    log.info("=" * 80)
    log.info("MERGING WORK EXPERIENCES")
    log.info(f"Existing work experiences: {len(existing_experiences)}")
    if existing_experiences:
        for i, exp in enumerate(existing_experiences, 1):
            log.info(f"  [{i}] {exp.get('company', 'N/A')} - {exp.get('title', 'N/A')} ({exp.get('start_date', 'N/A')} to {exp.get('end_date', 'N/A')})")
    
    log.info(f"New work experiences: {len(new_experiences)}")
    if new_experiences:
        for i, exp in enumerate(new_experiences, 1):
            log.info(f"  [{i}] {exp.get('company', 'N/A')} - {exp.get('title', 'N/A')} ({exp.get('start_date', 'N/A')} to {exp.get('end_date', 'N/A')})")
    
    if existing_experiences or new_experiences:
        merged_experiences = _merge_items_with_llm(
            existing_experiences, new_experiences, item_type="work_experience"
        )
        log.info(f"Merged work experiences: {len(merged_experiences)}")
        if merged_experiences:
            for i, exp in enumerate(merged_experiences, 1):
                log.info(f"  [{i}] {exp.get('company', 'N/A')} - {exp.get('title', 'N/A')} ({exp.get('start_date', 'N/A')} to {exp.get('end_date', 'N/A')})")
    else:
        merged_experiences = []
    
    # Use LLM to merge projects
    log.info("=" * 80)
    log.info("MERGING PROJECTS")
    log.info(f"Existing projects: {len(existing_projects)}")
    if existing_projects:
        for i, proj in enumerate(existing_projects, 1):
            log.info(f"  [{i}] {proj.get('name', 'N/A')}")
    
    log.info(f"New projects: {len(new_projects)}")
    if new_projects:
        for i, proj in enumerate(new_projects, 1):
            log.info(f"  [{i}] {proj.get('name', 'N/A')}")
    
    if existing_projects or new_projects:
        merged_projects = _merge_items_with_llm(
            existing_projects, new_projects, item_type="project"
        )
        log.info(f"Merged projects: {len(merged_projects)}")
        if merged_projects:
            for i, proj in enumerate(merged_projects, 1):
                log.info(f"  [{i}] {proj.get('name', 'N/A')}")
    else:
        merged_projects = []
    
    # Use LLM to merge education
    log.info("=" * 80)
    log.info("MERGING EDUCATION")
    log.info(f"Existing education: {len(existing_education)}")
    if existing_education:
        for i, edu in enumerate(existing_education, 1):
            log.info(f"  [{i}] {edu.get('degree', 'N/A')} from {edu.get('school', 'N/A')}")
    
    log.info(f"New education: {len(new_education)}")
    if new_education:
        for i, edu in enumerate(new_education, 1):
            log.info(f"  [{i}] {edu.get('degree', 'N/A')} from {edu.get('school', 'N/A')}")
    
    if existing_education or new_education:
        merged_education = _merge_items_with_llm(
            existing_education, new_education, item_type="education"
        )
        log.info(f"Merged education: {len(merged_education)}")
        if merged_education:
            for i, edu in enumerate(merged_education, 1):
                log.info(f"  [{i}] {edu.get('degree', 'N/A')} from {edu.get('school', 'N/A')}")
    else:
        merged_education = []
    
    log.info("=" * 80)
    
    # Update experience section
    if "experience" not in merged:
        merged["experience"] = {}
    
    merged["experience"]["work_experiences"] = merged_experiences
    merged["experience"]["projects"] = merged_projects
    merged["experience"]["education"] = merged_education
    
    # Remove any root-level duplicates (should not exist, but clean up just in case)
    if "work_experiences" in merged:
        del merged["work_experiences"]
    if "projects" in merged:
        del merged["projects"]
    if "education" in merged:
        del merged["education"]
    
    # Merge skills (combine arrays)
    if "skills_boundary" in new_data:
        if "skills_boundary" not in merged:
            merged["skills_boundary"] = {}
        
        for skill_type in ["programming_languages", "frameworks", "devops", "databases", "tools", "languages"]:
            existing_skills = set(merged["skills_boundary"].get(skill_type, []))
            new_skills = set(new_data["skills_boundary"].get(skill_type, []))
            merged["skills_boundary"][skill_type] = list(existing_skills | new_skills)
    
    # Update experience summary if provided
    if "experience" in new_data and isinstance(new_data["experience"], dict):
        exp_summary = new_data["experience"]
        if "years_of_experience_total" in exp_summary:
            merged["experience"]["years_of_experience_total"] = exp_summary["years_of_experience_total"]
        if "education_level" in exp_summary:
            merged["experience"]["education_level"] = exp_summary["education_level"]
        if "current_job_title" in exp_summary:
            merged["experience"]["current_job_title"] = exp_summary["current_job_title"]
        if "current_company" in exp_summary:
            merged["experience"]["current_company"] = exp_summary["current_company"]
        if "target_role" in exp_summary:
            merged["experience"]["target_role"] = exp_summary["target_role"]
    
    return merged


def _merge_items_with_llm(existing_items: list[dict], new_items: list[dict], item_type: str) -> list[dict]:
    """Use LLM to intelligently merge items (work experiences, projects, or education).
    
    Args:
        existing_items: List of existing items.
        new_items: List of new items to merge.
        item_type: Type of items ("work_experience", "project", or "education").
        
    Returns:
        Merged list of items with duplicates intelligently combined.
    """
    if not new_items:
        log.info(f"No new {item_type} items, keeping all {len(existing_items)} existing items")
        return existing_items
    if not existing_items:
        log.info(f"No existing {item_type} items, adding all {len(new_items)} new items")
        return new_items
    
    from jobpilot.llm import get_client
    import json
    
    # Identify potential duplicates before LLM merge
    duplicates = []
    new_unique = []
    
    if item_type == "work_experience":
        existing_keys = {(item.get("company", "").lower().strip(), item.get("title", "").lower().strip()) for item in existing_items}
        for new_item in new_items:
            key = (new_item.get("company", "").lower().strip(), new_item.get("title", "").lower().strip())
            if key in existing_keys:
                duplicates.append(new_item)
            else:
                new_unique.append(new_item)
    elif item_type == "project":
        existing_keys = {item.get("name", "").lower().strip() for item in existing_items}
        for new_item in new_items:
            key = new_item.get("name", "").lower().strip()
            if key in existing_keys:
                duplicates.append(new_item)
            else:
                new_unique.append(new_item)
    else:  # education
        existing_keys = {(item.get("school", "").lower().strip(), item.get("degree", "").lower().strip()) for item in existing_items}
        for new_item in new_items:
            key = (new_item.get("school", "").lower().strip(), new_item.get("degree", "").lower().strip())
            if key in existing_keys:
                duplicates.append(new_item)
            else:
                new_unique.append(new_item)
    
    log.info(f"[{item_type}] Analysis before LLM merge:")
    log.info(f"  - Existing items: {len(existing_items)}")
    log.info(f"  - New items: {len(new_items)}")
    log.info(f"  - Potential duplicates (exact match): {len(duplicates)}")
    if duplicates:
        for dup in duplicates:
            if item_type == "work_experience":
                log.info(f"    - {dup.get('company', 'N/A')} - {dup.get('title', 'N/A')}")
            elif item_type == "project":
                log.info(f"    - {dup.get('name', 'N/A')}")
            else:
                log.info(f"    - {dup.get('degree', 'N/A')} from {dup.get('school', 'N/A')}")
    log.info(f"  - New unique items: {len(new_unique)}")
    if new_unique:
        for item in new_unique:
            if item_type == "work_experience":
                log.info(f"    - {item.get('company', 'N/A')} - {item.get('title', 'N/A')}")
            elif item_type == "project":
                log.info(f"    - {item.get('name', 'N/A')}")
            else:
                log.info(f"    - {item.get('degree', 'N/A')} from {item.get('school', 'N/A')}")
    
    # Prepare prompt for LLM
    if item_type == "work_experience":
        prompt = """You are merging work experience entries from multiple resumes. Your task is to:
1. Identify duplicate or very similar work experiences (same company and similar role/time period)
2. Merge duplicates by combining the best information from both (keep more detailed bullets, more accurate dates, etc.)
3. Keep all unique work experiences
4. Return a deduplicated and merged list

EXISTING WORK EXPERIENCES:
{existing}

NEW WORK EXPERIENCES:
{new}

Return ONLY a valid JSON array of merged work experiences. Each entry should have: company, title, start_date, end_date, current (boolean), location, bullets (array of strings).

Format: [{{"company": "...", "title": "...", "start_date": "...", "end_date": "...", "current": true/false, "location": "...", "bullets": [...]}}, ...]"""
    elif item_type == "project":
        prompt = """You are merging project entries from multiple resumes. Your task is to:
1. Identify duplicate or very similar projects (same name or very similar description)
2. Merge duplicates by combining the best information (more detailed descriptions, complete tech stacks, etc.)
3. Keep all unique projects
4. Return a deduplicated and merged list

EXISTING PROJECTS:
{existing}

NEW PROJECTS:
{new}

Return ONLY a valid JSON array of merged projects. Each entry should have: name, description, tech_stack (array), start_date, end_date, current (boolean), url.

Format: [{{"name": "...", "description": "...", "tech_stack": [...], "start_date": "...", "end_date": "...", "current": true/false, "url": "..."}}, ...]"""
    else:  # education
        prompt = """You are merging education entries from multiple resumes. Your task is to:
1. Identify duplicate or very similar education entries (same school and degree)
2. Merge duplicates by combining the best information (GPA, honors, field, dates, etc.)
3. Keep all unique education entries
4. Return a deduplicated and merged list

EXISTING EDUCATION:
{existing}

NEW EDUCATION:
{new}

Return ONLY a valid JSON array of merged education entries. Each entry should have: school, degree, field, start_date, end_date, gpa, honors (array).

Format: [{{"school": "...", "degree": "...", "field": "...", "start_date": "...", "end_date": "...", "gpa": "...", "honors": [...]}}, ...]"""
    
    try:
        client = get_client()
        
        # Format the data for the prompt
        existing_json = json.dumps(existing_items, ensure_ascii=False, indent=2)
        new_json = json.dumps(new_items, ensure_ascii=False, indent=2)
        
        formatted_prompt = prompt.format(existing=existing_json, new=new_json)
        
        messages = [
            {
                "role": "system",
                "content": "You are a resume data merger. You intelligently merge duplicate entries while preserving all unique information. Always return valid JSON only."
            },
            {
                "role": "user",
                "content": formatted_prompt
            }
        ]
        
        response = client.chat(messages, max_tokens=4096, temperature=0.1)
        
        # Extract JSON from response
        json_text = response.strip()
        # Remove markdown code blocks if present
        if json_text.startswith("```"):
            json_text = json_text.split("```")[1]
            if json_text.startswith("json"):
                json_text = json_text[4:]
        json_text = json_text.strip()
        
        merged_items = json.loads(json_text)
        
        # Ensure it's a list
        if not isinstance(merged_items, list):
            log.warning(f"LLM returned non-list for {item_type}, falling back to simple merge")
            return _simple_merge_fallback(existing_items, new_items, item_type)
        
        # Log merge results
        log.info(f"[{item_type}] LLM merge completed:")
        log.info(f"  - Total merged items: {len(merged_items)}")
        log.info(f"  - Expected minimum: {len(existing_items)} (all existing should be preserved)")
        
        # Check if we lost any existing items
        if item_type == "work_experience":
            existing_keys = {(item.get("company", "").lower().strip(), item.get("title", "").lower().strip()) for item in existing_items}
            merged_keys = {(item.get("company", "").lower().strip(), item.get("title", "").lower().strip()) for item in merged_items}
        elif item_type == "project":
            existing_keys = {item.get("name", "").lower().strip() for item in existing_items}
            merged_keys = {item.get("name", "").lower().strip() for item in merged_items}
        else:  # education
            existing_keys = {(item.get("school", "").lower().strip(), item.get("degree", "").lower().strip()) for item in existing_items}
            merged_keys = {(item.get("school", "").lower().strip(), item.get("degree", "").lower().strip()) for item in merged_items}
        
        missing_keys = existing_keys - merged_keys
        if missing_keys:
            log.warning(f"[{item_type}] WARNING: Lost {len(missing_keys)} existing items after LLM merge!")
            for key in missing_keys:
                if item_type == "work_experience":
                    log.warning(f"  - Missing: {key[0]} - {key[1]}")
                elif item_type == "project":
                    log.warning(f"  - Missing: {key}")
                else:
                    log.warning(f"  - Missing: {key[1]} from {key[0]}")
        else:
            log.info(f"[{item_type}] All existing items preserved ✓")
        
        # Check new items
        if item_type == "work_experience":
            new_keys = {(item.get("company", "").lower().strip(), item.get("title", "").lower().strip()) for item in new_items}
        elif item_type == "project":
            new_keys = {item.get("name", "").lower().strip() for item in new_items}
        else:  # education
            new_keys = {(item.get("school", "").lower().strip(), item.get("degree", "").lower().strip()) for item in new_items}
        
        added_keys = new_keys - existing_keys
        merged_new_keys = merged_keys - existing_keys
        if len(merged_new_keys) < len(added_keys):
            log.warning(f"[{item_type}] Some new items may not have been added. Expected {len(added_keys)} new, got {len(merged_new_keys)}")
        else:
            log.info(f"[{item_type}] New items added: {len(merged_new_keys)} ✓")
        
        # Sort work experiences by date (most recent first)
        if item_type == "work_experience":
            merged_items = _sort_experiences_by_date(merged_items)
        
        return merged_items
        
    except Exception as e:
        log.error(f"LLM merge failed for {item_type}: {e}, using fallback")
        return _simple_merge_fallback(existing_items, new_items, item_type)


def _sort_experiences_by_date(experiences: list[dict]) -> list[dict]:
    """Sort work experiences by start date (most recent first)."""
    import re
    
    def get_sort_key(exp: dict) -> tuple:
        start_date = exp.get("start_date", "")
        if not start_date:
            return (0, 0, 0)  # Put entries without dates at the end
        try:
            # Handle formats like "2020-01" or "2020/01" or "Jan 2020"
            parts = re.split(r'[-/\s]', start_date)
            year = 0
            month = 0
            for part in parts:
                if part.isdigit() and len(part) == 4:
                    year = int(part)
                elif part.isdigit() and len(part) <= 2:
                    month = int(part)
            return (-year, -month, 0)  # Negative for descending order
        except:
            return (0, 0, 0)
    
    return sorted(experiences, key=get_sort_key)


def _simple_merge_fallback(existing_items: list[dict], new_items: list[dict], item_type: str = "work_experience") -> list[dict]:
    """Simple fallback merge: add new items that don't exist in existing."""
    merged = existing_items.copy()
    
    # Simple check: if an item with same key fields exists, skip it
    for new_item in new_items:
        is_duplicate = False
        for existing_item in existing_items:
            # Check if they're the same based on key fields
            if item_type == "work_experience":
                if (existing_item.get("company", "").lower() == new_item.get("company", "").lower() and
                    existing_item.get("title", "").lower() == new_item.get("title", "").lower()):
                    is_duplicate = True
                    break
            elif item_type == "project":
                if existing_item.get("name", "").lower() == new_item.get("name", "").lower():
                    is_duplicate = True
                    break
            else:  # education
                if (existing_item.get("school", "").lower() == new_item.get("school", "").lower() and
                    existing_item.get("degree", "").lower() == new_item.get("degree", "").lower()):
                    is_duplicate = True
                    break
        
        if not is_duplicate:
            merged.append(new_item)
    
    return merged
