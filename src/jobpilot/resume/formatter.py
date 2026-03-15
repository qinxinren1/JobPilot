"""Shared resume data formatting utilities.

This module provides unified functions for converting profile data or tailored
resume data into the format expected by the Resume React component.
"""

import re
from typing import Any


def format_date_for_resume(date_string: str, is_current: bool = False) -> str:
    """Format date to 'MMM YYYY' format, matching JavaScript formatDate.
    
    Args:
        date_string: Date string in various formats (YYYY-MM, YYYY/MM, MM/YYYY, etc.)
        is_current: Whether this is a current position (returns 'Present' if True and empty date)
        
    Returns:
        Formatted date string in 'MMM YYYY' format, or 'Present' if is_current and no date.
    """
    if is_current and not date_string:
        return "Present"
    
    if not date_string or date_string == "Present":
        return date_string or ""
    
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", 
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    full_month_names = ["January", "February", "March", "April", "May", "June",
                        "July", "August", "September", "October", "November", "December"]
    
    # Check if already in readable format (contains month name)
    for i, full_month in enumerate(full_month_names):
        if full_month in date_string:
            # Extract year and return in "MMM YYYY" format
            year_match = re.search(r"\d{4}", date_string)
            year = year_match.group(0) if year_match else ""
            return f"{month_names[i]} {year}" if year else date_string
    
    # Check if already in "MMM YYYY" format
    for month in month_names:
        if month in date_string:
            return date_string  # Already in correct format
    
    # Try to parse "YYYY-MM" format
    yyyy_mm_match = re.match(r"^(\d{4})-(\d{1,2})", date_string)
    if yyyy_mm_match:
        year = yyyy_mm_match.group(1)
        month = int(yyyy_mm_match.group(2))
        if 1 <= month <= 12:
            return f"{month_names[month - 1]} {year}"
    
    # Try to parse "YYYY/MM" format
    yyyy_slash_mm_match = re.match(r"^(\d{4})/(\d{1,2})", date_string)
    if yyyy_slash_mm_match:
        year = yyyy_slash_mm_match.group(1)
        month = int(yyyy_slash_mm_match.group(2))
        if 1 <= month <= 12:
            return f"{month_names[month - 1]} {year}"
    
    # Try to parse "MM/YYYY" format
    mm_slash_yyyy_match = re.match(r"^(\d{1,2})/(\d{4})", date_string)
    if mm_slash_yyyy_match:
        month = int(mm_slash_yyyy_match.group(1))
        year = mm_slash_yyyy_match.group(2)
        if 1 <= month <= 12:
            return f"{month_names[month - 1]} {year}"
    
    # If we can't parse it, return as is
    return date_string


def extract_handle_from_url(url: str) -> str:
    """Extract handle from LinkedIn/GitHub URL.
    
    Args:
        url: Full URL (e.g., 'https://www.linkedin.com/in/username')
        
    Returns:
        Handle/username extracted from URL.
    """
    if not url:
        return ""
    parts = [p for p in url.split("/") if p]
    return parts[-1] if parts else ""


def format_location(personal: dict[str, Any]) -> str:
    """Format location from personal info.
    
    Args:
        personal: Personal info dict with city, province_state, etc.
        
    Returns:
        Formatted location string.
    """
    location_parts = []
    if personal.get("city"):
        location_parts.append(personal["city"])
    if personal.get("province_state"):
        location_parts.append(personal["province_state"])
    return ", ".join(location_parts) if location_parts else ""


def format_contact_line(personal: dict[str, Any], use_handles: bool = False) -> str:
    """Format contact information as a single line (for text resumes).
    
    Args:
        personal: Personal info dict with email, phone, github_url, linkedin_url.
        use_handles: If True, extract handles from URLs. If False, use full URLs.
        
    Returns:
        Formatted contact line string (e.g., "email | phone | github_url | linkedin_url").
    """
    contact_parts: list[str] = []
    if personal.get("email"):
        contact_parts.append(personal["email"])
    if personal.get("phone"):
        contact_parts.append(personal["phone"])
    
    if use_handles:
        if personal.get("github_url"):
            handle = extract_handle_from_url(personal["github_url"])
            if handle:
                contact_parts.append(f"github.com/{handle}")
        if personal.get("linkedin_url"):
            handle = extract_handle_from_url(personal["linkedin_url"])
            if handle:
                contact_parts.append(f"linkedin.com/in/{handle}")
    else:
        # For text format, use full URLs
        if personal.get("github_url"):
            contact_parts.append(personal["github_url"])
        if personal.get("linkedin_url"):
            contact_parts.append(personal["linkedin_url"])
    
    return " | ".join(contact_parts) if contact_parts else ""


