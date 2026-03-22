"""Shared utility functions for scoring and resume operations."""

import json
import logging
from pathlib import Path

from jobpilot.config import BASE_RESUMES_DIR, PROFILE_PATH

log = logging.getLogger(__name__)


def get_safe_name_from_profile(profile: dict, fallback: str = "Resume") -> str:
    """Extract safe filename from profile personal name.
    
    Args:
        profile: User profile dict
        fallback: Default name if profile name is empty
        
    Returns:
        Safe filename string (alphanumeric, spaces replaced with underscores)
    """
    personal = profile.get("personal", {})
    full_name = personal.get("full_name", "").strip()
    safe_name = "".join(c for c in full_name if c.isalnum() or c in (' ', '-', '_')).strip()
    return safe_name.replace(" ", "_") if safe_name else fallback


def generate_resume_template_filename(
    profile: dict | None = None, 
    role_category: str = "", 
    name: str = ""
) -> str:
    """Generate safe filename for resume template: Name_Category format.
    
    Args:
        profile: Optional user profile dict (used to extract name)
        role_category: Target role category key (e.g., "frontend", "backend")
        name: Fallback name if profile not provided
        
    Returns:
        Safe filename string (e.g., "John_Doe_frontend" or "John_Doe")
    """
    if profile:
        safe_name = get_safe_name_from_profile(profile)
    else:
        safe_name = "".join(c for c in (name or "Resume") if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
        safe_name = safe_name.replace(" ", "_") if safe_name else "Resume"
    
    if role_category:
        return f"{safe_name}_{role_category}"
    else:
        return safe_name


def save_base_resume_txt(
    resume_text: str,
    role_key: str,
    profile: dict,
    custom_path: Path | None = None
) -> Path:
    """Save base resume txt file and update profile target_roles.
    
    Args:
        resume_text: The resume text content to save
        role_key: Target role key (e.g., "frontend", "backend")
        profile: Profile dict to update
        custom_path: Optional custom path. If None, uses default BASE_RESUMES_DIR/Name_Category.txt
        
    Returns:
        Path to saved txt file
    """
    if custom_path:
        base_resume_path = custom_path
    else:
        safe_name = get_safe_name_from_profile(profile)
        base_resume_path = BASE_RESUMES_DIR / f"{safe_name}_{role_key}.txt"
    
    BASE_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    base_resume_path.write_text(resume_text, encoding="utf-8")
    
    # Update profile
    target_roles = profile.get("target_roles", {})
    if role_key in target_roles:
        target_roles[role_key]["base_resume_path"] = str(base_resume_path)
        profile["target_roles"] = target_roles
        PROFILE_PATH.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        log.info(f"Auto-linked resume template to target_roles['{role_key}'].base_resume_path")
    
    return base_resume_path
