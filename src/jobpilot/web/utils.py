"""Shared utility functions for API endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from jobpilot.config import PROFILE_PATH, SEARCH_CONFIG_PATH, load_profile

log = logging.getLogger(__name__)


def load_profile_or_raise() -> dict[str, Any]:
    """Load profile from file or raise HTTPException if not found.
    
    Returns:
        Profile dictionary.
        
    Raises:
        HTTPException: If profile file doesn't exist.
    """
    if not PROFILE_PATH.exists():
        raise HTTPException(
            status_code=400,
            detail="Profile not found. Please complete your profile first."
        )
    
    try:
        return load_profile()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load profile: {str(e)}"
        )


def load_profile_safe() -> dict[str, Any]:
    """Load profile from file, return empty dict if not found.
    
    Returns:
        Profile dictionary or empty dict if file doesn't exist.
    """
    if not PROFILE_PATH.exists():
        return {}
    
    try:
        return load_profile()
    except Exception:
        return {}


def validate_file_type(
    file: UploadFile,
    allowed_extensions: list[str],
    error_message: str | None = None
) -> str:
    """Validate file type and return file extension.
    
    Args:
        file: Uploaded file.
        allowed_extensions: List of allowed file extensions (e.g., [".pdf", ".txt"]).
        error_message: Custom error message. If None, uses default.
        
    Returns:
        File extension (with dot, e.g., ".pdf").
        
    Raises:
        HTTPException: If filename is missing or extension is not allowed.
    """
    if file.filename is None:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    file_ext = Path(file.filename).suffix.lower()
    
    if file_ext not in allowed_extensions:
        if error_message:
            raise HTTPException(status_code=400, detail=error_message)
        else:
            extensions_str = ", ".join(allowed_extensions)
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type. Allowed extensions: {extensions_str}"
            )
    
    return file_ext


def sync_search_config_if_needed(
    profile: dict[str, Any],
    section_name: str | None = None
) -> None:
    """Sync search config from target_roles if needed.
    
    This function checks if target_roles was updated and automatically
    syncs the search configuration. Errors are logged but don't fail
    the operation.
    
    Args:
        profile: Profile dictionary (may be partial if section_name is provided).
        section_name: Optional section name that was updated. If "target_roles",
            sync will be triggered.
    """
    # Check if we need to sync
    should_sync = False
    if section_name == "target_roles":
        should_sync = True
    elif "target_roles" in profile:
        should_sync = True
    
    if not should_sync:
        return
    
    # Import here to avoid circular dependencies
    # Using importlib to import from the same module
    import importlib
    api_module = importlib.import_module("jobpilot.web.api")
    
    try:
        # If only a section was updated, we need the full profile
        if section_name and section_name != "target_roles":
            full_profile = load_profile_safe()
            full_profile[section_name] = profile.get(section_name, {})
            profile = full_profile
        
        search_config = api_module._generate_search_config_from_target_roles(
            profile,
            preserve_existing=True
        )
        api_module._save_search_config(search_config)
        log.debug("Successfully synced search config from target_roles")
    except Exception as e:
        # Log but don't fail the profile update
        log.warning(f"Failed to auto-sync searches.yaml from target_roles: {e}")


def unset_all_resume_defaults(conn: Any) -> None:
    """Unset all default flags for resume templates.
    
    Args:
        conn: Database connection.
    """
    conn.execute("UPDATE resume_templates SET is_default = 0")
    conn.commit()


def unset_all_cover_letter_defaults(meta: dict[str, Any]) -> None:
    """Unset all default flags for cover letter templates.
    
    Args:
        meta: Cover letter templates metadata dictionary.
    """
    for template in meta.get("templates", []):
        template["is_default"] = False


# Constants for database queries
RESUME_TEMPLATE_FIELDS = (
    "id, name, job_position, job_type, role_category, file_path, "
    "pdf_path, uploaded_at, is_default, file_size, file_type"
)