def format_skills_as_text(skills_boundary: dict[str, Any]) -> list[str]:
    """Format skills_boundary as text lines (for text resumes).
    
    Args:
        skills_boundary: Skills dict with programming_languages, frameworks, etc.
        
    Returns:
        List of formatted skill lines (e.g., ["Languages: Python, JavaScript", ...]).
    """
    if not isinstance(skills_boundary, dict):
        return []
    
    lines: list[str] = []
    category_labels = {
        "programming_languages": "Languages",
        "languages": "Languages",
        "frameworks": "Frameworks",
        "devops": "DevOps & Infra",
        "databases": "Databases",
        "tools": "Tools",
        "product_strategy": "Product Strategy",
        "technical_literacy": "Technical Literacy",
        "data_analysis": "Data Analysis",
        "soft_skills": "Soft Skills",
        "spoken_languages": "Spoken Languages",
    }
    
    for key, label in category_labels.items():
        if key in skills_boundary and skills_boundary[key]:
            skill_list = skills_boundary[key] if isinstance(skills_boundary[key], list) else [skills_boundary[key]]
            if skill_list:
                lines.append(f"{label}: {', '.join(str(s) for s in skill_list)}")
    
    return lines


def convert_experience_to_resume_format(exp: dict[str, Any]) -> dict[str, Any]:
    """Convert experience entry to Resume component format.
    
    Args:
        exp: Experience dict with company, title, start_date, end_date, current, location, bullets
        
    Returns:
        Formatted experience dict for Resume component.
    """
    return {
        "company": exp.get("company", ""),
        "title": exp.get("title", ""),
        "location": exp.get("location", ""),
        "startDate": format_date_for_resume(exp.get("start_date", "")),
        "endDate": "Present" if exp.get("current") else format_date_for_resume(exp.get("end_date", "")),
        "achievements": exp.get("bullets", []),
    }


def convert_project_to_resume_format(proj: dict[str, Any]) -> dict[str, Any]:
    """Convert project entry to Resume component format.
    
    Args:
        proj: Project dict with name, start_date, end_date, current, url, bullets
        
    Returns:
        Formatted project dict for Resume component.
    """
    start_date = format_date_for_resume(proj.get("start_date", ""))
    end_date = "Present" if proj.get("current") else format_date_for_resume(proj.get("end_date", ""))
    
    return {
        "name": proj.get("name", ""),
        "dateRange": f"{start_date} – {end_date}" if start_date or end_date else "",
        "githubUrl": proj.get("url", ""),
        "achievements": proj.get("bullets", []),
    }


def convert_education_to_resume_format(edu: dict[str, Any]) -> dict[str, Any]:
    """Convert education entry to Resume component format.
    
    Args:
        edu: Education dict with school, degree, field, location, start_date, end_date, gpa, honors
        
    Returns:
        Formatted education dict for Resume component.
    """
    return {
        "school": edu.get("school", ""),
        "degree": edu.get("degree", ""),
        "field": edu.get("field", ""),
        "location": edu.get("location", ""),
        "startDate": format_date_for_resume(edu.get("start_date", "")),
        "endDate": format_date_for_resume(edu.get("end_date", "")),
        "gpa": edu.get("gpa", ""),
        "honors": edu.get("honors", []),
    }


def convert_award_to_resume_format(award: dict[str, Any]) -> dict[str, Any]:
    """Convert award entry to Resume component format.
    
    Args:
        award: Award dict with name, category, issuer, date, description
        
    Returns:
        Formatted award dict for Resume component.
    """
    return {
        "name": award.get("name", ""),
        "category": award.get("category", ""),
        "issuer": award.get("issuer", ""),
        "date": format_date_for_resume(award.get("date", "")) if award.get("date") else "",
        "description": award.get("description", ""),
    }


def convert_skills_to_resume_format(skills_boundary: dict[str, Any]) -> dict[str, Any]:
    """Convert skills_boundary to Resume component format.
    
    Args:
        skills_boundary: Skills dict with programming_languages, frameworks, databases, devops, tools, etc.
        
    Returns:
        Formatted skills dict for Resume component.
    """
    return {
        "languages": skills_boundary.get("programming_languages", []),
        "frameworks": skills_boundary.get("frameworks", []),
        "technologies": [
            *(skills_boundary.get("databases", [])),
            *(skills_boundary.get("devops", [])),
            *(skills_boundary.get("tools", [])),
        ],
        "softSkills": [
            *(skills_boundary.get("product_strategy") or skills_boundary.get("productStrategy", [])),
            *(skills_boundary.get("technical_literacy") or skills_boundary.get("technicalLiteracy", [])),
            *(skills_boundary.get("data_analysis") or skills_boundary.get("dataAnalysis", [])),
            *(skills_boundary.get("soft_skills") or skills_boundary.get("softSkills", [])),
        ],
        "spokenLanguages": skills_boundary.get("spoken_languages") or skills_boundary.get("spokenLanguages") or skills_boundary.get("languages", []),
    }


def generate_summary(experience: dict[str, Any], job_position: str = "") -> str:
    """Generate summary text from experience data.
    
    Args:
        experience: Experience dict with years_of_experience_total, current_job_title, etc.
        job_position: Optional job position/title.
        
    Returns:
        Summary string.
    """
    summary_parts = []
    
    if experience.get("years_of_experience_total"):
        summary_parts.append(f"{experience['years_of_experience_total']} years of experience")
    
    if experience.get("current_job_title") and experience.get("current_company"):
        summary_parts.append(f"Currently {experience['current_job_title']} at {experience['current_company']}")
    elif job_position or experience.get("target_role"):
        summary_parts.append(f"Seeking {job_position or experience.get('target_role', '')} positions")
    
    if summary_parts:
        return ". ".join(summary_parts) + "."
    
    return "Experienced professional seeking new opportunities."


def generate_resume_text_from_profile(profile: dict[str, Any]) -> str:
    """Generate plain text resume from profile.json.
    
    This is a reusable function for generating resume text from profile data.
    Used by scoring, cover letter generation, and other modules that need
    text format resumes.
    
    Args:
        profile: User profile dict (source of truth).
        
    Returns:
        Formatted resume text string.
    """
    personal = profile.get("personal", {})
    experience = profile.get("experience", {})
    skills_boundary = profile.get("skills_boundary", {})
    
    lines: list[str] = []
    
    # Header
    lines.append(personal.get("full_name", ""))
    lines.append(format_contact_line(personal, use_handles=True))
    lines.append("")
    
    # Summary (if available)
    if profile.get("summary"):
        lines.append(profile["summary"])
        lines.append("")
    
    # Experience - use experience.work_experiences, fallback to root level for backward compatibility
    work_experiences = experience.get("work_experiences", [])
    if not work_experiences:
        work_experiences = profile.get("work_experiences", [])
    if work_experiences:
        for exp in work_experiences:
            title = exp.get("title", "")
            company = exp.get("company", "")
            start_date = exp.get("start_date", "")
            end_date = exp.get("end_date", "")
            current = exp.get("current", False)
            bullets = exp.get("bullets", [])
            
            if title and company:
                formatted_start = format_date_for_resume(start_date) if start_date else ""
                formatted_end = "Present" if current else (format_date_for_resume(end_date) if end_date else "")
                if formatted_start or formatted_end:
                    date_str = f"{formatted_start} – {formatted_end}" if formatted_start and formatted_end else (formatted_start or formatted_end)
                else:
                    date_str = ""
                lines.append(f"{title} | {company}" + (f" | {date_str}" if date_str else ""))
            elif company:
                formatted_start = format_date_for_resume(start_date) if start_date else ""
                formatted_end = "Present" if current else (format_date_for_resume(end_date) if end_date else "")
                if formatted_start or formatted_end:
                    date_str = f"{formatted_start} – {formatted_end}" if formatted_start and formatted_end else (formatted_start or formatted_end)
                else:
                    date_str = ""
                lines.append(f"{company}" + (f" | {date_str}" if date_str else ""))
            
            for bullet in bullets:
                lines.append(f"  • {bullet}")
            lines.append("")
    
    # Projects - use experience.projects, fallback to root level for backward compatibility
    projects = experience.get("projects", [])
    if not projects:
        projects = profile.get("projects", [])
    if projects:
        for proj in projects:
            name = proj.get("name", "")
            if name:
                lines.append(f"{name}")
            bullets = proj.get("bullets", [])
            for bullet in bullets:
                lines.append(f"  • {bullet}")
            lines.append("")
    
    # Education - use experience.education, fallback to root level for backward compatibility
    education = experience.get("education", [])
    if not education:
        education = profile.get("education", [])
    if education:
        lines.append("EDUCATION")
        for edu in education:
            school = edu.get("school", "")
            degree = edu.get("degree", "")
            field = edu.get("field", "")
            start_date = edu.get("start_date", "")
            end_date = edu.get("end_date", "")
            gpa = edu.get("gpa", "")
            honors = edu.get("honors", [])
            
            if school:
                edu_line = school
                if degree:
                    edu_line += f" | {degree}"
                if field:
                    edu_line += f", {field}"
                if start_date or end_date:
                    formatted_start = format_date_for_resume(start_date) if start_date else ""
                    formatted_end = format_date_for_resume(end_date) if end_date else ""
                    if formatted_start or formatted_end:
                        date_str = f"{formatted_start} – {formatted_end}" if formatted_start and formatted_end else (formatted_start or formatted_end)
                        edu_line += f" | {date_str}"
                if gpa:
                    edu_line += f" | GPA: {gpa}"
                lines.append(edu_line)
                if honors:
                    honors_str = ", ".join(honors) if isinstance(honors, list) else str(honors)
                    if honors_str:
                        lines.append(f"  Honors: {honors_str}")
        lines.append("")
    
    # Skills
    skills_lines = format_skills_as_text(skills_boundary)
    if skills_lines:
        lines.extend(skills_lines)
        lines.append("")
    
    # Awards
    awards = experience.get("awards", [])
    if awards:
        lines.append("HONORS AND AWARDS")
        # Group awards by category
        awards_by_category: dict[str, list[dict[str, Any]]] = {}
        uncategorized: list[dict[str, Any]] = []
        
        for award in awards:
            category = award.get("category", "").strip()
            if category:
                if category not in awards_by_category:
                    awards_by_category[category] = []
                awards_by_category[category].append(award)
            else:
                uncategorized.append(award)
        
        # Print categorized awards
        for category in sorted(awards_by_category.keys()):
            award_names = [award.get("name", "") for award in awards_by_category[category] if award.get("name")]
            if award_names:
                awards_str = "; ".join(award_names)
                lines.append(f"• {category}: {awards_str}")
        
        # Print uncategorized awards
        if uncategorized:
            award_names = [award.get("name", "") for award in uncategorized if award.get("name")]
            if award_names:
                awards_str = "; ".join(award_names)
                lines.append(f"• {awards_str}")
        
        if awards:
            lines.append("")
    
    return "\n".join(lines)


def convert_profile_to_resume_props(profile: dict[str, Any], job_position: str = "") -> dict[str, Any]:
    """Convert profile data to Resume component props format.
    
    This is the unified function for converting profile data to the format
    expected by the Resume React component.
    
    Args:
        profile: User profile dict with personal, experience, skills_boundary, etc.
        job_position: Optional job position/title for the resume.
        
    Returns:
        Dict with name, summary, contact, experience, projects, education, skills.
    """
    personal = profile.get("personal", {})
    experience = profile.get("experience", {})
    skills_boundary = profile.get("skills_boundary", {})
    
    # Use summary from experience if available, otherwise generate one
    summary = experience.get("summary") or generate_summary(experience, job_position)
    
    return {
        "name": personal.get("full_name", ""),
        "summary": summary,
        "contact": {
            "phone": personal.get("phone", ""),
            "email": personal.get("email", ""),
            "linkedin": extract_handle_from_url(personal.get("linkedin_url", "")),
            "github": extract_handle_from_url(personal.get("github_url", "")),
            "location": format_location(personal),
        },
        "experience": [
            convert_experience_to_resume_format(exp)
            for exp in experience.get("work_experiences", [])
        ],
        "projects": [
            convert_project_to_resume_format(proj)
            for proj in experience.get("projects", [])
        ],
        "education": [
            convert_education_to_resume_format(edu)
            for edu in experience.get("education", [])
        ],
        "skills": convert_skills_to_resume_format(skills_boundary),
        "awards": [
            convert_award_to_resume_format(award)
            for award in experience.get("awards", [])
        ] if experience.get("awards") else [],
        "portfolioUrl": personal.get("portfolio_url", ""),
    }
